import os
import time
import threading
from flask import Flask, request

from telegram import Update, ChatPermissions
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = set(int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip())

LINK_LOCK = True
TEMP_ACCESS = {}  # (chat_id, user_id) -> expiry_unix

app = Flask(__name__)

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# ---- Telegram handlers ----
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Admin bot active. /help")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Admins only:\n"
        "/approve (reply) <minutes>  e.g. reply to user then /approve 30\n"
        "/remove (reply)\n"
        "/locklinks\n"
        "/unlocklinks\n"
    )

async def locklinks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global LINK_LOCK
    if not is_admin(update.effective_user.id):
        return
    LINK_LOCK = True
    await update.message.reply_text("🔒 Link block ON")

async def unlocklinks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global LINK_LOCK
    if not is_admin(update.effective_user.id):
        return
    LINK_LOCK = False
    await update.message.reply_text("🔓 Link block OFF")

async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not update.message.reply_to_message or not context.args:
        return await update.message.reply_text("Reply to user → /approve 30")

    minutes = int(context.args[0])
    chat_id = update.effective_chat.id
    user = update.message.reply_to_message.from_user

    perms = ChatPermissions(can_send_messages=True)
    await context.bot.restrict_chat_member(chat_id, user.id, permissions=perms)

    TEMP_ACCESS[(chat_id, user.id)] = int(time.time()) + minutes * 60
    await update.message.reply_text(f"✅ {user.first_name} approved for {minutes} minutes")

async def remove_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not update.message.reply_to_message:
        return await update.message.reply_text("Reply to user message → /remove")
    chat_id = update.effective_chat.id
    user_id = update.message.reply_to_message.from_user.id
    await context.bot.ban_chat_member(chat_id, user_id)
    await update.message.reply_text("🚫 Removed")

async def anti_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not LINK_LOCK:
        return
    msg = update.message
    if not msg or not msg.text:
        return
    text = msg.text.lower()
    if "http://" in text or "https://" in text or "t.me/" in text or "www." in text:
        if msg.from_user and is_admin(msg.from_user.id):
            return
        try:
            await msg.delete()
        except:
            pass

def expiry_worker(tg_app: Application):
    while True:
        now = int(time.time())
        expired = [(k, v) for k, v in TEMP_ACCESS.items() if v <= now]
        for (chat_id, user_id), _ in expired:
            try:
                tg_app.bot.ban_chat_member(chat_id, user_id)
            except:
                pass
            TEMP_ACCESS.pop((chat_id, user_id), None)
        time.sleep(30)

# ---- Build telegram app (NO Updater hacks) ----
tg_app = Application.builder().token(BOT_TOKEN).build()
tg_app.add_handler(CommandHandler("start", start))
tg_app.add_handler(CommandHandler("help", help_cmd))
tg_app.add_handler(CommandHandler("approve", approve))
tg_app.add_handler(CommandHandler("remove", remove_user))
tg_app.add_handler(CommandHandler("locklinks", locklinks))
tg_app.add_handler(CommandHandler("unlocklinks", unlocklinks))
tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, anti_link))

# ---- Flask routes ----
@app.get("/")
def home():
    return "OK", 200

@app.post("/webhook")
def webhook():
    # Telegram sends JSON updates here
    data = request.get_json(force=True)
    update = Update.de_json(data, tg_app.bot)
    # process update in event loop safely
    tg_app.create_task(tg_app.process_update(update))
    return "OK", 200

def main():
    # start expiry thread
    threading.Thread(target=expiry_worker, args=(tg_app,), daemon=True).start()

    # IMPORTANT: start PTB application (initializes bot)
    tg_app.initialize()
    tg_app.start()

    # Bind to Render PORT
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
