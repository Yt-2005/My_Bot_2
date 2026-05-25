"""
handlers/image_handler.py — AI Image Generation & Upscaling handlers
/imagine — Generate images from text prompts with style selection
/upscale — Enhance uploaded photos to higher quality
"""

import logging
import io
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode, ChatAction

from ai import generate_image, upscale_image
from utils import is_rate_limited, image_style_keyboard, back_button
from database import ensure_user, log_error
from config import IMAGE_STYLES

logger = logging.getLogger(__name__)

# Conversation states
WAITING_FOR_UPSCALE_PHOTO = 1


# ─────────────────────────────────────────────
# /imagine — IMAGE GENERATION
# ─────────────────────────────────────────────

async def imagine_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Usage: /imagine <description>
    Shows style selector, then generates the image.
    """
    uid = update.effective_user.id
    ensure_user(uid)

    if is_rate_limited(uid):
        await update.message.reply_text("⏳ Please wait a moment before sending another request.")
        return

    # Extract prompt from command args
    prompt = " ".join(ctx.args) if ctx.args else ""

    if not prompt:
        await update.message.reply_text(
            "🎨 *AI Image Generator*\n\n"
            "Please provide a description after the command:\n\n"
            "`/imagine a dragon flying over mountains at sunset`\n\n"
            "Be as descriptive as possible for better results! 🖌️",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # Show style selection
    await update.message.reply_text(
        f"🎨 *Choose your art style:*\n\n"
        f"📝 Prompt: _{prompt}_",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=image_style_keyboard(prompt)
    )


async def image_style_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Handles the style button press.
    Callback data format: imgstyle|<style_name>|<short_prompt>
    """
    query = update.callback_query
    await query.answer("✨ Generating your image...")
    uid = query.from_user.id

    try:
        _, style_name, short_prompt = query.data.split("|", 2)
    except ValueError:
        await query.edit_message_text("❌ Invalid selection. Please try /imagine again.")
        return

    # Update message to show loading state
    await query.edit_message_text(
        f"🎨 *Generating your image...*\n\n"
        f"🖌️ Style: *{style_name}*\n"
        f"📝 Prompt: _{short_prompt}_\n\n"
        f"⏳ This may take 10-30 seconds. Please wait...",
        parse_mode=ParseMode.MARKDOWN
    )

    # Send "uploading photo" action
    await ctx.bot.send_chat_action(chat_id=query.message.chat_id, action=ChatAction.UPLOAD_PHOTO)

    # Generate image (full prompt reconstructed from style + short prompt)
    # Note: for short prompts this works fine. For full prompts, use ctx.user_data
    image_bytes, error = await generate_image(short_prompt, style_name)

    if error:
        log_error(uid, error, "image_generation")
        await query.edit_message_text(
            f"❌ *Image generation failed.*\n\n{error}\n\nTry /imagine again.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # Send the image
    caption = (
        f"🎨 *Your AI Image is ready!*\n\n"
        f"🖌️ Style: *{style_name}*\n"
        f"📝 Prompt: _{short_prompt}_"
    )

    await ctx.bot.send_photo(
        chat_id=query.message.chat_id,
        photo=io.BytesIO(image_bytes),
        caption=caption,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✨ Upscale This", callback_data=f"upscale_pending"),
            InlineKeyboardButton("🎨 Generate Again", callback_data=f"reimagine|{short_prompt}"),
        ]])
    )

    # Delete the loading message
    try:
        await query.delete_message()
    except Exception:
        pass


async def reimagine_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Re-generate with style selection."""
    query = update.callback_query
    await query.answer()
    try:
        _, prompt = query.data.split("|", 1)
        await query.edit_message_caption(
            caption=f"🎨 *Choose a style for:*\n_{prompt}_",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=image_style_keyboard(prompt)
        )
    except Exception:
        await query.answer("Please use /imagine to generate a new image.", show_alert=True)


# ─────────────────────────────────────────────
# /upscale — IMAGE ENHANCEMENT
# ─────────────────────────────────────────────

async def upscale_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Start the upscale flow — ask user to send a photo."""
    uid = update.effective_user.id
    ensure_user(uid)

    if is_rate_limited(uid):
        await update.message.reply_text("⏳ Please wait a moment.")
        return

    await update.message.reply_text(
        "✨ *AI Image Upscaler*\n\n"
        "Send me any photo and I'll enhance it:\n\n"
        "📐 *Resolution* — Upscale up to 4× larger\n"
        "🔍 *Sharpness* — Remove blur and add detail\n"
        "🎨 *Colors* — Boost vibrancy and contrast\n"
        "🧹 *Noise reduction* — Clean up grain\n\n"
        "📤 *Upload your photo now!*\n\n"
        "_Send /cancel to abort_",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=back_button("menu_main")
    )
    return WAITING_FOR_UPSCALE_PHOTO


async def upscale_photo_received(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Process the uploaded photo."""
    uid = update.effective_user.id

    if not update.message.photo and not update.message.document:
        await update.message.reply_text(
            "❌ Please send a *photo* (not a file/document).\n\nTry again or /cancel",
            parse_mode=ParseMode.MARKDOWN
        )
        return WAITING_FOR_UPSCALE_PHOTO

    # Show processing message
    msg = await update.message.reply_text(
        "✨ *Enhancing your image...*\n\n"
        "📐 Upscaling resolution...\n"
        "🔍 Sharpening details...\n"
        "🎨 Boosting colors...\n\n"
        "⏳ Please wait 10-20 seconds...",
        parse_mode=ParseMode.MARKDOWN
    )

    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_PHOTO)

    # Download the photo
    try:
        if update.message.photo:
            photo_file = await update.message.photo[-1].get_file()
        else:
            photo_file = await update.message.document.get_file()

        photo_bytes = await photo_file.download_as_bytearray()
    except Exception as e:
        await msg.edit_text(f"❌ Failed to download your photo: {str(e)[:100]}")
        return ConversationHandler.END

    # Enhance image
    enhanced_bytes, error = await upscale_image(bytes(photo_bytes))

    if error:
        log_error(uid, error, "upscale")
        await msg.edit_text(f"❌ *Enhancement failed.*\n\n{error}", parse_mode=ParseMode.MARKDOWN)
        return ConversationHandler.END

    # Send enhanced image
    await ctx.bot.send_photo(
        chat_id=update.effective_chat.id,
        photo=io.BytesIO(enhanced_bytes),
        caption=(
            "✨ *Image Enhanced!*\n\n"
            "📐 Resolution upscaled 2×\n"
            "🔍 Details sharpened\n"
            "🎨 Colors enhanced\n"
            "🧹 Noise reduced\n\n"
            "_Send another photo or /upscale again_"
        ),
        parse_mode=ParseMode.MARKDOWN
    )

    # Clean up loading message
    try:
        await msg.delete()
    except Exception:
        pass

    return ConversationHandler.END


async def upscale_pending_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Prompt user to upload a photo for upscaling."""
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "✨ *Upscale a photo?*\n\nJust send me the photo directly!",
        parse_mode=ParseMode.MARKDOWN
    )
