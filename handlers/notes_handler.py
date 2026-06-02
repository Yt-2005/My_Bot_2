"""
handlers/notes_handler.py — Personal notes system
/note add    — Save a new note (text or image)
/note list   — View all saved notes
/note delete — Delete a note by ID
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode

from database import add_note, get_notes, delete_note, count_notes, ensure_user, log_error
from utils import notes_keyboard, back_button, is_rate_limited
from config import MAX_NOTES_PER_USER

logger = logging.getLogger(__name__)

# Conversation states
ADDING_NOTE = 1
ADDING_NOTE_CAPTION = 2
DELETING_NOTE = 3


# ─────────────────────────────────────────────
# /note — ROUTER
# ─────────────────────────────────────────────

async def note_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Route /note add | list | delete
    /note (no args) → show menu
    """
    uid = update.effective_user.id
    ensure_user(uid)

    args = ctx.args
    if not args:
        return await note_menu(update, ctx)

    sub = args[0].lower()
    if sub == "add":
        return await note_add_start(update, ctx)
    elif sub == "list":
        return await note_list(update, ctx)
    elif sub in ("delete", "del", "remove"):
        return await note_delete_start(update, ctx)
    else:
        return await note_menu(update, ctx)


async def note_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show note options menu."""
    uid = update.effective_user.id
    count = count_notes(uid)

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Add Note",    callback_data="note_add"),
            InlineKeyboardButton("📋 List Notes",  callback_data="note_list"),
        ],
        [InlineKeyboardButton("🗑️ Delete Note",   callback_data="note_delete")],
        [InlineKeyboardButton("🔙 Main Menu",      callback_data="menu_main")],
    ])

    await update.message.reply_text(
        f"📝 *My Notes*\n\n"
        f"You have *{count}* note{'s' if count != 1 else ''} saved.\n\n"
        "What would you like to do?\n\n"
        "You can save text notes or send images to save as image notes.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb
    )
    return ConversationHandler.END


# ─────────────────────────────────────────────
# ADD NOTE
# ─────────────────────────────────────────────

async def note_add_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Prompt user to type their note or send an image."""
    uid = update.effective_user.id
    count = count_notes(uid)

    if count >= MAX_NOTES_PER_USER:
        await update.message.reply_text(
            f"❌ *Note limit reached!*\n\n"
            f"You can store up to {MAX_NOTES_PER_USER} notes.\n"
            "Please delete some before adding new ones.",
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "📝 *New Note*\n\n"
        "Type your note below or send an image to save as an image note.\n\n"
        "_Send /cancel to abort_",
        parse_mode=ParseMode.MARKDOWN
    )
    return ADDING_NOTE


async def note_add_receive(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Save the note text or image."""
    uid = update.effective_user.id
    
    # Handle text message
    if update.message.text:
        content = update.message.text.strip()
        
        if len(content) > 1000:
            await update.message.reply_text(
                "❌ Note is too long (max 1000 characters). Please shorten it."
            )
            return ADDING_NOTE
        
        try:
            note_id = add_note(uid, content=content)
            count = count_notes(uid)
            
            await update.message.reply_text(
                f"✅ *Text Note #{note_id} saved!*\n\n"
                f"📝 _{content}_\n\n"
                f"You now have {count} note{'s' if count != 1 else ''}.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("📋 View All Notes", callback_data="note_list"),
                    InlineKeyboardButton("🔙 Menu",           callback_data="menu_main"),
                ]])
            )
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Failed to save text note: {e}")
            await update.message.reply_text(
                "❌ Failed to save note. Please try again.",
                parse_mode=ParseMode.MARKDOWN
            )
            return ADDING_NOTE
    
    # Handle photo message
    elif update.message.photo:
        try:
            # Get the largest available photo
            photo = update.message.photo[-1]
            file = await ctx.bot.get_file(photo.file_id)
            image_data = await file.download_as_bytearray()
            image_data = bytes(image_data)
            
            # Get file info
            image_filename = f"photo_{photo.file_id}.jpg"
            
            # Optional: Ask for caption/description
            ctx.user_data["pending_image"] = {
                "data": image_data,
                "filename": image_filename
            }
            
            await update.message.reply_text(
                "🖼 *Image received!*\n\n"
                "Now you can add a caption/description for this image (optional):\n\n"
                "_Send /skip to save without caption_",
                parse_mode=ParseMode.MARKDOWN
            )
            return ADDING_NOTE_CAPTION
        except Exception as e:
            logger.error(f"Failed to process photo: {e}")
            await update.message.reply_text(
                "❌ Failed to process image. Please try again.",
                parse_mode=ParseMode.MARKDOWN
            )
            return ADDING_NOTE
    
    # Handle document message (if it's an image)
    elif update.message.document and update.message.document.mime_type and update.message.document.mime_type.startswith("image/"):
        try:
            # Get the document
            document = update.message.document
            file = await ctx.bot.get_file(document.file_id)
            image_data = await file.download_as_bytearray()
            image_data = bytes(image_data)
            
            # Use the original filename or generate one
            image_filename = document.file_name or f"image_{document.file_id}"
            
            # Optional: Ask for caption/description
            ctx.user_data["pending_image"] = {
                "data": image_data,
                "filename": image_filename
            }
            
            await update.message.reply_text(
                f"🖼 *Image received!* ({document.file_name or 'unnamed'})\n\n"
                "Now you can add a caption/description for this image (optional):\n\n"
                "_Send /skip to save without caption_",
                parse_mode=ParseMode.MARKDOWN
            )
            return ADDING_NOTE_CAPTION
        except Exception as e:
            logger.error(f"Failed to process image document: {e}")
            await update.message.reply_text(
                "❌ Failed to process image. Please try again.",
                parse_mode=ParseMode.MARKDOWN
            )
            return ADDING_NOTE
    
    else:
        await update.message.reply_text(
            "Please send text, a photo, or an image document for your note."
        )
        return ADDING_NOTE


async def note_add_receive_caption(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Save the caption for an image note."""
    uid = update.effective_user.id
    
    # Get the pending image data
    pending = ctx.user_data.get("pending_image")
    if not pending:
        await update.message.reply_text(
            "❌ Error: No image found. Please try again.",
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END
    
    content = None
    if update.message.text and update.message.text.strip() != "/skip":
        content = update.message.text.strip()
        if len(content) > 1000:
            await update.message.reply_text(
                "❌ Caption is too long (max 1000 characters). Please shorten it."
            )
            return ADDING_NOTE_CAPTION
    
    # Save the image note
    try:
        note_id = add_note(
            uid, 
            content=content, 
            image_data=pending["data"], 
            image_filename=pending["filename"]
        )
        
        # Clear pending data
        ctx.user_data.pop("pending_image", None)
        
        count = count_notes(uid)
        
        if content:
            await update.message.reply_text(
                f"✅ *Image Note #{note_id} saved!*\n\n"
                f"🖼 {pending['filename']}\n"
                f"📝 Caption: _{content}_\n\n"
                f"You now have {count} note{'s' if count != 1 else ''}.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("📋 View All Notes", callback_data="note_list"),
                    InlineKeyboardButton("🔙 Menu",           callback_data="menu_main"),
                ]])
            )
        else:
            await update.message.reply_text(
                f"✅ *Image Note #{note_id} saved!*\n\n"
                f"🖼 {pending['filename']}\n"
                f"(No caption added)\n\n"
                f"You now have {count} note{'s' if count != 1 else ''}.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("📋 View All Notes", callback_data="note_list"),
                    InlineKeyboardButton("🔙 Menu",           callback_data="menu_main"),
                ]])
            )
    
    except Exception as e:
        logger.error(f"Failed to save image note: {e}")
        await update.message.reply_text(
            "❌ Failed to save image note. Please try again.",
            parse_mode=ParseMode.MARKDOWN
        )
        # Clear pending data on error to avoid stale state
        ctx.user_data.pop("pending_image", None)
        return ADDING_NOTE_CAPTION
    
    return ConversationHandler.END
    
# ─────────────────────────────────────────────
# LIST NOTES
# ─────────────────────────────────────────────

async def note_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show all notes for the user."""
    uid = update.effective_user.id
    notes = get_notes(uid)

    if not notes:
        msg = update.message or update.callback_query.message
        await msg.reply_text(
            "📭 *No notes yet!*\n\nUse `/note add` to create your first note.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_button("menu_main")
        )
        return ConversationHandler.END

    text = f"📋 *Your Notes* ({len(notes)} total)\n\n"
    for note in notes:
        # Format date nicely — handle both datetime objects and strings
        raw = note["created_at"]
        date = raw.strftime("%Y-%m-%d") if hasattr(raw, "strftime") else str(raw)[:10]
        
        # Determine note type
        if note["image_data"]:
            note_type = "🖼 Image"
            if note["image_filename"]:
                note_type += f" ({note['image_filename']})"
            if note["content"]:
                note_type += f": _{note['content'][:50]}{'...' if len(note['content']) > 50 else ''}_"
            else:
                note_type += " (No caption)"
        else:
            note_type = "📝 Text"
            if note["content"]:
                note_type += f": _{note['content'][:50]}{'...' if len(note['content']) > 50 else ''}_"
            else:
                note_type += " (Empty)"
        
        text += f"*#{note['id']}* — {date}\n{note_type}\n\n"

    if len(text) > 4000:
        text = text[:3900] + "\n\n_...and more. Delete some to see all._"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑️ Delete a Note", callback_data="note_delete")],
        [InlineKeyboardButton("🔙 Menu",           callback_data="menu_main")],
    ])

    # Handle both direct command and callback
    if update.message:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
    else:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)

    return ConversationHandler.END


# ─────────────────────────────────────────────
# DELETE NOTE
# ─────────────────────────────────────────────

async def note_delete_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show notes list with delete buttons."""
    uid = update.effective_user.id
    notes = get_notes(uid)

    if not notes:
        await update.message.reply_text(
            "📭 *No notes to delete.*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_button("menu_main")
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "🗑️ *Delete a Note*\n\nTap the note you want to delete:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=notes_keyboard(notes)
    )
    return ConversationHandler.END


async def delete_note_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle tapping a note to delete it."""
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id

    try:
        _, note_id_str = query.data.split("|")
        note_id = int(note_id_str)
    except (ValueError, IndexError):
        await query.answer("Invalid note ID", show_alert=True)
        return

    success = delete_note(note_id, uid)
    if success:
        # Refresh the delete list
        notes = get_notes(uid)
        if notes:
            await query.edit_message_text(
                f"✅ *Note #{note_id} deleted!*\n\nTap another note to delete:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=notes_keyboard(notes)
            )
        else:
            await query.edit_message_text(
                "✅ *Note deleted!*\n\nYou have no more notes.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=back_button("menu_main")
            )
    else:
        await query.answer("❌ Note not found or already deleted.", show_alert=True)


# ─────────────────────────────────────────────
# INLINE CALLBACKS (from menu)
# ─────────────────────────────────────────────

async def note_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle note_add / note_list / note_delete callbacks from inline menus."""
    query = update.callback_query
    await query.answer()
    data = query.data

    uid = query.from_user.id

    if data == "note_add":
        count = count_notes(uid)
        if count >= MAX_NOTES_PER_USER:
            await query.edit_message_text(
                f"❌ Note limit reached ({MAX_NOTES_PER_USER} max).\nDelete some notes first.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=back_button("menu_notes")
            )
        else:
            await query.edit_message_text(
                "📝 *New Note*\n\nSend your note as a message or send an image!\n\n_Use /cancel to abort_",
                parse_mode=ParseMode.MARKDOWN
            )
            ctx.user_data["awaiting_note"] = True

    elif data == "note_list":
        notes = get_notes(uid)
        if not notes:
            await query.edit_message_text(
                "📭 *No notes yet!*\n\nUse `/note add` to start.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=back_button("menu_main")
            )
        else:
            text = f"📋 *Your Notes* ({len(notes)} total)\n\n"
            for note in notes:
                raw = note["created_at"]
                date = raw.strftime("%Y-%m-%d") if hasattr(raw, "strftime") else str(raw)[:10]
                
                # Determine note type
                if note["image_data"]:
                    note_type = "🖼 Image"
                    if note["image_filename"]:
                        note_type += f" ({note['image_filename']})"
                    if note["content"]:
                        note_type += f": _{note['content'][:30]}{'...' if len(note['content']) > 30 else ''}_"
                    else:
                        note_type += " (No caption)"
                else:
                    note_type = "📝 Text"
                    if note["content"]:
                        note_type += f": _{note['content'][:30]}{'...' if len(note['content']) > 30 else ''}_"
                    else:
                        note_type += " (Empty)"
                
                text += f"*#{note['id']}* — {date}\n{note_type}\n\n"
            
            if len(text) > 4000:
                text = text[:3900] + "\n\n_...trimmed_"
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑️ Delete a Note", callback_data="note_delete")],
                [InlineKeyboardButton("🔙 Back",           callback_data="menu_notes")],
            ])
            await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)

    elif data == "note_delete":
        notes = get_notes(uid)
        if not notes:
            await query.edit_message_text(
                "📭 Nothing to delete.",
                reply_markup=back_button("menu_notes")
            )
        else:
            await query.edit_message_text(
                "🗑️ *Tap a note to delete it:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=notes_keyboard(notes)
            )
    return ConversationHandler.END




