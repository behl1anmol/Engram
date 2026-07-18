#!/usr/bin/env python3
"""Engram — cross-agent persistent memory CLI.

Single-file, Python 3.9+ standard library only (ARCHITECTURE.md rule 4).
Store layout, formats, and protocols are normative in ARCHITECTURE.md;
section references below (§n) point there.
"""

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
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


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def doctor_checks(root: Path) -> list:
    """Minimal M0 checks; extended in later milestones (§13.2).

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


def cmd_doctor(args) -> int:
    root = store_root()
    checks = doctor_checks(root)
    worst = ("error" if any(c["status"] == "error" for c in checks)
             else "warn" if any(c["status"] == "warn" for c in checks) else "ok")
    if args.json:
        print(json.dumps({"store": str(root), "status": worst, "checks": checks}, indent=2))
    else:
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

    sp = sub.add_parser("doctor", help="store health checks")
    sp.add_argument("--json", action="store_true", help="machine-readable output")
    sp.add_argument("--fix", action="store_true", help="apply safe repairs")
    sp.set_defaults(func=cmd_doctor)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
