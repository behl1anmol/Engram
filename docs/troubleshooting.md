# Engram troubleshooting

First move, always: `engram doctor --json`. Every problem below has a doctor check.

## Doctor says…

| Check | Meaning | Action |
|-------|---------|--------|
| `store-exists` FAIL | No store at the resolved path | `engram init`; check `ENGRAM_HOME` |
| `config` FAIL | config.json missing/corrupt/unsupported version | `engram init` recreates on missing; restore from git/backup if corrupt |
| `memory-schema` WARN | Files outside the frontmatter subset (hand-edit gone wrong) | Fix the file per any valid memory's shape, or `--fix` quarantines it to `conflicts/` for later repair |
| `hash-drift` WARN | Hand-edited bodies (hash ≠ content) — not an error | `--fix` re-stamps |
| `expired` WARN | Memories past expiry, not yet swept | `--fix` archives them |
| `index-bijection` WARN | Index and files disagree | `--fix` rebuilds (index is a cache; this is always safe) |
| `conflicts` WARN | Files in `conflicts/` from write races or quarantine | Open them; merge what matters into the live memory (`edit`), delete the rest |
| `journal-rollups` WARN | Completed month without a rollup | `engram journal --rollup YYYY-MM`, then condense via `edit` |
| `index-scale` WARN | JSON index past its comfort zone | Consent to `engram reindex --backend sqlite` (reversible) |
| `cloud-sync` WARN | Store lives in Dropbox/OneDrive/iCloud path | Deliberate? Fine. Otherwise move the store and set `ENGRAM_HOME` |
| `wsl-dual-store` WARN | WSL and Windows have separate stores | To share one: `export ENGRAM_HOME=/mnt/c/Users/<you>/.agent-memory` (slower I/O — your call) |

## Python missing

Nothing breaks — that's designed (rule 12). Agents get degraded-mode instructions: read `MEMORY.md` + memory files directly. Shims and hooks print consent-gated install commands:

- Windows: `winget install Python.Python.3.12`
- Debian/Ubuntu: `sudo apt install python3`
- macOS: `brew install python3`

After install, `engram doctor` should pass; nothing else to redo.

## "Store busy: could not lock…"

A writer crashed inside a millisecond-held write lock. Stale locks self-heal after 10s — retry. If it persists, check `~/.agent-memory/locks/` and remove the stale `.lock` file **only if no agent is running**.

## Write conflict (exit code 3)

Two writers raced; the loser's full intended version is in `conflicts/<name>.<stamp>.<agent>.md`. Nothing was lost. Compare with the live memory, merge via `engram edit`, delete the conflict file.

## A memory refuses to store (secret pattern)

Working as intended — the body matched a credential pattern (§14). Store *where* a credential lives (vault path, env var name), never the credential.

## Recall returns nothing useful

- Descriptions too vague? Recall matches on name/description/tags — rewrite them to be discriminating (`engram edit --description`).
- Expired/archived? `engram list --archived`.
- Index confusion? `engram reindex` (always safe).

## Windows-specific

- Use `engram.cmd` from `%USERPROFILE%\.agent-memory\bin` (or `py -3 engram\src\engram.py`).
- CRLF is fine: hashing normalizes line endings — hand edits from Notepad don't cause drift.
- WSL + Windows both in play → see `wsl-dual-store` above.
