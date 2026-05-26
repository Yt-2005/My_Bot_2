"""
handlers/core.py — Core bot commands and menu navigation
/start, /help, /cancel, /clearchat, inline menu callbacks
"""

import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode

from database import ensure_user, get_language, clear_chat_history
from utils import main_menu_keyboard, back_button
import config as _cfg

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Welcome message with main menu."""
    user = update.effective_user
    ensure_user(user.id, user.username or "")

    if _cfg.MAINTENANCE_MODE:
        await update.message.reply_text(
            "🔧 *Bot is under maintenance.*\nPlease come back later!",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    lang = get_language(user.id)
    if lang == "km":
        welcome = (
            f"👋 *សួស្ដី, {user.first_name}!*\n\n"
            "ខ្ញុំជា AI assistant bot របស់អ្នក។ ខ្ញុំអាចធ្វើបាន:\n\n"
            "🎨 *AI Image Generator* — បង្កើតរូបភាពស្រស់ស្អាត\n"
            "✨ *AI Upscaler* — ធ្វើឱ្យរូបភាពមានគុណភាព 4K\n"
            "🤖 *AI Chat* — សន្ទនាឆ្លាត\n"
            "📝 *Notes* — រក្សាទុកការចំណាំ\n"
            "💰 *Expenses* — តាមដានការចំណាយ\n\n"
            "👇 *ជ្រើសរើសពីម៉ឺនុយ:*"
        )
    else:
        welcome = (
            f"👋 *Hello, {user.first_name}!*\n\n"
            "I'm your smart AI assistant bot. Here's what I can do:\n\n"
            "🎨 *AI Image Generator* — Create stunning images\n"
            "✨ *AI Upscaler* — Enhance photos to 4K quality\n"
            "🤖 *AI Chat* — Smart conversations\n"
            "📝 *Notes* — Save personal reminders\n"
            "💰 *Expenses* — Track your spending\n\n"
            "👇 *Choose from the menu below:*"
        )

    await update.message.reply_text(
        welcome,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu_keyboard(),
    )


# ─────────────────────────────────────────────
# /help
# ─────────────────────────────────────────────

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show all available commands."""
    text = (
        "📖 *All Commands*\n\n"
        "━━━ 🤖 *AI Features* ━━━\n"
        "/imagine   — 🎨 Generate AI images\n"
        "/upscale   — ✨ Enhance your photos\n"
        "/chat      — 💬 Chat with AI\n"
        "/clearchat — 🔄 Reset AI memory\n\n"
        "━━━ 📝 *Notes* ━━━\n"
        "/note add    — Add a note\n"
        "/note list   — View all notes\n"
        "/note delete — Delete a note\n\n"
        "━━━ 💰 *Expenses* ━━━\n"
        "/add       — Add expense\n"
        "/today     — Today's expenses\n"
        "/month     — Monthly summary\n"
        "/compare   — Compare months\n"
        "/budget    — Set monthly budget\n"
        "/date      — Search by date\n"
        "/tags      — Search by tag\n"
        "/delete    — Delete expense\n"
        "/recurring — Recurring expenses\n"
        "/ai        — 💡 AI finance advice\n\n"
        "━━━ ⚙️ *Settings* ━━━\n"
        "/lang      — Change language (KH/EN)\n"
        "/setpin    — Set security PIN\n"
        "/reminder  — Set daily reminder\n\n"
        "━━━ 📋 *Other* ━━━\n"
        "/start  — Main menu\n"
        "/help   — This help page\n"
        "/cancel — Cancel current action\n"
    )
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=back_button("menu_main"),
    )


# ─────────────────────────────────────────────
# /cancel
# ─────────────────────────────────────────────

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Cancel any active conversation."""
    ctx.user_data.clear()
    await update.message.reply_text(
        "❌ *Cancelled.* Use /start to go back to the main menu.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END


# ─────────────────────────────────────────────
# /clearchat
# ─────────────────────────────────────────────

async def clear_chat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Clear user's AI chat memory."""
    uid = update.effective_user.id
    clear_chat_history(uid)
    await update.message.reply_text(
        "🔄 *Chat memory cleared!*\nAI will start fresh.",
        parse_mode=ParseMode.MARKDOWN,
    )


# ─────────────────────────────────────────────
# INLINE MENU CALLBACKS
# ─────────────────────────────────────────────

MENU_TEXTS = {
    "menu_imagegen": (
        "🎨 *AI Image Generator*\n\n"
        "Turn your ideas into stunning images!\n\n"
        "*How to use:*\n"
        "Send /imagine followed by your description\n\n"
        "*Example:*\n"
        "`/imagine a cat sitting on the moon at night`\n\n"
        "Then pick your preferred art style 🖼️"
    ),
    "menu_upscale": (
        "✨ *AI Image Upscaler*\n\n"
        "Upload any photo and I'll enhance it:\n"
        "• 📐 Upscale to near-4K resolution\n"
        "• 🔍 Sharpen blurry details\n"
        "• 🎨 Boost colors and contrast\n"
        "• 🧹 Reduce noise\n\n"
        "*How to use:*\n"
        "Simply send /upscale then upload your photo!"
    ),
    "menu_chat": (
        "🤖 *AI Chat Assistant*\n\n"
        "I can help you with:\n"
        "• 💡 Questions and explanations\n"
        "• ✍️ Writing and editing\n"
        "• 🧮 Calculations and analysis\n"
        "• 🌍 Translations\n"
        "• And much more!\n\n"
        "*How to use:*\n"
        "Send /chat then start typing!"
    ),
    "menu_notes": (
        "📝 *My Notes*\n\nQuick personal reminders:\n\n"
        "• `/note add` — Write a new note\n"
        "• `/note list` — See all your notes\n"
        "• `/note delete` — Remove a note"
    ),
    "menu_expenses": (
        "💰 *Expense Tracker*\n\n"
        "Track your spending easily:\n\n"
        "• `/add` — Record new expense\n"
        "• `/today` — Today's total\n"
        "• `/month` — Monthly breakdown\n"
        "• `/budget` — Set spending limit\n"
        "• `/ai` — Get AI financial advice"
    ),
    "menu_settings": (
        "⚙️ *Settings*\n\n"
        "• `/lang` — Change language (KH/EN)\n"
        "• `/setpin` — Set security PIN\n"
        "• `/reminder` — Daily spending reminder\n"
        "• `/clearchat` — Reset AI chat memory"
    ),
    "menu_ai_finance": (
        "🤖 *AI Financial Advisor*\n\n"
        "Get personalized money-saving tips based on your spending data!\n\n"
        "Use `/ai` to get your analysis."
    ),
}


async def menu_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle all inline menu button presses."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "cancel":
        await query.edit_message_text("❌ Cancelled.")
        return

    if data == "menu_main":
        await query.edit_message_text(
            "🏠 *Main Menu*\n\nChoose what you'd like to do:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu_keyboard(),
        )
        return

    if data == "menu_help":
        await query.edit_message_text(
            "📖 *Help & Commands*\n\n"
            "Use /help to see all commands.\n\n"
            "For AI images: /imagine\n"
            "For upscaling: /upscale\n"
            "For AI chat: /chat",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_button("menu_main"),
        )
        return

    if data in MENU_TEXTS:
        await query.edit_message_text(
            MENU_TEXTS[data],
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_button("menu_main"),
        )
        return

    # Unknown callback — silently ignore
    logger.warning(f"Unknown menu callback: {data}")