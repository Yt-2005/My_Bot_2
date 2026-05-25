"""
handlers/settings_handler.py — User settings
/lang      — Switch language KH ↔ EN
/setpin    — Set/change 4-digit PIN
/reminder  — Set daily spending reminder
"""

import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode

from database import ensure_user, set_language, set_pin, get_pin, set_reminder

logger = logging.getLogger(__name__)

# States
LANG_CHOOSE = 1
PIN_SET     = 2
PIN_CONFIRM = 3
REMINDER_PICK = 4


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
        reply = "✅ Language changed to *English*!"
    else:
        set_language(uid, "km")
        reply = "✅ ប្ដូរជា *ភាសាខ្មែរ* រួចហើយ!"

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
    action   = "Change" if existing else "Set"

    await update.message.reply_text(
        f"🔒 *{action} Security PIN*\n\n"
        "Enter a new 4-digit PIN:\n\n"
        "_This protects your expense data. Type /cancel to abort._",
        parse_mode=ParseMode.MARKDOWN
    )
    return PIN_SET


async def pin_set_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    pin = update.message.text.strip()

    if not pin.isdigit() or len(pin) != 4:
        await update.message.reply_text(
            "❌ PIN must be exactly *4 digits*. Try again:",
            parse_mode=ParseMode.MARKDOWN
        )
        return PIN_SET

    ctx.user_data["new_pin"] = pin
    await update.message.reply_text(
        "🔐 *Confirm your PIN:*\n\nEnter the same PIN again:",
        parse_mode=ParseMode.MARKDOWN
    )
    return PIN_CONFIRM


async def pin_confirm_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid          = update.effective_user.id
    confirm      = update.message.text.strip()
    new_pin      = ctx.user_data.get("new_pin", "")

    if confirm != new_pin:
        await update.message.reply_text(
            "❌ *PINs don't match!* Please start over with /setpin",
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END

    set_pin(uid, new_pin)
    # Auto-authenticate
    from handlers.expense_handler import _authenticated
    _authenticated.add(uid)

    await update.message.reply_text(
        "✅ *PIN set successfully!*\n\nYour expenses are now protected.",
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
        "🔔 *Daily Reminder*\n\nChoose when to get reminded to log expenses:",
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
            "🔕 *Reminder turned off.*",
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
            f"✅ *Reminder set for {reminder_time}!*\n\nI'll remind you daily to log your expenses.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=ReplyKeyboardRemove()
        )
    else:
        await update.message.reply_text("❌ Couldn't set reminder. Try /reminder again.")

    return ConversationHandler.END
