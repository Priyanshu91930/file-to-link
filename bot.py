import os
import logging
import time
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.error import TelegramError

# --- Configuration ---
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", "8000"))

# Bot Owner's Telegram User ID (from environment variable)
try:
    OWNER_ID = int(os.getenv("OWNER_ID"))
except (TypeError, ValueError):
    OWNER_ID = None # Bot will warn if owner ID is not set

CHANNELS_FILE = "channels.json"

# --- Logging ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Channel Management Functions ---
def load_channels() -> list:
    """Loads the list of required channels from a JSON file."""
    try:
        with open(CHANNELS_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return [] # Return an empty list if the file doesn't exist yet

def save_channels(channels: list) -> None:
    """Saves the list of required channels to a JSON file."""
    with open(CHANNELS_FILE, "w") as f:
        json.dump(channels, f, indent=4)

# --- Helper Functions ---
async def is_subscribed(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> tuple[bool, list[str]]:
    """Checks if the user is subscribed to all required channels from the JSON file."""
    required_channels = load_channels()
    if not required_channels:
        return True, [] # If no channels are set, subscription is not required

    not_subscribed_channels = []
    for channel_username in required_channels:
        try:
            member = await context.bot.get_chat_member(chat_id=channel_username, user_id=user_id)
            if member.status not in ["member", "administrator", "creator"]:
                not_subscribed_channels.append(channel_username)
        except TelegramError as e:
            logger.warning(f"Could not check subscription for {user_id} in {channel_username}: {e.message}")
            not_subscribed_channels.append(channel_username)
    return len(not_subscribed_channels) == 0, not_subscribed_channels

async def send_force_subscribe_message(update: Update, not_subscribed_channels: list[str]) -> None:
    """Sends a message prompting the user to subscribe."""
    keyboard_buttons = []
    for channel in not_subscribed_channels:
        channel_name_for_link = channel.lstrip('@')
        keyboard_buttons.append(
            [InlineKeyboardButton(f"Join {channel}", url=f"https://t.me/{channel_name_for_link}")]
        )
    keyboard_buttons.append(
        [InlineKeyboardButton("✅ I have joined", callback_data="check_subscription")]
    )
    reply_markup = InlineKeyboardMarkup(keyboard_buttons)

    await update.message.reply_text(
        "To use this bot, you must first join our channel(s):",
        reply_markup=reply_markup
    )

async def upload_file_to_external_storage(file_path: str, file_name: str) -> str:
    """
    *** IMPORTANT: THIS IS A MOCK FUNCTION. YOU MUST REPLACE THIS ***
    This function should upload the file from `file_path` to your chosen cloud storage
    and return a direct, public download URL.
    """
    logger.info(f"Attempting to 'upload' {file_name} to external storage...")
    mock_link = f"https://mock.direct.download.link/{file_name}?token={int(time.time())}"
    logger.info(f"Mock upload successful. Link: {mock_link}")
    return mock_link

# --- Command Handlers (User-facing) ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await update.message.reply_html(
        f"Hi {user.mention_html()}! Send me any video or file, and I'll give you a direct download link.\n"
    )

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    subscribed, not_subscribed_channels = await is_subscribed(update, context, user_id)

    if not subscribed:
        await send_force_subscribe_message(update, not_subscribed_channels)
        return

    message = update.message
    file_id = None
    file_name = None

    if message.video:
        file_id = message.video.file_id
        file_name = f"video_{file_id}_{int(time.time())}.mp4"
    elif message.document:
        file_id = message.document.file_id
        file_name = message.document.file_name or f"document_{file_id}_{int(time.time())}.bin"
    else:
        await message.reply_text("Please send a video or a document.")
        return

    if file_id:
        processing_msg = await message.reply_text("Processing your file...")
        try:
            telegram_file = await context.bot.get_file(file_id)
            temp_file_path = os.path.join("/tmp", file_name)
            await telegram_file.download_to_drive(temp_file_path)
            logger.info(f"Downloaded {file_name} to {temp_file_path}")
            
            direct_link = await upload_file_to_external_storage(temp_file_path, file_name)
            
            await processing_msg.edit_text(f"✅ Here is your direct download link:\n\n{direct_link}")
            
            os.remove(temp_file_path)
            logger.info(f"Cleaned up temporary file: {temp_file_path}")
        except Exception as e:
            logger.error(f"Error processing file {file_name} ({file_id}): {e}", exc_info=True)
            await processing_msg.edit_text("Sorry, an error occurred while processing your file.")

# --- Admin Command Handlers ---

async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to add a new channel for force subscribe."""
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("You are not authorized to use this command.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /addchannel @channel_username")
        return

    channel_username = context.args[0]
    if not channel_username.startswith('@'):
        await update.message.reply_text("Invalid format. Please provide the channel username starting with '@'.")
        return

    channels = load_channels()
    if channel_username not in channels:
        channels.append(channel_username)
        save_channels(channels)
        await update.message.reply_text(f"Channel {channel_username} added successfully.")
    else:
        await update.message.reply_text(f"Channel {channel_username} is already in the list.")

async def del_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to remove a channel."""
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("You are not authorized to use this command.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /delchannel @channel_username")
        return

    channel_username = context.args[0]
    channels = load_channels()
    if channel_username in channels:
        channels.remove(channel_username)
        save_channels(channels)
        await update.message.reply_text(f"Channel {channel_username} removed successfully.")
    else:
        await update.message.reply_text(f"Channel {channel_username} not found in the list.")

async def list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to list all required channels."""
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("You are not authorized to use this command.")
        return

    channels = load_channels()
    if channels:
        message = "Required Channels:\n" + "\n".join(channels)
        await update.message.reply_text(message)
    else:
        await update.message.reply_text("No channels are currently required.")

# --- Callback and Post-Init ---

async def check_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the 'I have joined' button press."""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    subscribed, not_subscribed = await is_subscribed(update, context, user_id)

    if subscribed:
        await query.edit_message_text("🎉 Thanks for joining! Please send your file again.")
    else:
        await query.answer("You still haven't joined all the required channels.", show_alert=True)

async def post_init(application: Application) -> None:
    """This function runs once after the bot starts."""
    if not OWNER_ID:
        logger.warning("OWNER_ID is not set in environment variables! Admin commands will not work.")
    
    # Set the bot commands that appear when typing '/'
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("addchannel", "Add a force-sub channel (Admin)"),
        BotCommand("delchannel", "Remove a force-sub channel (Admin)"),
        BotCommand("listchannels", "List all required channels (Admin)"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Custom bot commands have been set.")

def main() -> None:
    if not BOT_TOKEN:
        logger.critical("TELEGRAM_BOT_TOKEN environment variable not set. Exiting.")
        return

    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("addchannel", add_channel))
    application.add_handler(CommandHandler("delchannel", del_channel))
    application.add_handler(CommandHandler("listchannels", list_channels))
    application.add_handler(MessageHandler(filters.VIDEO | filters.Document.ALL, handle_media))
    application.add_handler(CallbackQueryHandler(check_subscription_callback, pattern="^check_subscription$"))

    # Webhook setup
    if WEBHOOK_URL:
        logger.info(f"Setting up webhook for URL: {WEBHOOK_URL}/webhook on port {PORT}")
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path="webhook",
            webhook_url=f"{WEBHOOK_URL}/webhook"
        )
    else:
        logger.warning("WEBHOOK_URL not set. Running with long polling.")
        application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
