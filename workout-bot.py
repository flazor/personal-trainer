import asyncio
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    MessageReactionHandler,
    filters,
)


DATA_DIR = Path(__file__).parent
TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

sessions: Dict[int, dict] = {}


def git_pull():
    result = subprocess.run(
        ["git", "pull", "--rebase"],
        cwd=DATA_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"git pull warning: {result.stderr.strip()}")


def git_push_log(log_path: Path):
    git_pull()
    for cmd in [
        ["git", "add", str(log_path)],
        ["git", "commit", "-m", f"Add workout log {log_path.name}"],
        ["git", "push"],
    ]:
        result = subprocess.run(cmd, cwd=DATA_DIR, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"git warning ({cmd[1]}): {result.stderr.strip()}")
            break


def parse_workout(text: str) -> dict:
    result = {
        "frontmatter": {},
        "title": "",
        "warmup": "",
        "exercises": [],
        "cooldown": "",
    }

    fm_match = re.match(r'^---\n(.*?)\n---\n', text, re.DOTALL)
    if fm_match:
        for line in fm_match.group(1).strip().split('\n'):
            if ':' in line:
                key, val = line.split(':', 1)
                result["frontmatter"][key.strip()] = val.strip().strip('"')
        text = text[fm_match.end():]

    title_match = re.search(r'^# (.+)$', text, re.MULTILINE)
    if title_match:
        result["title"] = title_match.group(1).strip()

    sections = re.split(r'^## ', text, flags=re.MULTILINE)
    for section in sections:
        lower = section.lower()
        if lower.startswith('warm'):
            result["warmup"] = section.split('\n', 1)[1].strip() if '\n' in section else ""
        elif lower.startswith('session'):
            for line in section.strip().split('\n'):
                if line.startswith('|') and not line.startswith('|--'):
                    cols = [c.strip() for c in line.split('|')[1:-1]]
                    if len(cols) >= 6 and cols[0] != 'Exercise':
                        result["exercises"].append({
                            "name": cols[0],
                            "sets": cols[1],
                            "reps": cols[2],
                            "weight": cols[3],
                            "rest": cols[4],
                            "notes": cols[5],
                        })
        elif lower.startswith('cool'):
            result["cooldown"] = section.split('\n', 1)[1].strip() if '\n' in section else ""

    return result


def format_exercise(ex: dict, idx: int, total: int) -> str:
    lines = [
        f"-- Exercise {idx}/{total}: {ex['name']} --",
        f"{ex['sets']} sets x {ex['reps']} @ {ex['weight']}",
        f"Rest: {ex['rest']}",
    ]
    if ex["notes"]:
        lines.append(ex["notes"])
    return "\n".join(lines)


def build_log(session: dict) -> str:
    workout = session["workout"]
    fm = workout["frontmatter"]
    title = workout["title"].replace("Next Workout: ", "")
    started = session["started_at"]

    lines = ["---"]
    lines.append(f"date: {started.strftime('%Y-%m-%d')}")
    lines.append(f"time: {started.strftime('%H:%M')}")
    if fm.get("session"):
        lines.append(f"session: \"{fm['session']}\"")
    if fm.get("plan_week"):
        lines.append(f"plan_week: {fm['plan_week']}")
    lines.append("---")
    lines.append("")
    lines.append(f"# Workout Log: {title}")
    lines.append("")
    lines.append("## Warm-Up")
    lines.append("")
    lines.append(workout.get("warmup") or "As prescribed")
    lines.append("")
    lines.append("## Session")
    lines.append("")
    lines.append("| Exercise | Sets x Reps | Weight | Result | Notes |")
    lines.append("|----------|-------------|--------|--------|-------|")

    for idx, ex in enumerate(workout["exercises"]):
        replies = session["results"].get(idx, [])
        result = " / ".join(replies) if replies else "skipped"
        lines.append(
            f"| {ex['name']} | {ex['sets']}x{ex['reps']} "
            f"| {ex['weight']} | {result} | |"
        )

    lines.append("")
    lines.append("## Notes")
    lines.append("")
    if session["notes"]:
        for note in session["notes"]:
            lines.append(note)
            lines.append("")
    else:
        lines.append("")

    lines.append("## Transcript")
    lines.append("")
    for event in session["transcript"]:
        lines.append(event)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


async def cmd_workout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.to_thread(git_pull)
    chat_id = update.effective_chat.id

    if chat_id in sessions:
        await update.message.reply_text("Session already active. Send /quit to end it first.")
        return

    path = DATA_DIR / "next-workout.md"
    if not path.exists():
        await update.message.reply_text("No next-workout.md found. Run the personal-trainer skill first.")
        return

    workout = parse_workout(path.read_text())
    if not workout["exercises"]:
        await update.message.reply_text("Couldn't parse exercises from next-workout.md.")
        return

    session = {
        "workout": workout,
        "started_at": datetime.now(),
        "exercise_msg_ids": {},  # telegram message_id -> exercise idx
        "results": {},  # exercise idx -> [reply text, ...]
        "notes": [],
        "transcript": [],
        "phase": "active",  # "active" | "confirming_skip"
        "done_prompted": False,
    }
    sessions[chat_id] = session

    exercise_list = "\n".join(
        f"  {i+1}. {ex['name']}" for i, ex in enumerate(workout["exercises"])
    )
    overview = (
        f"{workout['title']}\n\n"
        f"Warm-up:\n{workout['warmup']}\n\n"
        f"Reply to each exercise message with your results. "
        f"Free-text messages become notes. Send /done when finished."
    )
    await update.message.reply_text(overview)
    session["transcript"].append(f"**Bot:** {overview}")

    for idx, ex in enumerate(workout["exercises"]):
        text = format_exercise(ex, idx + 1, len(workout["exercises"]))
        sent = await update.message.reply_text(text)
        session["exercise_msg_ids"][sent.message_id] = idx
        session["transcript"].append(f"**Bot:** {text}")


async def cmd_quit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text("Session discarded.")
    sessions.pop(chat_id, None)


async def cmd_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = sessions.get(chat_id)

    if not session:
        await update.message.reply_text("No active session. Start one with /workout.")
        return

    unresponded = [
        ex for idx, ex in enumerate(session["workout"]["exercises"])
        if idx not in session["results"]
    ]

    if unresponded and session["phase"] != "confirming_skip":
        names = "\n".join(f"  - {ex['name']}" for ex in unresponded)
        msg = (
            f"These exercises haven't been logged:\n{names}\n\n"
            f"Reply to add results, or send /done again to mark them skipped."
        )
        await update.message.reply_text(msg)
        session["transcript"].append(f"**Bot:** {msg}")
        session["phase"] = "confirming_skip"
        return

    log_text = build_log(session)
    started = session["started_at"]
    log_path = DATA_DIR / "log" / f"{started.strftime('%Y-%m-%d-%H%M')}.md"
    log_path.parent.mkdir(exist_ok=True)
    log_path.write_text(log_text)
    await asyncio.to_thread(git_push_log, log_path)
    await update.message.reply_text(f"Logged to {log_path.name}.")
    sessions.pop(chat_id, None)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = sessions.get(chat_id)

    if not session:
        await update.message.reply_text("Send /workout to start your session.")
        return

    text = update.message.text or ""
    reply_to = update.message.reply_to_message

    if reply_to and reply_to.message_id in session["exercise_msg_ids"]:
        idx = session["exercise_msg_ids"][reply_to.message_id]
        ex_name = session["workout"]["exercises"][idx]["name"]
        session["results"].setdefault(idx, []).append(text)
        session["transcript"].append(f"**Tim** (re: {ex_name}): {text}")
    else:
        session["notes"].append(text)
        session["transcript"].append(f"**Tim:** {text}")

    # New input may resolve a previously-unresponded exercise — re-prompt on next /done
    session["phase"] = "active"
    await maybe_prompt_done(update, session)


async def maybe_prompt_done(update: Update, session: dict):
    if session["done_prompted"]:
        return
    total = len(session["workout"]["exercises"])
    if len(session["results"]) < total:
        return
    msg = "All exercises logged. Tap /done to save."
    await update.effective_chat.send_message(msg)
    session["transcript"].append(f"**Bot:** {msg}")
    session["done_prompted"] = True


def _emojis(reactions) -> set:
    out = set()
    for r in reactions or []:
        emoji = getattr(r, "emoji", None)
        if emoji:
            out.add(emoji)
    return out


async def handle_reaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = sessions.get(chat_id)
    if not session:
        return

    reaction = update.message_reaction
    if not reaction:
        return

    msg_id = reaction.message_id
    if msg_id not in session["exercise_msg_ids"]:
        return

    added = _emojis(reaction.new_reaction) - _emojis(reaction.old_reaction)
    if not added:
        return

    idx = session["exercise_msg_ids"][msg_id]
    ex_name = session["workout"]["exercises"][idx]["name"]
    emoji_str = " ".join(sorted(added))
    session["results"].setdefault(idx, []).append(emoji_str)
    session["transcript"].append(f"**Tim** (reaction on {ex_name}): {emoji_str}")
    session["phase"] = "active"
    await maybe_prompt_done(update, session)


app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
app.add_handler(CommandHandler("workout", cmd_workout))
app.add_handler(CommandHandler("done", cmd_done))
app.add_handler(CommandHandler("quit", cmd_quit))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
app.add_handler(MessageReactionHandler(handle_reaction))

print("Bot running...")
app.run_polling(allowed_updates=Update.ALL_TYPES)
