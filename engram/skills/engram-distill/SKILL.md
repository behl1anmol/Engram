---
name: engram-distill
description: >
  End-of-session distill flow: persist what this session produced that is
  durable. Use when the user says goodbye, wraps up, or asks to "save
  context/memories", or when substantial work is concluding.
---

Walk this checklist against the session; store only what passes the durability bar. CLI path is in the session-start conventions block.

1. **New facts about the user or their work?** → /engram-remember flow (update-over-create).
2. **Mistakes corrected or approaches confirmed?** → /engram-lessons flow.
3. **Recalled lessons you applied?** → `lesson applied <name>` for each.
4. **Did the session produce something durable** (decisions, milestones, direction changes)? → write a journal entry (3–6 lines: what happened, decisions, what's next). Skip entirely for trivial sessions — no entry beats a noise entry.
5. **Anything in the recall packet now wrong?** → `edit` or `delete` it.

Then tell the user in 1–2 lines what was persisted (or that nothing met the bar).

Journal entry (skip if `engram journal` is unavailable — it arrives with M4; note it for next session instead):

```bash
echo "<3-6 line narrative>" | ENGRAM_AGENT=claude-code python3 "<engram_py>" journal --slug short-topic-slug
```
