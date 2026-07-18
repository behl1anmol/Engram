# Plan: Engram — Cross-Agent Persistent Memory Plugin — Architecture Doc + Milestones

## Identity (locked with user)

- **Name: Engram** — neuroscience term for the physical trace a memory leaves in the brain. CLI: `engram` (replaces `memoryctl` everywhere below).
- **ASCII icon** (README header + first-run banner):

```
      .    *    .
   *   \   |   /   *
     .  \  |  /  .
   ------ (@) ------
     '  /  |  \  '
   *   /   |   \   *
      '    *    '

   E  N  G  R  A  M
   memory that stays
```

- **Install intro**: Claude Code plugins can't show rich install UI, so: (a) icon + tagline top of README, (b) first-run SessionStart hook prints one-time welcome banner (icon, one-line what-it-does, `engram doctor` pointer), then never again (first-run flag in config). Documented in ARCHITECTURE.md §13 and M3/M7.

## Context

User wants a cross-platform (Windows/Linux/macOS), cross-agent (Claude Code, Codex, GitHub Copilot, opencode) persistent **user-level** memory plugin. Not per-project — lives at user home level. Goals: agents remember the user's journey, learn from mistakes (lessons), feel like a companion, and memories transfer between agents with zero re-creation (plug-and-play). Repo `/mnt/d/projects/Personal/persistent-memory` is empty — greenfield. Deliverable of THIS task is **documentation only**: an architecture document and a milestones document that a developing agent will later follow to build the plugin. No plugin code written in this task.

## Decisions locked with user (do not re-litigate)

1. **Single canonical shared store** (e.g. `~/.agent-memory/`), each agent gets a thin adapter — not per-agent stores with sync.
2. **Markdown files = source of truth.** Index = rebuildable cache. **JSON index in v1**; SQLite is an opt-in later upgrade the agent proactively offers when the store grows (~500+ memories or slow recall). Upgrade = `reindex --backend sqlite` (rebuild from md, near-zero risk). No install-time backend fork.
3. **Distilled + journal tier** persistence: atomic distilled facts (user/project/lesson/reference) + compact per-session journal entries. No raw transcripts.
4. **Python 3 stdlib-only tooling.** If Python missing, plugin must not fail — a bootstrap/doctor flow detects and offers guided install (with user consent) before proceeding.

## Deliverables

**Step 0 (user request): copy this plan file into workspace at `/mnt/d/projects/Personal/persistent-memory/plan/` first thing after approval** (plan mode blocked the write during planning).

Files to create in repo root:

### 0. `README.md` (stub)

Engram icon + tagline + one-paragraph pitch + link to ARCHITECTURE.md / MILESTONES.md. Full README lands in M7.

### 1. `ARCHITECTURE.md`

Well-organized doc with rationale attached to every decision (user constraint A). Sections:

1. **Overview & Goals** — problem statement, companion vision, non-goals (no cloud sync, no raw transcript storage, no per-project memory).
2. **Design Principles** — md as source of truth; index as disposable cache; agent-agnostic core + thin adapters; local-only/privacy-first; zero hard dependencies (Python stdlib); every feature degrades gracefully.
3. **Canonical Store Layout** — `~/.agent-memory/` tree: `memories/` (by type subdirs), `lessons/`, `journal/`, `index/index.json`, `config.json`, `locks/`. Windows path handling (`%USERPROFILE%`, pathlib).
4. **Memory File Format** — frontmatter schema: `name` (kebab slug), `description` (one-line, used for recall relevance), `type` (user|feedback|project|lesson|reference|journal), `created`/`updated`/`expires` (ISO 8601 absolute dates), `hash` (SHA-256 of body), `source_agent`, `tags`, `links` (`[[name]]` wiki-style). Body conventions per type (lessons carry **Mistake / Why / How to apply / Times applied**).
5. **Concurrency & Integrity** — the hash requirement: optimistic concurrency (read hash → modify → compare-and-swap), atomic writes (temp file + `os.replace`, atomic on POSIX and NTFS), per-file hash detects torn/conflicting writes, conflict resolution rule (newer wins + conflict copy preserved, never silent data loss). Rationale: file locks are unreliable cross-platform (WSL/NTFS); optimistic CAS + atomic rename is portable.
6. **Expiry & Lifecycle** — per-type default TTLs, `expires` override, `never` allowed; expired memories move to `archive/` (soft delete) before purge; user commands to extend/pin/delete; periodic review queue the agent surfaces ("these 3 memories expire soon — keep?").
7. **Lessons Subsystem (self-learning)** — capture trigger (agent made mistake, user corrected), lesson format, reinforcement counter (`times_applied`), promotion (frequently-applied lessons rank higher in recall), demotion/expiry of stale lessons. This is the self-enhancement loop (user constraint D).
8. **Journal Tier (user journey)** — one compact entry per session (3–6 lines: what happened, decisions, mood/preferences observed), rolling monthly rollup summaries to cap growth. Gives companion continuity without transcript bloat.
9. **Recall & Token Optimization** — index-first recall: load only `index.json` descriptions (cheap), relevance-match against current task, then read only matching md bodies; hard token budget per recall (configurable, default ~1500 tokens); tiered loading (descriptions → bodies → linked memories); never bulk-load store into context.
10. **Storage Backend Interface** — abstract ops (`put/get/query/delete/rebuild`); JSON backend v1; SQLite backend later (FTS5); auto-offer upgrade at scale threshold; `reindex` as universal migration primitive.
11. **Agent Adapters & Plug-and-Play** — per-agent integration table:
    - Claude Code: plugin (hooks: SessionStart recall + SessionEnd/Stop distill; skills: `/memory-*` commands; agent: memory-curator subagent).
    - Codex: `AGENTS.md` instruction block + notify/exec hooks where available.
    - Copilot: `.github/copilot-instructions.md` / user instructions block.
    - opencode: plugin/config equivalent.
    - **Sift workflow (constraint E)**: "set me up on codex" = agent runs `memoryctl adapt --target codex`, which generates target-agent adapter files pointing at the same canonical store — no memory copying, memories already shared. Adapter emits instruction text sized to target agent's context conventions.
12. **CLI Tooling (`memoryctl`)** — command reference: `add`, `recall`, `list`, `show`, `edit`, `pin`, `expire`, `delete`, `reindex`, `doctor`, `adapt`, `journal`, `lesson`. Single Python entry point, stdlib only.
13. **Bootstrap & Doctor** — Python detection per platform; if missing: never hard-fail, present install offer (winget/apt/brew commands) and only proceed with user consent; `doctor` validates store integrity, rebuilds index, reports orphan hashes.
14. **Security & Privacy** — local-only, no network; redaction rules (never store secrets/tokens/passwords — deny-pattern list); memories are user-readable plain text by design; note that store dir should be excluded from cloud-synced folders or consciously included.
15. **Rules & Constraints** — consolidated normative rules for the developing agent (MUST/SHOULD list): md source of truth, atomic writes only, no deps beyond stdlib in core, absolute dates only, token budget enforcement, ask-before-install, etc.
16. **Appendix** —
    - A: full example memory file, lesson file, journal entry.
    - B: `index.json` schema with example.
    - C: hook payload/registration examples per agent (Claude Code `hooks.json`, Codex config, Copilot instructions snippet).
    - D: decision log (ADR-style table: decision, alternatives considered, rationale) — satisfies "rationale behind every decision".
    - E: glossary.
    - F: future ideas parking lot (embeddings/semantic search, encryption at rest, cloud sync).

### 2. `MILESTONES.md`

Sequenced milestones, each with: goal, deliverables, acceptance criteria (testable), and explicit dependencies. Written so a developing agent can execute one milestone per session.

- **M0 — Scaffold**: repo layout, `config.json` schema, store directory bootstrap, cross-platform path resolution. AC: `memoryctl doctor` creates and validates empty store on Win + Linux.
- **M1 — Core store**: memory file format, frontmatter parser (stdlib, no PyYAML — constrained frontmatter subset), SHA-256 hashing, atomic write, CAS conflict handling, expiry fields. AC: concurrent-write test shows no data loss; expired memory archived correctly.
- **M2 — Index & recall**: `index.json` build/update, `recall` with relevance matching + token budget, `reindex`. AC: recall returns only matching memories within budget; index rebuild from md is lossless.
- **M3 — Claude Code plugin**: plugin manifest, SessionStart recall hook, session-end distill flow, `/memory` skills, curator subagent. AC: fresh Claude Code session auto-loads relevant memories; new fact from conversation persisted with correct frontmatter.
- **M4 — Lessons + journal (self-learning loop)**: lesson capture/apply/reinforce, journal entries + monthly rollup. AC: corrected mistake produces lesson; lesson surfaces in next relevant session; `times_applied` increments.
- **M5 — Cross-agent adapters + plug-and-play**: `adapt` command, Codex/Copilot/opencode adapter generation, sift workflow docs. AC: `memoryctl adapt --target codex` yields working Codex setup reading same store; no memory duplication.
- **M6 — SQLite upgrade path**: SQLite backend behind storage interface, scale detection, consent-gated upgrade, `reindex --backend sqlite`. AC: switch backends both directions with zero memory loss (md untouched).
- **M7 — Doctor, bootstrap & polish**: Python bootstrap flow, integrity repair, docs, install guide per agent per OS. AC: clean machine without Python reaches working state via guided consent flow.

## Not doing (this task)

- No plugin code, hooks, or scripts — docs only.
- No git init/commit unless user asks after doc review.

## Verification

- Both files render clean as GitHub markdown (check heading hierarchy, tables, code fences).
- Cross-check ARCHITECTURE.md against user's constraints A–F and requirements A–E — every one must map to a section; decision log (Appendix D) must have a rationale row for every major choice.
- MILESTONES.md acceptance criteria must be objectively testable, no vague "works well".
