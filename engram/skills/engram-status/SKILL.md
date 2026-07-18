---
name: engram-status
description: >
  Report Engram store health and contents: counts by type, expiring memories,
  backend, store path. Use when the user asks "what do you remember",
  "memory status", or something seems wrong with the memory store.
---

CLI path is in the session-start conventions block.

```bash
python3 "<engram_py>" doctor --json     # health: schema, hash drift, expired, tree
python3 "<engram_py>" list --json       # active memories
python3 "<engram_py>" list --expiring   # review queue
python3 "<engram_py>" list --archived   # soft-deleted
```

Summarize for the user: total memories by type, lessons with `times_applied`, anything expiring within 14 days, any doctor warnings. If doctor reports fixable issues, offer `doctor --fix` (it re-stamps hand-edited hashes and archives expired memories — safe, reversible via archive/).
