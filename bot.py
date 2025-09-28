import os
import logging
import time
import json
import pysftp
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes,
    ConversationHandler
)
from telegram.error import TelegramError

# --- Configuration and Setup (unchanged) ---
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", "8000"))
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
SFTP_HOST = os.getenv("FTP_HOST")
SFTP_USER = os.getenv("FTP_USER")
SFTP_PASS = os.getenv("FTP_PASS")
SFTP_PATH = os.getenv("FTP_PATH")
PUBLIC_URL_BASE = os.getenv("PUBLIC_URL_BASE")
CHANNELS_FILE = "channels.json"
AWAITING_FORWARD = range(1)
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Helper and Upload Functions (unchanged) ---
def load_channels():
    try:
        with open(CHANNELS_FILE, "r") as f: return json.load(f)
    except FileNotFoundError: return []
def save_channels(channels):
    with open(CHANNELS_FILE, "w") as f: json.dump(channels, f, indent=4)

def upload_file_with_progress(local_path: str, remote_filename: str, callback_func) -> str:
    missing_vars = [var for var, val in {"FTP_HOST": SFTP_HOST, "FTP_USER": SFTP_USER, "FTP_PASS": SFTP_PASS, "FTP_PATH": SFTP_PATH, "PUBLIC_URL_BASE": PUBLIC_URL_BASE}.items() if not val]
    if missing_vars:
        raise ValueError(f"Server hosting misconfigured. Missing: {', '.join(missing_vars)}")
    cnopts = pysftp.CnOpts(); cnopts.hostkeys = None
    remote_filepath = f"{SFTP_PATH.rstrip('/')}/{remote_filename}"
    try:
        with pysftp.Connection(host=SFTP_HOST, username=SFTP_USER, password=SFTP_PASS, port=22, cnopts=cnopts) as sftp:
            sftp.put(local_path, remote_filepath, callback=callback_func)
        return f"{PUBLIC_URL_BASE.rstrip('/')}/{remote_filename}"
    except pysftp.AuthenticationException:
        raise ConnectionRefusedError("Authentication failed. Check FTP_USER and FTP_PASS.")
    except Exception as e:
        logger.error(f"SFTP upload failed: {e}", exc_info=True); raise e

# --- Command Handlers (unchanged) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(f"Hi {update.effective_user.mention_html()}! Send a file (under 20MB).")
async def check_env(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    status_list = [f"{k}: {'✅ Set' if v else '❌ MISSING!'}" for k, v in {
        "BOT_TOKEN": BOT_TOKEN, "WEBHOOK_URL": WEBHOOK_URL, "OWNER_ID": OWNER_ID, "FTP_HOST": SFTP_HOST,
        "FTP_USER": SFTP_USER, "FTP_PASS": SFTP_PASS, "FTP_PATH": SFTP_PATH, "PUBLIC_URL_BASE": PUBLIC_URL_BASE
    }.items()]
    await update.message.reply_text("Environment Variable Status:\n" + "\n".join(status_list))
async def add_channel_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return ConversationHandler.END
    await update.message.reply_text("To add a channel:\n1. Make me an admin there.\n2. Forward a message from the channel to me.\n\nSend /cancel to abort.")
    return AWAITING_FORWARD
async def receive_forwarded_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message.forward_origin or message.forward_origin.type != 'channel':
        await message.reply_text("That is not a valid forwarded message from a channel. Please try again or /cancel.")
        return AWAITING_FORWARD
    origin = message.forward_origin; channel_id = f"@{origin.chat.username}" if origin.chat.username else origin.chat.id; channel_title = origin.chat.title
    try:
        member = await context.bot.get_chat_member(chat_id=channel_id, user_id=context.bot.id)
        if member.status != 'administrator':
            await message.reply_text(f"I am not an administrator in '{channel_title}'. Please make me an admin and forward the message again."); return ConversationHandler.END
    except Exception as e:
        await message.reply_text(f"Could not verify my status in '{channel_title}'. Error: {e}"); return ConversationHandler.END
    channels = load_channels()
    if str(channel_id) not in channels:
        channels.append(str(channel_id)); save_channels(channels); await update.message.reply_text(f"✅ Success! Channel '{channel_title}' has been added.")
    else: await update.message.reply_text(f"Channel '{channel_title}' is already in the list.")
    return ConversationHandler.END
async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operation cancelled."); return ConversationHandler.END
async def del_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    if not context.args: await update.message.reply_text("Usage: /delchannel @channel_username_or_id"); return
    channel_to_delete = context.args[0]
    channels = load_channels()
    if channel_to_delete in channels:
        channels.remove(channel_to_delete); save_channels(channels); await update.message.reply_text(f"Removed '{channel_to_delete}'.")
    else: await update.message.reply_text(f"'{channel_to_delete}' not found.")
async def list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    channels = load_channels()
    if channels: await update.message.reply_text("Required channels:\n" + "\n".join(channels))
    else: await update.message.reply_text("No channels required.")

# --- Media Handler (UPDATED WITH CORRECTED MESSAGE FLOW) ---
async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # (Force-subscribe logic is unchanged)
    # ...
    message = update.message
    file, file_name = (message.video, message.video.file_name or f"video_{int(time.time())}.mp4") if message.video else (message.document, message.document.file_name or f"file_{int(time.time())}.bin")
    if not file: return

    # --- UPDATED MESSAGE FLOW ---
    # 1. Send a neutral "Processing..." message first.
    processing_msg = await message.reply_text("⌛ Processing your file...")
    temp_file_path = os.path.join("/tmp", file_name)
    last_update_time = [0]

    async def progress_callback(sent, total):
        current_time = time.time()
        # Update at most every 1.5 seconds to avoid spamming Telegram's API
        if current_time - last_update_time[0] < 1.5: return
        
        percentage = int((sent / total) * 100)
        bar = '█' * int(percentage / 10) + '─' * (10 - int(percentage / 10))
        
        try:
            # 2. The very first progress update will change the message to "Uploading..."
            await processing_msg.edit_text(f"⬆️ Uploading...\n`[{bar}] {percentage}%`", parse_mode='Markdown')
            last_update_time[0] = current_time
        except Exception: # Ignore "message is not modified" errors
            pass

    try:
        # The download from Telegram happens silently in the background
        tg_file = await file.get_file()
        await tg_file.download_to_drive(temp_file_path)
        
        def sync_progress_callback(sent, total):
            context.application.create_task(progress_callback(sent, total))
        
        # This runs the upload in a separate thread so the progress bar can update
        direct_link = await asyncio.to_thread(
            upload_file_with_progress, temp_file_path, file_name, sync_progress_callback
        )
        
        # 3. Send the final link when done.
        await processing_msg.edit_text(f"✅ Your direct link is ready:\n\n{direct_link}", parse_mode=None)

    except (ValueError, ConnectionRefusedError) as e:
        await processing_msg.edit_text(f"🚫 Error: {e}")
    except Exception as e:
        logger.error(f"Error processing file {file_name}: {e}", exc_info=True)
        await processing_msg.edit_text("An unexpected error occurred.")
    finally:
        if os.path.exists(temp_file_path): os.remove(temp_file_path)

async def check_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message.reply_text("Thanks! Please send your file again.")

# --- Bot Initialization (unchanged) ---
async def post_init(application: Application):
    await application.bot.set_my_commands([
        BotCommand("start", "Start the bot"), BotCommand("checkenv", "Check variables (Admin)"),
        BotCommand("addchannel", "Add channel (Admin)"), BotCommand("delchannel", "Remove channel (Admin)"),
        BotCommand("listchannels", "List channels (Admin)")
    ])
    logger.info("Custom bot commands set.")

def main():
    if not BOT_TOKEN or not OWNER_ID:
        logger.critical("FATAL: BOT_TOKEN or OWNER_ID not set."); return
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    add_channel_conv = ConversationHandler(
        entry_points=[CommandHandler("addchannel", add_channel_start)],
        states={ AWAITING_FORWARD: [MessageHandler(filters.FORWARDED & filters.ChatType.PRIVATE, receive_forwarded_message)] },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
    )
    application.add_handler(add_channel_conv)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("checkenv", check_env))
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
        application.run_polling()

if __name__ == "__main__":
    main()
