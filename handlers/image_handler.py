"""
handlers/image_handler.py — Image Generation + Upscale (Pillow-based, no ML required)
✅ Works on Render free tier — no torch/realesrgan needed
"""

import io
import logging
import httpx
import urllib.parse

from PIL import Image

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from config import POLLINATIONS_URL, IMAGE_STYLES
from utils import is_rate_limited, back_button

logger = logging.getLogger(__name__)

# ── Conversation states ────────────────────────────────────────────────────
WAITING_FOR_UPSCALE_PHOTO = 1


# ══════════════════════════════════════════════════════════════════════════
# UPSCALE ENGINE (Pillow-based — replaces upscale_engine module)
# ══════════════════════════════════════════════════════════════════════════

def upscale_image(image_bytes: bytes, scale: int = 2) -> bytes:
    """
    Upscale image using Pillow LANCZOS resampling.
    Fast, lightweight, works on any server — no GPU/torch needed.
    scale=2 → 2x size, scale=4 → 4x size
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")

    # Cap max output size to avoid memory issues on free tier
    max_dim = 3000
    new_w = min(img.width * scale, max_dim)
    new_h = min(img.height * scale, max_dim)

    upscaled = img.resize((new_w, new_h), Image.LANCZOS)

    # Slight sharpness boost after resize
    from PIL import ImageFilter, ImageEnhance
    upscaled = upscaled.filter(ImageFilter.UnsharpMask(radius=1.5, percent=120, threshold=3))
    upscaled = ImageEnhance.Sharpness(upscaled).enhance(1.2)

    buf = io.BytesIO()
    upscaled.save(buf, format="JPEG", quality=92, optimize=True)
    return buf.getvalue()


def get_image_info(image_bytes: bytes) -> dict:
    """Return basic image metadata."""
    img = Image.open(io.BytesIO(image_bytes))
    return {
        "width":  img.width,
        "height": img.height,
        "mode":   img.mode,
        "format": img.format or "JPEG",
        "size_kb": round(len(image_bytes) / 1024, 1),
    }


# ══════════════════════════════════════════════════════════════════════════
# IMAGE GENERATION — /imagine
# ══════════════════════════════════════════════════════════════════════════

async def imagine_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle /imagine <prompt>"""
    user = update.effective_user
    if is_rate_limited(user.id):
        await update.message.reply_text("⏳ Please wait a moment before sending another request.")
        return

    prompt = " ".join(ctx.args) if ctx.args else ""
    if not prompt:
        await update.message.reply_text(
            "🎨 *AI Image Generator*\n\nUsage: `/imagine <your prompt>`\n\nExample: `/imagine a sunset over mountains, ultra realistic`",
            parse_mode="Markdown"
        )
        return

    # Show style selector
    keyboard = _style_keyboard(prompt)
    await update.message.reply_text(
        f"🎨 *Choose a style for:*\n_{prompt[:80]}_",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )


def _style_keyboard(prompt: str) -> InlineKeyboardMarkup:
    short = prompt[:30].replace("|", "")
    buttons = []
    row = []
    for name in IMAGE_STYLES:
        row.append(InlineKeyboardButton(name, callback_data=f"imgstyle|{name}|{short}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    return InlineKeyboardMarkup(buttons)


async def image_style_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle style selection for image generation."""
    query = update.callback_query
    await query.answer()

    try:
        _, style_name, short_prompt = query.data.split("|", 2)
    except ValueError:
        await query.edit_message_text("❌ Invalid selection.")
        return

    style_suffix = IMAGE_STYLES.get(style_name, "")
    full_prompt  = f"{short_prompt}, {style_suffix}"

    await query.edit_message_text(f"🎨 Generating image...\n_{full_prompt[:80]}_", parse_mode="Markdown")

    try:
        encoded = urllib.parse.quote(full_prompt)
        url = POLLINATIONS_URL.format(prompt=encoded)

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            image_data = resp.content

        caption = f"🎨 *{style_name}*\n_{short_prompt}_"
        regen_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔄 Regenerate", callback_data=f"reimagine|{style_name}|{short_prompt}"),
            InlineKeyboardButton("✨ Upscale 2×", callback_data=f"upscale_pending"),
        ]])

        await query.message.reply_photo(
            photo=image_data,
            caption=caption,
            parse_mode="Markdown",
            reply_markup=regen_kb,
        )
        await query.delete_message()

        # Store last image in context for upscale
        ctx.user_data["last_image"] = image_data

    except Exception as e:
        logger.error(f"Image gen error: {e}")
        await query.edit_message_text("❌ Failed to generate image. Please try again.")


async def reimagine_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Regenerate the same prompt/style."""
    query = update.callback_query
    await query.answer("🔄 Regenerating...")
    # Reuse image_style_callback logic
    await image_style_callback(update, ctx)


# ══════════════════════════════════════════════════════════════════════════
# UPSCALE — /upscale
# ══════════════════════════════════════════════════════════════════════════

async def upscale_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Start upscale conversation — ask user to send a photo."""
    await update.message.reply_text(
        "✨ *AI Image Upscaler*\n\n"
        "Send me a photo and I'll upscale it to 2× size with enhanced sharpness!\n\n"
        "📸 Please send your image now:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Cancel", callback_data="cancel")
        ]])
    )
    return WAITING_FOR_UPSCALE_PHOTO


async def upscale_photo_received(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Process the received photo and upscale it."""
    user = update.effective_user

    msg = await update.message.reply_text("⏳ Upscaling your image... please wait.")

    try:
        # Get the largest available photo or document
        if update.message.photo:
            file = await update.message.photo[-1].get_file()
        else:
            file = await update.message.document.get_file()

        image_bytes = await file.download_as_bytearray()
        image_bytes = bytes(image_bytes)

        # Get original info
        info = get_image_info(image_bytes)
        original_size = f"{info['width']}×{info['height']}"

        # Upscale
        result = upscale_image(image_bytes, scale=2)

        # Get new info
        info2 = get_image_info(result)
        new_size = f"{info2['width']}×{info2['height']}"

        caption = (
            f"✨ *Upscaled Successfully!*\n\n"
            f"📐 Original: `{original_size}` ({info['size_kb']} KB)\n"
            f"📐 Upscaled: `{new_size}` ({info2['size_kb']} KB)\n"
            f"🔍 Scale: 2×  |  Method: LANCZOS + Sharpen"
        )

        await update.message.reply_document(
            document=io.BytesIO(result),
            filename="upscaled.jpg",
            caption=caption,
            parse_mode="Markdown",
        )
        await msg.delete()

    except Exception as e:
        logger.error(f"Upscale error: {e}")
        await msg.edit_text("❌ Failed to upscale. Please send a valid image (JPG/PNG).")

    return ConversationHandler.END


async def upscale_pending_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle 'Upscale 2×' button on generated images."""
    query = update.callback_query
    await query.answer("✨ Upscaling...")

    last_image = ctx.user_data.get("last_image")
    if not last_image:
        await query.message.reply_text(
            "❌ No image found to upscale. Use /upscale and send a photo directly."
        )
        return

    msg = await query.message.reply_text("⏳ Upscaling generated image...")

    try:
        info    = get_image_info(last_image)
        result  = upscale_image(last_image, scale=2)
        info2   = get_image_info(result)

        caption = (
            f"✨ *Upscaled!*\n"
            f"`{info['width']}×{info['height']}` → `{info2['width']}×{info2['height']}`"
        )

        await query.message.reply_document(
            document=io.BytesIO(result),
            filename="upscaled.jpg",
            caption=caption,
            parse_mode="Markdown",
        )
        await msg.delete()

    except Exception as e:
        logger.error(f"Upscale pending error: {e}")
        await msg.edit_text("❌ Upscale failed. Please try /upscale command instead.")