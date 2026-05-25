"""
handlers/expense_handler.py — Expense tracking system
Refactored from original bot with improved structure and UI.
Commands: /add, /today, /month, /compare, /budget, /date,
          /tags, /delete, /recurring, /ai (financial advice)
"""

import logging
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode, ChatAction

from database import (
    ensure_user, add_expense, delete_expense,
    get_today, get_monthly, get_monthly_total,
    get_by_date, get_by_tag, get_recurring,
    get_budget, set_budget, get_pin, get_language,
    log_error,
)
from ai import get_financial_advice
from utils import (
    expense_category_keyboard, progress_bar,
    format_amount, back_button, is_rate_limited,
)
from config import GEMINI_KEYS

logger = logging.getLogger(__name__)

# ── Conversation states ──
(
    PIN_VERIFY,
    CHOOSE_CAT, ENTER_AMOUNT, ENTER_NOTE, ENTER_TAG,
    IS_RECURRING, RECURRING_INT,
    BUDGET_AMOUNT,
    SEARCH_DATE, SEARCH_TAG,
    DELETE_ID,
) = range(11)

# Authenticated users cache (in-memory)
_authenticated: set[int] = set()


# ─────────────────────────────────────────────
# AUTH HELPERS
# ─────────────────────────────────────────────

def _is_authed(uid: int) -> bool:
    pin = get_pin(uid)
    return (not pin) or (uid in _authenticated)


async def _require_auth(update: Update, uid: int) -> bool:
    """Returns True if user is authenticated (or no PIN set)."""
    if _is_authed(uid):
        return True
    await update.message.reply_text(
        "🔒 *PIN Required*\n\nPlease enter your 4-digit PIN:",
        parse_mode=ParseMode.MARKDOWN
    )
    return False


# ─────────────────────────────────────────────
# /add — ADD EXPENSE
# ─────────────────────────────────────────────

async def add_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)
    if not await _require_auth(update, uid):
        return PIN_VERIFY
    await update.message.reply_text(
        "💰 *Add Expense*\n\nSelect a category:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=expense_category_keyboard()
    )
    return CHOOSE_CAT


async def choose_category(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["cat"] = update.message.text
    uid = update.effective_user.id
    await update.message.reply_text(
        "💵 *Enter the amount:*\n\n_Example: 5000 or 2.50_",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=ReplyKeyboardRemove()
    )
    return ENTER_AMOUNT


async def enter_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        amount = float(update.message.text.replace(",", "").replace("$", "").strip())
        if amount <= 0:
            raise ValueError("Non-positive amount")
        ctx.user_data["amount"] = amount
        await update.message.reply_text(
            "📝 *Enter a note:*\n\n_What was this expense for?_\n_(Type `-` to skip)_",
            parse_mode=ParseMode.MARKDOWN
        )
        return ENTER_NOTE
    except ValueError:
        await update.message.reply_text("❌ Invalid amount. Please enter a number (e.g. `5000`).")
        return ENTER_AMOUNT


async def enter_note(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["note"] = update.message.text
    uid = update.effective_user.id
    await update.message.reply_text(
        "🏷️ *Enter a tag (optional):*\n\n"
        "_Tags help you group expenses (e.g. `work`, `family`, `trip`)_\n"
        "_(Type `-` to skip)_",
        parse_mode=ParseMode.MARKDOWN
    )
    return ENTER_TAG


async def enter_tag(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    tag = update.message.text if update.message.text != "-" else ""
    ctx.user_data["tag"] = tag
    kb = ReplyKeyboardMarkup([["✅ Yes", "❌ No"]], one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text(
        "🔄 *Is this a recurring expense?*\n_(e.g. monthly rent, subscriptions)_",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb
    )
    return IS_RECURRING


async def is_recurring_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    is_rec = "Yes" in update.message.text or "✅" in update.message.text
    ctx.user_data["is_recurring"] = is_rec
    if is_rec:
        kb = ReplyKeyboardMarkup(
            [["📅 Daily", "📅 Weekly"], ["📅 Monthly"]],
            one_time_keyboard=True, resize_keyboard=True
        )
        await update.message.reply_text(
            "🗓️ *How often?*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb
        )
        return RECURRING_INT
    return await _save_expense(update, ctx, "")


async def recurring_interval(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["interval"] = update.message.text
    return await _save_expense(update, ctx, update.message.text)


async def _save_expense(update: Update, ctx: ContextTypes.DEFAULT_TYPE, interval: str):
    uid     = update.effective_user.id
    cat     = ctx.user_data.get("cat", "Other")
    amount  = ctx.user_data.get("amount", 0)
    note    = ctx.user_data.get("note", "-")
    tag     = ctx.user_data.get("tag", "")
    is_rec  = ctx.user_data.get("is_recurring", False)

    add_expense(uid, cat, amount, note, tag, "", 1 if is_rec else 0, interval)

    # Check budget warning
    budget  = get_budget(uid)
    used    = get_monthly_total(uid)
    warning = ""

    if budget > 0:
        pct = (used / budget) * 100
        if pct >= 100:
            warning = (
                f"\n\n⚠️ *Budget exceeded!*\n"
                f"Used: {format_amount(used)} / {format_amount(budget)}"
            )
        elif pct >= 80:
            warning = (
                f"\n\n🔶 *Budget warning: {pct:.0f}% used*\n"
                f"{progress_bar(pct)}"
            )

    await update.message.reply_text(
        f"✅ *Expense saved!*\n\n"
        f"• Category: {cat}\n"
        f"• Amount: {format_amount(amount)}\n"
        f"• Note: {note}\n"
        f"• Tag: {tag or '—'}\n"
        f"• Recurring: {'Yes (' + interval + ')' if is_rec else 'No'}"
        f"{warning}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=ReplyKeyboardRemove()
    )
    ctx.user_data.clear()
    return ConversationHandler.END


# ─────────────────────────────────────────────
# /today
# ─────────────────────────────────────────────

async def today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)
    rows = get_today(uid)

    if not rows:
        await update.message.reply_text("📭 *No expenses today yet.*\nUse /add to record one!", parse_mode=ParseMode.MARKDOWN)
        return

    total = sum(r[2] for r in rows)
    lines = [f"📅 *Today's Expenses*\n"]
    for eid, cat, amt, note, tag in rows:
        line = f"• *#{eid}* {cat}: `{format_amount(amt)}`"
        if note and note != "-":
            line += f" — {note}"
        if tag and tag != "-":
            line += f" 🏷️ {tag}"
        lines.append(line)
    lines.append(f"\n💰 *Total: {format_amount(total)}*")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ─────────────────────────────────────────────
# /month
# ─────────────────────────────────────────────

async def month(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    ensure_user(uid)
    ym   = datetime.now().strftime("%Y-%m")
    rows = get_monthly(uid)

    if not rows:
        await update.message.reply_text("📭 *No expenses this month.*", parse_mode=ParseMode.MARKDOWN)
        return

    total  = sum(r[1] for r in rows)
    budget = get_budget(uid)
    lines  = [f"📊 *Monthly Summary — {ym}*\n"]

    for cat, amt in sorted(rows, key=lambda x: -x[1]):
        pct = (amt / total * 100) if total else 0
        lines.append(f"• {cat}: `{format_amount(amt)}` ({pct:.0f}%)")

    lines.append(f"\n💰 *Total: {format_amount(total)}*")

    if budget > 0:
        pct = (total / budget) * 100
        lines.append(f"\n📈 Budget: `{format_amount(total)}` / `{format_amount(budget)}`")
        lines.append(progress_bar(min(pct, 100)))

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ─────────────────────────────────────────────
# /compare
# ─────────────────────────────────────────────

async def compare(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)
    now        = datetime.now()
    this_month = now.strftime("%Y-%m")
    last_dt    = (now.replace(day=1) - timedelta(days=1))
    last_month = last_dt.strftime("%Y-%m")
    this_total = get_monthly_total(uid, this_month)
    last_total = get_monthly_total(uid, last_month)
    diff       = this_total - last_total

    trend = "📈 More" if diff > 0 else ("📉 Less" if diff < 0 else "➡️ Same")

    await update.message.reply_text(
        f"📊 *Month Comparison*\n\n"
        f"• {last_month}: `{format_amount(last_total)}`\n"
        f"• {this_month}: `{format_amount(this_total)}`\n\n"
        f"{trend}: `{format_amount(abs(diff))}`",
        parse_mode=ParseMode.MARKDOWN
    )


# ─────────────────────────────────────────────
# /budget
# ─────────────────────────────────────────────

async def budget_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)
    current = get_budget(uid)
    await update.message.reply_text(
        f"💳 *Set Monthly Budget*\n\n"
        f"Current budget: `{format_amount(current)}`\n\n"
        "Enter your new budget amount:",
        parse_mode=ParseMode.MARKDOWN
    )
    return BUDGET_AMOUNT


async def budget_set(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        budget = float(update.message.text.replace(",", "").strip())
        set_budget(uid, budget)
        await update.message.reply_text(
            f"✅ *Budget set to {format_amount(budget)}!*",
            parse_mode=ParseMode.MARKDOWN
        )
    except ValueError:
        await update.message.reply_text("❌ Invalid number. Try again.")
        return BUDGET_AMOUNT
    return ConversationHandler.END


# ─────────────────────────────────────────────
# /date
# ─────────────────────────────────────────────

async def date_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text(
        "📅 *Search by Date*\n\nEnter date in format: `YYYY-MM-DD`\n\nExample: `2025-01-15`",
        parse_mode=ParseMode.MARKDOWN
    )
    return SEARCH_DATE


async def date_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid      = update.effective_user.id
    date_str = update.message.text.strip()
    rows     = get_by_date(uid, date_str)

    if not rows:
        await update.message.reply_text(f"📭 No expenses found for `{date_str}`", parse_mode=ParseMode.MARKDOWN)
        return ConversationHandler.END

    total = sum(r[2] for r in rows)
    lines = [f"📅 *Expenses on {date_str}*\n"]
    for eid, cat, amt, note, tag in rows:
        lines.append(f"• #{eid} {cat}: `{format_amount(amt)}` — {note}")
    lines.append(f"\n💰 *Total: {format_amount(total)}*")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    return ConversationHandler.END


# ─────────────────────────────────────────────
# /tags
# ─────────────────────────────────────────────

async def tags_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🏷️ *Search by Tag*\n\nEnter a tag name:",
        parse_mode=ParseMode.MARKDOWN
    )
    return SEARCH_TAG


async def tag_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    tag  = update.message.text.strip()
    rows = get_by_tag(uid, tag)

    if not rows:
        await update.message.reply_text(f"📭 No expenses with tag `{tag}`", parse_mode=ParseMode.MARKDOWN)
        return ConversationHandler.END

    total = sum(r[2] for r in rows)
    lines = [f"🏷️ *Tag: {tag}*\n"]
    for eid, cat, amt, note, date in rows:
        lines.append(f"• {date} {cat}: `{format_amount(amt)}` — {note}")
    lines.append(f"\n💰 *Total: {format_amount(total)}*")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    return ConversationHandler.END


# ─────────────────────────────────────────────
# /recurring
# ─────────────────────────────────────────────

async def recurring(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    ensure_user(uid)
    rows = get_recurring(uid)

    if not rows:
        await update.message.reply_text("📭 *No recurring expenses.*", parse_mode=ParseMode.MARKDOWN)
        return

    lines = ["🔄 *Recurring Expenses*\n"]
    for cat, amt, note, interval in rows:
        lines.append(f"• {cat}: `{format_amount(amt)}` ({interval})\n  📝 {note}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ─────────────────────────────────────────────
# /delete
# ─────────────────────────────────────────────

async def delete_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🗑️ *Delete Expense*\n\nEnter the expense ID number:\n\n"
        "_You can find IDs using /today or /date_",
        parse_mode=ParseMode.MARKDOWN
    )
    return DELETE_ID


async def delete_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        eid = int(update.message.text.replace("#", "").strip())
        delete_expense(eid, uid)
        await update.message.reply_text(f"✅ *Expense #{eid} deleted.*", parse_mode=ParseMode.MARKDOWN)
    except ValueError:
        await update.message.reply_text("❌ Invalid ID. Please enter a number.")
    return ConversationHandler.END


# ─────────────────────────────────────────────
# /ai — FINANCIAL ADVICE
# ─────────────────────────────────────────────

async def ai_finance(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)

    if not GEMINI_KEYS:
        await update.message.reply_text(
            "❌ *AI not configured.*\n\nAdmin must add `GEMINI_KEY_1` to environment.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    rows   = get_monthly(uid)
    total  = get_monthly_total(uid)
    budget = get_budget(uid)

    if not rows:
        await update.message.reply_text(
            "📭 *No expense data yet.*\n\nUse /add to record some expenses first!",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    await update.message.reply_text("🤖 *Analyzing your finances...*", parse_mode=ParseMode.MARKDOWN)
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    summary = "\n".join(f"- {cat}: {format_amount(amt)}" for cat, amt in rows)
    summary += f"\nTotal: {format_amount(total)}"
    if budget > 0:
        summary += f"\nBudget: {format_amount(budget)}"

    lang   = get_language(uid)
    advice, error = await get_financial_advice(uid, summary, lang)

    if error:
        log_error(uid, error, "ai_finance")
        await update.message.reply_text(f"❌ {error}", parse_mode=ParseMode.MARKDOWN)
        return

    try:
        await update.message.reply_text(
            f"🤖 *AI Financial Advice*\n\n{advice}",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception:
        await update.message.reply_text(f"🤖 AI Financial Advice\n\n{advice}")
