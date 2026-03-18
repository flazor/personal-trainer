import httpx
import json
import asyncio
import os
import re
from datetime import datetime
from pathlib import Path
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters
from telegram.constants import ChatAction
from typing import Dict

import subprocess


def git_pull():
    result = subprocess.run(
        ["git", "pull", "--rebase"],
        cwd=DATA_DIR,
        capture_output=True,
        text=True
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

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "llama3.1:8b"
TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
DATA_DIR = Path(__file__).parent  # repo root; run from anywhere


# Per-chat session state
sessions: Dict[int, dict] = {}


def parse_workout(text: str) -> dict:
    """Parse next-workout.md into structured exercises, warm-up, and cooldown."""
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
    """Format a single exercise for display in Telegram."""
    lines = [
        f"-- Exercise {idx}/{total}: {ex['name']} --",
        f"{ex['sets']} sets x {ex['reps']} @ {ex['weight']}",
        f"Rest: {ex['rest']}",
    ]
    if ex["notes"]:
        lines.append(ex["notes"])
    return "\n".join(lines)


def build_coaching_prompt(workout: dict) -> str:
    """System prompt scoped to coaching only — no exercise presentation."""
    exercises = ", ".join(ex["name"] for ex in workout["exercises"])
    return f"""You are a personal trainer coaching Tim through his gym session via Telegram. Be brief — he's at the gym.

Today's session: {workout['title']}
Exercises: {exercises}

Rules:
- When asked for a coaching cue, give ONE brief tip for that exercise. One or two sentences max.
- When Tim reports results, give brief feedback (one sentence). Note if he struggled or missed reps.
- Do NOT restate sets, reps, or weights — those are shown separately.
- Keep every message short."""


def build_log(session: dict, notes: str = "") -> str:
    """Build a structured workout log from session data."""
    workout = session["workout"]
    fm = workout["frontmatter"]
    title = workout["title"].replace("Next Workout: ", "")

    lines = ["---"]
    lines.append(f"date: {fm.get('date', datetime.now().strftime('%Y-%m-%d'))}")
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

    completed_names = set()
    for ex, result_text in session["results"]:
        completed_names.add(ex["name"])
        lines.append(
            f"| {ex['name']} | {ex['sets']}x{ex['reps']} "
            f"| {ex['weight']} | {result_text} | |"
        )

    for ex in workout["exercises"]:
        if ex["name"] not in completed_names:
            lines.append(
                f"| {ex['name']} | {ex['sets']}x{ex['reps']} "
                f"| {ex['weight']} | skipped | |"
            )

    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append(notes)
    lines.append("")

    return "\n".join(lines)


async def chat_llm(messages: list) -> str:
    """Non-streaming LLM call for short responses."""
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            OLLAMA_URL,
            json={"model": MODEL, "messages": messages, "stream": False}
        )
    return response.json().get("message", {}).get("content", "").strip()


async def stream_to_telegram(update: Update, context: ContextTypes.DEFAULT_TYPE, messages: list) -> str:
    """Stream an LLM response to Telegram with live message updates."""
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    accumulated_text = ""
    sent_message = None
    last_edit_time = asyncio.get_event_loop().time()
    last_typing_time = last_edit_time

    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream("POST", OLLAMA_URL, json={"model": MODEL, "messages": messages, "stream": True}) as response:
            async for line in response.aiter_lines():
                if not line:
                    continue
                data = json.loads(line)
                accumulated_text += data.get("message", {}).get("content", "")

                now = asyncio.get_event_loop().time()

                if now - last_typing_time > 4:
                    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
                    last_typing_time = now

                if sent_message is None and len(accumulated_text) > 80:
                    sent_message = await update.message.reply_text(accumulated_text)
                    last_edit_time = now
                elif sent_message and now - last_edit_time > 2:
                    try:
                        await sent_message.edit_text(accumulated_text)
                        last_edit_time = now
                    except Exception:
                        pass

                if data.get("done"):
                    break

    if sent_message is None:
        await update.message.reply_text(accumulated_text)
    else:
        try:
            await sent_message.edit_text(accumulated_text)
        except Exception:
            pass

    return accumulated_text


async def send_next_exercise(update: Update, context: ContextTypes.DEFAULT_TYPE, session: dict):
    """Send the next exercise verbatim, then stream a coaching cue from the LLM."""
    idx = session["exercise_idx"]
    exercises = session["workout"]["exercises"]

    if idx >= len(exercises):
        await update.message.reply_text("All exercises done! Send /done to save your log.")
        session["phase"] = "complete"
        return

    ex = exercises[idx]
    await update.message.reply_text(format_exercise(ex, idx + 1, len(exercises)))

    session["history"].append({"role": "user", "content": f"Brief coaching cue for {ex['name']}."})
    cue = await stream_to_telegram(update, context, session["history"])
    session["history"].append({"role": "assistant", "content": cue})

    session["phase"] = "awaiting_result"


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

    sessions[chat_id] = {
        "workout": workout,
        "exercise_idx": 0,
        "phase": "warmup",
        "results": [],
        "history": [
            {"role": "system", "content": build_coaching_prompt(workout)},
        ],
    }

    exercise_list = "\n".join(
        f"  {i+1}. {ex['name']}" for i, ex in enumerate(workout["exercises"])
    )
    overview = (
        f"{workout['title']}\n\n"
        f"{exercise_list}\n\n"
        f"Warm-up:\n{workout['warmup']}\n\n"
        f"Let me know when you're warmed up."
    )
    await update.message.reply_text(overview)


async def cmd_quit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text("Bye!")
    sessions.pop(chat_id, None)


async def cmd_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = sessions.get(chat_id)

    if not session:
        await update.message.reply_text("No active session. Start one with /workout.")
        return

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    session["history"].append({
        "role": "user",
        "content": "Summarize today's session in one sentence for the workout log."
    })
    notes = await chat_llm(session["history"])

    log_text = build_log(session, notes=notes)

    date_str = datetime.now().strftime("%Y-%m-%d")
    log_path = DATA_DIR / "log" / f"{date_str}-gym.md"
    log_path.parent.mkdir(exist_ok=True)
    log_path.write_text(log_text)
    await asyncio.to_thread(git_push_log, log_path)
    await update.message.reply_text(f"Logged to {log_path.name}. Nice work!")
    sessions.pop(chat_id, None)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = sessions.get(chat_id)

    if not session:
        await update.message.reply_text("Send /workout to start your session.")
        return

    text = update.message.text
    phase = session["phase"]

    if phase == "warmup":
        await send_next_exercise(update, context, session)

    elif phase == "awaiting_result":
        if "?" in text:
            # Question — pass to LLM, stay on current exercise
            session["history"].append({"role": "user", "content": text})
            reply = await stream_to_telegram(update, context, session["history"])
            session["history"].append({"role": "assistant", "content": reply})
        elif text.strip().lower() in ("skip", "next"):
            session["exercise_idx"] += 1
            await send_next_exercise(update, context, session)
        else:
            # Result report
            ex = session["workout"]["exercises"][session["exercise_idx"]]
            session["results"].append((ex, text))

            session["history"].append({
                "role": "user",
                "content": f"Result for {ex['name']} ({ex['sets']}x{ex['reps']} @ {ex['weight']}): {text}"
            })
            feedback = await stream_to_telegram(update, context, session["history"])
            session["history"].append({"role": "assistant", "content": feedback})

            session["exercise_idx"] += 1
            await send_next_exercise(update, context, session)

    elif phase == "complete":
        await update.message.reply_text("Session's done. Send /done to save or /quit to discard.")

    else:
        session["history"].append({"role": "user", "content": text})
        reply = await stream_to_telegram(update, context, session["history"])
        session["history"].append({"role": "assistant", "content": reply})


app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
app.add_handler(CommandHandler("workout", cmd_workout))
app.add_handler(CommandHandler("done", cmd_done))
app.add_handler(CommandHandler("quit", cmd_quit))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("Bot running...")
app.run_polling()
