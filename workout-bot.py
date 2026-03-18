import httpx
import json
import asyncio
import os
from datetime import datetime
from pathlib import Path
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters
from telegram.constants import ChatAction
from typing import Optional, Dict, List

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


# Per-chat conversation history
conversation_history: Dict[int, List] = {}


def load_workout() -> Optional[str]:
    path = DATA_DIR / "next-workout.md"
    return path.read_text() if path.exists() else None


def build_system_prompt(workout: str) -> str:
    return f"""You are a personal trainer coaching Tim through his gym session via Telegram. Be brief — he's at the gym.

Today's workout:
{workout}

Guide him through the session:
1. Start by briefly listing today's exercises (no weights yet) and a bullet-point summary of the warmup. Prompt for confirmation that warmup is complete.
2. Introduce one exercise at a time: tell him the sets, reps, weight, rest time between sets and important cues to do the exercise correctly. Wait for him to report results after he has attempted all the sets.
3. After each result, give brief feedback (one sentence). Note if he struggled or missed reps.
4. Move to the next exercise. Keep it moving.
5. When all exercises are done, tell him to send /done to save his log.

Accept any result format: "y", "done", "5/5/5", "got 4 on the last set", "10kg each side", etc.
Keep every message short. No long paragraphs."""


def build_log_prompt() -> str:
    return """Based on our conversation, write a workout log in this exact format — nothing else, no commentary:

Warm-up

[what he did, one item per line]

[Exercise Name]

[sets x reps x weight as reported, one set per line]

[Next Exercise]

[etc.]

Notes

[One sentence about how it went. If nothing notable, write "Felt good."]

Only include exercises Tim actually completed and reported. Use the exact weights he mentioned. No bullet points or dashes."""


async def stream_to_telegram(update: Update, context: ContextTypes.DEFAULT_TYPE, messages: list) -> str:
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


async def cmd_workout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.to_thread(git_pull)
    chat_id = update.effective_chat.id
    workout = load_workout()
    if not workout:
        await update.message.reply_text("No next-workout.md found. Run the personal-trainer skill first.")
        return

    conversation_history[chat_id] = [
        {"role": "system", "content": build_system_prompt(workout)},
        {"role": "user", "content": "Let's go."},
    ]

    reply = await stream_to_telegram(update, context, conversation_history[chat_id])
    conversation_history[chat_id].append({"role": "assistant", "content": reply})


async def cmd_quit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text("Bye!")
    conversation_history.pop(chat_id, None)


async def cmd_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    history = conversation_history.get(chat_id)

    if not history:
        await update.message.reply_text("No active session. Start one with /workout.")
        return

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    log_messages = history + [{"role": "user", "content": build_log_prompt()}]
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            OLLAMA_URL,
            json={"model": MODEL, "messages": log_messages, "stream": False}
        )
    log_text = response.json().get("message", {}).get("content", "").strip()

    date_str = datetime.now().strftime("%Y-%m-%d")
    log_path = DATA_DIR / "log" / f"{date_str}-gym.md"
    log_path.parent.mkdir(exist_ok=True)
    log_path.write_text(log_text)
    await asyncio.to_thread(git_push_log, log_path)
    await update.message.reply_text(f"Logged to {log_path.name}. Nice work!")
    conversation_history.pop(chat_id, None)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if chat_id not in conversation_history:
        await update.message.reply_text("Send /workout to start your session.")
        return

    history = conversation_history[chat_id]
    history.append({"role": "user", "content": update.message.text})

    reply = await stream_to_telegram(update, context, history)
    history.append({"role": "assistant", "content": reply})


app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
app.add_handler(CommandHandler("workout", cmd_workout))
app.add_handler(CommandHandler("done", cmd_done))
app.add_handler(CommandHandler("quit", cmd_quit))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("Bot running...")
app.run_polling()
