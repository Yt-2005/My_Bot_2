"""
handlers/core.py — Core handlers: /start, /help, /cancel, menu_callback
All menu_ callbacks handled here with full Back button navigation.
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from database import ensure_user
from utils import main_menu_keyboard, back_button
from config import ADMIN_IDS

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════
# /start
# ══════════════════════════════════════════════
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, user.username or "")

    text = (
        f"👋 *Welcome, {user.first_name}!*\n\n"
        "I'm your all-in-one AI assistant:\n"
        "💰 Track expenses • 🤖 AI chat • 🎨 Image gen\n"
        "📝 Notes • 📄 PDF tools • ✨ Image upscaler\n\n"
        "Choose an option below:"
    )
    if update.message:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())
    else:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())


# ══════════════════════════════════════════════
# /help
# ══════════════════════════════════════════════
async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = _help_text()
    kb = back_button("menu_main")
    if update.message:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
    else:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)


def _help_text() -> str:
    return (
        "📖 *Bot Commands*\n\n"
        "━━━ 💰 *Expenses* ━━━\n"
        "/add — Record new expense\n"
        "/today — Today's total\n"
        "/month — Monthly breakdown\n"
        "/compare — Compare months\n"
        "/budget — Set spending limit\n"
        "/recurring — View recurring expenses\n"
        "/date — Search by date\n"
        "/tags — Search by tag\n"
        "/delete — Delete an expense\n"
        "/ai — AI financial advice\n\n"
        "━━━ 🎨 *AI & Media* ━━━\n"
        "/imagine — Generate AI image\n"
        "/upscale — Upscale a photo\n"
        "/chat — AI conversation\n\n"
        "━━━ 📄 *PDF Tools* ━━━\n"
        "/pdf — PDF menu\n"
        "  📝 Text → PDF\n"
        "  🖼️ Image → PDF\n"
        "  📄 PDF → Text\n\n"
        "━━━ 📝 *Notes* ━━━\n"
        "/note — Manage notes\n\n"
        "━━━ ⚙️ *Settings* ━━━\n"
        "/lang — Change language\n"
        "/setpin — Set PIN lock\n"
        "/reminder — Daily reminder\n\n"
        "/cancel — Cancel any action"
    )


# ══════════════════════════════════════════════
# /cancel
# ══════════════════════════════════════════════
async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text(
        "❌ *Cancelled.*\n\nUse /start to go back to the main menu.",
        parse_mode="Markdown",
        reply_markup=back_button("menu_main"),
    )
    return ConversationHandler.END


# ══════════════════════════════════════════════
# /clearchat
# ══════════════════════════════════════════════
async def clear_chat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from database import clear_chat_memory
    try:
        clear_chat_memory(update.effective_user.id)
    except Exception:
        pass
    await update.message.reply_text(
        "🧹 *Chat memory cleared!*\n\nStart a fresh conversation with /chat.",
        parse_mode="Markdown",
        reply_markup=back_button("menu_main"),
    )


# ══════════════════════════════════════════════
# MENU CALLBACK ROUTER — handles ALL menu_ callbacks
# ══════════════════════════════════════════════
async def menu_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    handlers = {
        "menu_main":       _menu_main,
        "cancel":          _menu_main,
        "menu_imagegen":   _menu_imagegen,
        "menu_upscale":    _menu_upscale,
        "menu_chat":       _menu_chat,
        "menu_notes":      _menu_notes,
        "menu_expenses":   _menu_expenses,
        "menu_ai_finance": _menu_ai_finance,
        "menu_pdf":        _menu_pdf,
        "menu_settings":   _menu_settings,
        "menu_help":       _menu_help,
    }

    fn = handlers.get(data)
    if fn:
        await fn(query, ctx)
    else:
        await query.edit_message_text(
            "❓ Unknown option. Use /start.",
            reply_markup=back_button("menu_main"),
        )


# ── Individual menu screens ──────────────────

async def _menu_main(query, ctx):
    await query.edit_message_text(
        "🏠 *Main Menu*\n\nChoose an option:",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )


async def _menu_imagegen(query, ctx):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎨 Generate Image", switch_inline_query_current_chat="/imagine ")],
        [InlineKeyboardButton("🔙 Back", callback_data="menu_main")],
    ])
    await query.edit_message_text(
        "🎨 *AI Image Generator*\n\n"
        "Use /imagine followed by your prompt.\n\n"
        "*Example:*\n`/imagine a sunset over mountains, photorealistic`\n\n"
        "Available styles:\n"
        "🌄 Realistic • 🎌 Anime • 🌆 Cyberpunk\n"
        "🕹️ Pixel Art • 🎲 3D Render",
        parse_mode="Markdown",
        reply_markup=kb,
    )


async def _menu_upscale(query, ctx):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✨ Start Upscaling", switch_inline_query_current_chat="/upscale")],
        [InlineKeyboardButton("🔙 Back", callback_data="menu_main")],
    ])
    await query.edit_message_text(
        "✨ *AI Image Upscaler*\n\n"
        "Send /upscale and then send a photo to enhance its resolution.\n\n"
        "Great for:\n"
        "• Low-res photos 📷\n"
        "• Old family pictures 🖼️\n"
        "• Blurry screenshots 📱",
        parse_mode="Markdown",
        reply_markup=kb,
    )


async def _menu_chat(query, ctx):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Start Chatting", switch_inline_query_current_chat="/chat")],
        [InlineKeyboardButton("🧹 Clear Memory", callback_data="menu_clearchat")],
        [InlineKeyboardButton("🔙 Back", callback_data="menu_main")],
    ])
    await query.edit_message_text(
        "🤖 *AI Chat*\n\n"
        "Have a conversation with AI.\n"
        "The bot remembers your last 10 messages.\n\n"
        "Use /chat to start chatting.\n"
        "Use /clearchat to reset memory.",
        parse_mode="Markdown",
        reply_markup=kb,
    )


async def _menu_notes(query, ctx):
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Add Note", switch_inline_query_current_chat="/note add"),
            InlineKeyboardButton("📋 List Notes", switch_inline_query_current_chat="/note list"),
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="menu_main")],
    ])
    await query.edit_message_text(
        "📝 *My Notes*\n\n"
        "Save and manage your personal notes.\n\n"
        "Commands:\n"
        "• /note — Open notes menu\n"
        "• Add, list, or delete notes",
        parse_mode="Markdown",
        reply_markup=kb,
    )


async def _menu_expenses(query, ctx):
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Add",     switch_inline_query_current_chat="/add"),
            InlineKeyboardButton("📅 Today",   switch_inline_query_current_chat="/today"),
        ],
        [
            InlineKeyboardButton("📆 Month",   switch_inline_query_current_chat="/month"),
            InlineKeyboardButton("💰 Budget",  switch_inline_query_current_chat="/budget"),
        ],
        [
            InlineKeyboardButton("📊 Compare", switch_inline_query_current_chat="/compare"),
            InlineKeyboardButton("🔁 Recurring", switch_inline_query_current_chat="/recurring"),
        ],
        [
            InlineKeyboardButton("🔍 By Date", switch_inline_query_current_chat="/date"),
            InlineKeyboardButton("🏷️ By Tag",  switch_inline_query_current_chat="/tags"),
        ],
        [
            InlineKeyboardButton("🗑️ Delete",  switch_inline_query_current_chat="/delete"),
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="menu_main")],
    ])
    await query.edit_message_text(
        "💰 *Expense Tracker*\n\n"
        "Track your spending easily with AI:\n\n"
        "• /add — Record new expense\n"
        "• /today — Today's total\n"
        "• /month — Monthly breakdown\n"
        "• /budget — Set spending limit\n"
        "• /compare — Compare months\n"
        "• /recurring — Recurring expenses\n"
        "• /date — Search by date\n"
        "• /tags — Search by tag\n"
        "• /delete — Delete expense",
        parse_mode="Markdown",
        reply_markup=kb,
    )


async def _menu_ai_finance(query, ctx):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 Get AI Advice", switch_inline_query_current_chat="/ai")],
        [InlineKeyboardButton("🔙 Back", callback_data="menu_main")],
    ])
    await query.edit_message_text(
        "🤖 *AI Financial Advisor*\n\n"
        "Get personalized financial insights based on your spending data.\n\n"
        "Use /ai to ask questions like:\n"
        "• _\"Where am I spending the most?\"_\n"
        "• _\"How can I save more this month?\"_\n"
        "• _\"Am I close to my budget?\"_",
        parse_mode="Markdown",
        reply_markup=kb,
    )


async def _menu_pdf(query, ctx):
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📝 Text → PDF", callback_data="pdf_text"),
            InlineKeyboardButton("🖼️ Image → PDF", callback_data="pdf_image"),
        ],
        [
            InlineKeyboardButton("📄 PDF → Text", callback_data="pdf_extract"),
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="menu_main")],
    ])
    await query.edit_message_text(
        "📄 *PDF Tools*\n\n"
        "Choose what you want to do:\n\n"
        "📝 *Text → PDF* — Convert text into a PDF file\n"
        "🖼️ *Image → PDF* — Convert a photo into a PDF file\n"
        "📄 *PDF → Text* — Extract text from a PDF file",
        parse_mode="Markdown",
        reply_markup=kb,
    )


async def _menu_settings(query, ctx):
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🌐 Language",    switch_inline_query_current_chat="/lang"),
            InlineKeyboardButton("🔐 Set PIN",     switch_inline_query_current_chat="/setpin"),
        ],
        [
            InlineKeyboardButton("⏰ Reminder",    switch_inline_query_current_chat="/reminder"),
            InlineKeyboardButton("🧹 Clear Chat",  switch_inline_query_current_chat="/clearchat"),
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="menu_main")],
    ])
    await query.edit_message_text(
        "⚙️ *Settings*\n\n"
        "• /lang — Change language\n"
        "• /setpin — Set a PIN lock for expenses\n"
        "• /reminder — Set daily expense reminder\n"
        "• /clearchat — Clear AI chat memory",
        parse_mode="Markdown",
        reply_markup=kb,
    )


async def _menu_help(query, ctx):
    await query.edit_message_text(
        _help_text(),
        parse_mode="Markdown",
        reply_markup=back_button("menu_main"),
    )