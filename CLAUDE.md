# Personal Trainer

AI-assisted personal training data and workout programming.

## What This Is

A personal fitness repo containing training profiles, workout logs, and a Claude Code skill that generates training plans and next-workout briefs. Not a software project — no build, lint, or test commands.

## Structure

```
training-profile.md    # Tim's profile (goals, injuries, equipment, schedule)
training-plan.md       # Current macro training plan
next-workout.md        # Working copy of the next session (editable)
next-workouts/         # Archive of all generated workout briefs (YYYY-MM-DD-focus.md)
gym-log.md             # Index of logged workouts
log/                   # Individual workout logs (YYYY-MM-DD-*.md)
clients/               # Other training contexts (baseball, robbie, practical-exam)
.claude/skills/        # Claude Code skill for plan generation
```

## Conventions

- Log filenames: `YYYY-MM-DD-description.md` (e.g., `2026-03-03-gym.md`)
- Plain markdown — no wiki-links or Obsidian syntax
- Frontmatter (YAML) is used in plans and workouts for metadata (date, week, session type)
- Write notes as if they will be used as LLM context: be explicit, avoid ambiguous pronouns

## Skill Usage

Run `/personal-trainer` from the repo root to generate or update the next workout.

Run `/personal-trainer "feedback text"` to revise the training plan with specific feedback, then regenerate the next workout.

Run `/personal-trainer clients/baseball/training-profile.md` to target a specific client profile.
