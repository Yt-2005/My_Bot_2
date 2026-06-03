"""
handlers/notes_handler.py — Personal notes system
/note add    — Save a new note (text or image)
/note list   — View all saved notes
/note delete — Delete a note by ID
/note search <query> — Search notes
/note edit <id> — Edit a note
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode

from database import add_note, get_note, get_notes, delete_note, count_notes, search_notes, update_note, ensure_user, log_error
from utils import notes_keyboard, back_button, is_rate_limited
from config import MAX_NOTES_PER_USER

logger = logging.getLogger(__name__)

# Conversation states
ADDING_NOTE = 1
ADDING_NOTE_CAPTION = 2
DELETING_NOTE = 3
SEARCHING_NOTES = 4
EDITING_NOTE_ID = 5
EDITING_NOTE_CONTENT = 6


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
    elif sub == "search":
        if len(args) > 1:
            ctx.user_data["search_query_override"] = " ".join(args[1:])
        return await note_search_start(update, ctx)
    elif sub == "edit":
        if len(args) > 1:
            try:
                note_id = int(args[1])
                ctx.user_data["editing_note_id"] = note_id
                uid = update.effective_user.id
                note = get_note(note_id, uid)
                if note:
                    current = note["content"] or "(No text)"
                    await update.message.reply_text(
                        f"✏️ *Editing Note #{note_id}*\n\n"
                        f"Current content:\n_{current}_\n\n"
                        f"Please send the new content for this note:",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return EDITING_NOTE_CONTENT
                else:
                    await update.message.reply_text(
                        "❌ Note not found. Please enter a valid note ID.",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return ConversationHandler.END
            except ValueError:
                await update.message.reply_text(
                    "⚠️ Please use: /note edit <note_id>",
                    parse_mode=ParseMode.MARKDOWN
                )
                return ConversationHandler.END
        return await note_edit_start(update, ctx)
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
        [
            InlineKeyboardButton("🔍 Search Notes", callback_data="note_search"),
            InlineKeyboardButton("✏️ Edit Note",   callback_data="note_edit"),
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
                f"✅ *Text Note #{note_id} saved successfully!*\n\n"
                f"📝 _{content}_\n\n"
                f"📊 Total notes: {count}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("👁 View Note", callback_data=f"shownote|{note_id}"),
                    InlineKeyboardButton("📋 View All",  callback_data="note_list"),
                    InlineKeyboardButton("🔙 Menu",      callback_data="menu_main"),
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
                f"✅ *Image Note #{note_id} saved successfully!*\n\n"
                f"🖼 {pending['filename']}\n"
                f"📝 Caption: _{content}_\n\n"
                f"📊 Total notes: {count}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("👁 View Note", callback_data=f"shownote|{note_id}"),
                    InlineKeyboardButton("📋 View All",  callback_data="note_list"),
                    InlineKeyboardButton("🔙 Menu",      callback_data="menu_main"),
                ]])
            )
        else:
            await update.message.reply_text(
                f"✅ *Image Note #{note_id} saved successfully!*\n\n"
                f"🖼 {pending['filename']}\n"
                f"(No caption added)\n\n"
                f"📊 Total notes: {count}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("👁 View Note", callback_data=f"shownote|{note_id}"),
                    InlineKeyboardButton("📋 View All",  callback_data="note_list"),
                    InlineKeyboardButton("🔙 Menu",      callback_data="menu_main"),
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
        [InlineKeyboardButton("✏️ Edit a Note",   callback_data="note_edit")],
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


async def note_show_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id

    try:
        _, note_id_str = query.data.split("|")
        note_id = int(note_id_str)
    except (ValueError, IndexError):
        await query.answer("Invalid note ID", show_alert=True)
        return

    note = get_note(note_id, uid)
    if not note:
        await query.answer("❌ Note not found.", show_alert=True)
        return

    raw = note["created_at"]
    date = raw.strftime("%Y-%m-%d %H:%M") if hasattr(raw, "strftime") else str(raw)[:16]

    if note["image_data"]:
        caption = f"*Note #{note['id']}* — {date}\n\n"
        if note["content"]:
            caption += f"📝 {note['content']}"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Edit", callback_data=f"editnote|{note['id']}")],
            [InlineKeyboardButton("🔙 Back to List", callback_data="note_list")],
        ])
        await query.message.reply_photo(
            photo=note["image_data"],
            filename=note["image_filename"] or f"note_{note['id']}.jpg",
            caption=caption,
            parse_mode="Markdown",
            reply_markup=kb,
        )
    else:
        text = f"*Note #{note['id']}* — {date}\n\n"
        text += note["content"] or "(Empty)"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Edit", callback_data=f"editnote|{note['id']}")],
            [InlineKeyboardButton("🔙 Back to List", callback_data="note_list")],
        ])
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)


async def edit_note_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Entry point for editing a note via inline button."""
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id

    try:
        _, note_id_str = query.data.split("|")
        note_id = int(note_id_str)
    except (ValueError, IndexError):
        await query.answer("Invalid note ID", show_alert=True)
        return ConversationHandler.END

    note = get_note(note_id, uid)
    if not note:
        await query.answer("❌ Note not found.", show_alert=True)
        return ConversationHandler.END

    ctx.user_data["editing_note_id"] = note_id
    current = note["content"] or "(No text)"

    await query.edit_message_text(
        f"✏️ *Editing Note #{note_id}*\n\n"
        f"Current content:\n_{current}_\n\n"
        f"Send the new content for this note:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=back_button("note_list")
    )
    return EDITING_NOTE_CONTENT


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
# SEARCH NOTES
# ─────────────────────────────────────────────

async def note_search_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Start note search conversation."""
    override = ctx.user_data.pop("search_query_override", None)
    if override:
        ctx.user_data["_search_override"] = override
    if update.message:
        await update.message.reply_text(
            "🔍 *Search Notes*\n\nEnter a keyword to search through your notes:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_button("menu_notes")
        )
    return SEARCHING_NOTES


async def note_search_receive(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle search query input."""
    uid = update.effective_user.id
    query_text = ctx.user_data.pop("_search_override", None) or update.message.text.strip()

    if len(query_text) < 2:
        await update.message.reply_text(
            "⚠️ Search query too short. Please enter at least 2 characters.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_button("menu_notes")
        )
        return SEARCHING_NOTES

    results = search_notes(uid, query_text)

    if not results:
        await update.message.reply_text(
            f"📭 *No results found*\n\nNo notes match \"{query_text}\".",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_button("menu_notes")
        )
        return ConversationHandler.END

    text = f"🔍 *Search Results* ({len(results)} found)\n\n"
    for note in results:
        raw = note["created_at"]
        date = raw.strftime("%Y-%m-%d") if hasattr(raw, "strftime") else str(raw)[:10]
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
        text = text[:3900] + "\n\n_...more results. Refine your search._"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="menu_notes")],
    ])

    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
    return ConversationHandler.END


# ─────────────────────────────────────────────
# EDIT NOTE
# ─────────────────────────────────────────────

async def note_edit_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Start note edit conversation."""
    uid = update.effective_user.id
    notes = get_notes(uid)
    if not notes:
        if update.message:
            await update.message.reply_text(
                "📭 *No notes to edit.*\n\nUse /note add to create a note first.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=back_button("menu_notes")
            )
        return ConversationHandler.END

    if update.message:
        await update.message.reply_text(
            "✏️ *Edit a Note*\n\nEnter the note ID you want to edit:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=notes_keyboard(notes)
        )
    ctx.user_data["editing_note"] = True
    return EDITING_NOTE_ID


async def note_edit_receive(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle note edit input."""
    uid = update.effective_user.id
    text = update.message.text.strip()

    try:
        note_id = int(text)
    except ValueError:
        await update.message.reply_text(
            "⚠️ Please enter a valid note ID number.",
            parse_mode=ParseMode.MARKDOWN
        )
        return EDITING_NOTE_ID

    note = get_note(note_id, uid)
    if not note:
        await update.message.reply_text(
            "❌ Note not found. Please enter a valid note ID.",
            parse_mode=ParseMode.MARKDOWN
        )
        return EDITING_NOTE_ID

    ctx.user_data["editing_note_id"] = note_id

    current = note["content"] or "(No text)"
    await update.message.reply_text(
        f"✏️ *Editing Note #{note_id}*\n\n"
        f"Current content:\n_{current}_\n\n"
        f"Please send the new content for this note:",
        parse_mode=ParseMode.MARKDOWN
    )
    return EDITING_NOTE_CONTENT


async def note_edit_save(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Save the edited note content."""
    uid = update.effective_user.id
    note_id = ctx.user_data.get("editing_note_id")

    if not note_id:
        await update.message.reply_text(
            "❌ Session expired. Please start editing again.",
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END

    new_content = update.message.text.strip()
    if len(new_content) > 1000:
        await update.message.reply_text(
            "❌ Note is too long (max 1000 characters). Please shorten it."
        )
        return EDITING_NOTE_CONTENT

    success = update_note(note_id, uid, new_content)
    if success:
        await update.message.reply_text(
            f"✅ *Note #{note_id} updated successfully!*\n\n"
            f"📝 New content: _{new_content}_",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("👁 View Note", callback_data=f"shownote|{note_id}"),
                InlineKeyboardButton("📋 View All",  callback_data="note_list"),
                InlineKeyboardButton("🔙 Menu",      callback_data="menu_main"),
            ]])
        )
        ctx.user_data.pop("editing_note", None)
        ctx.user_data.pop("editing_note_id", None)
        return ConversationHandler.END
    else:
        await update.message.reply_text(
            "❌ Failed to update note. Please try again.",
            parse_mode=ParseMode.MARKDOWN
        )
        return EDITING_NOTE_CONTENT


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
            kb = notes_keyboard(notes)
            await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)

    elif data == "shownote":
        await note_show_callback(update, ctx)

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
    elif data == "note_search":
        await query.edit_message_text(
            "🔍 *Search Notes*\n\nEnter a keyword to search through your notes:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_button("menu_notes")
        )
        ctx.user_data["searching_notes"] = True
        return SEARCHING_NOTES

    elif data == "note_edit":
        notes = get_notes(uid)
        if not notes:
            await query.edit_message_text(
                "📭 *No notes to edit.*\n\nUse /note add to create a note first.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=back_button("menu_notes")
            )
        else:
            await query.edit_message_text(
                "✏️ *Edit a Note*\n\nTap the note you want to edit:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=notes_keyboard(notes, show_edit=True)
            )
            ctx.user_data["editing_note"] = True
            return EDITING_NOTE_ID
    return ConversationHandler.END




