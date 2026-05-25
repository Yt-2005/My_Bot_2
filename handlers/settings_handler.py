"""
handlers/settings_handler.py — User settings
/lang      — Switch language KH ↔ EN
/setpin    — Set/change 4-digit PIN
/reminder  — Set daily spending reminder
"""

import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode

from database import ensure_user, set_language, set_pin, get_pin, set_reminder, get_language

logger = logging.getLogger(__name__)

# States
LANG_CHOOSE   = 1
PIN_SET       = 2
PIN_CONFIRM   = 3
REMINDER_PICK = 4

# ─── UI Text by language ───────────────────────────────────────────────────────
TEXTS = {
    "en": {
        "lang_prompt":      "🌐 *Choose your language:*",
        "lang_set_en":      "✅ Language changed to *English*!",
        "lang_set_km":      "✅ Language changed to *Khmer*!",
        "pin_set_title":    "🔒 *{action} Security PIN*\n\nEnter a new 4-digit PIN:\n\n_Type /cancel to abort._",
        "pin_action_set":   "Set",
        "pin_action_change":"Change",
        "pin_invalid":      "❌ PIN must be exactly *4 digits*. Try again:",
        "pin_confirm":      "🔐 *Confirm your PIN:*\n\nEnter the same PIN again:",
        "pin_mismatch":     "❌ *PINs don't match!* Please start over with /setpin",
        "pin_success":      "✅ *PIN set successfully!*\n\nYour expenses are now protected.",
        "reminder_prompt":  "🔔 *Daily Reminder*\n\nChoose when to get reminded to log expenses:",
        "reminder_off":     "🔕 *Reminder turned off.*",
        "reminder_set":     "✅ *Reminder set for {time}!*\n\nI'll remind you daily to log your expenses.",
        "reminder_fail":    "❌ Couldn't set reminder. Try /reminder again.",
    },
    "km": {
        "lang_prompt":      "🌐 *ជ្រើសរើសភាសារបស់អ្នក:*",
        "lang_set_en":      "✅ ប្ដូរជា *ភាសាអង់គ្លេស* រួចហើយ!",
        "lang_set_km":      "✅ ប្ដូរជា *ភាសាខ្មែរ* រួចហើយ!",
        "pin_set_title":    "🔒 *{action} PIN សុវត្ថិភាព*\n\nបញ្ចូល PIN 4 ខ្ទង់ថ្មី:\n\n_វាយ /cancel ដើម្បីបោះបង់។_",
        "pin_action_set":   "កំណត់",
        "pin_action_change":"ផ្លាស់ប្ដូរ",
        "pin_invalid":      "❌ PIN ត្រូវមាន *4 ខ្ទង់* ប៉ុណ្ណោះ។ សាកម្ដងទៀត:",
        "pin_confirm":      "🔐 *បញ្ជាក់ PIN របស់អ្នក:*\n\nបញ្ចូល PIN ដដែលម្ដងទៀត:",
        "pin_mismatch":     "❌ *PIN មិនត្រូវគ្នា!* សូមចាប់ផ្ដើមឡើងវិញ /setpin",
        "pin_success":      "✅ *PIN កំណត់ជោគជ័យ!*\n\nការចំណាយរបស់អ្នកត្រូវបានការពារហើយ។",
        "reminder_prompt":  "🔔 *រំលឹកប្រចាំថ្ងៃ*\n\nជ្រើសពេលដែលអ្នកចង់ឱ្យរំលឹក:",
        "reminder_off":     "🔕 *បិទការរំលឹករួចហើយ។*",
        "reminder_set":     "✅ *កំណត់ការរំលឹកនៅ {time}!*\n\nខ្ញុំនឹងរំលឹកអ្នករៀងរាល់ថ្ងៃ។",
        "reminder_fail":    "❌ មិនអាចកំណត់ការរំលឹក។ សាក /reminder ម្ដងទៀត។",
    },
}


def _t(uid: int, key: str, **kwargs) -> str:
    try:
        lang = get_language(uid)
    except Exception:
        lang = "en"
    lang = lang if lang in TEXTS else "en"
    text = TEXTS[lang].get(key, TEXTS["en"].get(key, ""))
    return text.format(**kwargs) if kwargs else text


# ─────────────────────────────────────────────
# /lang
# ─────────────────────────────────────────────

async def lang_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)
    kb = ReplyKeyboardMarkup(
        [["🇰🇭 ខ្មែរ (Khmer)", "🇬🇧 English"]],
        one_time_keyboard=True, resize_keyboard=True
    )
    await update.message.reply_text(
        "🌐 *Choose Language / ជ្រើសរើសភាសា:*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb
    )
    return LANG_CHOOSE


async def lang_choose(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    text = update.message.text

    if "English" in text:
        set_language(uid, "en")
        reply = _t(uid, "lang_set_en")
    else:
        set_language(uid, "km")
        # Get text AFTER setting language so it reflects new choice
        reply = TEXTS["km"]["lang_set_km"]

    await update.message.reply_text(
        reply,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END


# ─────────────────────────────────────────────
# /setpin
# ─────────────────────────────────────────────

async def setpin_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)
    existing = get_pin(uid)
    action = _t(uid, "pin_action_change") if existing else _t(uid, "pin_action_set")

    await update.message.reply_text(
        _t(uid, "pin_set_title", action=action),
        parse_mode=ParseMode.MARKDOWN
    )
    return PIN_SET


async def pin_set_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    pin = update.message.text.strip()

    if not pin.isdigit() or len(pin) != 4:
        await update.message.reply_text(
            _t(uid, "pin_invalid"),
            parse_mode=ParseMode.MARKDOWN
        )
        return PIN_SET

    ctx.user_data["new_pin"] = pin
    await update.message.reply_text(
        _t(uid, "pin_confirm"),
        parse_mode=ParseMode.MARKDOWN
    )
    return PIN_CONFIRM


async def pin_confirm_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid     = update.effective_user.id
    confirm = update.message.text.strip()
    new_pin = ctx.user_data.get("new_pin", "")

    if confirm != new_pin:
        await update.message.reply_text(
            _t(uid, "pin_mismatch"),
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END

    set_pin(uid, new_pin)
    from handlers.expense_handler import _authenticated
    _authenticated.add(uid)

    await update.message.reply_text(
        _t(uid, "pin_success"),
        parse_mode=ParseMode.MARKDOWN
    )
    ctx.user_data.clear()
    return ConversationHandler.END


# ─────────────────────────────────────────────
# /reminder
# ─────────────────────────────────────────────

async def reminder_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)

    kb = ReplyKeyboardMarkup(
        [
            ["⏰ 8:00 AM",  "⏰ 12:00 PM"],
            ["⏰ 6:00 PM",  "⏰ 9:00 PM"],
            ["🔕 Turn Off Reminder"],
        ],
        one_time_keyboard=True, resize_keyboard=True
    )
    await update.message.reply_text(
        _t(uid, "reminder_prompt"),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb
    )
    return REMINDER_PICK


async def reminder_set(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    text = update.message.text

    if "Turn Off" in text or "🔕" in text:
        set_reminder(uid, False)
        await update.message.reply_text(
            _t(uid, "reminder_off"),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END

    time_map = {
        "8:00 AM":  "08:00",
        "12:00 PM": "12:00",
        "6:00 PM":  "18:00",
        "9:00 PM":  "21:00",
    }

    reminder_time = None
    for key, val in time_map.items():
        if key in text:
            reminder_time = val
            break

    if reminder_time:
        set_reminder(uid, True, reminder_time)
        await update.message.reply_text(
            _t(uid, "reminder_set", time=reminder_time),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=ReplyKeyboardRemove()
        )
    else:
        await update.message.reply_text(_t(uid, "reminder_fail"))

    return ConversationHandler.END