"""
handlers/chat_handler.py — AI Chat Assistant handler
/chat — Start a conversation with AI (powered by Groq)
Supports: memory per user, typing animation, markdown formatting, KH/EN language
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode, ChatAction

from ai import chat as ai_chat, is_configured
from utils import is_rate_limited, back_button
from database import ensure_user, log_error, get_language

logger = logging.getLogger(__name__)

CHATTING = 1

# ─── UI Text by language ───────────────────────────────────────────────────────
TEXTS = {
    "en": {
        "not_configured": (
            "❌ *AI Chat not configured.*\n\n"
            "Add `GROQ_API_KEY` to your environment.\n"
            "Get a free key at: [console.groq.com](https://console.groq.com)"
        ),
        "welcome": (
            "🤖 *AI Chat Assistant*\n\n"
            "⚡ _Powered by Groq AI (llama-3.3-70b)_\n\n"
            "I'm ready! Send me any message.\n\n"
            "💡 I remember our recent conversation.\n"
            "🔄 Use /clearchat to reset memory.\n"
            "❌ Use /cancel to exit.\n\n"
            "✉️ *What's on your mind?*"
        ),
        "slow_down": "⏳ Please slow down a little!",
        "ai_error": "❌ *AI Error:*\n{error}\n\nTry again or /clearchat to reset.",
        "use_chat": "💬 Want to chat with AI? Use /chat to start!\n\nOr use /start to see all features.",
        "system_prompt": (
            "You are a helpful, friendly AI assistant. "
            "Always respond clearly and concisely in English."
        ),
    },
    "km": {
        "not_configured": (
            "❌ *AI Chat មិនទាន់ដំឡើងទេ។*\n\n"
            "បន្ថែម `GROQ_API_KEY` ក្នុង environment.\n"
            "ទទួល key ឥតគិតថ្លៃ: [console.groq.com](https://console.groq.com)"
        ),
        "welcome": (
            "🤖 *AI Chat Assistant*\n\n"
            "⚡ _ដំណើរការដោយ Groq AI (llama-3.3-70b)_\n\n"
            "ខ្ញុំរួចរាល់ហើយ! សូមផ្ញើសារមកខ្ញុំ។\n\n"
            "💡 ខ្ញុំចងចាំការសន្ទនារបស់យើង។\n"
            "🔄 ប្រើ /clearchat ដើម្បីលុបការចងចាំ។\n"
            "❌ ប្រើ /cancel ដើម្បីចេញ។\n\n"
            "✉️ *អ្នកចង់សួរអ្វី?*"
        ),
        "slow_down": "⏳ សូមធ្វើ천천 យឺតៗបន្តិច!",
        "ai_error": "❌ *AI Error:*\n{error}\n\nសាកម្ដងទៀត ឬ /clearchat ដើម្បី reset.",
        "use_chat": "💬 ចង់និយាយជាមួយ AI? ប្រើ /chat ដើម្បីចាប់ផ្ដើម!\n\nឬប្រើ /start ដើម្បីមើល features ទាំងអស់។",
        "system_prompt": (
            "អ្នកជា AI assistant ដែលមានប្រយោជន៍និងរួសរាយ។ "
            "តែងតែឆ្លើយជាភាសាខ្មែរ ច្បាស់លាស់និងសង្ខេប។ "
            "ប្រើអក្សរខ្មែរទាំងស្រុង លើកលែងតែពាក្យបច្ចេកទេស។"
        ),
    },
}


def _t(uid: int, key: str, **kwargs) -> str:
    """Get text in user's language."""
    try:
        lang = get_language(uid)
    except Exception:
        lang = "en"
    lang = lang if lang in TEXTS else "en"
    text = TEXTS[lang].get(key, TEXTS["en"].get(key, ""))
    return text.format(**kwargs) if kwargs else text


async def chat_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)

    if not is_configured():
        await update.message.reply_text(
            _t(uid, "not_configured"),
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END

    await update.message.reply_text(
        _t(uid, "welcome"),
        parse_mode=ParseMode.MARKDOWN
    )
    return CHATTING


async def chat_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    text = update.message.text.strip()

    if not text:
        return CHATTING

    if is_rate_limited(uid):
        await update.message.reply_text(_t(uid, "slow_down"))
        return CHATTING

    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    # Pass system prompt in user's language
    system = _t(uid, "system_prompt")
    reply, error = await ai_chat(uid, text, system_prompt=system)

    if error:
        log_error(uid, error, "ai_chat")
        await update.message.reply_text(
            _t(uid, "ai_error", error=error),
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
    uid = update.effective_user.id
    await update.message.reply_text(
        _t(uid, "use_chat"),
        reply_markup=back_button("menu_main")
    )