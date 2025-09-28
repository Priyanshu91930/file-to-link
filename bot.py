import os
import logging
import time
import json
import pysftp # Library for secure file transfer
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.error import TelegramError

# --- Configuration ---
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL") # Should be the base URL, e.g., https://file-to-link-1.onrender.com
PORT = int(os.getenv("PORT", "8000"))
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

# --- SFTP Configuration (from Hostinger SSH Access) ---
SFTP_HOST = os.getenv("FTP_HOST")
SFTP_USER = os.getenv("FTP_USER")
SFTP_PASS = os.getenv("FTP_PASS")
SFTP_PATH = os.getenv("FTP_PATH") # e.g., /public_html/files
PUBLIC_URL_BASE = os.getenv("PUBLIC_URL_BASE") # e.g., https://yourdomain.com/files

CHANNELS_FILE = "channels.json"

# --- Logging ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Channel Management ---
def load_channels() -> list:
    try:
        with open(CHANNELS_FILE, "r") as f: return json.load(f)
    except FileNotFoundError: return []

def save_channels(channels: list):
    with open(CHANNELS_FILE, "w") as f: json.dump(channels, f, indent=4)

# --- Real Upload Function ---
def upload_file_to_hosting(local_path: str, remote_filename: str) -> str:
    if not all([SFTP_HOST, SFTP_USER, SFTP_PASS, SFTP_PATH, PUBLIC_URL_BASE]):
        logger.error("SFTP environment variables are not fully configured!")
        raise ValueError("Server-side hosting is not configured.")

    cnopts = pysftp.CnOpts()
    cnopts.hostkeys = None
    remote_filepath = f"{SFTP_PATH}/{remote_filename}"
    
    try:
        logger.info(f"Connecting to SFTP host: {SFTP_HOST}")
        # We explicitly connect to port 22 for SFTP
        with pysftp.Connection(host=SFTP_HOST, username=SFTP_USER, password=SFTP_PASS, port=22, cnopts=cnopts) as sftp:
            logger.info(f"Uploading {local_path} to {remote_filepath}")
            sftp.put(local_path, remote_filepath)
            logger.info("Upload successful.")
        
        public_url = f"{PUBLIC_URL_BASE}/{remote_filename}"
        return public_url
    except Exception as e:
        logger.error(f"SFTP upload failed: {e}", exc_info=True)
        raise e

# --- Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_html(f"Hi {update.effective_user.mention_html()}! Send me a file (under 20MB).")

async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != OWNER_ID: return
    if not context.args: await update.message.reply_text("Usage: /addchannel @username"); return
    channel = context.args[0]
    channels = load_channels()
    if channel not in channels:
        channels.append(channel); save_channels(channels)
        await update.message.reply_text(f"Added {channel}.")
    else: await update.message.reply_text(f"{channel} is already in the list.")

async def del_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != OWNER_ID: return
    if not context.args: await update.message.reply_text("Usage: /delchannel @username"); return
    channel = context.args[0]
    channels = load_channels()
    if channel in channels:
        channels.remove(channel); save_channels(channels)
        await update.message.reply_text(f"Removed {channel}.")
    else: await update.message.reply_text(f"{channel} not found.")

async def list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != OWNER_ID: return
    channels = load_channels()
    if channels: await update.message.reply_text("Required channels:\n" + "\n".join(channels))
    else: await update.message.reply_text("No channels required.")

# --- Media and Callback Handlers ---
async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    required_channels = load_channels()
    if required_channels:
        user_id = update.effective_user.id
        not_subscribed = []
        for channel in required_channels:
            try:
                member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
                if member.status not in ["member", "administrator", "creator"]: not_subscribed.append(channel)
            except TelegramError: not_subscribed.append(channel)
        
        if not_subscribed:
            buttons = [[InlineKeyboardButton(f"Join {c}", url=f"https://t.me/{c.lstrip('@')}")] for c in not_subscribed]
            buttons.append([InlineKeyboardButton("✅ I have joined", callback_data="check_subscription")])
            await update.message.reply_text("Please join our channel(s) to use this bot:", reply_markup=InlineKeyboardMarkup(buttons))
            return

    message = update.message
    file, file_name = (message.video, message.video.file_name or f"video_{int(time.time())}.mp4") if message.video else (message.document, message.document.file_name or f"file_{int(time.time())}.bin")
    if not file: return

    processing_msg = await message.reply_text("Downloading...")
    temp_file_path = os.path.join("/tmp", file_name)
    try:
        tg_file = await file.get_file()
        await tg_file.download_to_drive(temp_file_path)
        await processing_msg.edit_text("Uploading...")
        direct_link = upload_file_to_hosting(temp_file_path, file_name)
        await processing_msg.edit_text(f"✅ Your direct link is ready:\n\n{direct_link}")
    except ValueError as ve: await processing_msg.edit_text(f"Error: {ve}")
    except Exception as e:
        logger.error(f"Error processing file {file_name}: {e}", exc_info=True)
        await processing_msg.edit_text("Sorry, an error occurred while processing your file.")
    finally:
        if os.path.exists(temp_file_path): os.remove(temp_file_path)

async def check_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    # Logic to re-check subscription... (omitted for brevity, can be added back if needed)
    await query.edit_message_text("Thanks! Please send your file again.")

# --- Bot Initialization ---
async def post_init(application: Application) -> None:
    commands = [ BotCommand("start", "Start the bot"), BotCommand("addchannel", "Add channel (Admin)"), BotCommand("delchannel", "Remove channel (Admin)"), BotCommand("listchannels", "List channels (Admin)") ]
    await application.bot.set_my_commands(commands)
    logger.info("Custom bot commands set.")

def main() -> None:
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("addchannel", add_channel))
    application.add_handler(CommandHandler("delchannel", del_channel))
    application.add_handler(CommandHandler("listchannels", list_channels))
    application.add_handler(MessageHandler(filters.VIDEO | filters.Document.ALL, handle_media))
    application.add_handler(CallbackQueryHandler(check_subscription_callback, pattern="^check_subscription$"))

    if WEBHOOK_URL:
        url_path = "webhook"
        full_webhook_url = f"{WEBHOOK_URL.rstrip('/')}/{url_path}"
        logger.info(f"Setting up webhook: {full_webhook_url}")
        application.run_webhook(listen="0.0.0.0", port=PORT, url_path=url_path, webhook_url=full_webhook_url)
    else:
        logger.warning("No WEBHOOK_URL set, running in polling mode.")
        application.run_polling()

if __name__ == "__main__":
    main()
