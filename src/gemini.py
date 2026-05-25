"""
ai/gemini.py — Gemini AI client with automatic key rotation
Handles: text chat, image analysis, financial advice
"""

import logging
from google import genai as google_genai
from config import GEMINI_KEYS, AI_CHAT_MEMORY
from database import save_chat_message, get_chat_history

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# KEY ROTATION STATE
# ─────────────────────────────────────────────
_current_key_index = 0


def _get_key() -> str:
    return GEMINI_KEYS[_current_key_index] if GEMINI_KEYS else ""


def _rotate_key() -> bool:
    """Rotate to next key. Returns False if only one key available."""
    global _current_key_index
    if len(GEMINI_KEYS) <= 1:
        return False
    _current_key_index = (_current_key_index + 1) % len(GEMINI_KEYS)
    logger.info(f"🔄 Rotated to Gemini Key #{_current_key_index + 1}")
    return True


def _call_gemini_raw(prompt: str, system: str = "") -> tuple[str | None, str | None]:
    """
    Low-level Gemini call with key rotation.
    Returns (text, error_message).
    """
    if not GEMINI_KEYS:
        return None, "❌ No Gemini API key configured."

    max_attempts = len(GEMINI_KEYS)
    for attempt in range(max_attempts):
        key = _get_key()
        try:
            client = google_genai.Client(api_key=key)
            full_prompt = f"{system}\n\n{prompt}" if system else prompt
            response = client.models.generate_content(
                model="gemini-2.0-flash-lite",
                contents=full_prompt,
            )
            return response.text, None

        except Exception as e:
            err = str(e)
            if any(code in err for code in ["429", "RESOURCE_EXHAUSTED", "quota"]):
                logger.warning(f"⚠️  Key #{_current_key_index + 1} quota exhausted — rotating...")
                if not _rotate_key():
                    return None, "❌ All Gemini API keys have hit their quota. Please wait 24 hours."
            else:
                logger.error(f"Gemini error: {err[:300]}")
                return None, f"❌ AI error: {err[:200]}"

    return None, "❌ All Gemini API keys are exhausted. Please try again later."


# ─────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────

def chat(user_id: int, user_message: str) -> tuple[str | None, str | None]:
    """
    Conversational chat with per-user memory.
    Returns (reply_text, error_message).
    """
    # Build history context
    history = get_chat_history(user_id, limit=AI_CHAT_MEMORY)
    context_lines = []
    for msg in history:
        role_label = "User" if msg["role"] == "user" else "Assistant"
        context_lines.append(f"{role_label}: {msg['content']}")
    context = "\n".join(context_lines)

    system = (
        "You are a helpful, friendly AI assistant embedded in a Telegram bot. "
        "Reply concisely using Telegram-compatible Markdown (*bold*, _italic_, `code`). "
        "Be warm, smart, and practical."
    )

    prompt = f"{context}\nUser: {user_message}\nAssistant:" if context else user_message

    text, error = _call_gemini_raw(prompt, system=system)

    if text:
        # Save both sides of the conversation to memory
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
            "Analyze the expense data and give 3-5 practical saving tips. "
            "Keep it under 200 words. Use bullet points. Be encouraging."
        )
        prompt = f"My expense summary this month:\n{summary}"
    else:
        system = (
            "អ្នកជាទីប្រឹក្សាហិរញ្ញវត្ថុ។ "
            "វិភាគចំណាយ និងណែនាំ 3-5 វិធីសន្សំប្រាក់ជាភាសាខ្មែរ។ "
            "ខ្លី 200 ពាក្យ ប្រើ bullet points ផ្ដល់ការ លើកទឹកចិត្ត។"
        )
        prompt = f"ចំណាយខែនេះ:\n{summary}"

    return _call_gemini_raw(prompt, system=system)


def current_key_number() -> int:
    """Return current active key index (1-based)."""
    return _current_key_index + 1


def keys_loaded() -> int:
    return len(GEMINI_KEYS)
