# Next Workout Format

`next-workout.md` is a focused brief for the upcoming training session. It must be fully actionable — the client should be able to walk into the gym with only this file.

## Structure

```markdown
---
date: YYYY-MM-DD
session: "Day N — Focus"
plan_week: N
---

# Next Workout: <Session Name>

## Warm-Up (5-10 min)
- [warm-up activities specific to this session's focus]

## Session

| Exercise | Sets | Reps | Weight | Rest | Notes |
|----------|------|------|--------|------|-------|
| Exercise Name | 3 | 8-10 | 62.5 kg | 90s | Up from 60 kg — hit 10 reps last session |

## Progression Notes
Brief explanation of weight decisions (2-4 bullet points max).

## Cooldown (5 min)
- [stretches targeting this session's muscle groups]
```

## Rules

- **Weight column**: always a specific value (e.g. "60 kg", "25 lb DBs") — never "moderate", "as needed", or a range
- **Notes column**: if increasing load, show the previous weight; if holding load, state the target RPE or RIR
- If no log exists for an exercise, write "Est. starting weight" in Notes
- Date should be the next logical training day based on the log (account for rest days in the profile)
- Rep target should be specific (e.g. "8" not "8-10") when progressing from a known log entry; use a range only when the client is new to the exercise
- Warm-up and cooldown must be specific to the muscle groups trained that session

## Archive

Each generated workout is written to two locations:
1. `next-workout.md` (root) — the working copy the client takes to the gym. The client may edit this before their session.
2. `next-workouts/<DATE>-<focus-slug>.md` — the permanent "as prescribed" archive copy.

Archive filenames use the **generation date** (the date the skill was run), not the planned workout date, since actual training days often shift. The planned date stays in the frontmatter.

Example: a squat-focus workout generated on 2026-03-18 for a planned 2026-03-20 session → `next-workouts/2026-03-18-squat-pull-focus.md`
