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
log/                   # Individual workout logs (YYYY-MM-DD-HHMM.md, written by the bot)
clients/               # Other training contexts (baseball, practical-exam)
workout-bot.py         # Telegram bot that captures gym sessions and writes log files
scripts/               # Automation scripts (next-workout PR generation)
.claude/skills/        # Claude Code skill for plan generation
```

## Conventions

- Log filenames: `YYYY-MM-DD-HHMM.md` (timestamp of session start; supports multiple sessions per day)
- Plain markdown — no wiki-links or Obsidian syntax
- Frontmatter (YAML) is used in plans, workouts, and logs for metadata (date, time, week, session type)
- Write notes as if they will be used as LLM context: be explicit, avoid ambiguous pronouns

## Workflow

1. **In the gym** — send `/workout` to the Telegram bot. It posts the warm-up plus one message per exercise; reply or react (e.g. 👍) to each one with results. Free-text messages become session notes. Send `/done` (the bot prompts you with a tappable link once everything is logged) and the log is committed and pushed.
2. **Generate next workout** — run `scripts/generate-next-workout.sh` on a machine with `claude` and `gh` authenticated. It branches, runs the `/personal-trainer` skill against the latest log, and opens a PR.
3. **Review and merge** the PR.

The bot is intentionally LLM-free — it captures the raw conversation as ground truth (in a `## Transcript` section of each log) so the planning skill can mine equipment swaps, RPE cues, and out-of-order changes without confabulation.

## Skill Usage

Run `/personal-trainer` from the repo root to generate or update the next workout.

Run `/personal-trainer "feedback text"` to revise the training plan with specific feedback, then regenerate the next workout.

Run `/personal-trainer clients/baseball/training-profile.md` to target a specific client profile.
