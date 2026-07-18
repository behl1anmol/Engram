# Engram adapters — per-agent setup

One canonical store, thin adapters (ARCHITECTURE.md §11). Setting up a new agent never copies memories — `engram adapt` only installs a pointer block into that agent's global instructions.

```bash
python3 engram/src/engram.py adapt --target <agent> [--yes] [--export DIR]
```

`--yes` consents to writing the target file (required when non-interactive). `--export DIR` writes the block + install README to a directory instead — works for any agent, including ones Engram has never heard of.

The installed block is delimited by `<!-- ENGRAM:BEGIN -->` / `<!-- ENGRAM:END -->` markers; re-running `adapt` updates it in place and never touches surrounding content.

## Claude Code (reference adapter — the plugin)

Install the plugin (see repo README). The `SessionStart` hook handles recall injection, store bootstrap, and the first-run banner; skills handle remember/lessons/distill flows. No `adapt` needed.

## Codex CLI

| | |
|---|---|
| Target file | `$CODEX_HOME/AGENTS.md` (default `~/.codex/AGENTS.md`) |
| Source | learn.chatgpt.com/docs/agent-configuration/agents-md — "In your Codex home directory (defaults to `~/.codex`) … Codex reads `AGENTS.md`" (verified 2026-07-18) |
| Install | `engram adapt --target codex --yes` |
| Verify | New Codex session → "what do you remember about me?" → it should run the recall command from the block |

Note: if `AGENTS.override.md` exists in `$CODEX_HOME`, it shadows `AGENTS.md` — put the block there instead (manually, or `--export`).

## opencode

| | |
|---|---|
| Target file | `$XDG_CONFIG_HOME/opencode/AGENTS.md` (default `~/.config/opencode/AGENTS.md`) |
| Source | opencode.ai/docs/rules — global rules file, applied across all sessions (verified 2026-07-18) |
| Install | `engram adapt --target opencode --yes` |
| Verify | Same as Codex |

## GitHub Copilot CLI

| | |
|---|---|
| Target file | `$COPILOT_HOME/copilot-instructions.md` (default `~/.copilot/copilot-instructions.md`) |
| Source caveat | GitHub docs confirm `~/.copilot` as the CLI home (mcp-config.json, agents/) but do **not** explicitly document a global instructions file; support varies by CLI version. **Verify after install.** |
| Install | `engram adapt --target copilot --yes`, then verify |
| Fallback | If the block is ignored: `engram adapt --target copilot --export <dir>`, then paste the block into a repo-level `AGENTS.md` or `.github/copilot-instructions.md` (repo-level IS documented) |

## Any other agent

```bash
engram adapt --target <name> --export ./engram-adapter
```

Produces `engram-instructions.md` (the portable block — the adapter floor, ARCHITECTURE.md AD-11) and a README with install steps. Paste into whatever global-instructions mechanism the agent has. An agent with no instructions file at all can still participate: point it at `~/.agent-memory/MEMORY.md` (degraded mode).

## Degraded mode (all agents)

No Python → memory still works: the block tells the agent to read `MEMORY.md` and memory files directly. Restore tooling with a consent-gated Python install (`winget install Python.Python.3.12` / `sudo apt install python3` / `brew install python3`).
