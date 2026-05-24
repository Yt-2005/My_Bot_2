"""
handlers/admin_handler.py — Admin-only commands
/broadcast   — Send message to all users
/stats       — Bot usage statistics
/errorlogs   — Recent error logs
/maintenance — Toggle maintenance mode
/restart     — Restart reminder (Render redeploys via CI)
"""

import logging
import asyncio
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode

from database import count_users, get_all_user_ids, get_recent_errors, log_error
from config import ADMIN_IDS
import config as cfg  # for toggling MAINTENANCE_MODE

logger = logging.getLogger(__name__)

# Conversation state
BROADCAST_MSG = 1


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def admin_only(update: Update) -> bool:
    """Check admin and reply if not. Returns True if admin."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ *Admin only command.*", parse_mode=ParseMode.MARKDOWN)
        return False
    return True


# ─────────────────────────────────────────────
# /stats
# ─────────────────────────────────────────────

async def stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return

    total_users = count_users()
    await update.message.reply_text(
        f"📊 *Bot Statistics*\n\n"
        f"👥 Total users: *{total_users}*\n"
        f"🔑 Gemini keys: *{len(cfg.GEMINI_KEYS)}*\n"
        f"🔧 Maintenance: *{'ON' if cfg.MAINTENANCE_MODE else 'OFF'}*",
        parse_mode=ParseMode.MARKDOWN
    )


# ─────────────────────────────────────────────
# /errorlogs
# ─────────────────────────────────────────────

async def error_logs_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return

    errors = get_recent_errors(limit=10)
    if not errors:
        await update.message.reply_text("✅ *No recent errors.*", parse_mode=ParseMode.MARKDOWN)
        return

    lines = ["📋 *Recent Errors (last 10)*\n"]
    for e in errors:
        lines.append(
            f"• `{e['created_at'][:16]}` — user `{e['user_id']}`\n"
            f"  {e['error'][:100]}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ─────────────────────────────────────────────
# /maintenance
# ─────────────────────────────────────────────

async def maintenance_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return

    cfg.MAINTENANCE_MODE = not cfg.MAINTENANCE_MODE
    state = "🔧 ON" if cfg.MAINTENANCE_MODE else "✅ OFF"
    await update.message.reply_text(
        f"🔧 *Maintenance mode: {state}*\n\n"
        "Users will see a maintenance message until you turn it off.",
        parse_mode=ParseMode.MARKDOWN
    )


# ─────────────────────────────────────────────
# /broadcast
# ─────────────────────────────────────────────

async def broadcast_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return ConversationHandler.END

    await update.message.reply_text(
        "📢 *Broadcast Message*\n\n"
        "Type the message to send to all users.\n"
        "_Send /cancel to abort._",
        parse_mode=ParseMode.MARKDOWN
    )
    return BROADCAST_MSG


async def broadcast_send(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return ConversationHandler.END

    message_text = update.message.text
    user_ids     = get_all_user_ids()
    total        = len(user_ids)

    status_msg = await update.message.reply_text(
        f"📤 *Sending to {total} users...*",
        parse_mode=ParseMode.MARKDOWN
    )

    sent = 0
    failed = 0

    for target_uid in user_ids:
        try:
            await ctx.bot.send_message(
                chat_id=target_uid,
                text=f"📢 *Announcement*\n\n{message_text}",
                parse_mode=ParseMode.MARKDOWN
            )
            sent += 1
        except Exception as e:
            failed += 1
            logger.warning(f"Broadcast failed for {target_uid}: {e}")

        # Small delay to avoid rate limiting
        if sent % 25 == 0:
            await asyncio.sleep(1)

    await status_msg.edit_text(
        f"✅ *Broadcast complete!*\n\n"
        f"• Sent: {sent}\n"
        f"• Failed: {failed}\n"
        f"• Total: {total}",
        parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END


# ─────────────────────────────────────────────
# /restart (informational — Render redeploys via dashboard)
# ─────────────────────────────────────────────

async def restart_info(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    await update.message.reply_text(
        "🔄 *Restart Info*\n\n"
        "To restart the bot on Render:\n"
        "1. Go to your Render dashboard\n"
        "2. Click 'Manual Deploy' → 'Deploy latest commit'\n\n"
        "The bot will restart automatically on redeploy.",
        parse_mode=ParseMode.MARKDOWN
    )
