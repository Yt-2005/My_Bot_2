"""
handlers/chat_handler.py — AI Chat Assistant handler
/chat — Start a conversation with AI (powered by Groq)
Supports: memory per user, typing animation, markdown formatting
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode, ChatAction

from ai import chat as ai_chat, is_configured
from utils import is_rate_limited, back_button
from database import ensure_user, log_error

logger = logging.getLogger(__name__)

CHATTING = 1


async def chat_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)

    if not is_configured():
        await update.message.reply_text(
            "❌ *AI Chat not configured.*\n\n"
            "Add `GROQ_API_KEY` to your environment.\n"
            "Get a free key at: [console.groq.com](https://console.groq.com)",
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "🤖 *AI Chat Assistant*\n\n"
        "⚡ _Powered by Groq AI (llama-3.3-70b)_\n\n"
        "I'm ready! Send me any message.\n\n"
        "💡 I remember our recent conversation.\n"
        "🔄 Use /clearchat to reset memory.\n"
        "❌ Use /cancel to exit.\n\n"
        "✉️ *What's on your mind?*",
        parse_mode=ParseMode.MARKDOWN
    )
    return CHATTING


async def chat_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    text = update.message.text.strip()

    if not text:
        return CHATTING

    if is_rate_limited(uid):
        await update.message.reply_text("⏳ Please slow down a little!")
        return CHATTING

    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    reply, error = await ai_chat(uid, text)

    if error:
        log_error(uid, error, "ai_chat")
        await update.message.reply_text(
            f"❌ *AI Error:*\n{error}\n\nTry again or /clearchat to reset.",
            parse_mode=ParseMode.MARKDOWN
        )
        return CHATTING

    try:
        await update.message.reply_text(reply, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        await update.message.reply_text(reply)

    return CHATTING


async def handle_text_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    text = update.message.text
    if text.startswith("/") or len(text) < 3:
        return
    await update.message.reply_text(
        "💬 Want to chat with AI? Use /chat to start!\n\n"
        "Or use /start to see all features.",
        reply_markup=back_button("menu_main")
    )
