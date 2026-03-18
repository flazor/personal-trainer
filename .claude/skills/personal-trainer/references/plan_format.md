# Training Plan Format

`training-plan.md` is a markdown file with YAML frontmatter.

## Structure

```markdown
---
created: YYYY-MM-DD
duration_weeks: <integer>
goal: <primary goal summary>
days_per_week: <integer>
experience_level: <beginner|intermediate|advanced>
---

# Training Plan: <Title>

## Overview
Brief explanation of the plan rationale, approach, and what to expect.

## Weekly Schedule

### Day 1 — <Day Name>: <Focus>

**Warm-up** (5-10 min)
- Exercise description

| Exercise | Sets | Reps | Rest | Notes |
|----------|------|------|------|-------|
| Exercise Name | 3 | 8-10 | 90s | Cue or note |

**Cooldown**
- Stretch or mobility work

### Day 2 — <Day Name>: <Focus>
(same format)

...

## Progression Guidelines
How to increase weight/volume over the program duration. When to deload.

## Notes
Health accommodations, schedule flexibility tips, any other relevant guidance.
```

## Rules

- Every training day gets its own `### Day N` section
- Exercise tables use the 5-column format shown above
- Rest periods as shorthand: "60s", "90s", "2min"
- Rep ranges for hypertrophy (8-12), strength (3-5), endurance (15-20)
- RPE or RIR notation when appropriate (e.g. "RPE 7" or "2 RIR")
- Warm-up included for each session
- Frontmatter `created` date must be ISO format (YYYY-MM-DD)
- Do not include specific weights in training-plan.md — those belong in next-workout.md
