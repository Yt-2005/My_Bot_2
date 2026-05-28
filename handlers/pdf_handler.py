"""
handlers/pdf_handler.py — PDF Tools for Telegram Bot
Features:
  ✅ Text → PDF   (/pdf then send text)
  ✅ Image → PDF  (send photo with caption /pdf)
  ✅ PDF → Text   (send PDF file)
"""

import logging
import io
import os
import tempfile
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

logger = logging.getLogger(__name__)

# ── Conversation states ──
WAITING_PDF_TEXT = "WAITING_PDF_TEXT"
WAITING_PDF_IMAGE = "WAITING_PDF_IMAGE"

# ── Helper: check library availability ──
def _can_use_fpdf():
    try:
        from fpdf import FPDF
        return True
    except ImportError:
        return False

def _can_use_pymupdf():
    try:
        import fitz
        return True
    except ImportError:
        return False

def _can_use_pillow():
    try:
        from PIL import Image
        return True
    except ImportError:
        return False


# ══════════════════════════════════════════════
# /pdf — Entry point: show PDF menu
# ══════════════════════════════════════════════
PDF_MENU_KB = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("📝 Text → PDF",  callback_data="pdf_text"),
        InlineKeyboardButton("🖼️ Image → PDF", callback_data="pdf_image"),
    ],
    [
        InlineKeyboardButton("📄 PDF → Text",  callback_data="pdf_extract"),
    ],
    [InlineKeyboardButton("🔙 Back", callback_data="menu_main")],
])

PDF_MENU_TEXT = (
    "📄 *PDF Tools*\n\n"
    "Choose what you want to do:\n\n"
    "📝 *Text → PDF* — Convert your text into a PDF file\n"
    "🖼️ *Image → PDF* — Convert a photo into a PDF file\n"
    "📄 *PDF → Text* — Extract text from a PDF file"
)


async def pdf_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show PDF tools menu."""
    await update.message.reply_text(
        PDF_MENU_TEXT,
        parse_mode="Markdown",
        reply_markup=PDF_MENU_KB,
    )


# ══════════════════════════════════════════════
# PDF CALLBACK ROUTER
# ══════════════════════════════════════════════
async def pdf_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "pdf_text":
        await query.edit_message_text(
            "📝 *Text → PDF*\n\n"
            "Send me the text you want to convert to PDF.\n"
            "You can send multiple paragraphs.\n\n"
            "Type /cancel to go back.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="menu_pdf")]]),
        )
        ctx.user_data["pdf_mode"] = "text"
        return WAITING_PDF_TEXT

    elif data == "pdf_image":
        await query.edit_message_text(
            "🖼️ *Image → PDF*\n\n"
            "Send me a photo and I'll convert it to a PDF file.\n\n"
            "Type /cancel to go back.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="menu_pdf")]]),
        )
        ctx.user_data["pdf_mode"] = "image"
        return WAITING_PDF_IMAGE

    elif data == "pdf_extract":
        await query.edit_message_text(
            "📄 *PDF → Text*\n\n"
            "Send me a PDF file and I'll extract all the text from it.\n\n"
            "Type /cancel to go back.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="menu_pdf")]]),
        )
        ctx.user_data["pdf_mode"] = "extract"
        return WAITING_PDF_IMAGE  # reuse same state for file reception


# ══════════════════════════════════════════════
# TEXT → PDF
# ══════════════════════════════════════════════
async def pdf_receive_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Receive text and generate PDF."""
    text = update.message.text.strip()
    if not text:
        await update.message.reply_text("❌ Please send some text.")
        return WAITING_PDF_TEXT

    msg = await update.message.reply_text("⏳ Creating PDF...")

    try:
        pdf_bytes = _text_to_pdf(text)
        username = update.effective_user.first_name or "user"
        filename = f"document_{update.effective_user.id}.pdf"

        await update.message.reply_document(
            document=io.BytesIO(pdf_bytes),
            filename=filename,
            caption=f"✅ *PDF Ready!*\n📄 {len(text)} characters converted",
            parse_mode="Markdown",
        )
        await msg.delete()
    except Exception as e:
        logger.error(f"Text→PDF error: {e}")
        await msg.edit_text(f"❌ Failed to create PDF: {e}\n\nMake sure `fpdf2` is installed.")

    ctx.user_data.pop("pdf_mode", None)
    return ConversationHandler.END


def _text_to_pdf(text: str) -> bytes:
    """Convert text string to PDF bytes using fpdf2."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_margins(15, 15, 15)
    pdf.set_auto_page_break(auto=True, margin=15)

    # Title bar
    pdf.set_fill_color(41, 128, 185)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "Generated by ExpenseBot", ln=True, fill=True, align="C")
    pdf.ln(5)

    # Body text
    pdf.set_text_color(30, 30, 30)
    pdf.set_font("Helvetica", size=11)

    # Handle multi-line text
    for paragraph in text.split("\n"):
        if paragraph.strip():
            pdf.multi_cell(0, 7, paragraph.encode("latin-1", "replace").decode("latin-1"))
            pdf.ln(2)
        else:
            pdf.ln(4)

    return bytes(pdf.output())


# ══════════════════════════════════════════════
# IMAGE → PDF  /  PDF → TEXT
# ══════════════════════════════════════════════
async def pdf_receive_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle photo (image→pdf) or document (pdf→text or image→pdf)."""
    mode = ctx.user_data.get("pdf_mode", "")

    # ── Photo received ──
    if update.message.photo:
        if mode != "image":
            await update.message.reply_text(
                "📝 I was expecting text. Send /pdf to start over."
            )
            return ConversationHandler.END
        await _handle_image_to_pdf(update, ctx)
        ctx.user_data.pop("pdf_mode", None)
        return ConversationHandler.END

    # ── Document received ──
    if update.message.document:
        doc = update.message.document
        mime = doc.mime_type or ""

        if mime == "application/pdf" or doc.file_name.lower().endswith(".pdf"):
            await _handle_pdf_to_text(update, ctx)
            ctx.user_data.pop("pdf_mode", None)
            return ConversationHandler.END

        if mime.startswith("image/") or doc.file_name.lower().rsplit(".", 1)[-1] in (
            "jpg", "jpeg", "png", "bmp", "gif", "webp"
        ):
            await _handle_image_to_pdf(update, ctx, from_document=True)
            ctx.user_data.pop("pdf_mode", None)
            return ConversationHandler.END

    await update.message.reply_text(
        "❌ Unsupported file. Please send:\n"
        "• A *photo* for Image→PDF\n"
        "• A *PDF file* for PDF→Text",
        parse_mode="Markdown",
    )
    return WAITING_PDF_IMAGE


async def _handle_image_to_pdf(update: Update, ctx: ContextTypes.DEFAULT_TYPE, from_document=False):
    """Convert image to PDF."""
    msg = await update.message.reply_text("⏳ Converting image to PDF...")
    try:
        from PIL import Image as PILImage

        # Download image
        if from_document:
            file = await ctx.bot.get_file(update.message.document.file_id)
        else:
            photo = update.message.photo[-1]  # highest resolution
            file = await ctx.bot.get_file(photo.file_id)

        img_bytes = await file.download_as_bytearray()

        # Convert with Pillow
        img = PILImage.open(io.BytesIO(img_bytes)).convert("RGB")

        pdf_buffer = io.BytesIO()
        img.save(pdf_buffer, format="PDF", resolution=100)
        pdf_bytes = pdf_buffer.getvalue()

        filename = f"image_{update.effective_user.id}.pdf"
        await update.message.reply_document(
            document=io.BytesIO(pdf_bytes),
            filename=filename,
            caption="✅ *Image converted to PDF!*",
            parse_mode="Markdown",
        )
        await msg.delete()

    except ImportError:
        await msg.edit_text("❌ Pillow library not available. Please install it.")
    except Exception as e:
        logger.error(f"Image→PDF error: {e}")
        await msg.edit_text(f"❌ Conversion failed: {e}")


async def _handle_pdf_to_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Extract text from PDF."""
    msg = await update.message.reply_text("⏳ Extracting text from PDF...")
    try:
        import fitz  # PyMuPDF

        file = await ctx.bot.get_file(update.message.document.file_id)
        pdf_bytes = await file.download_as_bytearray()

        doc = fitz.open(stream=bytes(pdf_bytes), filetype="pdf")
        full_text = ""
        for page_num, page in enumerate(doc, 1):
            page_text = page.get_text()
            if page_text.strip():
                full_text += f"--- Page {page_num} ---\n{page_text}\n\n"

        doc.close()

        if not full_text.strip():
            await msg.edit_text(
                "⚠️ No text found in this PDF.\n"
                "It might be a scanned/image PDF."
            )
            return

        # If text is short, send as message
        if len(full_text) <= 3500:
            await msg.edit_text(
                f"📄 *Extracted Text:*\n\n```\n{full_text[:3000]}\n```",
                parse_mode="Markdown",
            )
        else:
            # Send as text file
            txt_buffer = io.BytesIO(full_text.encode("utf-8"))
            filename = f"extracted_{update.effective_user.id}.txt"
            await update.message.reply_document(
                document=txt_buffer,
                filename=filename,
                caption=f"📄 *Text extracted!*\n{len(full_text):,} characters from {doc.page_count if hasattr(doc, 'page_count') else '?'} pages",
                parse_mode="Markdown",
            )
            await msg.delete()

    except ImportError:
        await msg.edit_text(
            "❌ PyMuPDF not installed.\n"
            "Add `pymupdf` to requirements.txt"
        )
    except Exception as e:
        logger.error(f"PDF→Text error: {e}")
        await msg.edit_text(f"❌ Extraction failed: {e}")


# ══════════════════════════════════════════════
# INLINE: detect PDF sent without /pdf command
# ══════════════════════════════════════════════
async def auto_pdf_detect(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Auto-detect PDF files sent to bot and offer extraction."""
    if not update.message or not update.message.document:
        return
    doc = update.message.document
    if doc.mime_type == "application/pdf" or (doc.file_name or "").lower().endswith(".pdf"):
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("📄 Extract Text", callback_data="pdf_auto_extract"),
            InlineKeyboardButton("❌ Ignore", callback_data="cancel"),
        ]])
        ctx.user_data["auto_pdf_file_id"] = doc.file_id
        await update.message.reply_text(
            "📎 *PDF detected!*\n\nWould you like me to extract the text?",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )


async def auto_pdf_extract_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle auto-extract button from PDF detection."""
    query = update.callback_query
    await query.answer()

    file_id = ctx.user_data.get("auto_pdf_file_id")
    if not file_id:
        await query.edit_message_text("❌ File not found. Please send the PDF again.")
        return

    await query.edit_message_text("⏳ Extracting text...")

    try:
        import fitz
        file = await ctx.bot.get_file(file_id)
        pdf_bytes = await file.download_as_bytearray()

        doc = fitz.open(stream=bytes(pdf_bytes), filetype="pdf")
        full_text = ""
        for page_num, page in enumerate(doc, 1):
            page_text = page.get_text()
            if page_text.strip():
                full_text += f"--- Page {page_num} ---\n{page_text}\n\n"
        doc.close()

        if not full_text.strip():
            await query.edit_message_text("⚠️ No extractable text found in this PDF.")
            return

        if len(full_text) <= 3500:
            await query.edit_message_text(
                f"📄 *Extracted Text:*\n\n```\n{full_text[:3000]}\n```",
                parse_mode="Markdown",
            )
        else:
            txt_buffer = io.BytesIO(full_text.encode("utf-8"))
            await ctx.bot.send_document(
                chat_id=query.message.chat_id,
                document=txt_buffer,
                filename="extracted_text.txt",
                caption=f"📄 *Done!* {len(full_text):,} characters extracted.",
                parse_mode="Markdown",
            )
            await query.delete_message()

    except ImportError:
        await query.edit_message_text("❌ PyMuPDF not installed. Add `pymupdf` to requirements.txt")
    except Exception as e:
        await query.edit_message_text(f"❌ Error: {e}")