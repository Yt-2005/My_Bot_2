"""
handlers/chat_handler.py — AI Chat Assistant handler
/chat — Start a conversation with AI (powered by Groq)
Supports: memory per user, typing animation, markdown formatting, KH/EN language,
          conversation history, message streaming, clear chat, character counter,
          thinking indicator, auto-retry on failure
"""

import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode, ChatAction

from ai import chat as ai_chat, is_configured
from utils import is_rate_limited, back_button
from database import ensure_user, log_error, get_language

logger = logging.getLogger(__name__)

CHATTING = 1

# Max characters to show in long-message warning
MAX_INPUT_CHARS = 1000
# How many times to auto-retry on AI failure
MAX_RETRIES = 2

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
            "🔄 /clearchat — Reset memory\n"
            "📋 /history — Show recent messages\n"
            "❌ /cancel — Exit chat\n\n"
            "✉️ *What's on your mind?*"
        ),
        "slow_down": "⏳ Please slow down a little!",
        "ai_error": "❌ *AI Error:*\n`{error}`\n\nTry again or /clearchat to reset.",
        "ai_retry": "⚠️ _Having trouble, retrying... ({attempt}/{max})_",
        "use_chat": (
            "💬 Want to chat with AI? Use /chat to start!\n\n"
            "Or use /start to see all features."
        ),
        "system_prompt": (
            "You are a helpful, friendly AI assistant. "
            "Always respond clearly and concisely in English. "
            "Use markdown formatting where appropriate (bold, italic, bullet points). "
            "If asked to do a task, do it directly without unnecessary preamble."
        ),
        "thinking": "🧠 _Thinking..._",
        "too_long": (
            "⚠️ Your message is very long ({chars} chars). "
            "I'll do my best, but consider breaking it into smaller parts."
        ),
        "cleared": "🗑️ *Conversation memory cleared!* Starting fresh.\n\n✉️ Send a message to continue.",
        "history_empty": "📭 No conversation history yet.",
        "history_header": "📋 *Recent Conversation ({count} messages):*\n\n",
        "history_you": "👤 *You:* {text}\n",
        "history_ai": "🤖 *AI:* {text}\n\n",
        "cancelled": "👋 Chat ended. Use /chat to start a new conversation!",
        "char_count": "_{chars}/{max} chars_",
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
            "🔄 /clearchat — លុបការចងចាំ\n"
            "📋 /history — មើលសារថ្មីៗ\n"
            "❌ /cancel — ចេញពី chat\n\n"
            "✉️ *អ្នកចង់សួរអ្វី?*"
        ),
        "slow_down": "⏳ សូមធ្វើយឺតៗបន្តិច!",
        "ai_error": "❌ *AI Error:*\n`{error}`\n\nសាកម្ដងទៀត ឬ /clearchat ដើម្បី reset.",
        "ai_retry": "⚠️ _មានបញ្ហា កំពុង retry... ({attempt}/{max})_",
        "use_chat": (
            "💬 ចង់និយាយជាមួយ AI? ប្រើ /chat ដើម្បីចាប់ផ្ដើម!\n\n"
            "ឬប្រើ /start ដើម្បីមើល features ទាំងអស់។"
        ),
        "system_prompt": (
            "អ្នកជា AI assistant ដែលមានប្រយោជន៍និងរួសរាយ។ "
            "តែងតែឆ្លើយជាភាសាខ្មែរ ច្បាស់លាស់និងសង្ខេប។ "
            "ប្រើអក្សរខ្មែរទាំងស្រុង លើកលែងតែពាក្យបច្ចេកទេស។ "
            "ប្រើ markdown formatting សមស្រប (bold, italic, bullet points)។"
        ),
        "thinking": "🧠 _កំពុងគិត..._",
        "too_long": (
            "⚠️ សារអ្នកវែងណាស់ ({chars} តួអក្សរ)។ "
            "ខ្ញុំនឹងព្យាយាម ប៉ុន្តែសូមបំបែកជាផ្នែកតូចៗ។"
        ),
        "cleared": "🗑️ *ការចងចាំការសន្ទនាត្រូវបានលុប!* ចាប់ផ្ដើមថ្មី។\n\n✉️ ផ្ញើសារដើម្បីបន្ត។",
        "history_empty": "📭 មិនទាន់មីប្រវត្តិការសន្ទនានៅឡើយទេ។",
        "history_header": "📋 *ការសន្ទនាថ្មីៗ ({count} សារ):*\n\n",
        "history_you": "👤 *អ្នក:* {text}\n",
        "history_ai": "🤖 *AI:* {text}\n\n",
        "cancelled": "👋 Chat បានបញ្ចប់។ ប្រើ /chat ដើម្បីចាប់ផ្ដើមថ្មី!",
        "char_count": "_{chars}/{max} តួអក្សរ_",
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


def _quick_actions_keyboard(uid: int) -> InlineKeyboardMarkup:
    """Inline keyboard with quick actions shown after AI reply."""
    lang = "km"
    try:
        lang = get_language(uid)
    except Exception:
        pass
    if lang == "km":
        buttons = [
            [
                InlineKeyboardButton("🔄 Reset", callback_data="clearchat"),
                InlineKeyboardButton("📋 History", callback_data="chat_history"),
                InlineKeyboardButton("❌ ចេញ", callback_data="cancel_chat"),
            ]
        ]
    else:
        buttons = [
            [
                InlineKeyboardButton("🔄 Reset", callback_data="clearchat"),
                InlineKeyboardButton("📋 History", callback_data="chat_history"),
                InlineKeyboardButton("❌ Exit", callback_data="cancel_chat"),
            ]
        ]
    return InlineKeyboardMarkup(buttons)


# ─── Handlers ──────────────────────────────────────────────────────────────────

async def chat_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Entry point: /chat"""
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
    """Handle incoming user message inside a chat session."""
    uid  = update.effective_user.id
    text = update.message.text.strip()

    if not text:
        return CHATTING

    # ── Rate limit check ──────────────────────────────────────────────────────
    if is_rate_limited(uid):
        await update.message.reply_text(_t(uid, "slow_down"))
        return CHATTING

    # ── Long message warning ──────────────────────────────────────────────────
    if len(text) > MAX_INPUT_CHARS:
        await update.message.reply_text(
            _t(uid, "too_long", chars=len(text)),
            parse_mode=ParseMode.MARKDOWN
        )

    # ── Thinking indicator ────────────────────────────────────────────────────
    await ctx.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING
    )
    thinking_msg = await update.message.reply_text(
        _t(uid, "thinking"),
        parse_mode=ParseMode.MARKDOWN
    )

    # ── Call AI with system_prompt + auto-retry ───────────────────────────────
    system = _t(uid, "system_prompt")
    reply, error = None, None

    for attempt in range(1, MAX_RETRIES + 1):
        # FIX: pass system_prompt as a positional arg or keyword matching ai.chat()'s signature.
        # ai.chat(uid, text, system) — adjust if your ai.py uses a different param name.
        reply, error = await _call_ai(uid, text, system)

        if not error:
            break

        if attempt < MAX_RETRIES:
            await thinking_msg.edit_text(
                _t(uid, "ai_retry", attempt=attempt, max=MAX_RETRIES),
                parse_mode=ParseMode.MARKDOWN
            )
            await asyncio.sleep(1.5)

    # ── Delete thinking indicator ─────────────────────────────────────────────
    try:
        await thinking_msg.delete()
    except Exception:
        pass

    # ── Handle error ──────────────────────────────────────────────────────────
    if error:
        log_error(uid, error, "ai_chat")
        await update.message.reply_text(
            _t(uid, "ai_error", error=error),
            parse_mode=ParseMode.MARKDOWN
        )
        return CHATTING

    # ── Send reply with quick-action buttons ──────────────────────────────────
    try:
        await update.message.reply_text(
            reply,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_quick_actions_keyboard(uid),
        )
    except Exception:
        # Fallback: plain text if markdown fails (e.g. unbalanced symbols)
        await update.message.reply_text(
            reply,
            reply_markup=_quick_actions_keyboard(uid),
        )

    return CHATTING


async def chat_history_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/history — Show last N messages from in-memory context (if stored in ctx.user_data)."""
    uid = update.effective_user.id
    history: list = ctx.user_data.get("chat_history", [])

    if not history:
        await update.message.reply_text(_t(uid, "history_empty"))
        return CHATTING

    lines = [_t(uid, "history_header", count=len(history))]
    for entry in history[-10:]:           # Show last 10 entries max
        role = entry.get("role", "")
        content = entry.get("content", "")[:120]  # Truncate long messages
        if role == "user":
            lines.append(_t(uid, "history_you", text=content))
        elif role == "assistant":
            lines.append(_t(uid, "history_ai", text=content))

    await update.message.reply_text(
        "".join(lines),
        parse_mode=ParseMode.MARKDOWN
    )
    return CHATTING


async def clear_chat_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/clearchat — Wipe conversation memory."""
    uid = update.effective_user.id
    ctx.user_data.pop("chat_history", None)   # Clear local history if stored here

    # Also clear in ai module if it exposes a clear function
    try:
        from ai import clear_history
        clear_history(uid)
    except ImportError:
        pass

    await update.message.reply_text(
        _t(uid, "cleared"),
        parse_mode=ParseMode.MARKDOWN
    )
    return CHATTING


async def cancel_chat_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/cancel — End the conversation."""
    uid = update.effective_user.id
    await update.message.reply_text(
        _t(uid, "cancelled"),
        reply_markup=back_button("menu_main")
    )
    return ConversationHandler.END


async def chat_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle inline button presses from quick-action keyboard."""
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    data = query.data

    if data == "clearchat":
        ctx.user_data.pop("chat_history", None)
        try:
            from ai import clear_history
            clear_history(uid)
        except ImportError:
            pass
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            _t(uid, "cleared"),
            parse_mode=ParseMode.MARKDOWN
        )

    elif data == "chat_history":
        history: list = ctx.user_data.get("chat_history", [])
        if not history:
            await query.message.reply_text(_t(uid, "history_empty"))
        else:
            lines = [_t(uid, "history_header", count=len(history))]
            for entry in history[-10:]:
                role = entry.get("role", "")
                content = entry.get("content", "")[:120]
                if role == "user":
                    lines.append(_t(uid, "history_you", text=content))
                elif role == "assistant":
                    lines.append(_t(uid, "history_ai", text=content))
            await query.message.reply_text(
                "".join(lines),
                parse_mode=ParseMode.MARKDOWN
            )

    elif data == "cancel_chat":
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            _t(uid, "cancelled"),
            reply_markup=back_button("menu_main")
        )
        return ConversationHandler.END

    return CHATTING


async def handle_text_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Catch-all for messages outside of a /chat session."""
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


# ─── Internal helpers ──────────────────────────────────────────────────────────

async def _call_ai(uid: int, text: str, system: str):
    """
    Wrapper that calls ai.chat() tolerantly.

    Tries three calling conventions in order so this handler works regardless
    of how ai.chat() is currently defined:
      1. chat(uid, text, system)          — positional 3rd arg
      2. chat(uid, text, system_prompt=system) — keyword arg (original intent)
      3. chat(uid, text)                  — no system prompt (fallback)
    """
    # Convention 1: positional
    try:
        return await ai_chat(uid, text, system)
    except TypeError:
        pass

    # Convention 2: keyword
    try:
        return await ai_chat(uid, text, system_prompt=system)
    except TypeError:
        pass

    # Convention 3: no system prompt
    try:
        return await ai_chat(uid, text)
    except Exception as e:
        return None, str(e)