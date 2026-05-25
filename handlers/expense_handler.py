"""
handlers/expense_handler.py — Expense tracking system
Improved UI, better error messages, Groq AI financial advice.
Commands: /add, /today, /month, /compare, /budget, /date,
          /tags, /delete, /recurring, /ai (financial advice)
"""

import logging
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode, ChatAction

from database import (
    ensure_user, add_expense, delete_expense,
    get_today, get_monthly, get_monthly_total,
    get_by_date, get_by_tag, get_recurring,
    get_budget, set_budget, get_pin, get_language,
    log_error,
)
from ai import get_financial_advice, is_configured
from utils import (
    expense_category_keyboard, progress_bar,
    format_amount, back_button, is_rate_limited,
)

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
    await update.message.reply_text(
        "💵 *Enter the amount:*\n\n_Example: 5000 or 2.50_",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=ReplyKeyboardRemove()
    )
    return ENTER_AMOUNT


async def enter_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.replace(",", "").replace("$", "").replace("៛", "").strip())
        if amount <= 0:
            raise ValueError("Non-positive amount")
        ctx.user_data["amount"] = amount
        await update.message.reply_text(
            "📝 *Enter a note:*\n\n_What was this expense for?_\n_(Type `-` to skip)_",
            parse_mode=ParseMode.MARKDOWN
        )
        return ENTER_NOTE
    except ValueError:
        await update.message.reply_text(
            "❌ *Invalid amount.*\n\nPlease enter a number (e.g. `5000` or `2.50`)",
            parse_mode=ParseMode.MARKDOWN
        )
        return ENTER_AMOUNT


async def enter_note(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["note"] = update.message.text if update.message.text != "-" else ""
    await update.message.reply_text(
        "🏷️ *Enter a tag (optional):*\n\n"
        "_Tags help group expenses (e.g. `work`, `family`, `trip`)_\n"
        "_(Type `-` to skip)_",
        parse_mode=ParseMode.MARKDOWN
    )
    return ENTER_TAG


async def enter_tag(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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
    is_rec = "Yes" in update.message.text or "✅" in update.message.text
    ctx.user_data["is_recurring"] = is_rec
    if is_rec:
        kb = ReplyKeyboardMarkup(
            [["📅 Daily", "📅 Weekly"], ["📅 Monthly", "📅 Yearly"]],
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
    cat     = ctx.user_data.get("cat", "📦 Other")
    amount  = ctx.user_data.get("amount", 0)
    note    = ctx.user_data.get("note", "")
    tag     = ctx.user_data.get("tag", "")
    is_rec  = ctx.user_data.get("is_recurring", False)

    add_expense(uid, cat, amount, note, tag, "", 1 if is_rec else 0, interval)

    # Budget check
    budget = get_budget(uid)
    used   = get_monthly_total(uid)
    warning = ""

    if budget > 0:
        pct = (used / budget) * 100
        if pct >= 100:
            warning = (
                f"\n\n🚨 *Budget exceeded!*\n"
                f"Used: `{format_amount(used)}` / `{format_amount(budget)}`\n"
                f"{progress_bar(100)}"
            )
        elif pct >= 80:
            warning = (
                f"\n\n⚠️ *Budget alert: {pct:.0f}% used*\n"
                f"{progress_bar(pct)}"
            )

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("📊 Today", callback_data="menu_expenses"),
        InlineKeyboardButton("➕ Add More", callback_data="menu_expenses"),
    ]])

    await update.message.reply_text(
        f"✅ *Expense Saved!*\n\n"
        f"📁 Category: {cat}\n"
        f"💵 Amount: `{format_amount(amount)}`\n"
        f"📝 Note: {note or '—'}\n"
        f"🏷️ Tag: {tag or '—'}\n"
        f"🔄 Recurring: {'Yes (' + interval + ')' if is_rec else 'No'}"
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
        await update.message.reply_text(
            "📭 *No expenses today yet.*\n\nUse /add to record one! 💪",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=back_button("menu_expenses")
        )
        return

    total = sum(r[2] for r in rows)
    budget = get_budget(uid)
    today_str = datetime.now().strftime("%d %b %Y")

    lines = [f"📅 *Expenses — {today_str}*\n"]
    for eid, cat, amt, note, tag in rows:
        line = f"• *#{eid}* {cat}: `{format_amount(amt)}`"
        if note and note != "-":
            line += f"\n  📝 {note}"
        if tag and tag != "-":
            line += f" 🏷️ _{tag}_"
        lines.append(line)

    lines.append(f"\n💰 *Total: {format_amount(total)}*")

    if budget > 0:
        monthly_used = get_monthly_total(uid)
        pct = (monthly_used / budget) * 100
        lines.append(f"📊 Monthly: `{format_amount(monthly_used)}` / `{format_amount(budget)}`")
        lines.append(progress_bar(min(pct, 100)))

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
        await update.message.reply_text(
            "📭 *No expenses this month.*\n\nStart tracking with /add!",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    total  = sum(r[1] for r in rows)
    budget = get_budget(uid)
    month_name = datetime.now().strftime("%B %Y")
    lines  = [f"📊 *Monthly Summary — {month_name}*\n"]

    for cat, amt in sorted(rows, key=lambda x: -x[1]):
        pct = (amt / total * 100) if total else 0
        bar = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
        lines.append(f"• {cat}: `{format_amount(amt)}` ({pct:.0f}%)\n  {bar}")

    lines.append(f"\n💰 *Total: {format_amount(total)}*")

    if budget > 0:
        pct = (total / budget) * 100
        remaining = max(budget - total, 0)
        lines.append(f"\n📈 Budget Progress:")
        lines.append(f"`{format_amount(total)}` / `{format_amount(budget)}`")
        lines.append(progress_bar(min(pct, 100)))
        if remaining > 0:
            lines.append(f"✅ Remaining: `{format_amount(remaining)}`")
        else:
            lines.append(f"🚨 Over budget by: `{format_amount(abs(remaining))}`")

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🤖 AI Advice", callback_data="menu_ai_finance"),
        InlineKeyboardButton("📊 Compare", callback_data="menu_expenses"),
    ]])
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN, reply_markup=kb)


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

    if diff > 0:
        trend = f"📈 Spent *{format_amount(diff)} more* than last month"
        emoji = "⚠️"
    elif diff < 0:
        trend = f"📉 Spent *{format_amount(abs(diff))} less* than last month"
        emoji = "🎉"
    else:
        trend = "➡️ Same as last month"
        emoji = "😐"

    this_name = now.strftime("%B %Y")
    last_name = last_dt.strftime("%B %Y")

    await update.message.reply_text(
        f"📊 *Month Comparison*\n\n"
        f"• {last_name}: `{format_amount(last_total)}`\n"
        f"• {this_name}: `{format_amount(this_total)}`\n\n"
        f"{emoji} {trend}",
        parse_mode=ParseMode.MARKDOWN
    )


# ─────────────────────────────────────────────
# /budget
# ─────────────────────────────────────────────

async def budget_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)
    current = get_budget(uid)
    used    = get_monthly_total(uid)

    text = f"💳 *Set Monthly Budget*\n\n"
    if current > 0:
        pct = (used / current * 100) if current else 0
        text += f"Current budget: `{format_amount(current)}`\n"
        text += f"Used this month: `{format_amount(used)}` ({pct:.0f}%)\n\n"
    text += "Enter your new monthly budget amount:"

    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    return BUDGET_AMOUNT


async def budget_set(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        budget = float(update.message.text.replace(",", "").replace("$", "").strip())
        if budget <= 0:
            raise ValueError
        set_budget(uid, budget)
        used = get_monthly_total(uid)
        pct  = (used / budget * 100) if budget else 0
        await update.message.reply_text(
            f"✅ *Budget set to `{format_amount(budget)}`!*\n\n"
            f"📊 This month: `{format_amount(used)}` used ({pct:.0f}%)\n"
            f"{progress_bar(min(pct, 100))}",
            parse_mode=ParseMode.MARKDOWN
        )
    except ValueError:
        await update.message.reply_text(
            "❌ *Invalid amount.* Enter a positive number (e.g. `500000`)",
            parse_mode=ParseMode.MARKDOWN
        )
        return BUDGET_AMOUNT
    return ConversationHandler.END


# ─────────────────────────────────────────────
# /date
# ─────────────────────────────────────────────

async def date_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    today_str = datetime.now().strftime("%Y-%m-%d")
    await update.message.reply_text(
        f"📅 *Search by Date*\n\n"
        f"Enter date in format: `YYYY-MM-DD`\n\n"
        f"Example: `{today_str}`",
        parse_mode=ParseMode.MARKDOWN
    )
    return SEARCH_DATE


async def date_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid      = update.effective_user.id
    date_str = update.message.text.strip()

    # Validate date format
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        await update.message.reply_text(
            "❌ *Invalid date format.*\n\nUse: `YYYY-MM-DD` (e.g. `2025-05-25`)",
            parse_mode=ParseMode.MARKDOWN
        )
        return SEARCH_DATE

    rows = get_by_date(uid, date_str)

    if not rows:
        await update.message.reply_text(
            f"📭 No expenses found for `{date_str}`",
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END

    total = sum(r[2] for r in rows)
    lines = [f"📅 *Expenses on {date_str}*\n"]
    for eid, cat, amt, note, tag in rows:
        line = f"• *#{eid}* {cat}: `{format_amount(amt)}`"
        if note and note != "-":
            line += f" — {note}"
        lines.append(line)
    lines.append(f"\n💰 *Total: {format_amount(total)}*")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    return ConversationHandler.END


# ─────────────────────────────────────────────
# /tags
# ─────────────────────────────────────────────

async def tags_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🏷️ *Search by Tag*\n\nEnter a tag name to search:",
        parse_mode=ParseMode.MARKDOWN
    )
    return SEARCH_TAG


async def tag_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    tag  = update.message.text.strip()
    rows = get_by_tag(uid, tag)

    if not rows:
        await update.message.reply_text(
            f"📭 No expenses with tag `{tag}`\n\nTry another tag or /tags to search again.",
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END

    total = sum(r[2] for r in rows)
    lines = [f"🏷️ *Tag: #{tag}* ({len(rows)} expenses)\n"]
    for eid, cat, amt, note, date in rows:
        lines.append(f"• `{date}` {cat}: `{format_amount(amt)}`\n  📝 {note or '—'}")
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
        await update.message.reply_text(
            "📭 *No recurring expenses.*\n\nWhen adding an expense, mark it as recurring!",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    total_monthly = sum(r[1] for r in rows if "month" in (r[3] or "").lower())
    lines = [f"🔄 *Recurring Expenses* ({len(rows)} total)\n"]
    for cat, amt, note, interval in rows:
        lines.append(f"• {cat}: `{format_amount(amt)}` 🗓️ {interval}\n  📝 {note or '—'}")

    if total_monthly > 0:
        lines.append(f"\n📊 Monthly fixed costs: `{format_amount(total_monthly)}`")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ─────────────────────────────────────────────
# /delete
# ─────────────────────────────────────────────

async def delete_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    rows = get_today(uid)
    text = "🗑️ *Delete Expense*\n\nEnter the expense ID:\n\n"
    if rows:
        text += "*Recent expenses:*\n"
        for eid, cat, amt, note, tag in rows[:5]:
            text += f"• `#{eid}` {cat}: {format_amount(amt)}\n"
    text += "\n_Find more IDs with /today or /date_"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    return DELETE_ID


async def delete_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        eid = int(update.message.text.replace("#", "").strip())
        delete_expense(eid, uid)
        await update.message.reply_text(
            f"✅ *Expense #{eid} deleted.*",
            parse_mode=ParseMode.MARKDOWN
        )
    except ValueError:
        await update.message.reply_text(
            "❌ *Invalid ID.* Please enter a number (e.g. `42`)",
            parse_mode=ParseMode.MARKDOWN
        )
    return ConversationHandler.END


# ─────────────────────────────────────────────
# /ai — FINANCIAL ADVICE (powered by Groq)
# ─────────────────────────────────────────────

async def ai_finance(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(uid)

    if not is_configured():
        await update.message.reply_text(
            "❌ *AI not configured.*\n\n"
            "Add `GROQ_API_KEY` to your environment variables.\n\n"
            "Get a *free* key at: [console.groq.com](https://console.groq.com)",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    rows   = get_monthly(uid)
    total  = get_monthly_total(uid)
    budget = get_budget(uid)

    if not rows:
        await update.message.reply_text(
            "📭 *No expense data yet.*\n\nUse /add to record some expenses first, then come back for AI advice!",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    thinking_msg = await update.message.reply_text(
        "🤖 *Analyzing your finances...*\n\n⚡ Powered by Groq AI (llama-3.3-70b)",
        parse_mode=ParseMode.MARKDOWN
    )
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    summary = "\n".join(f"- {cat}: {format_amount(amt)}" for cat, amt in rows)
    summary += f"\nTotal spent: {format_amount(total)}"
    if budget > 0:
        pct = (total / budget * 100)
        summary += f"\nMonthly budget: {format_amount(budget)} ({pct:.0f}% used)"

    lang   = get_language(uid)
    advice, error = await get_financial_advice(uid, summary, lang)

    # Delete thinking message
    try:
        await thinking_msg.delete()
    except Exception:
        pass

    if error:
        log_error(uid, error, "ai_finance")
        await update.message.reply_text(
            f"❌ *AI Error*\n\n{error}",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    try:
        await update.message.reply_text(
            f"🤖 *AI Financial Advice*\n\n{advice}\n\n_⚡ Powered by Groq AI_",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception:
        await update.message.reply_text(f"🤖 AI Financial Advice\n\n{advice}")
