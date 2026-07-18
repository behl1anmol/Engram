---
name: engram-remember
description: >
  Store a durable fact in Engram persistent memory. Use when the user says
  "remember this/that", shares a lasting preference, role, goal, or project
  fact, or corrects you in a way worth keeping. Enforces update-over-create
  and the one-fact-per-file rule.
---

Store a memory in the Engram user-level store. The CLI path and store location are in the session-start "Engram memory conventions" block.

## Steps

1. **Distill to one atomic fact.** Not a transcript — the fact, plus for feedback why it matters and how to apply it.
2. **Check for an existing memory covering the same fact** (look at the recall packet first, then `engram list --json`). If one exists, update it with `edit` — never create a near-duplicate. If an existing memory is now wrong, `delete` it.
3. **Pick the type:** `user` (who they are), `feedback` (corrections/confirmed approaches — body must contain `**Why:**` and `**How to apply:**` lines), `project` (ongoing work/goals), `reference` (URLs/tickets/dashboards). Lessons have their own flow: /engram-lessons.
4. **Store it:**

```bash
echo "<body>" | ENGRAM_AGENT=claude-code python3 "<engram_py>" add \
  --type feedback --name kebab-case-slug \
  --description "One discriminating line, <= 120 chars" \
  --tags comma,separated
```

## Rules

- Name: lowercase kebab-case, unique, ≤ 64 chars. Description is what future recall matches on — make it specific, not generic.
- Absolute ISO dates in bodies, never "last week".
- Never store secrets — the CLI rejects them, don't try to rephrase around it.
- Omit `--expires` to accept the type's default TTL; use `--expires never` only for durable identity facts.
- **Time-bound fact with a known end?** Set expiry to that end: `expire <name> --in 4y` (units d/w/m/y) or `--expires YYYY-MM-DD`. If the duration is knowable but the user didn't say, ask ("how long will that be true?").
- **Innate fact** (name, hobbies, durable identity)? Offer to lock it: `protect <name>` makes it readonly for agents and pins it. Only protect with the user's agreement — it adds friction to every future correction.
- Confirm to the user what was stored, in one line.
