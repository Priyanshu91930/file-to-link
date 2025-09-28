import os
import logging
import time
import json
import pysftp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes,
    ConversationHandler
)
from telegram.error import TelegramError

# --- Configuration ---
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", "8000"))
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

# --- SFTP Configuration ---
SFTP_HOST = os.getenv("FTP_HOST")
SFTP_USER = os.getenv("FTP_USER")
SFTP_PASS = os.getenv("FTP_PASS")
SFTP_PATH = os.getenv("FTP_PATH")
PUBLIC_URL_BASE = os.getenv("PUBLIC_URL_BASE")

CHANNELS_FILE = "channels.json"

# --- Conversation Handler States ---
AWAITING_FORWARD = range(1)

# --- Logging ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Channel Management ---
def load_channels():
    try:
        with open(CHANNELS_FILE, "r") as f: return json.load(f)
    except FileNotFoundError: return []

def save_channels(channels):
    with open(CHANNELS_FILE, "w") as f: json.dump(channels, f, indent=4)

# --- UPLOAD FUNCTION WITH PROGRESS BAR ---
def upload_file_with_progress(local_path: str, remote_filename: str, callback_func) -> str:
    missing_vars = [var for var, val in {"FTP_HOST": SFTP_HOST, "FTP_USER": SFTP_USER, "FTP_PASS": SFTP_PASS, "FTP_PATH": SFTP_PATH, "PUBLIC_URL_BASE": PUBLIC_URL_BASE}.items() if not val]
    if missing_vars:
        raise ValueError(f"Server hosting misconfigured. Missing: {', '.join(missing_vars)}")

    cnopts = pysftp.CnOpts()
    cnopts.hostkeys = None
    remote_filepath = f"{SFTP_PATH.rstrip('/')}/{remote_filename}"
    
    try:
        with pysftp.Connection(host=SFTP_HOST, username=SFTP_USER, password=SFTP_PASS, port=22, cnopts=cnopts) as sftp:
            logger.info(f"Uploading {local_path} to {remote_filepath}")
            sftp.put(local_path, remote_filepath, callback=callback_func)
        return f"{PUBLIC_URL_BASE.rstrip('/')}/{remote_filename}"
    except pysftp.AuthenticationException:
        raise ConnectionRefusedError("Authentication failed. Check FTP_USER and FTP_PASS.")
    except Exception as e:
        logger.error(f"SFTP upload failed: {e}", exc_info=True)
        raise e

# --- Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(f"Hi {update.effective_user.mention_html()}! Send a file (under 20MB).")

async def check_env(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    status_list = [
        f"BOT_TOKEN: {'✅ Set' if BOT_TOKEN else '❌ MISSING!'}",
        f"WEBHOOK_URL: {f'✅ Set to {WEBHOOK_URL}' if WEBHOOK_URL else '❌ MISSING!'}",
        f"OWNER_ID: {f'✅ Set to {OWNER_ID}' if OWNER_ID else '❌ MISSING!'}",
        "-" * 20,
        f"FTP_HOST: {f'✅ Set to {SFTP_HOST}' if SFTP_HOST else '❌ MISSING!'}",
        f"FTP_USER: {f'✅ Set to {SFTP_USER}' if SFTP_USER else '❌ MISSING!'}",
        f"FTP_PASS: {'✅ Set' if SFTP_PASS else '❌ MISSING!'}",
        f"FTP_PATH: {f'✅ Set to {SFTP_PATH}' if SFTP_PATH else '❌ MISSING!'}",
        f"PUBLIC_URL_BASE: {f'✅ Set to {PUBLIC_URL_BASE}' if PUBLIC_URL_BASE else '❌ MISSING!'}"
    ]
    await update.message.reply_text("Environment Variable Status:\n" + "\n".join(status_list))

# --- Add Channel Conversation ---
async def add_channel_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return ConversationHandler.END
    await update.message.reply_text(
        "To add a channel for force-subscribe:\n"
        "1. Make me an administrator in the channel.\n"
        "2. Forward any message from that channel to me here.\n\n"
        "Send /cancel to abort."
    )
    return AWAITING_FORWARD

async def receive_forwarded_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message.forward_from_chat or message.forward_from_chat.type != 'channel':
        await message.reply_text("This is not a forwarded message from a channel. Please try again or /cancel.")
        return AWAITING_FORWARD

    # Public channels have usernames, private ones don't
    channel_id = f"@{message.forward_from_chat.username}" if message.forward_from_chat.username else message.forward_from_chat.id
    channel_title = message.forward_from_chat.title
    
    try:
        member = await context.bot.get_chat_member(chat_id=channel_id, user_id=context.bot.id)
        if member.status != 'administrator':
            await message.reply_text(f"I am not an administrator in '{channel_title}'. Please make me an admin and forward the message again.")
            return ConversationHandler.END
    except Exception as e:
        await message.reply_text(f"Could not verify my status in '{channel_title}'. Error: {e}")
        return ConversationHandler.END

    channels = load_channels()
    # Check both ID and username to prevent duplicates
    if str(channel_id) not in channels:
        channels.append(str(channel_id))
        save_channels(channels)
        await message.reply_text(f"✅ Success! Channel '{channel_title}' has been added to the list.")
    else:
        await message.reply_text(f"Channel '{channel_title}' is already in the list.")
    
    return ConversationHandler.END

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END

async def del_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    if not context.args: await update.message.reply_text("Usage: /delchannel @channel_username_or_id"); return
    
    channel_to_delete = context.args[0]
    channels = load_channels()
    if channel_to_delete in channels:
        channels.remove(channel_to_delete)
        save_channels(channels)
        await update.message.reply_text(f"Removed '{channel_to_delete}' from the list.")
    else:
        await update.message.reply_text(f"'{channel_to_delete}' not found in the list.")

async def list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    channels = load_channels()
    if channels: await update.message.reply_text("Required channels:\n" + "\n".join(channels))
    else: await update.message.reply_text("No channels required.")


# --- Media Handler with Progress Bar ---
async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    processing_msg = await message.reply_text("Downloading file...")
    temp_file_path = os.path.join("/tmp", file_name)
    last_update_time = [0]

    async def progress_callback(sent, total):
        current_time = time.time()
        if current_time - last_update_time[0] < 2: return
        
        percentage = int((sent / total) * 100)
        bar = '█' * int(percentage / 10) + '─' * (10 - int(percentage / 10))
        
        try:
            await processing_msg.edit_text(f"Uploading...\n`[{bar}] {percentage}%`", parse_mode='Markdown')
            last_update_time[0] = current_time
        except Exception: pass

    try:
        tg_file = await file.get_file()
        await tg_file.download_to_drive(temp_file_path)
        
        def sync_progress_callback(sent, total):
            context.application.create_task(progress_callback(sent, total))
        
        direct_link = upload_file_with_progress(temp_file_path, file_name, sync_progress_callback)
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
    await query.edit_message_text("Thanks! Please send your file again.")

# --- Bot Initialization ---
async def post_init(application: Application):
    await application.bot.set_my_commands([
        BotCommand("start", "Start the bot"),
        BotCommand("checkenv", "Check environment variables (Admin)"),
        BotCommand("addchannel", "Add a force-subscribe channel (Admin)"),
        BotCommand("delchannel", "Remove a channel by ID/@username (Admin)"),
        BotCommand("listchannels", "List required channels (Admin)")
    ])
    logger.info("Custom bot commands set.")

def main():
    if not BOT_TOKEN: logger.critical("FATAL: BOT_TOKEN not set."); return
    if not OWNER_ID: logger.critical("FATAL: OWNER_ID not set."); return
    
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    
    add_channel_conv = ConversationHandler(
        entry_points=[CommandHandler("addchannel", add_channel_start)],
        states={ AWAITING_FORWARD: [MessageHandler(filters.FORWARDED, receive_forwarded_message)] },
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
        logger.warning("No WEBHOOK_URL set, running in polling mode.")
        application.run_polling()

if __name__ == "__main__":
    main()
