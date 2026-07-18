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
