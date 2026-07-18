#!/usr/bin/env python3
"""Engram — cross-agent persistent memory CLI.

Single-file, Python 3.9+ standard library only (ARCHITECTURE.md rule 4).
Store layout, formats, and protocols are normative in ARCHITECTURE.md;
section references below (§n) point there.
"""

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ENGRAM_VERSION = "0.1.0"
CONFIG_SCHEMA_VERSION = 1
SUPPORTED_SCHEMA_VERSIONS = {1}

MEMORY_TYPES = ("user", "feedback", "project", "reference", "lesson", "journal")

# §3.2 canonical tree, relative to store root
STORE_DIRS = (
    "memories/user",
    "memories/project",
    "memories/feedback",
    "memories/reference",
    "lessons",
    "journal",
    "index",
    "archive",
    "conflicts",
)

DEFAULT_CONFIG = {
    "schema_version": CONFIG_SCHEMA_VERSION,
    "backend": "json",
    "recall_token_budget": 1500,
    "first_run_done": False,
    "created": None,  # stamped at init
    "ttl_defaults": {
        "user": "never",
        "feedback": "365d",
        "project": "180d",
        "reference": "180d",
        "lesson": "365d",
        "journal": "90d",
    },
    "redaction_patterns_extra": [],
}

# §4.2 frontmatter schema. Serialization keeps this order for diff-friendly files.
FIELD_ORDER = (
    "name", "description", "type", "created", "updated", "expires", "hash",
    "source_agent", "tags", "links", "times_applied", "last_applied", "archived",
)
REQUIRED_FIELDS = ("name", "description", "type", "created", "updated",
                   "expires", "hash", "source_agent")
LIST_FIELDS = {"tags", "links"}
INT_FIELDS = {"times_applied"}

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
KEY_RE = re.compile(r"^[a-z_]+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TTL_RE = re.compile(r"^(\d+)d$")

# §14 secret deny-patterns. Writers refuse content matching any of these.
SECRET_PATTERNS = (
    ("api key (sk-...)", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}")),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}")),
    ("GitHub fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("credential in URL", re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s@]+@")),
    ("password assignment", re.compile(r"(?i)\b(?:password|passwd|pwd)\s*[=:]\s*\S+")),
)


class EngramError(Exception):
    """User-facing error: printed to stderr, non-zero exit, no traceback."""


class FrontmatterError(EngramError):
    pass


class ConflictError(EngramError):
    def __init__(self, name, conflict_path):
        super().__init__(
            f"Write conflict on '{name}': another writer changed the file first. "
            f"Your version was preserved at {conflict_path} — reconcile and retry."
        )
        self.conflict_path = conflict_path


# ---------------------------------------------------------------------------
# Paths & config
# ---------------------------------------------------------------------------

def store_root() -> Path:
    """Resolve store root: ENGRAM_HOME override, else ~/.agent-memory (§3.1)."""
    override = os.environ.get("ENGRAM_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".agent-memory"


def config_path(root: Path) -> Path:
    return root / "config.json"


def load_config(root: Path) -> dict:
    with open(config_path(root), encoding="utf-8") as f:
        return json.load(f)


def atomic_write_text(target: Path, content: str) -> None:
    """Same-directory temp + fsync + os.replace (§5.4). Atomic on POSIX and NTFS."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.parent / f".{target.name}.tmp.{os.getpid()}"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        if os.environ.get("ENGRAM_TEST_CRASH_BEFORE_REPLACE"):
            os._exit(9)  # crash-safety test hook: die between temp write and replace
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def save_config(root: Path, cfg: dict) -> None:
    atomic_write_text(config_path(root), json.dumps(cfg, indent=2) + "\n")


def is_wsl() -> bool:
    """Detect WSL via /proc/version (§3.1)."""
    try:
        return "microsoft" in Path("/proc/version").read_text(encoding="utf-8").lower()
    except OSError:
        return False


def today() -> str:
    return date.today().isoformat()


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def current_agent() -> str:
    return os.environ.get("ENGRAM_AGENT", "user")


# ---------------------------------------------------------------------------
# Frontmatter (§4.3 constrained subset — no PyYAML, strict rejection)
# ---------------------------------------------------------------------------

def parse_memory_text(text: str, origin: str = "<memory>"):
    """Parse a memory file into (meta: dict, body: str).

    Accepts only the constrained subset: `key: value` scalars and inline
    lists `key: [a, b]`. Anything else (nesting, multi-line values, block
    lists) is rejected — never guessed at (§4.3).
    """
    if not text.startswith("---\n"):
        raise FrontmatterError(f"{origin}: missing opening '---' frontmatter fence")
    end = text.find("\n---\n", 3)
    if end == -1:
        raise FrontmatterError(f"{origin}: missing closing '---' frontmatter fence")
    header = text[4:end + 1]
    body = text[end + 5:]
    if body.startswith("\n"):
        body = body[1:]

    meta = {}
    for lineno, line in enumerate(header.splitlines(), start=2):
        if not line.strip():
            continue
        if line[0] in " \t":
            raise FrontmatterError(
                f"{origin}:{lineno}: indented line — nesting is outside the "
                f"supported frontmatter subset")
        if ":" not in line:
            raise FrontmatterError(f"{origin}:{lineno}: expected 'key: value'")
        key, _, raw = line.partition(":")
        key = key.strip()
        raw = raw.strip()
        if not KEY_RE.match(key):
            raise FrontmatterError(f"{origin}:{lineno}: bad key {key!r}")
        if key in meta:
            raise FrontmatterError(f"{origin}:{lineno}: duplicate key {key!r}")
        if raw.startswith("["):
            if not raw.endswith("]"):
                raise FrontmatterError(
                    f"{origin}:{lineno}: list must be inline '[a, b]'")
            items = [i.strip().strip("'\"") for i in raw[1:-1].split(",")]
            meta[key] = [i for i in items if i]
        elif raw == "":
            raise FrontmatterError(
                f"{origin}:{lineno}: empty value for {key!r} — nested or "
                f"multi-line values are outside the supported frontmatter subset")
        else:
            if (raw[0] == raw[-1]) and raw[0] in "'\"" and len(raw) >= 2:
                raw = raw[1:-1]
            meta[key] = raw
    for key in INT_FIELDS & meta.keys():
        try:
            meta[key] = int(meta[key])
        except ValueError:
            raise FrontmatterError(f"{origin}: field {key!r} must be an integer")
    return meta, body


def serialize_memory(meta: dict, body: str) -> str:
    lines = ["---"]
    for key in FIELD_ORDER:
        if key not in meta:
            continue
        val = meta[key]
        if key in LIST_FIELDS:
            if not val:
                continue
            lines.append(f"{key}: [{', '.join(val)}]")
        else:
            lines.append(f"{key}: {val}")
    unknown = [k for k in meta if k not in FIELD_ORDER]
    for key in sorted(unknown):  # preserve forward-compatible unknown fields
        lines.append(f"{key}: {meta[key]}")
    lines.append("---")
    lines.append("")
    return "\n".join(lines) + "\n" + body.rstrip("\n") + "\n"


def body_hash(body: str) -> str:
    """SHA-256 of the normalized body, first 16 hex chars (§4.2).

    Normalization: CRLF/CR -> LF, per-line trailing whitespace stripped,
    trailing blank lines stripped — so the same content hashes identically
    on Windows and Linux checkouts.
    """
    norm = body.replace("\r\n", "\n").replace("\r", "\n")
    norm = "\n".join(line.rstrip() for line in norm.split("\n")).rstrip("\n")
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def validate_meta(meta: dict, origin: str = "<memory>") -> None:
    for f in REQUIRED_FIELDS:
        if f not in meta:
            raise FrontmatterError(f"{origin}: missing required field {f!r}")
    name = meta["name"]
    if not NAME_RE.match(name) or len(name) > 64:
        raise FrontmatterError(
            f"{origin}: name {name!r} must be lowercase kebab-case ASCII, <= 64 chars")
    if meta["type"] not in MEMORY_TYPES:
        raise FrontmatterError(
            f"{origin}: type {meta['type']!r} not one of {MEMORY_TYPES}")
    for f in ("created", "updated"):
        if not DATE_RE.match(meta[f]):
            raise FrontmatterError(f"{origin}: {f} must be ISO date YYYY-MM-DD")
    exp = meta["expires"]
    if exp != "never" and not DATE_RE.match(exp):
        raise FrontmatterError(f"{origin}: expires must be ISO date or 'never'")
    if len(meta["description"]) > 120:
        raise FrontmatterError(f"{origin}: description over 120 chars (§9.5)")


# ---------------------------------------------------------------------------
# Store operations
# ---------------------------------------------------------------------------

def type_dir(root: Path, mtype: str) -> Path:
    if mtype == "lesson":
        return root / "lessons"
    if mtype == "journal":
        return root / "journal"
    return root / "memories" / mtype


def active_memory_files(root: Path):
    """Yield every active (non-archived) memory file path."""
    for sub in ("memories/user", "memories/project", "memories/feedback",
                "memories/reference", "lessons"):
        d = root / sub
        if d.is_dir():
            yield from sorted(d.glob("*.md"))
    jd = root / "journal"
    if jd.is_dir():
        for p in sorted(jd.rglob("*.md")):
            yield p


def find_memory(root: Path, name: str) -> Path:
    for p in active_memory_files(root):
        if p.stem == name:
            return p
    raise EngramError(f"No active memory named '{name}'. See: engram list")


def read_memory(path: Path):
    text = path.read_text(encoding="utf-8")
    meta, body = parse_memory_text(text, origin=path.name)
    return text, meta, body


def scan_secrets(text: str, cfg: dict):
    """Return the label of the first matched deny-pattern, or None (§14)."""
    for label, rx in SECRET_PATTERNS:
        if rx.search(text):
            return label
    for extra in cfg.get("redaction_patterns_extra", []):
        try:
            if re.search(extra, text):
                return f"custom pattern {extra!r}"
        except re.error:
            continue  # invalid user pattern: doctor reports it, writes don't crash
    return None


def default_expiry(cfg: dict, mtype: str) -> str:
    ttl = cfg.get("ttl_defaults", {}).get(mtype, "never")
    if ttl == "never":
        return "never"
    m = TTL_RE.match(ttl)
    if not m:
        raise EngramError(f"config ttl_defaults.{mtype} invalid: {ttl!r} (want 'Nd' or 'never')")
    return (date.today() + timedelta(days=int(m.group(1)))).isoformat()


def create_memory(root: Path, meta: dict, body: str) -> Path:
    """Create a new memory file. Exclusive-create makes simultaneous
    same-name creation an explicit error, not a silent overwrite (§5.3)."""
    meta["hash"] = body_hash(body)
    validate_meta(meta)
    path = type_dir(root, meta["type"]) / f"{meta['name']}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "x", encoding="utf-8") as f:
            f.close()
    except FileExistsError:
        raise EngramError(
            f"Memory '{meta['name']}' already exists at {path}. "
            f"Update it (engram edit) instead of duplicating (§6.5).")
    atomic_write_text(path, serialize_memory(meta, body))
    return path


def cas_update(root: Path, name: str, mutate, agent: str) -> Path:
    """Optimistic compare-and-swap update (§5.3).

    `mutate(meta, body) -> (meta, body)` builds the intended new version.
    CAS token: the full raw text read at step 1 — strictly stronger than the
    stored body hash alone, since it also catches metadata-only races
    (e.g. concurrent pin vs expire) that share a body hash.
    On conflict the intended version goes to conflicts/, nothing is lost (§5.5).
    """
    path = find_memory(root, name)
    raw_read, meta, body = read_memory(path)
    new_meta, new_body = mutate(dict(meta), body)
    new_meta["updated"] = today()
    new_meta["hash"] = body_hash(new_body)
    new_meta["source_agent"] = agent
    validate_meta(new_meta)
    raw_current = path.read_text(encoding="utf-8")
    if raw_current != raw_read:
        conflict_path = (root / "conflicts" /
                         f"{name}.{utc_stamp()}.{os.getpid()}.{agent}.md")
        atomic_write_text(conflict_path, serialize_memory(new_meta, new_body))
        raise ConflictError(name, conflict_path)
    atomic_write_text(path, serialize_memory(new_meta, new_body))
    return path


def archive_memory(root: Path, path: Path, meta: dict, body: str) -> Path:
    """Soft delete: stamp archived date, move under archive/ (§6.3)."""
    meta["archived"] = today()
    dest = root / "archive" / path.name
    if dest.exists():
        dest = root / "archive" / f"{path.stem}.{utc_stamp()}.md"
    atomic_write_text(dest, serialize_memory(meta, body))
    path.unlink()
    return dest


def sweep_expired(root: Path):
    """Move expired memories to archive/ (§6). Returns archived paths."""
    swept = []
    today_d = date.today()
    for path in list(active_memory_files(root)):
        try:
            _, meta, body = read_memory(path)
        except FrontmatterError:
            continue  # nonconforming files are doctor's business, not sweep's
        exp = meta.get("expires", "never")
        if exp != "never" and DATE_RE.match(exp) and date.fromisoformat(exp) < today_d:
            swept.append(archive_memory(root, path, meta, body))
    return swept


def read_body_input(args) -> str:
    if getattr(args, "body_file", None):
        return Path(args.body_file).read_text(encoding="utf-8")
    if sys.stdin.isatty():
        raise EngramError("Provide the body via --body-file or stdin")
    return sys.stdin.read()


def require_store(root: Path) -> dict:
    if not config_path(root).exists():
        raise EngramError(f"No store at {root}. Run: engram init")
    return load_config(root)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_init(args) -> int:
    root = store_root()
    existed = config_path(root).exists()
    for rel in STORE_DIRS:
        (root / rel).mkdir(parents=True, exist_ok=True)
    if existed:
        print(f"Store already initialized at {root}")
        return 0
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    cfg["created"] = today()
    save_config(root, cfg)
    if not (root / "MEMORY.md").exists():
        atomic_write_text(root / "MEMORY.md", "# Memory index\n\n(no memories yet)\n")
    print(f"Initialized Engram store at {root}")
    return 0


def cmd_add(args) -> int:
    root = store_root()
    cfg = require_store(root)
    if args.type == "journal":
        raise EngramError("Journal entries use 'engram journal', not 'add'")
    body = read_body_input(args)
    hit = scan_secrets(args.description + "\n" + body, cfg)
    if hit:
        raise EngramError(
            f"Refusing to store: content matches secret deny-pattern [{hit}] (§14). "
            f"Memories are long-lived plain text — never store credentials.")
    meta = {
        "name": args.name,
        "description": args.description,
        "type": args.type,
        "created": today(),
        "updated": today(),
        "expires": args.expires or default_expiry(cfg, args.type),
        "source_agent": current_agent(),
    }
    if args.tags:
        meta["tags"] = [t.strip() for t in args.tags.split(",") if t.strip()]
    if args.links:
        meta["links"] = [l.strip() for l in args.links.split(",") if l.strip()]
    if args.type == "lesson":
        meta["times_applied"] = 0
    path = create_memory(root, meta, body)
    print(f"Stored {args.type} memory '{args.name}' -> {path}")
    return 0


def cmd_show(args) -> int:
    root = store_root()
    require_store(root)
    path = find_memory(root, args.name)
    sys.stdout.write(path.read_text(encoding="utf-8"))
    return 0


def cmd_edit(args) -> int:
    root = store_root()
    cfg = require_store(root)
    new_body = read_body_input(args)
    hit = scan_secrets(new_body, cfg)
    if hit:
        raise EngramError(
            f"Refusing to store: content matches secret deny-pattern [{hit}] (§14).")

    def mutate(meta, _body):
        if args.description:
            meta["description"] = args.description
        return meta, new_body

    path = cas_update(root, args.name, mutate, current_agent())
    print(f"Updated '{args.name}' -> {path}")
    return 0


def cmd_delete(args) -> int:
    root = store_root()
    require_store(root)
    path = find_memory(root, args.name)
    _, meta, body = read_memory(path)
    dest = archive_memory(root, path, meta, body)
    print(f"Archived '{args.name}' -> {dest} (restore by moving back; purge removes permanently)")
    return 0


def cmd_pin(args) -> int:
    root = store_root()
    require_store(root)

    def mutate(meta, body):
        meta["expires"] = "never"
        return meta, body

    cas_update(root, args.name, mutate, current_agent())
    print(f"Pinned '{args.name}' (expires: never)")
    return 0


def cmd_expire(args) -> int:
    root = store_root()
    require_store(root)
    m = TTL_RE.match(args.in_)
    if not m:
        raise EngramError(f"--in wants 'Nd' (e.g. 30d), got {args.in_!r}")
    new_date = (date.today() + timedelta(days=int(m.group(1)))).isoformat()

    def mutate(meta, body):
        meta["expires"] = new_date
        return meta, body

    cas_update(root, args.name, mutate, current_agent())
    print(f"'{args.name}' now expires {new_date}")
    return 0


def cmd_purge(args) -> int:
    root = store_root()
    require_store(root)
    m = TTL_RE.match(args.older_than)
    if not m:
        raise EngramError(f"--older-than wants 'Nd' (e.g. 90d), got {args.older_than!r}")
    cutoff = date.today() - timedelta(days=int(m.group(1)))
    victims = []
    for p in sorted((root / "archive").glob("*.md")):
        try:
            _, meta, _ = read_memory(p)
        except FrontmatterError:
            continue
        archived = meta.get("archived")
        if archived and DATE_RE.match(archived) and date.fromisoformat(archived) < cutoff:
            victims.append(p)
    if not victims:
        print("Nothing in archive older than cutoff.")
        return 0
    print(f"Will permanently delete {len(victims)} archived memories:")
    for p in victims:
        print(f"  {p.name}")
    if not args.yes:
        answer = input("This cannot be undone. Type 'purge' to confirm: ")
        if answer.strip() != "purge":
            print("Aborted.")
            return 1
    for p in victims:
        p.unlink()
    print(f"Purged {len(victims)} files.")
    return 0


def doctor_checks(root: Path) -> list:
    """Minimal M0/M1 checks; extended through M7 (§13.2).

    Returns list of {check, status(ok|warn|error), detail}.
    """
    checks = []

    if not root.exists():
        checks.append({"check": "store-exists", "status": "error",
                       "detail": f"No store at {root}. Run: engram init"})
        return checks
    checks.append({"check": "store-exists", "status": "ok", "detail": str(root)})

    probe = root / ".engram-write-probe"
    try:
        probe.write_text("probe", encoding="utf-8")
        probe.unlink()
        checks.append({"check": "store-writable", "status": "ok", "detail": ""})
    except OSError as e:
        checks.append({"check": "store-writable", "status": "error", "detail": str(e)})

    try:
        cfg = load_config(root)
        sv = cfg.get("schema_version")
        if sv in SUPPORTED_SCHEMA_VERSIONS:
            checks.append({"check": "config", "status": "ok", "detail": f"schema_version={sv}"})
        else:
            checks.append({"check": "config", "status": "error",
                           "detail": f"Unsupported schema_version={sv}; supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"})
    except FileNotFoundError:
        checks.append({"check": "config", "status": "error",
                       "detail": "config.json missing. Run: engram init"})
    except (json.JSONDecodeError, OSError) as e:
        checks.append({"check": "config", "status": "error", "detail": f"config.json unreadable: {e}"})

    missing = [rel for rel in STORE_DIRS if not (root / rel).is_dir()]
    if missing:
        checks.append({"check": "store-tree", "status": "warn",
                       "detail": f"Missing dirs (run engram init to repair): {', '.join(missing)}"})
    else:
        checks.append({"check": "store-tree", "status": "ok", "detail": ""})

    # M1: schema conformance + hash drift over active memories
    bad, drift, expired = [], [], []
    today_d = date.today()
    for p in active_memory_files(root):
        try:
            _, meta, body = read_memory(p)
            validate_meta(meta, origin=p.name)
        except FrontmatterError as e:
            bad.append(str(e))
            continue
        if meta["hash"] != body_hash(body):
            drift.append(p.name)
        exp = meta.get("expires", "never")
        if exp != "never" and DATE_RE.match(exp) and date.fromisoformat(exp) < today_d:
            expired.append(p.name)
    if bad:
        checks.append({"check": "memory-schema", "status": "warn",
                       "detail": f"{len(bad)} nonconforming file(s), skipped by index: " + "; ".join(bad[:5])})
    else:
        checks.append({"check": "memory-schema", "status": "ok", "detail": ""})
    if drift:
        checks.append({"check": "hash-drift", "status": "warn",
                       "detail": f"Hand-edited (hash mismatch), --fix re-stamps: {', '.join(drift[:10])}"})
    else:
        checks.append({"check": "hash-drift", "status": "ok", "detail": ""})
    if expired:
        checks.append({"check": "expired", "status": "warn",
                       "detail": f"{len(expired)} expired memory(ies), --fix archives: {', '.join(expired[:10])}"})
    else:
        checks.append({"check": "expired", "status": "ok", "detail": ""})

    # §3.1 WSL dual-store advisory: advisory only, never automatic.
    if is_wsl() and not os.environ.get("ENGRAM_HOME"):
        checks.append({
            "check": "wsl-dual-store", "status": "warn",
            "detail": ("Running under WSL: Windows agents use a separate home directory, "
                       "so this store is not shared with them. To share one store, set "
                       "ENGRAM_HOME=/mnt/c/Users/<user>/.agent-memory on the WSL side "
                       "(note: 9p-mount I/O is slower)."),
        })

    return checks


def doctor_fix(root: Path) -> list:
    """Apply safe repairs: re-stamp drifted hashes, archive expired (§13.2)."""
    actions = []
    for p in list(active_memory_files(root)):
        try:
            _, meta, body = read_memory(p)
            validate_meta(meta, origin=p.name)
        except FrontmatterError:
            continue
        if meta["hash"] != body_hash(body):
            meta["hash"] = body_hash(body)
            meta["updated"] = today()
            atomic_write_text(p, serialize_memory(meta, body))
            actions.append(f"re-stamped hash: {p.name}")
    for dest in sweep_expired(root):
        actions.append(f"archived expired: {dest.name}")
    return actions


def cmd_doctor(args) -> int:
    root = store_root()
    fixes = []
    if args.fix and root.exists():
        fixes = doctor_fix(root)
    checks = doctor_checks(root)
    worst = ("error" if any(c["status"] == "error" for c in checks)
             else "warn" if any(c["status"] == "warn" for c in checks) else "ok")
    if args.json:
        print(json.dumps({"store": str(root), "status": worst,
                          "checks": checks, "fixes": fixes}, indent=2))
    else:
        for f in fixes:
            print(f"[fix ] {f}")
        for c in checks:
            mark = {"ok": "ok  ", "warn": "WARN", "error": "FAIL"}[c["status"]]
            line = f"[{mark}] {c['check']}"
            if c["detail"]:
                line += f" — {c['detail']}"
            print(line)
        print(f"Store: {root} — {worst}")
    return 1 if worst == "error" else 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="engram",
                                description="Engram — persistent user-level memory for AI agents")
    p.add_argument("--version", action="version", version=f"engram {ENGRAM_VERSION}")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("init", help="create store skeleton and config (idempotent)")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("add", help="store a new memory")
    sp.add_argument("--type", required=True, choices=[t for t in MEMORY_TYPES if t != "journal"])
    sp.add_argument("--name", required=True, help="kebab-case slug, unique store-wide")
    sp.add_argument("--description", required=True, help="one line <= 120 chars; recall matches on this")
    sp.add_argument("--expires", help="ISO date or 'never' (default: type TTL from config)")
    sp.add_argument("--tags", help="comma-separated keywords")
    sp.add_argument("--links", help="comma-separated related memory names")
    sp.add_argument("--body-file", help="read body from file (default: stdin)")
    sp.set_defaults(func=cmd_add)

    sp = sub.add_parser("show", help="print one memory file in full")
    sp.add_argument("name")
    sp.set_defaults(func=cmd_show)

    sp = sub.add_parser("edit", help="replace a memory's body (CAS-protected)")
    sp.add_argument("name")
    sp.add_argument("--body-file", help="read new body from file (default: stdin)")
    sp.add_argument("--description", help="optionally update the description too")
    sp.set_defaults(func=cmd_edit)

    sp = sub.add_parser("delete", help="soft-delete a memory into archive/")
    sp.add_argument("name")
    sp.set_defaults(func=cmd_delete)

    sp = sub.add_parser("pin", help="set expires: never")
    sp.add_argument("name")
    sp.set_defaults(func=cmd_pin)

    sp = sub.add_parser("expire", help="set expiry N days from now")
    sp.add_argument("name")
    sp.add_argument("--in", dest="in_", required=True, metavar="Nd")
    sp.set_defaults(func=cmd_expire)

    sp = sub.add_parser("purge", help="permanently delete old archived memories")
    sp.add_argument("--older-than", required=True, metavar="Nd")
    sp.add_argument("--yes", action="store_true", help="skip confirmation (agents)")
    sp.set_defaults(func=cmd_purge)

    sp = sub.add_parser("doctor", help="store health checks")
    sp.add_argument("--json", action="store_true", help="machine-readable output")
    sp.add_argument("--fix", action="store_true", help="apply safe repairs")
    sp.set_defaults(func=cmd_doctor)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ConflictError as e:
        print(f"conflict: {e}", file=sys.stderr)
        return 3
    except EngramError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
