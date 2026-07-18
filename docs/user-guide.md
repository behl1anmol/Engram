# Engram user guide

CLI shown as `engram` (add `~/.agent-memory/bin` to PATH, or use `python3 engram/src/engram.py`). Everything here works identically on Windows (`engram.cmd`), Linux, macOS, and WSL.

## Memory types

| Type | Holds | Default TTL |
|------|-------|-------------|
| `user` | Who you are: role, preferences, style | never |
| `feedback` | Corrections and confirmed approaches (**Why** + **How to apply**) | 365d |
| `project` | Ongoing work, goals, status — your relationship to a project | 180d |
| `reference` | URLs, dashboards, tickets | 180d |
| `lesson` | Agent mistakes → behavior changes (see below) | 365d |
| `journal` | Session narratives + monthly rollups | 90d |

One file = one fact, always. TTLs live in `config.json` (`ttl_defaults`).

## Everyday commands

```bash
engram add --type feedback --name prefers-pytest \
  --description "User prefers pytest style tests"     # body via stdin or --body-file
engram list [--type lesson] [--expiring] [--archived]
engram show <name>
engram edit <name> --body-file new.md                 # CAS-protected replace
engram recall --query "current task keywords"         # ranked, token-budgeted
engram doctor [--fix]                                 # health check / safe repairs
```

## Lifecycle: expiry, pin, delete, purge

Memories expire so the store stays believable. You always override:

```bash
engram pin <name>              # expires: never
engram expire <name> --in 90d  # durations: Nd / Nw / Nm (~30d) / Ny (~365d), e.g. --in 4y
engram delete <name>           # soft: moves to archive/ (restorable by moving back)
engram purge --older-than 90d  # hard-delete old archive entries; asks for confirmation
```

Recall surfaces up to 3 memories expiring within 14 days per session — answer pin / extend / let lapse and the nagging stays light.

**Time-bound facts:** when the end is known, put it in the expiry — "in college for 4 more years" is `engram expire in-college --in 4y` (or `--expires 2030-06-01` at add time). Month/year durations are approximations (30d/365d) on purpose: expiry is a review trigger, not a deadline.

## Protected memories — readonly for agents

Innate facts (your name, hobbies, durable preferences) can be locked so no agent edits or deletes them:

```bash
engram protect users-name                  # locks it AND pins it (expires: never)
engram protect in-college --keep-expiry    # locked, but keeps its end date
engram unprotect users-name                # deliberate two-step to unlock
```

While protected: `edit`/`delete` refuse (pointing at `unprotect`), the expiry sweep / `doctor --fix` / `purge` never touch it, and if a kept expiry date passes the memory *stays served* and sits in the review queue until you decide. Shown as `[protected]` in `list` and `(type, protected)` in recall packets.

This is friction against accidental agent curation, not security — the files are yours and hand edits always win.

## Lessons — the self-learning loop

When an agent gets corrected, it records a lesson:

```markdown
**Mistake:** ran npm install in a pnpm workspace.
**Why it happened:** assumed default tooling instead of checking the lockfile.
**How to apply:** check for pnpm-lock.yaml / yarn.lock before package commands.
```

When a recalled lesson actually changes behavior, the agent runs `engram lesson applied <name>`: the counter bumps, the lesson ranks higher in future recall, and its expiry renews. Lessons that never get applied simply lapse. That's the whole decay model — usage is fitness.

## Journal — your journey

One compact entry per meaningful session:

```bash
echo "Shipped auth flow. Decided JWT over sessions. Next: rate limiting." | \
  engram journal --slug auth-flow --description "Auth flow shipped, JWT decision"
```

Monthly, generate a rollup and condense it (≤ 15 lines): `engram journal --rollup 2026-06`, then `engram edit 2026-06-rollup`. Daily entries age out (90d); rollups carry the narrative for a year. Recent journal entries ride along in every recall packet — that's why sessions open like a conversation that never stopped.

## Reading your own store

It's just markdown. `~/.agent-memory/MEMORY.md` is a regenerated index of everything; each memory file's frontmatter shows its expiry, hash, tags, and which agent wrote it. Edit freely — `doctor --fix` re-stamps hashes afterward.

## Index backends

JSON by default; at ~500+ memories `doctor` suggests SQLite (FTS5 search). The switch is a rebuild, both directions, markdown untouched:

```bash
engram reindex --backend sqlite   # upgrade
engram reindex --backend json     # downgrade, anytime
```

## Setting up another agent

```bash
engram adapt --target codex --yes
```

Same store, zero copying. See [adapters.md](adapters.md).
