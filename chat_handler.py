"""
handlers/chat_handler.py — AI Chat Assistant handler
/chat — Start a conversation with AI
Supports: memory per user, typing animation, markdown formatting
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode, ChatAction

from ai import chat as ai_chat
from utils import is_rate_limited, back_button
from database import ensure_user, log_error
from config import GEMINI_KEYS

logger = logging.getLogger(__name__)

# Conversation state
CHATTING = 1


# ─────────────────────────────────────────────
# /chat — START AI CONVERSATION
# ─────────────────────────────────────────────

async def chat_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Start AI chat mode."""
    uid = update.effective_user.id
    ensure_user(uid)

    if not GEMINI_KEYS:
        await update.message.reply_text(
            "❌ *AI Chat is not configured.*\n\n"
            "The admin needs to add `GEMINI_KEY_1` to the environment variables.",
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "🤖 *AI Chat Assistant*\n\n"
        "I'm ready to help! Send me any message and I'll reply.\n\n"
        "💡 I remember our recent conversation.\n"
        "🔄 Use /clearchat to reset my memory.\n"
        "❌ Use /cancel to exit chat mode.\n\n"
        "✉️ *What's on your mind?*",
        parse_mode=ParseMode.MARKDOWN
    )
    return CHATTING


async def chat_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle a message in chat mode."""
    uid = update.effective_user.id
    text = update.message.text.strip()

    if not text:
        return CHATTING

    if is_rate_limited(uid):
        await update.message.reply_text("⏳ Please slow down a little!")
        return CHATTING

    # Show typing animation
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    # Call AI
    reply, error = await ai_chat(uid, text)

    if error:
        log_error(uid, error, "ai_chat")
        await update.message.reply_text(
            f"❌ *AI Error:*\n{error}\n\nTry again or /clearchat to reset.",
            parse_mode=ParseMode.MARKDOWN
        )
        return CHATTING

    # Send AI reply with Markdown
    # Telegram can fail on malformed markdown — fall back to plain text
    try:
        await update.message.reply_text(
            reply,
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception:
        await update.message.reply_text(reply)

    return CHATTING


# ─────────────────────────────────────────────
# DIRECT MESSAGE AI (outside /chat mode)
# ─────────────────────────────────────────────

async def handle_text_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    If user sends a plain text message outside any conversation,
    offer to use AI chat.
    """
    if not update.message or not update.message.text:
        return

    text = update.message.text
    if text.startswith("/"):
        return  # Ignore commands

    # Don't respond to very short messages to avoid noise
    if len(text) < 3:
        return

    await update.message.reply_text(
        "💬 Want to chat with AI? Use /chat to start!\n\n"
        "Or use /start to see all features.",
        reply_markup=back_button("menu_main")
    )
