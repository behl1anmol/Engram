---
name: engram-lessons
description: >
  Record or reinforce an Engram lesson — the self-learning loop. Use when the
  user corrects a mistake, when an action failed in a generalizable way, when
  the user confirms an approach as right, or when you just applied a
  previously recalled lesson.
---

Lessons make you measurably better with this user over time, in any agent. CLI path is in the session-start conventions block.

## Capture (§7.3 triggers)

Record when: the user corrected you; your action failed and a general check would have prevented it; the user confirmed "always do it this way".

**Quality bar — apply before writing:** would this lesson change behavior in a future session? One-off trivia (flaky network, typo) is not a lesson.

Body must follow this shape:

```markdown
**Mistake:** <what went wrong, concrete>
**Why it happened:** <the assumption or missing check>
**How to apply:** <the behavior-changing rule for next time>
```

```bash
echo "<body>" | ENGRAM_AGENT=claude-code python3 "<engram_py>" add \
  --type lesson --name kebab-case-slug \
  --description "Discriminating one-liner recall can match" --tags ...
```

For a confirmed-good approach, same shape with **Mistake:** replaced by **Approach:**.

## Reinforce (§7.4)

When a recalled lesson actually changed what you did this session:

```bash
python3 "<engram_py>" lesson applied <name>
```

This bumps `times_applied` (ranks it higher) and renews its expiry. Unapplied lessons lapse naturally — that is the decay model, don't fight it.
