"""
handlers/admin_handler.py — Admin-only commands
/broadcast   — Send message to all users
/stats       — Bot usage statistics
/errorlogs   — Recent error logs
/maintenance — Toggle maintenance mode
/restart     — Restart reminder
"""

import logging
import asyncio
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode

from database import count_users, get_all_user_ids, get_recent_errors, log_error
from config import ADMIN_IDS, GROQ_API_KEY
import config as cfg

logger = logging.getLogger(__name__)

BROADCAST_MSG = 1


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def admin_only(update: Update) -> bool:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ *Admin only command.*", parse_mode=ParseMode.MARKDOWN)
        return False
    return True


async def stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return

    total_users = count_users()
    ai_status = "✅ Configured" if GROQ_API_KEY else "❌ Not configured"
    key_preview = f"`{GROQ_API_KEY[:8]}...`" if GROQ_API_KEY else "None"

    await update.message.reply_text(
        f"📊 *Bot Statistics*\n\n"
        f"👥 Total users: *{total_users}*\n"
        f"🤖 Groq AI: *{ai_status}*\n"
        f"🔑 Key: {key_preview}\n"
        f"🔧 Maintenance: *{'ON 🔴' if cfg.MAINTENANCE_MODE else 'OFF 🟢'}*",
        parse_mode=ParseMode.MARKDOWN
    )


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
            f"  _{e['error'][:100]}_"
        )
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def maintenance_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    cfg.MAINTENANCE_MODE = not cfg.MAINTENANCE_MODE
    state = "🔴 ON" if cfg.MAINTENANCE_MODE else "🟢 OFF"
    await update.message.reply_text(
        f"🔧 *Maintenance mode: {state}*",
        parse_mode=ParseMode.MARKDOWN
    )


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


async def restart_info(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    await update.message.reply_text(
        "🔄 *Restart Info*\n\n"
        "To restart on Render:\n"
        "1. Go to Render dashboard\n"
        "2. Click 'Manual Deploy' → 'Deploy latest commit'\n\n"
        "Bot restarts automatically on redeploy.",
        parse_mode=ParseMode.MARKDOWN
    )
