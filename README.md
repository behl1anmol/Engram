<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/banner-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="assets/banner-light.svg">
  <img alt="Engram" src="assets/banner-dark.svg">
</picture>

**Engram** gives your AI coding agents one shared, persistent, user-level memory. Claude Code, Codex, GitHub Copilot, opencode — they all read and write the same store, so your agents remember who you are, what you're working toward, and what they've learned from working with you. Switch agents tomorrow and nothing needs migrating: the memory was shared all along.

> An *engram* is the physical trace a memory leaves in the brain. This plugin is the trace your journey leaves behind.

## Why

Every agent session starts as a stranger. Project files (`CLAUDE.md`, `AGENTS.md`) capture repo conventions — nothing captures **you**: your preferences, ongoing goals across projects, the corrections you've repeated, the story of your work. And whatever one agent learns stays locked in that agent's config. Engram fixes both.

- **Plain markdown you own.** Every memory is a readable `.md` file in `~/.agent-memory/`. Open, edit, delete with any editor. The index is a rebuildable cache — never the truth.
- **Learns from mistakes.** Corrections become *lessons* with a reinforcement loop: applied lessons rank higher and live longer; stale ones quietly expire.
- **Remembers the journey.** Compact per-session journal entries plus monthly rollups — narrative continuity without transcript bloat.
- **Token-frugal.** Recall is index-first and budget-capped (default ~1500 tokens). Your context window is never taxed by memory noise.
- **Safe under concurrency.** Hash-checked compare-and-swap writes, atomic renames, conflicts preserved — two agents can't silently destroy each other's writes.
- **Expiry with consent.** Memories carry expiry dates (`--in 30d/6w/18m/4y` or explicit dates); you pin, extend, or delete. Nothing is hard-deleted without confirmation.
- **Protected memories.** Innate facts (name, hobbies, durable preferences) can be locked readonly for agents: `engram protect <name>` — no agent edit/delete, no automated lifecycle action, ever.
- **No secrets, no network.** Writes are scanned against credential patterns and refused. The tooling never touches the network.

## Install

### Claude Code (plugin — reference adapter)

```
/plugin marketplace add behl1anmol/Engram
/plugin install engram@engram-marketplace
```

Next session: one-time welcome banner, then your memories load automatically at session start. Skills: `/engram-remember`, `/engram-recall`, `/engram-lessons`, `/engram-status`, `/engram-distill`.

### Codex / opencode / Copilot CLI / anything else

Clone this repo, then let any Engram-aware agent set the next one up — or do it yourself:

```bash
python3 engram/src/engram.py adapt --target codex --yes      # ~/.codex/AGENTS.md
python3 engram/src/engram.py adapt --target opencode --yes   # ~/.config/opencode/AGENTS.md
python3 engram/src/engram.py adapt --target copilot --yes    # ~/.copilot/ (verify: docs vary)
python3 engram/src/engram.py adapt --target anything --export ./dir   # any future agent
```

No memories are copied — `adapt` installs a pointer block into the target agent's global instructions. Same store, instantly. Details and doc citations: [docs/adapters.md](docs/adapters.md).

## Quickstart

```bash
python3 engram/src/engram.py init                 # create ~/.agent-memory (+ bin/ shims)
echo "Prefers pytest over unittest." | python3 engram/src/engram.py add \
  --type feedback --name prefers-pytest --description "User prefers pytest style tests"
python3 engram/src/engram.py recall --query "python testing"
python3 engram/src/engram.py doctor               # health check
```

Add `~/.agent-memory/bin` to PATH and it's just `engram <command>`.

## Requirements

Python 3.9+ standard library — nothing else. No pip, no dependencies. Windows, Linux, macOS, WSL. **No Python?** Nothing breaks: agents fall back to degraded mode (reading `MEMORY.md` and memory files directly) and offer a consent-gated install.

## The store

```
~/.agent-memory/
├── memories/{user,project,feedback,reference}/   # one fact per file
├── lessons/                                      # the self-learning loop
├── journal/YYYY/YYYY-MM/                         # session narratives + rollups
├── index/                                        # rebuildable cache (JSON; SQLite at scale)
├── archive/  conflicts/  locks/  bin/            # soft deletes, race losers, shims
├── MEMORY.md                                     # human/degraded-mode index
└── config.json
```

## Documentation

- [User guide](docs/user-guide.md) — memory lifecycle, lessons, journal, backends
- [Adapters](docs/adapters.md) — per-agent setup with doc citations
- [Troubleshooting](docs/troubleshooting.md) — doctor, conflicts, WSL, degraded mode
- [Architecture](ARCHITECTURE.md) — full design with rationale for every decision
- [Milestones](MILESTONES.md) + [progress log](plan/progress.md) — how it was built

## Privacy

Local-only, forever. Memories are plain text under your OS user account — that is the access boundary, by design. Credential-shaped content is refused at write time. Keep the store out of cloud-synced folders unless that's a conscious choice (`doctor` warns).

## FAQ

**Is my conversation history stored?** No. Only distilled facts, lessons, and 3–6-line journal summaries. Never transcripts.

**What if two agents write at once?** Compare-and-swap + a millisecond micro-lock. A losing write lands in `conflicts/`, never silently vanishes.

**JSON or SQLite?** JSON until you pass ~500 memories; `doctor` will suggest the SQLite upgrade, which is just a reindex — markdown is never touched, and it's reversible.

**Can I edit memory files by hand?** Yes — they're yours. `doctor --fix` re-stamps hashes after hand edits.
