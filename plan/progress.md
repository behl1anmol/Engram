# Engram — milestone progress log

Handoff file between development sessions (MILESTONES.md working agreements).
Record per milestone: date, AC results, notes, deviations.

## Layout deviation (approved)

User chose "workspace = repo, code in `engram/` subfolder". MILESTONES.md M0 said
`src/engram.py` at repo root; actual paths are `engram/src/engram.py` and
`engram/tests/`. Test command: `cd engram && python3 -m unittest discover tests`.

## M0 — Scaffold — 2026-07-18

| AC | Result |
|----|--------|
| `engram init` creates §3.2 tree; second run no-op | PASS (test_init_creates_full_tree, test_init_is_idempotent) |
| `ENGRAM_HOME` override respected | PASS (test_engram_home_override_wins + CLI smoke) |
| `doctor --json` exit 0 healthy / non-zero + actionable on missing/corrupt | PASS (TestDoctor, 4 tests) |
| Pass on Linux/WSL and Windows | Linux/WSL PASS (Python 3.14.4). **pending-windows** — no Windows Python in this session |
| Unit tests green | PASS — 10/10 |

Notes:
- WSL dual-store advisory implemented as doctor `warn`; suppressed when `ENGRAM_HOME` set (already shared deliberately).
- `atomic_write_text` (§5.4) landed in M0 since init/config writes need it; M1 reuses it.
- Doctor healthy-store AC accepts `warn` status (WSL advisory is a warn, not an error).

## M1 — Core store — 2026-07-18

| AC | Result |
|----|--------|
| Round-trip add→show byte-for-byte | PASS (test_add_show_round_trip_body_exact) |
| CRLF vs LF identical hash | PASS (TestHashing) |
| Concurrency: 2 procs × 50 CAS edits, zero loss | PASS — successes + conflict files == 100, final file valid |
| Crash safety: kill between temp-write and replace | PASS — old version intact (subprocess, exit 9 hook) |
| Secret deny-patterns rejected, pattern named | PASS — 8 categories tested |
| Expiry sweep → archive with stamp; pin → never | PASS (TestLifecycle) |
| Parser rejects nonconforming files with clear error | PASS (TestStrictParser, 5 tests) |

Deviations / decisions:
- CAS token = full raw file text (not just body hash): strictly stronger than §5.3's
  minimum — also catches metadata-only races (pin vs expire share a body hash).
  Stored `hash` field semantics unchanged.
- Trivial-merge-then-retry (§5.5 step 2) not implemented: CLI edits are whole-body
  replacements, so no merge is "trivially safe" at this layer. Conflict preservation
  covers all cases; revisit if a field-level edit command appears.
- `engram add --type journal` rejected — journal entries arrive in M4 via `engram journal`.
- Crash-test hook `ENGRAM_TEST_CRASH_BEFORE_REPLACE` lives in `atomic_write_text`
  (test-only env var; inert in normal use).
- Doctor gained memory-schema / hash-drift / expired checks + `--fix` (re-stamp, sweep)
  early — M1 needed the sweep exercised; full §13.2 checklist still lands in M7.
- Tests: 30 passing total. Windows: **pending-windows**.
