"""
ai/groq_ai.py — Groq AI client (replaces Gemini)
Ultra-fast inference, generous free tier, no quota issues.
Model: llama-3.3-70b-versatile
"""

import logging
import asyncio
from groq import Groq
from config import GROQ_API_KEY, AI_CHAT_MEMORY
from database import save_chat_message, get_chat_history

logger = logging.getLogger(__name__)

_client: Groq | None = None


def _get_client() -> Groq | None:
    global _client
    if not GROQ_API_KEY:
        return None
    if _client is None:
        _client = Groq(api_key=GROQ_API_KEY)
    return _client


def _call_groq(messages: list, system: str = "") -> tuple[str | None, str | None]:
    """
    Low-level Groq call.
    Returns (text, error_message).
    """
    client = _get_client()
    if not client:
        return None, "❌ Groq API key not configured. Add `GROQ_API_KEY` to your .env file.\n\nGet a free key at: https://console.groq.com"

    full_messages = []
    if system:
        full_messages.append({"role": "system", "content": system})
    full_messages.extend(messages)

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=full_messages,
            max_tokens=1024,
            temperature=0.7,
        )
        text = response.choices[0].message.content
        return text, None

    except Exception as e:
        err = str(e)
        logger.error(f"Groq error: {err[:300]}")
        if "rate_limit" in err.lower() or "429" in err:
            return None, "⏳ Rate limit hit. Please wait a moment and try again."
        if "invalid_api_key" in err.lower() or "401" in err:
            return None, "❌ Invalid Groq API key. Check your GROQ_API_KEY in .env"
        return None, f"❌ AI error: {err[:150]}"


# ─────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────

def chat(user_id: int, user_message: str) -> tuple[str | None, str | None]:
    """
    Conversational chat with per-user memory.
    Returns (reply_text, error_message).
    """
    history = get_chat_history(user_id, limit=AI_CHAT_MEMORY)

    messages = []
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_message})

    system = (
        "You are a helpful, friendly AI assistant inside a Telegram bot. "
        "Reply concisely using Telegram-compatible Markdown (*bold*, _italic_, `code`). "
        "Be warm, smart, and practical. Keep replies under 300 words unless asked for more."
    )

    text, error = _call_groq(messages, system=system)

    if text:
        save_chat_message(user_id, "user", user_message)
        save_chat_message(user_id, "assistant", text)

    return text, error


def get_financial_advice(user_id: int, summary: str, language: str = "km") -> tuple[str | None, str | None]:
    """
    Generate personalized financial advice from expense summary.
    Returns (advice_text, error_message).
    """
    if language == "en":
        system = (
            "You are a personal finance advisor. "
            "Analyze the expense data and give 3-5 practical, actionable saving tips. "
            "Keep it under 250 words. Use bullet points. Be encouraging and specific."
        )
        prompt = f"My expense summary this month:\n{summary}\n\nGive me personalized saving tips."
    else:
        system = (
            "អ្នកជាទីប្រឹក្សាហិរញ្ញវត្ថុផ្ទាល់ខ្លួន។ "
            "វិភាគទិន្នន័យចំណាយ និងផ្ដល់ 3-5 គន្លឹះសន្សំប្រាក់ជាក់ស្ដែង ជាភាសាខ្មែរ។ "
            "ខ្លីក្នុង 250 ពាក្យ ប្រើ bullet points ផ្ដល់ការលើកទឹកចិត្ត និងមានប្រយោជន៍ជាក់ស្ដែង។"
        )
        prompt = f"ចំណាយខែនេះ:\n{summary}\n\nផ្ដល់គន្លឹះសន្សំប្រាក់ជូនខ្ញុំ។"

    messages = [{"role": "user", "content": prompt}]
    return _call_groq(messages, system=system)


def is_configured() -> bool:
    return bool(GROQ_API_KEY)
