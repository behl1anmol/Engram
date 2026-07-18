# Engram — Milestones

Build plan for the developing agent. Execute milestones **in order** — each lists its dependencies, deliverables, and objective acceptance criteria (AC). Do not start a milestone before its dependencies' ACs pass. All work MUST comply with [ARCHITECTURE.md §15 Rules & constraints](ARCHITECTURE.md#15-rules--constraints-normative); section references below (§n) point into ARCHITECTURE.md.

**Working agreements for every milestone**

- Re-read the referenced architecture sections before coding; the architecture document wins over memory of it.
- Python 3.9+ stdlib only in core (Rule 4). If a milestone seems to need a dependency, stop and consult the user.
- Every milestone ends with its AC checklist executed and results recorded in `plan/progress.md` (create on M0): date, milestone, AC pass/fail, notes. This file is the handoff between sessions.
- Tests live in `tests/`, runnable via `python3 -m unittest discover tests` (stdlib runner — no pytest dependency in this repo's core; ironic but consistent with Rule 4).
- Windows verification: run the AC on both Linux/WSL and Windows (`py -3`) whenever the AC says "both platforms". If no Windows environment is available in-session, mark the AC "pending-windows" in `plan/progress.md` rather than passing it.

---

## M0 — Scaffold

**Goal:** Repo skeleton + store bootstrap; prove cross-platform path handling.
**Depends on:** nothing.
**Architecture:** §3 (store layout, config), §12.1 (CLI shape), §13.2 (doctor, minimal).

**Deliverables**

- Repo layout: `src/engram.py` (single-file CLI entry), `tests/`, `plan/progress.md`.
- `engram init`: creates the full directory tree of §3.2 + `config.json` per §3.3. Idempotent — running twice changes nothing and reports "already initialized".
- Path resolution: `ENGRAM_HOME` env override, else `pathlib.Path.home()/".agent-memory"`.
- `engram doctor` (minimal): store exists, writable, config parses, schema_version supported. `--json` output mode.
- WSL detection in doctor (`/proc/version` contains `microsoft`) with the dual-store advisory of §3.1 (advisory text only; no auto-change).

**Acceptance criteria**

- [ ] `engram init` on a machine with no store creates exactly the §3.2 tree; second run is a no-op (verify with before/after directory listing).
- [ ] `ENGRAM_HOME=/tmp/x engram init` creates the store at `/tmp/x`, not in home.
- [ ] `engram doctor --json` exits 0 on a healthy store; exits non-zero with an actionable message when the store is missing or config is corrupt.
- [ ] All of the above pass on Linux/WSL **and** Windows (`py -3`).
- [ ] Unit tests cover path resolution and init idempotency; `python3 -m unittest discover tests` green.

---

## M1 — Core store

**Goal:** Memory files: format, parsing, hashing, atomic CAS writes, lifecycle fields.
**Depends on:** M0.
**Architecture:** §4 (file format, frontmatter subset), §5 (concurrency), §6 (expiry), §14 (secret deny-patterns).

**Deliverables**

- Constrained-frontmatter parser + serializer (§4.3): scalars + inline lists, strict rejection of nonconforming files.
- Body hashing: SHA-256, 16 hex chars, `\n`-normalized, trailing-whitespace-stripped (§4.2).
- Atomic write helper: same-dir temp + fsync + `os.replace` (§5.4). Used by every file write from now on.
- `engram add` — schema validation, name/filename rules (§4.1), TTL default from config when `--expires` omitted, secret deny-pattern scan (§14) with rejection naming the matched pattern.
- `engram edit` — full CAS protocol (§5.3): trivial-merge retry once, then conflict file to `conflicts/` + non-zero exit with report (§5.5).
- `engram show`, `engram delete` (soft → `archive/` with `archived:` stamp), `engram pin`, `engram expire --in <Nd>`, `engram purge --older-than <Nd>` (interactive confirmation; `--yes` for agents).
- Expiry sweep function (used by doctor): moves expired memories to `archive/`.

**Acceptance criteria**

- [ ] Round-trip: `add` → file on disk matches §4.2 schema exactly; `show` reproduces the body byte-for-byte.
- [ ] Hash stability: same body with CRLF vs LF line endings produces the identical hash (test both).
- [ ] **Concurrency test (critical):** two parallel processes (`multiprocessing`) CAS-edit the same memory 50 times each; after completion, the memory file is valid, and every losing write exists in `conflicts/` — total surviving versions across file+conflicts equals total writes; zero data loss, zero torn files.
- [ ] Crash safety: kill a writer mid-write (test hook between temp-write and replace); target file is either the old or new version, never partial.
- [ ] `add` with a body containing `ghp_XXXX…` (and one pattern from each deny category) is rejected, naming the pattern.
- [ ] Expired memory (fixture with past `expires`) is moved to `archive/` by the sweep and carries an `archived:` stamp; `pin` sets `expires: never`.
- [ ] Parser rejects a nested-YAML fixture file with a clear error; does not guess.

---

## M2 — Index & recall

**Goal:** JSON index, ranked budget-capped recall, reindex, MEMORY.md generation.
**Depends on:** M1.
**Architecture:** §9 (recall pipeline, packet, ranking, MEMORY.md), §10.1–10.2 (backend interface, JSON backend).

**Deliverables**

- Storage backend interface (`put/get/query/delete/rebuild`) with JSON implementation (§10.1–10.2); index updated incrementally by `add/edit/delete`, atomically written.
- `engram reindex`: full rebuild from md scan; also regenerates `MEMORY.md` (§9.4).
- `engram recall [--query] [--budget]`: Tier 0→1→2 pipeline, ranking per §9.3 principles, packet per §9.2 (bodies ranked, description-only stubs past budget, latest 1–2 journal entries once M4 lands, expiring-review queue ≤ 3 items).
- Token estimation: chars/4 heuristic (document the choice in code — stdlib has no tokenizer; the budget is a cap, not an exact science).
- `engram list` with `--type/--expiring/--archived` filters.
- Drift self-heal: commands that detect index/file mismatch (missing file, stale hash) trigger a targeted or full rebuild rather than erroring (P2).

**Acceptance criteria**

- [ ] Lossless rebuild: populate 30 fixture memories → snapshot index → delete `index.json` → `reindex` → index deep-equals snapshot (modulo `generated` timestamp).
- [ ] Recall relevance: with fixtures spanning distinct topics, `recall --query "python testing"` returns the testing memories ranked above unrelated ones, and excludes archived/expired ones.
- [ ] Budget enforcement: with a 100-token budget and 30 memories, packet stays ≤ budget (by the documented estimator) and lower-ranked entries appear as name+description stubs only.
- [ ] Ranking honors `times_applied`: two equally-matching lessons, one with `times_applied: 5`, ranks first.
- [ ] Hand-deleting a memory file then running `recall` self-heals (no crash, no stale entry served).
- [ ] `MEMORY.md` regenerates with one line per active memory, grouped by type, links valid.

---

## M3 — Claude Code plugin (reference adapter)

**Goal:** Installable Claude Code plugin: recall at SessionStart, distill flow, skills, first-run banner.
**Depends on:** M2.
**Architecture:** §11.1–11.2 (adapter contract), §13.3 (first-run), Appendix C.1. **Verify current Claude Code plugin/hook APIs against official docs before implementing — Appendix C shapes are illustrative (AD-11 caveat).**

**Deliverables**

- Plugin package: manifest, `hooks/` config, `skills/`, bundled `engram.py`.
- `SessionStart` hook: python-probe (§13.1) → `engram recall` → inject packet; on missing Python, inject degraded-mode instructions (Appendix C.2 variant) instead — never block the session.
- Distill flow at session end (Stop hook or skill-guided, per what current hook API supports): guides the agent to write feedback/lessons/journal per conventions, using `engram add`/`journal`.
- Skills: `/engram-remember`, `/engram-recall`, `/engram-lessons`, `/engram-status` (thin wrappers over CLI with agent-friendly `--json`).
- Optional memory-curator subagent definition (review queue handling, update-over-create enforcement).
- First-run banner (§13.3) gated by `first_run_done`, flipped after display.

**Acceptance criteria**

- [ ] Fresh install + new session: recall packet appears in context (verify via session transcript), banner shows exactly once across two sessions.
- [ ] Saying "remember that I prefer X" results in a schema-valid feedback memory on disk with correct type, TTL default, and index entry.
- [ ] Session on a machine (or PATH-stripped env) without Python: session starts normally, degraded-mode instructions injected, no hook error surfaced to the user.
- [ ] `/engram-status` reports store stats (counts by type, expiring soon, backend, store path).
- [ ] Plugin passes Claude Code's plugin validation/loads without warnings.

---

## M4 — Lessons + journal (self-learning loop)

**Goal:** Close the loop that makes the agent improve with the user.
**Depends on:** M3 (capture triggers live in the adapter's distill flow).
**Architecture:** §7 (lessons), §8 (journal & rollups).

**Deliverables**

- `engram lesson applied <name>`: increments `times_applied`, stamps `last_applied`, renews `expires` (§7.4) — CAS-protected.
- Lesson capture guidance wired into the distill flow with the §7.3 quality bar ("would this change behavior in a future session?") and the §7.3 triggers.
- `engram journal --slug s`: creates the dated entry at the §8.2 path; skip-if-nothing-durable guidance in distill flow.
- Rollup: `engram journal --rollup <YYYY-MM>` generates the ≤ 15-line monthly summary skeleton from that month's entries (agent fills narrative); doctor flags completed months lacking rollups.
- Recall integration: latest 1–2 journal entries in packet; lessons ranked per §9.3.

**Acceptance criteria**

- [ ] End-to-end lesson loop: seed a correction scenario → lesson file created with all §7.2 fields → next session's recall surfaces it for a matching query → `lesson applied` bumps counter, extends `expires`, and re-ranks it above an unapplied peer.
- [ ] `lesson applied` under concurrent invocation (two processes) never loses an increment (CAS conflict path exercised).
- [ ] Journal entry lands at `journal/<YYYY>/<YYYY-MM>/<date>-<slug>.md`, 90-day TTL default; recall packet contains the latest entries.
- [ ] Rollup command produces a file covering all entries of the month; after rollup exists, doctor stops flagging that month; aged daily entries sweep to archive while the rollup survives.

---

## M5 — Cross-agent adapters + plug-and-play

**Goal:** `engram adapt` — the constraint-E payoff. Codex, Copilot, opencode, and generic export.
**Depends on:** M3 (adapter contract proven by reference implementation).
**Architecture:** §11 (contract, per-agent table, adapt), Appendix C.2–C.3. **Verify each target agent's current config locations/instruction-file conventions against official docs before implementing — the table fixes the contract, not API details.**

**Deliverables**

- `engram adapt --target codex|copilot|opencode` — generates conventions block + any hook/config snippets for the same canonical store; writes to the target's user-level location **only with per-file user consent**; prints an install/verify report.
- `engram adapt --target <any> --export <dir>` — generic path: emits Appendix C.2 portable block + files for manual install.
- Idempotent re-runs: existing Engram blocks are updated in place (marker-comment delimited), never duplicated.
- Docs: `docs/adapters.md` — per-agent setup + verification steps, degraded-mode notes.

**Acceptance criteria**

- [ ] `adapt --target codex` on a machine with a store produces a Codex user-level `AGENTS.md` block pointing at the canonical store; a Codex session (or a simulated read of that block) can recall and add a memory that Claude Code then sees — **zero memories copied, single store, verified by file count unchanged in `memories/`**.
- [ ] `adapt --target copilot` emits the instructions block in Copilot's user instructions location; block contains recall-first + distill + never-store-secrets rules.
- [ ] Running `adapt` twice produces byte-identical target files (idempotency).
- [ ] `--export` produces a directory whose contents alone (plus the store) are sufficient to onboard an undocumented agent — validated by following only the exported README.
- [ ] Consent path: refusing consent for a target file leaves it untouched and reports what was skipped.

---

## M6 — SQLite upgrade path

**Goal:** Second backend behind the interface; consent-gated scale upgrade; both-direction switching.
**Depends on:** M2 (interface), M5 recommended first (adapters exercise recall broadly).
**Architecture:** §10.3–10.4.

**Deliverables**

- SQLite backend (stdlib `sqlite3`, FTS5) implementing the full `put/get/query/delete/rebuild` interface; `query` uses FTS for Tier 0.
- `engram reindex --backend sqlite|json`: rebuild into target backend, flip `config.json.backend` atomically after successful rebuild.
- Scale detection in doctor/recall (500 active memories or Tier-0 > 200 ms) emitting the one-line consent-seeking suggestion (§10.4); no automatic switching.
- FTS5-absent fallback: if the platform's sqlite build lacks FTS5, backend falls back to LIKE-based query and doctor notes it (P6).

**Acceptance criteria**

- [ ] Round-trip: 600-memory fixture store → `reindex --backend sqlite` → recall results (set + ranking) match JSON backend's for a battery of 10 queries → `reindex --backend json` → index deep-equals the pre-switch JSON snapshot. `memories/` untouched throughout (verify by tree hash).
- [ ] All M1/M2/M4 test suites pass unmodified against the SQLite backend (interface compliance).
- [ ] Scale suggestion appears at 500+ active memories and never below; upgrade only proceeds on explicit consent flag/confirmation.
- [ ] Backend switch interrupted mid-rebuild (kill test) leaves the old backend active and functional (`config.json.backend` unflipped).

---

## M7 — Doctor, bootstrap & polish

**Goal:** Production hardening: full doctor, Python bootstrap, complete docs, release readiness.
**Depends on:** all previous.
**Architecture:** §13 (bootstrap/doctor/first-run), §14 (privacy checks), §3.1 (WSL).

**Deliverables**

- Full `engram doctor [--fix]`: every check in §13.2 (schema conformance, hash drift re-stamp, index bijection, expiry sweep, conflict/archive size report, WSL advisory, cloud-sync-folder warning, scale check, rollup gaps).
- Bootstrap flow finalized for all adapters: probe order `python3` → `python` → `py -3` (≥ 3.9); degraded mode injection; consent-gated install offers with per-platform commands (§13.1).
- `bin/engram` shim + `engram.cmd` generation on init/install for direct human use.
- Full `README.md`: icon, pitch, install per agent per OS, quickstart, FAQ, degraded-mode explanation, privacy statement.
- `docs/`: user guide (memory lifecycle, pin/expire/delete, reading your own store), troubleshooting.
- Final cross-check: every MUST/SHOULD in §15 mapped to implementing code or docs — record the mapping table in `plan/progress.md`.

**Acceptance criteria**

- [ ] Doctor on a deliberately broken fixture store (bad frontmatter, hash drift, orphan index entry, expired memories, missing rollup) reports every defect; `--fix` resolves the fixable ones and re-reports clean.
- [ ] Clean-machine simulation without Python (PATH-stripped): adapter session still works in degraded mode; following the consent flow's printed instructions yields a working `engram doctor` afterward.
- [ ] `engram` / `engram.cmd` shims work from a fresh shell on Linux and Windows.
- [ ] README quickstart followed verbatim by a fresh agent session reaches "first memory stored and recalled" with no undocumented steps.
- [ ] §15 compliance table complete in `plan/progress.md`; any deviation is listed with user-approved rationale.

---

## Milestone dependency graph

```
M0 ── M1 ── M2 ── M3 ── M4
              │     └─── M5 ──┐
              └───────────────┼── M6 ── M7
                              └────────  (M7 depends on all)
```

## Out of scope (all milestones)

Embeddings/semantic search, encryption at rest, cloud sync, team sharing, transcript mining — parked in [ARCHITECTURE.md Appendix F](ARCHITECTURE.md#appendix-f--parking-lot-explicitly-out-of-scope-recorded-for-later). Do not implement without explicit user request.
