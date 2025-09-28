import os
import logging
import time # For unique filenames, though file_id is often good enough
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# --- Configuration ---
# Get your bot token from environment variables (HIGHLY RECOMMENDED for security)
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
# Replace with your actual channel usernames (e.g., "@my_awesome_channel")
# The bot MUST be an administrator in these channels to check subscriptions.
REQUIRED_CHANNELS = ["@test_channel_for_bot_dev_01", "@test_channel_for_bot_dev_02"] # IMPORTANT: Use actual channel @usernames!

# For webhook deployment on Render
WEBHOOK_URL = os.getenv("WEBHOOK_URL") # e.g., https://your-render-service-name.onrender.com
PORT = int(os.getenv("PORT", "8000")) # Render usually sets this to 10000, but 8000 is a common default

# --- Logging ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Helper Functions ---

async def is_subscribed(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> tuple[bool, list[str]]:
    """
    Checks if the user is subscribed to all required channels.
    Returns (True, []) if subscribed, or (False, list_of_unsubscribed_channels) otherwise.
    """
    not_subscribed_channels = []
    for channel_username in REQUIRED_CHANNELS:
        try:
            # getChatMember requires the bot to be an administrator in the channel
            member = await context.bot.get_chat_member(chat_id=channel_username, user_id=user_id)
            if member.status not in ["member", "administrator", "creator"]:
                not_subscribed_channels.append(channel_username)
        except Exception as e:
            logger.warning(f"Could not check subscription for {user_id} in {channel_username}: {e}")
            # If bot cannot access channel info (e.g., not admin), assume not subscribed for safety
            not_subscribed_channels.append(channel_username)
    return len(not_subscribed_channels) == 0, not_subscribed_channels

async def send_force_subscribe_message(update: Update, context: ContextTypes.DEFAULT_TYPE, not_subscribed_channels: list[str]) -> None:
    """Sends a message prompting the user to subscribe."""
    keyboard_buttons = []
    for channel in not_subscribed_channels:
        # Remove '@' for the URL as Telegram links often use it without
        channel_name_for_link = channel.lstrip('@')
        keyboard_buttons.append(
            [InlineKeyboardButton(f"Join {channel}", url=f"https://t.me/{channel_name_for_link}")]
        )
    keyboard_buttons.append(
        [InlineKeyboardButton("✅ I have joined", callback_data="check_subscription")]
    )
    reply_markup = InlineKeyboardMarkup(keyboard_buttons)

    await update.message.reply_text(
        "To use this bot, you must join the following channels:",
        reply_markup=reply_markup
    )

async def upload_file_to_external_storage(file_path: str, file_name: str) -> str:
    """
    *** IMPORTANT: THIS IS A MOCK FUNCTION. YOU MUST REPLACE THIS ***
    This function should upload the file from `file_path` to your chosen cloud storage
    (e.g., AWS S3, Google Cloud Storage, Backblaze B2) and return a direct, public
    download URL for that file.

    Render's free tier is NOT suitable for storing large user-uploaded media files.
    """
    logger.info(f"Attempting to 'upload' {file_name} to external storage...")
    
    # --- YOUR CLOUD STORAGE INTEGRATION GOES HERE ---
    # Example for AWS S3 (requires 'boto3' installed and AWS credentials as env vars):
    # import boto3
    # s3_client = boto3.client(
    #     's3',
    #     aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    #     aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    #     region_name=os.getenv("AWS_REGION")
    # )
    # bucket_name = os.getenv("S3_BUCKET_NAME")
    # s3_key = f"media/{file_name}" # Path inside your S3 bucket
    # s3_client.upload_file(file_path, bucket_name, s3_key)
    #
    # # Generate a pre-signed URL for direct download (e.g., valid for 7 days)
    # direct_link = s3_client.generate_presigned_url(
    #     'get_object',
    #     Params={'Bucket': bucket_name, 'Key': s3_key},
    #     ExpiresIn=604800 # 7 days in seconds
    # )
    # return direct_link
    # --- END OF S3 EXAMPLE ---

    # --- MOCK RESPONSE FOR DEMONSTRATION ONLY ---
    # In a real scenario, this would be a real link from your cloud storage.
    mock_link = f"https://mock.direct.download.link/{file_name}?token={int(time.time())}"
    logger.info(f"Mock upload successful. Link: {mock_link}")
    return mock_link

# --- Command Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await update.message.reply_html(
        f"Hi {user.mention_html()}! Send me any video or file, and I'll give you a direct download link.\n"
        "Make sure you are subscribed to our channels!"
    )

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    subscribed, not_subscribed_channels = await is_subscribed(update, context, user_id)

    if not subscribed:
        # Store the original message if it's not a callback query, so we can re-process it later
        if update.message:
            context.user_data['pending_media_message'] = update.message.to_dict()
        await send_force_subscribe_message(update, context, not_subscribed_channels)
        return

    message = update.message
    file_id = None
    file_name = None

    if message.video:
        file_id = message.video.file_id
        # Use a more robust filename, possibly including file_id to prevent clashes
        file_name = f"video_{file_id}_{int(time.time())}.mp4" 
    elif message.document:
        file_id = message.document.file_id
        file_name = message.document.file_name or f"document_{file_id}_{int(time.time())}.bin"
    else:
        await message.reply_text("Please send a video or a document.")
        return

    if file_id:
        await message.reply_text("Processing your file... please wait. This might take a moment for large files.")
        try:
            # 1. Get file from Telegram
            telegram_file = await context.bot.get_file(file_id)
            
            # Create a temporary path for the file. /tmp is usually writable on Linux servers.
            # Ensure the directory exists if you use subdirectories.
            temp_file_path = os.path.join("/tmp", file_name) 
            
            # 2. Download file data to a temporary location
            await telegram_file.download_to_drive(temp_file_path)
            logger.info(f"Downloaded {file_name} to {temp_file_path}")
            
            # 3. Upload to external storage and get direct link
            direct_link = await upload_file_to_external_storage(temp_file_path, file_name)
            
            # 4. Send link to user
            await message.reply_text(f"✅ Here is your direct download link: {direct_link}")
            
            # Clean up temporary file
            os.remove(temp_file_path)
            logger.info(f"Cleaned up temporary file: {temp_file_path}")

        except Exception as e:
            logger.error(f"Error processing file {file_name} ({file_id}): {e}", exc_info=True)
            await message.reply_text("Sorry, an error occurred while processing your file. Please try again later.")

async def check_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the 'I have joined' button press."""
    query = update.callback_query
    await query.answer() # Acknowledge the button press

    user_id = query.from_user.id
    subscribed, not_subscribed_channels = await is_subscribed(update, context, user_id)

    if subscribed:
        await query.edit_message_text("🎉 Thanks for joining! You can now send your files.")
        # If there was a pending media message, re-process it
        if 'pending_media_message' in context.user_data:
            # Reconstruct an Update object to pass to handle_media
            # This is a bit of a hack but allows re-triggering the logic
            # For simplicity, we'll just ask the user to resend for now
            # A more robust solution would deserialize the message and pass it directly.
            await query.message.reply_text("You are all set! Please send your file again.")
            del context.user_data['pending_media_message'] # Clear pending state
    else:
        await query.edit_message_text(
            "It looks like you haven't joined all channels yet. Please join them and try again.",
            reply_markup=query.message.reply_markup # Keep the same keyboard
        )


def main() -> None:
    application = Application.builder().token(BOT_TOKEN).build()

    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.VIDEO | filters.Document.ALL, handle_media))
    application.add_handler(CallbackQueryHandler(check_subscription_callback, pattern="^check_subscription$"))

    # --- Deploying with Webhooks on Render ---
    if WEBHOOK_URL:
        logger.info(f"Setting up webhook for URL: {WEBHOOK_URL}/webhook on port {PORT}")
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path="webhook", # This is the path your webhook will listen on
            webhook_url=f"{WEBHOOK_URL}/webhook"
        )
    else:
        # --- For Local Testing / Long Polling (not recommended for Render) ---
        logger.warning("WEBHOOK_URL not set. Running with long polling. This is not ideal for Render free tier.")
        application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
