"""
handlers/image_handler.py — AI Image Generation & Upscaling  (v2)

Upscale improvements:
  ✅ Real-ESRGAN x4+ (photo) or x4+ anime_6B (anime mode)
  ✅ GFPGAN face enhancement (toggled per-request)
  ✅ Adaptive OpenCV sharpening after upscale
  ✅ Output as PNG (not JPEG) — lossless, highest quality
  ✅ User picks: Photo mode / Anime mode / Face enhance on/off
  ✅ Requests image sent AS FILE for max Telegram resolution
  ✅ Live step-by-step progress messages
  ✅ Shows before/after resolution in caption
  ✅ Graceful fallback to Pillow if GPU libs unavailable
"""

import logging
import io
import asyncio
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode, ChatAction

from upscale_engine import upscale_image, get_image_info
from ai import generate_image
from utils import is_rate_limited, image_style_keyboard, back_button
from database import ensure_user, log_error
from config import IMAGE_STYLES

logger = logging.getLogger(__name__)

# Conversation states
WAITING_UPSCALE_OPTIONS = 1
WAITING_FOR_UPSCALE_PHOTO = 2


# ─────────────────────────────────────────────
# /imagine — IMAGE GENERATION (unchanged)
# ─────────────────────────────────────────────

async def imagine_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)

    if is_rate_limited(uid):
        await update.message.reply_text("⏳ Please wait a moment before sending another request.")
        return

    prompt = " ".join(ctx.args) if ctx.args else ""

    if not prompt:
        await update.message.reply_text(
            "🎨 *AI Image Generator*\n\n"
            "Provide a description after the command:\n\n"
            "`/imagine a dragon flying over mountains at sunset`\n\n"
            "Be as descriptive as possible for better results! 🖌️",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await update.message.reply_text(
        f"🎨 *Choose your art style:*\n\n📝 Prompt: _{prompt}_",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=image_style_keyboard(prompt),
    )


async def image_style_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("✨ Generating your image...")
    uid = query.from_user.id

    try:
        _, style_name, short_prompt = query.data.split("|", 2)
    except ValueError:
        await query.edit_message_text("❌ Invalid selection. Please try /imagine again.")
        return

    await query.edit_message_text(
        f"🎨 *Generating your image...*\n\n"
        f"🖌️ Style: *{style_name}*\n"
        f"📝 Prompt: _{short_prompt}_\n\n"
        f"⏳ This may take 10–30 seconds...",
        parse_mode=ParseMode.MARKDOWN,
    )
    await ctx.bot.send_chat_action(chat_id=query.message.chat_id, action=ChatAction.UPLOAD_PHOTO)

    image_bytes, error = await generate_image(short_prompt, style_name)

    if error:
        log_error(uid, error, "image_generation")
        await query.edit_message_text(
            f"❌ *Image generation failed.*\n\n{error}\n\nTry /imagine again.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

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
            InlineKeyboardButton("✨ Upscale This", callback_data="upscale_pending"),
            InlineKeyboardButton("🎨 Generate Again", callback_data=f"reimagine|{short_prompt}"),
        ]]),
    )
    try:
        await query.delete_message()
    except Exception:
        pass


async def reimagine_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        _, prompt = query.data.split("|", 1)
        await query.edit_message_caption(
            caption=f"🎨 *Choose a style for:*\n_{prompt}_",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=image_style_keyboard(prompt),
        )
    except Exception:
        await query.answer("Please use /imagine to generate a new image.", show_alert=True)


# ─────────────────────────────────────────────
# /upscale — STEP 1: show mode options
# ─────────────────────────────────────────────

def _upscale_options_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📷 Photo (Real-ESRGAN)",  callback_data="ups_mode_photo"),
            InlineKeyboardButton("🎌 Anime / Art",           callback_data="ups_mode_anime"),
        ],
        [
            InlineKeyboardButton("👤 Face Enhance ON  ✅",   callback_data="ups_face_on"),
            InlineKeyboardButton("👤 Face Enhance OFF ☐",    callback_data="ups_face_off"),
        ],
        [
            InlineKeyboardButton("✅ Start Upscaling →",     callback_data="ups_confirm"),
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="menu_main")],
    ])


def _upscale_options_text(ctx) -> str:
    mode = ctx.user_data.get("ups_mode", "photo")
    face = ctx.user_data.get("ups_face", True)
    mode_label = "📷 Photo (Real-ESRGAN x4+)" if mode == "photo" else "🎌 Anime / Illustration"
    face_label = "✅ ON" if face else "☐ OFF"
    return (
        "✨ *AI Image Upscaler*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🖼  Mode:           {mode_label}\n"
        f"👤  Face Enhance:   {face_label}\n"
        f"📐  Scale:          4×\n"
        f"🔍  Sharpening:     ✅ ON\n"
        f"📁  Output:         PNG (lossless)\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Pick options then press *Start Upscaling* →\n"
        "then send your photo.\n\n"
        "💡 _Tip: Send the image as a **File** (📎 Attach → File) for maximum quality_\n\n"
        "_/cancel to abort_"
    )


async def upscale_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)

    if is_rate_limited(uid):
        await update.message.reply_text("⏳ Please wait a moment.")
        return

    # Set defaults
    ctx.user_data["ups_mode"] = "photo"
    ctx.user_data["ups_face"] = True

    await update.message.reply_text(
        _upscale_options_text(ctx),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_upscale_options_keyboard(),
    )
    return WAITING_UPSCALE_OPTIONS


# ─────────────────────────────────────────────
# /upscale — STEP 2: handle option buttons
# ─────────────────────────────────────────────

async def upscale_options_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "ups_mode_photo":
        ctx.user_data["ups_mode"] = "photo"
    elif data == "ups_mode_anime":
        ctx.user_data["ups_mode"] = "anime"
    elif data == "ups_face_on":
        ctx.user_data["ups_face"] = True
    elif data == "ups_face_off":
        ctx.user_data["ups_face"] = False
    elif data == "ups_confirm":
        mode = ctx.user_data.get("ups_mode", "photo")
        face = ctx.user_data.get("ups_face", True)
        face_label = "✅ face enhance ON" if face else "face enhance OFF"
        await query.edit_message_text(
            f"✨ *Ready!*\n\n"
            f"Mode: *{'Photo' if mode == 'photo' else 'Anime'}*  ·  {face_label}\n\n"
            f"📤 *Send your photo now.*\n"
            f"💡 _Send as a File for best quality_ (📎 → File)\n\n"
            f"_/cancel to abort_",
            parse_mode=ParseMode.MARKDOWN,
        )
        return WAITING_FOR_UPSCALE_PHOTO

    # Refresh options screen
    await query.edit_message_text(
        _upscale_options_text(ctx),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_upscale_options_keyboard(),
    )
    return WAITING_UPSCALE_OPTIONS


# ─────────────────────────────────────────────
# /upscale — STEP 3: receive photo and process
# ─────────────────────────────────────────────

async def upscale_photo_received(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    mode = ctx.user_data.get("ups_mode", "photo")
    face = ctx.user_data.get("ups_face", True)

    has_photo = bool(update.message.photo)
    has_doc   = bool(update.message.document)

    if not has_photo and not has_doc:
        await update.message.reply_text(
            "❌ Please send a *photo* or image *file*.\n\nTry again or /cancel",
            parse_mode=ParseMode.MARKDOWN,
        )
        return WAITING_FOR_UPSCALE_PHOTO

    # ── Step progress message ──────────────────────────────────────────────────
    steps = [
        "⏳ Downloading your image…",
        "🔍 Running Real-ESRGAN x4+ upscale…",
        "👤 Enhancing faces with GFPGAN…" if face else "🔍 Sharpening details…",
        "🎨 Applying adaptive sharpening…",
        "📁 Encoding PNG output…",
    ]
    msg = await update.message.reply_text(steps[0], parse_mode=ParseMode.MARKDOWN)
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_PHOTO)

    # ── Download ───────────────────────────────────────────────────────────────
    try:
        if has_doc:
            # Sent as file — full resolution
            file_obj = await ctx.bot.get_file(update.message.document.file_id)
        else:
            # Sent as compressed photo — highest available size
            file_obj = await ctx.bot.get_file(update.message.photo[-1].file_id)

        raw_bytes = bytes(await file_obj.download_as_bytearray())
    except Exception as e:
        await msg.edit_text(f"❌ Download failed: {str(e)[:120]}")
        return ConversationHandler.END

    # Get input dimensions
    info_in = get_image_info(raw_bytes)
    in_w = info_in.get("width", "?")
    in_h = info_in.get("height", "?")

    # ── Progress: step 2 ──────────────────────────────────────────────────────
    await msg.edit_text(steps[1])
    await asyncio.sleep(0.3)   # let Telegram render the edit

    # ── Upscale ───────────────────────────────────────────────────────────────
    enhanced_bytes, error = await upscale_image(
        raw_bytes,
        scale=4,
        face_enhance=face,
        sharpen=True,
        mode=mode,
    )

    if error:
        log_error(uid, error, "upscale")
        await msg.edit_text(
            f"❌ *Enhancement failed.*\n\n`{error[:300]}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ConversationHandler.END

    # Get output dimensions
    info_out = get_image_info(enhanced_bytes)
    out_w = info_out.get("width", "?")
    out_h = info_out.get("height", "?")
    size_kb = round(len(enhanced_bytes) / 1024)

    # ── Progress: done ────────────────────────────────────────────────────────
    await msg.edit_text("📤 Sending enhanced image…")

    mode_label = "📷 Photo (Real-ESRGAN)" if mode == "photo" else "🎌 Anime"
    face_label = "✅ GFPGAN" if face else "—"

    caption = (
        "✨ *Image Enhanced!*\n\n"
        f"📐  Resolution: `{in_w}×{in_h}` → `{out_w}×{out_h}`\n"
        f"🔬  Scale: *4×*\n"
        f"🖼  Mode: *{mode_label}*\n"
        f"👤  Face Enhance: {face_label}\n"
        f"🔍  Sharpening: ✅ Adaptive\n"
        f"📁  Format: PNG  ·  {size_kb} KB\n\n"
        "_Send another photo or /upscale again_"
    )

    # Send as document (file) to bypass Telegram's JPEG recompression
    await ctx.bot.send_document(
        chat_id=update.effective_chat.id,
        document=io.BytesIO(enhanced_bytes),
        filename="upscaled.png",
        caption=caption,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✨ Upscale Another", callback_data="upscale_pending"),
            InlineKeyboardButton("🔙 Menu",            callback_data="menu_main"),
        ]]),
    )

    try:
        await msg.delete()
    except Exception:
        pass

    ctx.user_data.pop("ups_mode", None)
    ctx.user_data.pop("ups_face", None)
    return ConversationHandler.END


# ─────────────────────────────────────────────
# Inline "Upscale This" from generated image
# ─────────────────────────────────────────────

async def upscale_pending_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    ctx.user_data["ups_mode"] = "photo"
    ctx.user_data["ups_face"] = True

    await query.message.reply_text(
        _upscale_options_text(ctx),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_upscale_options_keyboard(),
    )