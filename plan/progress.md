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

## M2 — Index & recall — 2026-07-18

| AC | Result |
|----|--------|
| Lossless rebuild: delete index → reindex → deep-equal | PASS (30-memory fixture) |
| Recall relevance: matching ranked in, unrelated excluded | PASS |
| Budget enforcement ≤ budget with stubs | PASS (100-token / 30-memory case) |
| `times_applied` outranks equal match | PASS |
| Hand-deleted file self-heals on recall | PASS |
| MEMORY.md grouped, one line per memory, valid links | PASS |

Decisions:
- Backend `query()` returns candidates; scoring centralized in `rank_entries`
  (SQLite backend will pre-filter via FTS, same contract).
- Token estimator: chars/4 (documented in code — stdlib has no tokenizer; budget is a cap).
- Two-pass packing: when memories overflow the budget, ~30 tokens reserved so the
  "not loaded" stub section always fits — agent must always learn unloaded memories exist.
- Serve-then-heal freshness: recall reads files behind index entries (file = truth, P1);
  out-of-band expired/hand-edited entries are skipped this call and the index rebuilds after.
- Review queue included only if it fits the budget (budget is a hard cap; queue reappears
  next session — acceptable per §6.4 "lightweight, never nagging").
- Tests: 42 passing total. Windows: **pending-windows**.

## M3 — Claude Code plugin — 2026-07-18

| AC | Result |
|----|--------|
| Fresh install + new session: packet in context, banner exactly once | PASS (subprocess hook tests) |
| "Remember X" produces schema-valid memory w/ correct type + TTL + index | PASS (test_stored_memory_appears_in_next_session_packet) |
| No-Python / broken-store session: degrades, never blocks | PASS (corrupt-config test + echo floor in manifest command) |
| /engram-status reports store stats | PASS (doctor/list --json already covered; skill wraps them) |
| Plugin loads without warnings | **pending-manual** — structure verified against installed plugin ground truth + official docs; live `/plugin install` needs an interactive session |

Ground truth used (no-hallucination constraint):
- Installed caveman plugin inspected for real manifest/hook/skill/agent layout
  (`.claude-plugin/plugin.json`, inline hooks, `${CLAUDE_PLUGIN_ROOT}`, `skills/*/SKILL.md`,
  `agents/*.md` with tools frontmatter).
- Marketplace schema fetched from code.claude.com/docs/en/plugin-marketplaces:
  `.claude-plugin/marketplace.json` at repo root, name/owner/plugins[{name, source, description}].
  Docs also confirm plugins are cached as a copied directory — plugin cannot reference
  files outside its root.

Decisions:
- **Plugin root = `engram/` itself** (manifest at `engram/.claude-plugin/plugin.json`):
  self-contained per the caching rule above, and `src/engram.py` ships inside the plugin
  with zero duplication.
- **Distill flow via SessionStart conventions + skills, not a Stop hook**: SessionStart is
  verified ground truth; a Stop hook would fire on every reply (noise) and its payload
  contract was not verifiable here. Conventions block + /engram-distill cover the ACs.
- Store bootstrap happens in the hook on first activation (installing the plugin is the
  consent for creating `~/.agent-memory`; the one-time banner explains what appeared).
- Hook command carries the §13.1 probe chain (`python3` → `python` → `py -3`) with an
  echo degraded-mode floor, so a Python-less machine still gets memory instructions.
- Tests: 52 passing total. Windows: **pending-windows**.
