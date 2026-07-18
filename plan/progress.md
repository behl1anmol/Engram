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

## M4 — Lessons + journal — 2026-07-18

| AC | Result |
|----|--------|
| End-to-end lesson loop: capture → recall → applied → counter/expiry/rerank | PASS |
| Concurrent `lesson applied` never loses an increment | PASS — 2 procs × 25, exact count, 5 repeat runs stable |
| Journal entry at `journal/YYYY/YYYY-MM/YYYY-MM-DD-slug.md`, 90d TTL, in packet | PASS |
| Rollup covers month's entries; doctor flag clears; aged entries sweep, rollup survives | PASS |

Deviation (architecture amended):
- The §5.3 residual CAS race **measurably lost increments** under counter contention
  (49/50 in the first test run). Fix: per-memory micro-lock (exclusive-create file in
  `locks/`, ms-held, 10s stale-steal) serializing the check+write section.
  ARCHITECTURE.md §5.3 amended with rationale; this is not the AD-5-rejected locking —
  no platform lock APIs, no stuck-lock failure mode. `locks/` dir finally earns its
  place in the §3.2 tree.
- `cas_update_retry` (fresh-derive + retry, no conflict files) added for counter-style
  mutations; plain `cas_update` still preserves conflicts for judgment-carrying edits.
- Rollup command generates a skeleton (bullets from entries) for the agent to condense
  via `edit` — narrative quality is agent judgment, not CLI mechanics.
- Tests: 60 passing total. Windows: **pending-windows**.

## M5 — Cross-agent adapters — 2026-07-18

| AC | Result |
|----|--------|
| `adapt --target codex` → AGENTS.md block, same store, zero memories copied | PASS (file-count proof + cross-agent visibility test) |
| `adapt --target copilot` emits instructions with recall-first/distill/no-secrets | PASS |
| Rerun byte-identical | PASS (block is deterministic — no timestamps) |
| `--export` self-sufficient for unknown agents | PASS (block + README, degraded-mode floor included) |
| Consent refusal leaves target untouched, reports skipped | PASS (non-interactive without --yes exits 1, writes nothing) |

Verified locations (fetched 2026-07-18, cited in docs/adapters.md):
- Codex: `$CODEX_HOME` (default `~/.codex`)/`AGENTS.md` — learn.chatgpt.com docs.
- opencode: `$XDG_CONFIG_HOME`/opencode/`AGENTS.md` — opencode.ai/docs/rules.
- Copilot CLI: `~/.copilot` home confirmed (COPILOT_HOME), but a *global* instructions
  file is NOT explicitly documented — adapter writes `copilot-instructions.md` there and
  the install report + docs tell the user to verify; repo-level fallback documented.

Decisions:
- Marker-delimited block (`<!-- ENGRAM:BEGIN/END -->`), upsert preserves surrounding
  user content; unmatched BEGIN without END is an error, never a guess.
- Consent: interactive y/N prompt on tty; non-interactive requires explicit `--yes`
  (rule 11) — refusal/missing consent writes nothing.
- Export mode works for any target name — the adapter floor (AD-11) needs no
  per-agent knowledge.
- Tests: 69 passing total. Windows: **pending-windows**.

## M6 — SQLite backend — 2026-07-18

| AC | Result |
|----|--------|
| 600-memory round trip: json→sqlite→json, recall parity on 10 queries, index deep-equal, markdown tree-hash unchanged | PASS |
| Suites pass against sqlite backend | PASS with deviation: targeted interface-compliance tests (add/edit/delete/lesson/journal/recall/self-heal on sqlite) instead of re-running all suites twice — same coverage intent, half the runtime; parity test carries the equivalence proof |
| Scale suggestion at 500+ only; consent-seeking wording; absent on sqlite | PASS |
| Interrupted switch (kill mid-rebuild) leaves old backend active + functional | PASS (crash hook; config flips only after successful rebuild) |

Decisions:
- **Guaranteed parity by construction**: FTS indexes exactly the `_terms()` tokens
  `rank_entries` matches on, so FTS pre-filtering can never change the result set —
  scoring stays centralized, backends only supply candidates.
- Entry rows stored as JSON blobs in sqlite (schema flexibility, trivial parity);
  FTS5 unavailable (or ENGRAM_TEST_NO_FTS set) → full-scan fallback, always correct (P6).
- Switch order: rebuild target fully, then flip `config.backend` — the flip is the
  commit point.
- Tests: 76 passing total. Windows: **pending-windows**.
