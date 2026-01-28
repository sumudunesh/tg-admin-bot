import os, time, threading
from flask import Flask, request
from telegram import Update
from telegram.constants import ChatPermissions
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = set(int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip())

# Demo store (memory). For real use, DB needed.
TEMP_ACCESS = {}  # (chat_id, user_id) -> expiry_unix
LINK_LOCK = True

app = Flask(__name__)
tg_app = Application.builder().token(BOT_TOKEN).build()

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Admin bot active. /help බලන්න.")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Admins only commands:\n"
        "/approve <reply> <minutes>  (ex: reply to user then /approve 30)\n"
        "/remove <reply>\n"
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
    if not update.message.reply_to_message:
        return await update.message.reply_text("User msg එකකට reply වෙලා: /approve 30 කියලා දාන්න.")
    if not context.args:
        return await update.message.reply_text("Minutes දෙන්න. Example: /approve 30")

    minutes = int(context.args[0])
    chat_id = update.effective_chat.id
    user = update.message.reply_to_message.from_user
    user_id = user.id

    perms = ChatPermissions(
        can_send_messages=True,
        can_send_media_messages=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
        can_change_info=False,
        can_invite_users=False,
        can_pin_messages=False,
    )
    await context.bot.restrict_chat_member(chat_id, user_id, permissions=perms)

    expiry = int(time.time()) + minutes * 60
    TEMP_ACCESS[(chat_id, user_id)] = expiry

    await update.message.reply_text(f"✅ {user.first_name} approved for {minutes} min.")

async def remove_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not update.message.reply_to_message:
        return await update.message.reply_text("User msg එකකට reply වෙලා: /remove කියලා දාන්න.")
    chat_id = update.effective_chat.id
    user_id = update.message.reply_to_message.from_user.id
    await context.bot.ban_chat_member(chat_id, user_id)
    await update.message.reply_text("🚫 Removed.")

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

def expiry_worker():
    while True:
        now = int(time.time())
        expired = [k for k, v in TEMP_ACCESS.items() if v <= now]
        for chat_id, user_id in expired:
            try:
                # remove user when time ends
                tg_app.bot.ban_chat_member(chat_id, user_id)
            except:
                pass
            TEMP_ACCESS.pop((chat_id, user_id), None)
        time.sleep(30)

@tg_app.post_init
async def on_start(_: Application):
    threading.Thread(target=expiry_worker, daemon=True).start()

tg_app.add_handler(CommandHandler("start", start))
tg_app.add_handler(CommandHandler("help", help_cmd))
tg_app.add_handler(CommandHandler("approve", approve))
tg_app.add_handler(CommandHandler("remove", remove_user))
tg_app.add_handler(CommandHandler("locklinks", locklinks))
tg_app.add_handler(CommandHandler("unlocklinks", unlocklinks))
tg_app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), anti_link))

@app.route("/", methods=["GET"])
def home():
    return "OK", 200

@app.route("/webhook", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), tg_app.bot)
    tg_app.update_queue.put_nowait(update)
    return "OK", 200
