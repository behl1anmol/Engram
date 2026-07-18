# Engram

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

**Engram** is a cross-platform, cross-agent persistent memory plugin. It gives AI coding agents — Claude Code, Codex, GitHub Copilot, opencode, and others — a single shared, user-level memory store, so your agents remember who you are, what you're working on, and what they've learned from working with you. Memories live in plain markdown files you own and can read, edit, or delete at any time. Switch agents tomorrow and your memories come with you: nothing to re-teach, nothing to migrate.

> An *engram* is the physical trace a memory leaves in the brain. This plugin is the trace your journey leaves behind.

## Status

Design phase. No code yet.

- [Architecture](ARCHITECTURE.md) — full design: store layout, file format, concurrency, recall, adapters, rules.
- [Milestones](MILESTONES.md) — sequenced build plan with acceptance criteria, written for a developing agent to execute.
- [Plan](plan/engram-plan.md) — the original approved planning document.
