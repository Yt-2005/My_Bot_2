"""
utils/helpers.py — Shared utility functions
Rate limiter, keyboard builders, message formatters, anti-spam
"""

import time
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from config import RATE_LIMIT_SECONDS, IMAGE_STYLES

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# RATE LIMITER (in-memory, per user)
# ─────────────────────────────────────────────
_last_message_time: dict[int, float] = {}


def is_rate_limited(user_id: int) -> bool:
    """Returns True if the user is sending messages too fast."""
    now = time.time()
    last = _last_message_time.get(user_id, 0)
    if now - last < RATE_LIMIT_SECONDS:
        return True
    _last_message_time[user_id] = now
    return False


# ─────────────────────────────────────────────
# INLINE KEYBOARD BUILDERS
# ─────────────────────────────────────────────

def main_menu_keyboard() -> InlineKeyboardMarkup:
    """The main menu shown after /start."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎨 AI Image Gen",   callback_data="menu_imagegen"),
            InlineKeyboardButton("✨ AI Upscaler",    callback_data="menu_upscale"),
        ],
        [
            InlineKeyboardButton("🤖 AI Chat",        callback_data="menu_chat"),
            InlineKeyboardButton("📝 My Notes",       callback_data="menu_notes"),
        ],
        [
            InlineKeyboardButton("💰 Expenses",       callback_data="menu_expenses"),
            InlineKeyboardButton("🤖 AI Finance",     callback_data="menu_ai_finance"),
        ],
        [
            InlineKeyboardButton("📄 PDF Tools",      callback_data="menu_pdf"),
            InlineKeyboardButton("⚙️ Settings",       callback_data="menu_settings"),
        ],
        [
            InlineKeyboardButton("❓ Help",            callback_data="menu_help"),
        ],
    ])

def main_menu_keyboard() -> InlineKeyboardMarkup:
    """The main menu shown after /start, filtered by dashboard feature toggles."""
    try:
        from database import get_bot_features
        visible = get_bot_features()
    except Exception as e:
        logger.warning(f"Feature visibility unavailable: {e}")
        visible = {}

    items = [
        ("imagegen", "ðŸŽ¨ AI Image Gen", "menu_imagegen"),
        ("upscale", "âœ¨ AI Upscaler", "menu_upscale"),
        ("chat", "ðŸ¤– AI Chat", "menu_chat"),
        ("notes", "ðŸ“ My Notes", "menu_notes"),
        ("expenses", "ðŸ’° Expenses", "menu_expenses"),
        ("ai_finance", "ðŸ¤– AI Finance", "menu_ai_finance"),
        ("pdf", "ðŸ“„ PDF Tools", "menu_pdf"),
        ("settings", "âš™ï¸ Settings", "menu_settings"),
        ("calendar", "ðŸ“… Khmer Calendar", "menu_calendar"),
        ("help", "â“ Help", "menu_help"),
    ]

    buttons = [
        InlineKeyboardButton(label, callback_data=callback)
        for key, label, callback in items
        if visible.get(key, True)
    ]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    if not rows:
        rows = [[InlineKeyboardButton("â“ Help", callback_data="menu_help")]]
    return InlineKeyboardMarkup(rows)


def main_menu_keyboard() -> InlineKeyboardMarkup:
    """The main menu shown after /start, filtered by dashboard feature toggles."""
    try:
        from database import get_bot_features
        visible = get_bot_features()
    except Exception as e:
        logger.warning(f"Feature visibility unavailable: {e}")
        visible = {}

    items = [
        ("imagegen", "AI Image Gen", "menu_imagegen"),
        ("upscale", "AI Upscaler", "menu_upscale"),
        ("chat", "AI Chat", "menu_chat"),
        ("notes", "My Notes", "menu_notes"),
        ("expenses", "Expenses", "menu_expenses"),
        ("ai_finance", "AI Finance", "menu_ai_finance"),
        ("pdf", "PDF Tools", "menu_pdf"),
        ("settings", "Settings", "menu_settings"),
        ("calendar", "Khmer Calendar", "menu_calendar"),
        ("help", "Help", "menu_help"),
    ]

    buttons = [
        InlineKeyboardButton(label, callback_data=callback)
        for key, label, callback in items
        if visible.get(key, True)
    ]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    if not rows:
        rows = [[InlineKeyboardButton("Help", callback_data="menu_help")]]
    return InlineKeyboardMarkup(rows)


def image_style_keyboard(prompt: str) -> InlineKeyboardMarkup:
    """Style selector for image generation."""
    buttons = []
    row = []
    for i, style_name in enumerate(IMAGE_STYLES.keys()):
        # Encode prompt into callback; truncate to avoid telegram 64-byte limit
        short_prompt = prompt[:30].replace("|", "")
        row.append(InlineKeyboardButton(
            style_name,
            callback_data=f"imgstyle|{style_name}|{short_prompt}"
        ))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    return InlineKeyboardMarkup(buttons)


def notes_keyboard(notes: list, show_edit: bool = False) -> InlineKeyboardMarkup:
    """Keyboard to show/delete/edit individual notes."""
    buttons = []
    for note in notes[:20]:
        short = note["content"][:25] + ("…" if len(note["content"]) > 25 else "") if note["content"] else "(No text)"
        label = f"👁 #{note['id']}" if note["image_data"] else f"📄 #{note['id']}"
        row = [InlineKeyboardButton(
            f"{label} {short}",
            callback_data=f"shownote|{note['id']}"
        )]
        actions = [InlineKeyboardButton("🗑️", callback_data=f"delnote|{note['id']}")]
        if show_edit:
            actions.insert(0, InlineKeyboardButton("✏️", callback_data=f"editnote|{note['id']}"))
        row.extend(actions)
        buttons.append(row)
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="menu_notes")])
    return InlineKeyboardMarkup(buttons)


def back_button(target: str = "menu_main") -> InlineKeyboardMarkup:
    """A single back button."""
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=target)]])


def confirm_keyboard(yes_data: str, no_data: str = "cancel") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes", callback_data=yes_data),
        InlineKeyboardButton("❌ No",  callback_data=no_data),
    ]])


# ─────────────────────────────────────────────
# MESSAGE FORMATTERS
# ─────────────────────────────────────────────

def progress_bar(pct: float, width: int = 10) -> str:
    """Generate a text progress bar. e.g. ████░░░░░░ 40%"""
    filled = int(min(pct, 100) / 100 * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"{bar} {pct:.0f}%"


def format_amount(amount: float) -> str:
    """Format a number with commas. e.g. 1234567 → 1,234,567"""
    return f"{amount:,.0f}"


def truncate(text: str, max_len: int = 50) -> str:
    return text[:max_len] + "…" if len(text) > max_len else text


LOADING_FRAMES = ["⏳", "🔄", "✨", "💫"]


def loading_text(frame: int = 0) -> str:
    return f"{LOADING_FRAMES[frame % len(LOADING_FRAMES)]} Processing..."


# ─────────────────────────────────────────────
# EXPENSE CATEGORIES KEYBOARD
# ─────────────────────────────────────────────

EXPENSE_CATEGORIES = [
    ["🍜 Food",       "🚗 Transport"],
    ["🛒 Shopping",   "💊 Health"],
    ["📱 Phone",      "🏠 Housing"],
    ["🎮 Fun",        "✈️ Travel"],
    ["📚 Education",  "👔 Clothing"],
    ["📦 Other"],
]


def expense_category_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(EXPENSE_CATEGORIES, one_time_keyboard=True, resize_keyboard=True)
