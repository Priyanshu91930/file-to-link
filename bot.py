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

# --- FTP/SFTP Configuration for your Premium Hosting ---
FTP_HOST = os.getenv("FTP_HOST")
FTP_USER = os.getenv("FTP_USER")
FTP_PASS = os.getenv("FTP_PASS")
FTP_PATH = os.getenv("FTP_PATH") # e.g., /home/username/public_html/files
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

# --- NEW: Real Upload Function ---
def upload_file_to_premium_hosting(local_path: str, remote_filename: str) -> str:
    """Uploads a file to your premium web hosting via SFTP and returns a public URL."""
    if not all([FTP_HOST, FTP_USER, FTP_PASS, FTP_PATH, PUBLIC_URL_BASE]):
        logger.error("FTP/SFTP environment variables are not fully configured!")
        raise ValueError("Server-side hosting is not configured.")

    # This disables host key checking. Less secure but avoids common initial setup issues.
    cnopts = pysftp.CnOpts()
    cnopts.hostkeys = None

    remote_filepath = f"{FTP_PATH}/{remote_filename}"
    
    try:
        logger.info(f"Connecting to SFTP host: {FTP_HOST}")
        with pysftp.Connection(host=FTP_HOST, username=FTP_USER, password=FTP_PASS, cnopts=cnopts) as sftp:
            logger.info(f"Uploading {local_path} to {remote_filepath}")
            sftp.put(local_path, remote_filepath)
            logger.info("Upload successful.")
        
        # Construct the final public URL
        public_url = f"{PUBLIC_URL_BASE}/{remote_filename}"
        return public_url
    except Exception as e:
        logger.error(f"SFTP upload failed: {e}", exc_info=True)
        raise e

# --- Handlers and Bot Logic (Mostly unchanged, but calls the new upload function) ---

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Force subscribe check...
    required_channels = load_channels()
    if required_channels:
        user_id = update.effective_user.id
        not_subscribed_channels = []
        for channel in required_channels:
            try:
                member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
                if member.status not in ["member", "administrator", "creator"]:
                    not_subscribed_channels.append(channel)
            except TelegramError as e:
                logger.warning(f"Could not check subscription for {user_id} in {channel}: {e.message}")
                not_subscribed_channels.append(channel)
        
        if not_subscribed_channels:
            # Code to send force-sub message... (omitted for brevity, it's the same)
            return

    message = update.message
    file_id = None
    file_name = None

    if message.video:
        file_id = message.video.file_id
        file_name = message.video.file_name or f"video_{file_id}_{int(time.time())}.mp4"
    elif message.document:
        file_id = message.document.file_id
        file_name = message.document.file_name or f"file_{file_id}_{int(time.time())}.bin"
    else: return

    if file_id:
        processing_msg = await message.reply_text("Downloading file from Telegram...")
        temp_file_path = os.path.join("/tmp", file_name)
        try:
            telegram_file = await context.bot.get_file(file_id)
            await telegram_file.download_to_drive(temp_file_path)
            logger.info(f"Downloaded {file_name} to {temp_file_path}")
            
            await processing_msg.edit_text("Uploading to hosting...")
            
            # --- CALL THE NEW UPLOAD FUNCTION ---
            direct_link = upload_file_to_premium_hosting(temp_file_path, file_name)
            
            await processing_msg.edit_text(f"✅ Your direct download link is ready:\n\n{direct_link}")
            
        except ValueError as ve: # Catching our custom configuration error
             await processing_msg.edit_text(f"Error: {ve}")
        except Exception as e:
            logger.error(f"Error processing file {file_name}: {e}", exc_info=True)
            await processing_msg.edit_text("Sorry, an error occurred while processing your file.")
        finally:
            # Clean up the temporary file from Render's server
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)

# --- Admin commands, start command, etc. are the same as before ---
# (You can copy them from your existing code or the previous version I gave you)
# ...

async def post_init(application: Application) -> None:
    # ... (same post_init function)
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("addchannel", "Add a force-sub channel (Admin)"),
        BotCommand("delchannel", "Remove a force-sub channel (Admin)"),
        BotCommand("listchannels", "List all required channels (Admin)"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Custom bot commands have been set.")


def main() -> None:
    # ... (same setup)
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    
    # ... (same handlers)

    # --- Webhook setup (FIXED) ---
    if WEBHOOK_URL:
        # The URL path and the full webhook_url are now constructed correctly
        url_path = "webhook" 
        full_webhook_url = f"{WEBHOOK_URL.rstrip('/')}/{url_path}"
        logger.info(f"Setting up webhook for URL: {full_webhook_url} on port {PORT}")
        
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=url_path,
            webhook_url=full_webhook_url
        )
    else:
        application.run_polling()

if __name__ == "__main__":
    main()

# NOTE: You will need to copy over the admin command functions (`add_channel`, `del_channel`, etc.)
# and other handlers from the previous code block as they are unchanged.
