"""
bot.py — Webhook mode via Flask (គ្មាន port conflict)
"""

import sys
import logging
import asyncio
import os

if sys.version_info >= (3, 13):
    try:
        import telegram.ext._updater as _upd
        _slot = "_Updater__polling_cleanup_cb"
        if _slot not in _upd.Updater.__slots__:
            _upd.Updater.__slots__ = tuple(_upd.Updater.__slots__) + (_slot,)
    except Exception:
        pass

from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, TypeHandler, filters,
)
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.ext._application import ApplicationHandlerStop

from config import TOKEN, GROQ_API_KEY, ADMIN_IDS
from database import init_db
import config as cfg

from handlers.core import start, help_cmd, cancel, clear_chat, menu_callback
from handlers.image_handler import (
    imagine_cmd, image_style_callback, reimagine_callback,
    upscale_cmd, upscale_photo_received, upscale_pending_callback,
    WAITING_FOR_UPSCALE_PHOTO,
)
from handlers.ai_handler import (
    chat_cmd, chat_message, handle_text_message, CHATTING,
    translate_cmd, translate_lang_callback, translate_receive, TRANSLATE_WAIT,
    write_cmd, write_format_callback, write_receive, WRITE_TOPIC, WRITE_CONTENT,
    summarize_cmd, summarize_receive, SUMMARIZE_WAIT,
    explain_cmd, explain_receive, EXPLAIN_WAIT,
    ideas_cmd, ideas_receive, IDEAS_WAIT,
    codehelp_cmd, code_action_callback, code_receive, CODE_WAIT,
    ask_cmd, ask_receive, ASK_WAIT,
    roast_cmd,
    ai_menu_callback,
)
from handlers.notes_handler import (
    note_cmd, note_add_start, note_add_receive,
    note_list, note_delete_start, delete_note_callback,
    note_callback,
    ADDING_NOTE, DELETING_NOTE,
)
from handlers.expense_handler import (
    add_start, choose_category, enter_amount, enter_note, enter_tag,
    is_recurring_handler, recurring_interval,
    today, month, compare, recurring,
    budget_start, budget_set,
    date_start, date_search,
    tags_start, tag_search,
    delete_start, delete_handler,
    ai_finance,
    PIN_VERIFY, CHOOSE_CAT, ENTER_AMOUNT, ENTER_NOTE, ENTER_TAG,
    IS_RECURRING, RECURRING_INT, BUDGET_AMOUNT,
    SEARCH_DATE, SEARCH_TAG, DELETE_ID,
)
from handlers.settings_handler import (
    lang_start, lang_choose,
    setpin_start, pin_set_handler, pin_confirm_handler,
    reminder_start, reminder_set,
    LANG_CHOOSE, PIN_SET, PIN_CONFIRM, REMINDER_PICK,
)
from handlers.admin_handler import (
    stats, error_logs_cmd, maintenance_toggle,
    broadcast_start, broadcast_send, restart_info,
    BROADCAST_MSG,
)
from handlers.pdf_handler import (
    pdf_cmd, pdf_callback,
    pdf_receive_text, pdf_receive_file,
    auto_pdf_detect, auto_pdf_extract_callback,
    WAITING_PDF_TEXT, WAITING_PDF_IMAGE,
)
from handlers.khmer_calendar_handler import (
    khmer_calendar_cmd, khmer_calendar_callback,
    calendar_convert_receive, calendar_search_receive,
    CALENDAR_CONVERT_WAIT, CALENDAR_SEARCH_WAIT,
)

from flask import Flask, request as flask_request, jsonify
from dashboard import register_dashboard

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("werkzeug").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

PORT = int(os.getenv("PORT", 10000))
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://my-bot-2-4ayy.onrender.com")
WEBHOOK_PATH = f"/webhook/{TOKEN}"


# ══════════════════════════════════════════════════════
# 🛡️ ADMIN CHECK — reads BOTH config.py AND bot_admins DB table
# ══════════════════════════════════════════════════════

def _get_db_admins() -> dict:
    """
    Returns {user_id: role} for all admins in bot_admins table.
    Falls back to {} on any error.
    """
    try:
        from database import get_conn
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("""
                CREATE TABLE IF NOT EXISTS bot_admins (
                    user_id   BIGINT PRIMARY KEY,
                    username  TEXT,
                    role      TEXT NOT NULL DEFAULT 'admin',
                    note      TEXT,
                    added_at  TIMESTAMPTZ DEFAULT NOW(),
                    added_by  TEXT DEFAULT 'dashboard'
                )
            """)
            conn.commit()
            c.execute("SELECT user_id, role FROM bot_admins")
            rows = c.fetchall()
            # Support both dict-row and tuple-row cursors
            result = {}
            for r in rows:
                if hasattr(r, 'keys'):
                    result[int(r['user_id'])] = r['role']
                else:
                    result[int(r[0])] = r[1]
            return result
    except Exception as e:
        logger.warning(f"_get_db_admins error: {e}")
        return {}


def _is_admin(user_id: int) -> bool:
    """True if user is in config ADMIN_IDS OR bot_admins table."""
    if user_id in ADMIN_IDS:
        return True
    db_admins = _get_db_admins()
    return user_id in db_admins


def _get_role(user_id: int) -> str | None:
    """Return role string or None if not admin."""
    if user_id in ADMIN_IDS:
        return "superadmin"
    db_admins = _get_db_admins()
    return db_admins.get(user_id)


def _has_role(user_id: int, min_role: str) -> bool:
    """
    Role hierarchy: superadmin > admin > moderator
    Returns True if user's role >= min_role.
    """
    hierarchy = {"moderator": 1, "admin": 2, "superadmin": 3}
    role = _get_role(user_id)
    if role is None:
        return False
    return hierarchy.get(role, 0) >= hierarchy.get(min_role, 99)


async def _admin_only(update: Update, min_role: str = "moderator") -> bool:
    """
    Check admin and reply with ⛔ if not authorized.
    Returns True if authorized, False otherwise.
    """
    uid = update.effective_user.id
    if _has_role(uid, min_role):
        return True
    role = _get_role(uid)
    if role is not None:
        await update.message.reply_text(
            f"⛔ *Permission Denied.*\n\nYour role (`{role}`) doesn't have access to this command.\n"
            f"Required: `{min_role}` or higher.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "⛔ *Admin only command.*\n\nYou are not registered as a bot admin.\n"
            "Ask a super admin to grant you access via the dashboard.",
            parse_mode="Markdown"
        )
    return False


# ══════════════════════════════════════════════════════
# 🛡️ GLOBAL BOT BLOCKER
# ══════════════════════════════════════════════════════
async def block_bots(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user and user.is_bot:
        logger.warning(f"🚫 Bot blocked: @{user.username or user.id}")
        raise ApplicationHandlerStop


async def send_reminders(ctx: ContextTypes.DEFAULT_TYPE):
    """✅ Fixed: uses PostgreSQL via database.py (no more sqlite3)."""
    from datetime import datetime
    from database import send_reminders_db
    hour = datetime.now().strftime("%H")
    try:
        user_ids = send_reminders_db(hour)
        for uid in user_ids:
            try:
                await ctx.bot.send_message(
                    uid,
                    "⏰ *Daily Reminder!*\n\nDon't forget to log your expenses today! 💰\n\nUse /add to record a new expense.",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.warning(f"រំលឹកបរាជ័យ {uid}: {e}")
    except Exception as e:
        logger.error(f"កំហុស send_reminders: {e}")


async def error_handler(update: object, ctx: ContextTypes.DEFAULT_TYPE):
    logger.error(f"កំហុស: {ctx.error}", exc_info=ctx.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "❌ *Something went wrong.* Please try again or use /start.",
                parse_mode="Markdown"
            )
        except Exception:
            pass


# ══════════════════════════════════════════════════════
# 👑 ADMIN COMMANDS
# ══════════════════════════════════════════════════════

async def admin_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/admin_help — show available admin commands based on role."""
    uid = update.effective_user.id
    role = _get_role(uid)
    if role is None:
        await update.message.reply_text(
            "⛔ You are not a bot admin.\n\nAsk a super admin to grant you access via the dashboard.",
            parse_mode="Markdown"
        )
        return

    hierarchy = {"moderator": 1, "admin": 2, "superadmin": 3}
    level = hierarchy.get(role, 0)
    role_labels = {"superadmin": "👑 Super Admin", "admin": "🛡️ Admin", "moderator": "🔰 Moderator"}
    role_label = role_labels.get(role, role)

    lines = [f"🤖 *Admin Help — {role_label}*\n"]

    # All admins (moderator+)
    lines.append("*📋 Available to you:*")
    lines.append("`/admin_help` — Show this help")
    lines.append("`/botstats` — Bot statistics summary")
    lines.append("`/userinfo <id>` — User profile & spending")
    lines.append("`/ban <id>` — Ban a user")
    lines.append("`/unban <id>` — Unban a user")
    lines.append("`/sendmsg <id> <text>` — Send message to user")

    if level >= 2:
        lines.append("\n*🛡️ Admin commands:*")
        lines.append("`/broadcast <msg>` — Message all users")
        lines.append("`/deleteuser <id>` — Delete user & all data")
        lines.append("`/errorlogs` — View recent errors")
        lines.append("`/topadmins` — List all bot admins")
        lines.append("`/usertop` — Top 10 spenders")
        lines.append("`/recentusers` — Last 10 joined users")
        lines.append("`/maintenance` — Toggle maintenance mode")

    if level >= 3:
        lines.append("\n*👑 Super Admin commands:*")
        lines.append("`/setadmin <id> <role>` — Grant admin role")
        lines.append("`/removeadmin <id>` — Remove admin role")
        lines.append("`/dbstats` — Raw DB table counts")

    lines.append(f"\n🌐 Dashboard: {WEBHOOK_URL}/admin")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def tg_userinfo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/userinfo <user_id>"""
    if not await _admin_only(update, "moderator"):
        return
    from database import get_user_info
    args = ctx.args
    if not args:
        await update.message.reply_text("Usage: `/userinfo <user_id>`", parse_mode="Markdown")
        return
    try:
        uid = int(args[0])
        info = get_user_info(uid)
        if not info:
            await update.message.reply_text(f"❌ User `{uid}` not found.", parse_mode="Markdown")
            return
        text = (
            f"👤 *User Info*\n\n"
            f"🆔 ID: `{info['user_id']}`\n"
            f"👤 Username: @{info['username'] or 'N/A'}\n"
            f"🌐 Language: `{info['language']}`\n"
            f"💵 Budget: `${info['budget'] or 0:.2f}`\n"
            f"⏰ Reminder: `{'ON' if info['daily_reminder'] else 'OFF'}` {info['reminder_time'] or ''}\n"
            f"💰 Total Spent: `${info['total_spent']:.2f}`\n"
            f"🧾 Expenses: `{info['expense_count']}`\n"
            f"📅 Joined: `{str(info['created_at'])[:10]}`"
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🌐 View in Dashboard", url=f"{WEBHOOK_URL}/admin/user/{uid}")
        ]])
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def tg_ban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/ban <user_id> [reason]"""
    if not await _admin_only(update, "moderator"):
        return
    from database import ban_user
    args = ctx.args
    if not args:
        await update.message.reply_text("Usage: `/ban <user_id> [reason]`", parse_mode="Markdown")
        return
    try:
        uid = int(args[0])
        reason = " ".join(args[1:]) if len(args) > 1 else "No reason given"
        ban_user(uid)
        await update.message.reply_text(
            f"🚫 User `{uid}` has been banned.\n📝 Reason: _{reason}_",
            parse_mode="Markdown"
        )
        # Notify the banned user
        try:
            await ctx.bot.send_message(
                chat_id=uid,
                text=f"🚫 *You have been banned.*\n\nReason: _{reason}_\n\nContact support if you think this is a mistake.",
                parse_mode="Markdown"
            )
        except Exception:
            pass
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def tg_unban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/unban <user_id>"""
    if not await _admin_only(update, "moderator"):
        return
    from database import unban_user
    args = ctx.args
    if not args:
        await update.message.reply_text("Usage: `/unban <user_id>`", parse_mode="Markdown")
        return
    try:
        uid = int(args[0])
        unban_user(uid)
        await update.message.reply_text(
            f"✅ User `{uid}` has been unbanned.",
            parse_mode="Markdown"
        )
        try:
            await ctx.bot.send_message(
                chat_id=uid,
                text="✅ *You have been unbanned!*\n\nYou can use the bot again. Use /start to begin.",
                parse_mode="Markdown"
            )
        except Exception:
            pass
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def tg_botstats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/botstats — full stats from PostgreSQL."""
    if not await _admin_only(update, "moderator"):
        return
    from database import get_bot_stats
    try:
        s = get_bot_stats()
        text = (
            f"📊 *Bot Statistics*\n\n"
            f"👥 Users: *{s['total_users']}* (+{s['new_today']} today)\n"
            f"💰 Total Spent: *${s['total_spent']:.2f}*\n"
            f"🧾 Expenses logged: *{s.get('total_expenses', 'N/A')}*\n"
            f"📝 Notes: *{s['total_notes']}*\n"
            f"⚠️ Errors: *{s['errors']}*\n"
            f"🚫 Banned: *{s['banned']}*\n"
            f"📅 Active (30d): *{s.get('active_30d', 'N/A')}*"
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🌐 Open Dashboard", url=f"{WEBHOOK_URL}/admin")
        ]])
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def tg_sendmsg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/sendmsg <user_id> <message>"""
    if not await _admin_only(update, "moderator"):
        return
    args = ctx.args
    if not args or len(args) < 2:
        await update.message.reply_text("Usage: `/sendmsg <user_id> <message text>`", parse_mode="Markdown")
        return
    try:
        uid = int(args[0])
        msg = " ".join(args[1:])
        await ctx.bot.send_message(
            chat_id=uid,
            text=f"📬 *Message from Admin:*\n\n{msg}",
            parse_mode="Markdown"
        )
        await update.message.reply_text(f"✅ Sent to `{uid}`", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def tg_deleteuser(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/deleteuser <user_id>"""
    if not await _admin_only(update, "admin"):
        return
    args = ctx.args
    if not args:
        await update.message.reply_text("Usage: `/deleteuser <user_id>`", parse_mode="Markdown")
        return
    try:
        from database import get_conn
        uid = int(args[0])
        with get_conn() as conn:
            c = conn.cursor()
            for tbl in ["expenses", "notes", "chat_memory", "error_logs", "users"]:
                c.execute(f"DELETE FROM {tbl} WHERE user_id=%s", (uid,))
            conn.commit()
        await update.message.reply_text(
            f"🗑 User `{uid}` and all their data deleted.",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def tg_set_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/setadmin <user_id> <role>  — superadmin only"""
    if not await _admin_only(update, "superadmin"):
        return
    args = ctx.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: `/setadmin <user_id> <role>`\n\nRoles: `superadmin` | `admin` | `moderator`",
            parse_mode="Markdown"
        )
        return
    try:
        uid = int(args[0])
        role = args[1].lower()
        if role not in ("superadmin", "admin", "moderator"):
            await update.message.reply_text(
                "❌ Invalid role. Use: `superadmin`, `admin`, or `moderator`",
                parse_mode="Markdown"
            )
            return
        from database import get_conn
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("""
                CREATE TABLE IF NOT EXISTS bot_admins (
                    user_id BIGINT PRIMARY KEY, username TEXT,
                    role TEXT NOT NULL DEFAULT 'admin', note TEXT,
                    added_at TIMESTAMPTZ DEFAULT NOW(), added_by TEXT DEFAULT 'telegram'
                )
            """)
            # Try to get username
            try:
                member = await ctx.bot.get_chat(uid)
                uname = member.username or None
            except Exception:
                uname = None

            c.execute("""
                INSERT INTO bot_admins (user_id, username, role, added_by)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET role=EXCLUDED.role, username=COALESCE(EXCLUDED.username, bot_admins.username)
            """, (uid, uname, role, f"tg:{update.effective_user.username or update.effective_user.id}"))
            conn.commit()

        role_labels = {"superadmin": "Super Admin 👑", "admin": "Admin 🛡️", "moderator": "Moderator 🔰"}
        await update.message.reply_text(
            f"✅ User `{uid}` granted *{role_labels[role]}* access.",
            parse_mode="Markdown"
        )
        try:
            await ctx.bot.send_message(
                chat_id=uid,
                text=f"🎉 *You have been granted bot admin access!*\n\nRole: *{role_labels[role]}*\n\nUse /admin\\_help to see your available commands.",
                parse_mode="Markdown"
            )
        except Exception:
            pass
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def tg_remove_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/removeadmin <user_id>  — superadmin only"""
    if not await _admin_only(update, "superadmin"):
        return
    args = ctx.args
    if not args:
        await update.message.reply_text("Usage: `/removeadmin <user_id>`", parse_mode="Markdown")
        return
    try:
        uid = int(args[0])
        from database import get_conn
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM bot_admins WHERE user_id=%s", (uid,))
            conn.commit()
        await update.message.reply_text(
            f"🗑 Admin `{uid}` removed.",
            parse_mode="Markdown"
        )
        try:
            await ctx.bot.send_message(
                chat_id=uid,
                text="ℹ️ Your bot admin access has been revoked.",
                parse_mode="Markdown"
            )
        except Exception:
            pass
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def tg_top_admins(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/topadmins — list all bot admins"""
    if not await _admin_only(update, "admin"):
        return
    try:
        db_admins = _get_db_admins()
        role_labels = {"superadmin": "👑", "admin": "🛡️", "moderator": "🔰"}

        lines = ["👑 *Bot Admins*\n"]
        # Config admins
        if ADMIN_IDS:
            lines.append("*From config.py:*")
            for uid in ADMIN_IDS:
                lines.append(f"  👑 `{uid}` — superadmin (config)")
        # DB admins
        if db_admins:
            lines.append("\n*From database:*")
            for uid, role in db_admins.items():
                icon = role_labels.get(role, "👤")
                lines.append(f"  {icon} `{uid}` — {role}")
        if not ADMIN_IDS and not db_admins:
            lines.append("_No admins configured._")

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def tg_usertop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/usertop — top 10 spenders"""
    if not await _admin_only(update, "admin"):
        return
    try:
        from database import get_conn
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT e.user_id, u.username, SUM(e.amount) as total, COUNT(*) as cnt
                FROM expenses e LEFT JOIN users u ON e.user_id=u.user_id
                GROUP BY e.user_id, u.username ORDER BY total DESC LIMIT 10
            """)
            rows = c.fetchall()

        lines = ["🏆 *Top 10 Spenders*\n"]
        medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 7
        for i, r in enumerate(rows):
            if hasattr(r, 'keys'):
                uid, uname, total, cnt = r['user_id'], r['username'], r['total'], r['cnt']
            else:
                uid, uname, total, cnt = r
            uname_str = f"@{uname}" if uname else f"`{uid}`"
            lines.append(f"{medals[i]} {uname_str} — *${float(total):.2f}* ({cnt} expenses)")

        if not rows:
            lines.append("_No expense data yet._")

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def tg_recent_users(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/recentusers — last 10 registered users"""
    if not await _admin_only(update, "admin"):
        return
    try:
        from database import get_conn
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT user_id, username, language, created_at
                FROM users ORDER BY created_at DESC LIMIT 10
            """)
            rows = c.fetchall()

        lines = ["🆕 *Recent Users*\n"]
        for r in rows:
            if hasattr(r, 'keys'):
                uid, uname, lang, ts = r['user_id'], r['username'], r['language'], r['created_at']
            else:
                uid, uname, lang, ts = r
            uname_str = f"@{uname}" if uname else "no username"
            lines.append(f"• `{uid}` {uname_str} [{lang}] — {str(ts)[:10]}")

        if not rows:
            lines.append("_No users yet._")

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def tg_db_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/dbstats — raw table row counts (superadmin only)"""
    if not await _admin_only(update, "superadmin"):
        return
    try:
        from database import get_conn
        tables = ["users", "expenses", "notes", "chat_memory", "error_logs", "banned_users", "bot_admins"]
        lines = ["🗄️ *Database Table Counts*\n"]
        with get_conn() as conn:
            c = conn.cursor()
            for tbl in tables:
                try:
                    c.execute(f"SELECT COUNT(*) FROM {tbl}")
                    row = c.fetchone()
                    cnt = row[0] if row else 0
                    lines.append(f"`{tbl}`: *{cnt}* rows")
                except Exception:
                    lines.append(f"`{tbl}`: _(table not found)_")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


# ══════════════════════════════════════════════════════
# 🔨 BUILD APP
# ══════════════════════════════════════════════════════

def build_app():
    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .updater(None)
        .build()
    )

    # 🛡️ Block bots
    app.add_handler(TypeHandler(Update, block_bots), group=-1)

    fallbacks = [
        CommandHandler("cancel", cancel),
        CommandHandler("start",  start),
        CommandHandler("today",  today),
        CommandHandler("month",  month),
        CommandHandler("compare",compare),
    ]

    chat_conv = ConversationHandler(
        entry_points=[CommandHandler("chat", chat_cmd)],
        states={CHATTING: [MessageHandler(filters.TEXT & ~filters.COMMAND, chat_message)]},
        fallbacks=fallbacks,
        allow_reentry=True,
    )

    translate_conv = ConversationHandler(
        entry_points=[CommandHandler("translate", translate_cmd)],
        states={TRANSLATE_WAIT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, translate_receive),
            CallbackQueryHandler(translate_lang_callback, pattern=r"^tl_"),
        ]},
        fallbacks=fallbacks,
        allow_reentry=True,
    )

    write_conv = ConversationHandler(
        entry_points=[CommandHandler("write", write_cmd)],
        states={
            WRITE_TOPIC:   [CallbackQueryHandler(write_format_callback, pattern=r"^write_")],
            WRITE_CONTENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, write_receive)],
        },
        fallbacks=fallbacks,
        allow_reentry=True,
    )

    summarize_conv = ConversationHandler(
        entry_points=[CommandHandler("summarize", summarize_cmd)],
        states={SUMMARIZE_WAIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, summarize_receive)]},
        fallbacks=fallbacks,
        allow_reentry=True,
    )

    explain_conv = ConversationHandler(
        entry_points=[CommandHandler("explain", explain_cmd)],
        states={EXPLAIN_WAIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, explain_receive)]},
        fallbacks=fallbacks,
        allow_reentry=True,
    )

    ideas_conv = ConversationHandler(
        entry_points=[CommandHandler("ideas", ideas_cmd)],
        states={IDEAS_WAIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ideas_receive)]},
        fallbacks=fallbacks,
        allow_reentry=True,
    )

    code_conv = ConversationHandler(
        entry_points=[CommandHandler("codehelp", codehelp_cmd)],
        states={CODE_WAIT: [
            CallbackQueryHandler(code_action_callback, pattern=r"^code_"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, code_receive),
        ]},
        fallbacks=fallbacks,
        allow_reentry=True,
    )

    ask_conv = ConversationHandler(
        entry_points=[CommandHandler("ask", ask_cmd)],
        states={ASK_WAIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_receive)]},
        fallbacks=fallbacks,
        allow_reentry=True,
    )

    upscale_conv = ConversationHandler(
        entry_points=[CommandHandler("upscale", upscale_cmd)],
        states={
            WAITING_FOR_UPSCALE_PHOTO: [
                MessageHandler(filters.PHOTO | filters.Document.IMAGE, upscale_photo_received),
            ]
        },
        fallbacks=fallbacks,
        allow_reentry=True,
    )

    notes_conv = ConversationHandler(
        entry_points=[CommandHandler("note", note_cmd)],
        states={
            ADDING_NOTE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, note_add_receive)],
            DELETING_NOTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, note_delete_start)],
        },
        fallbacks=fallbacks,
        allow_reentry=True,
    )

    add_conv = ConversationHandler(
        entry_points=[CommandHandler("add", add_start)],
        states={
            CHOOSE_CAT:    [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_category)],
            ENTER_AMOUNT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_amount)],
            ENTER_NOTE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_note)],
            ENTER_TAG:     [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_tag)],
            IS_RECURRING:  [MessageHandler(filters.TEXT & ~filters.COMMAND, is_recurring_handler)],
            RECURRING_INT: [MessageHandler(filters.TEXT & ~filters.COMMAND, recurring_interval)],
        },
        fallbacks=fallbacks,
        allow_reentry=True,
    )

    budget_conv = ConversationHandler(
        entry_points=[CommandHandler("budget", budget_start)],
        states={BUDGET_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, budget_set)]},
        fallbacks=fallbacks,
        allow_reentry=True,
    )

    date_conv = ConversationHandler(
        entry_points=[CommandHandler("date", date_start)],
        states={SEARCH_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, date_search)]},
        fallbacks=fallbacks,
        allow_reentry=True,
    )

    tag_conv = ConversationHandler(
        entry_points=[CommandHandler("tags", tags_start)],
        states={SEARCH_TAG: [MessageHandler(filters.TEXT & ~filters.COMMAND, tag_search)]},
        fallbacks=fallbacks,
        allow_reentry=True,
    )

    delete_conv = ConversationHandler(
        entry_points=[CommandHandler("delete", delete_start)],
        states={DELETE_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, delete_handler)]},
        fallbacks=fallbacks,
        allow_reentry=True,
    )

    lang_conv = ConversationHandler(
        entry_points=[CommandHandler("lang", lang_start)],
        states={LANG_CHOOSE: [MessageHandler(filters.TEXT & ~filters.COMMAND, lang_choose)]},
        fallbacks=fallbacks,
        allow_reentry=True,
    )

    setpin_conv = ConversationHandler(
        entry_points=[CommandHandler("setpin", setpin_start)],
        states={
            PIN_SET:     [MessageHandler(filters.TEXT & ~filters.COMMAND, pin_set_handler)],
            PIN_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, pin_confirm_handler)],
        },
        fallbacks=fallbacks,
        allow_reentry=True,
    )

    reminder_conv = ConversationHandler(
        entry_points=[CommandHandler("reminder", reminder_start)],
        states={REMINDER_PICK: [MessageHandler(filters.TEXT & ~filters.COMMAND, reminder_set)]},
        fallbacks=fallbacks,
        allow_reentry=True,
    )

    broadcast_conv = ConversationHandler(
        entry_points=[CommandHandler("broadcast", broadcast_start)],
        states={BROADCAST_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_send)]},
        fallbacks=fallbacks,
        allow_reentry=True,
    )

    pdf_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(pdf_callback, pattern=r"^pdf_(text|image|extract)$")],
        states={
            WAITING_PDF_TEXT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, pdf_receive_text)],
            WAITING_PDF_IMAGE: [MessageHandler(filters.PHOTO | filters.Document.ALL, pdf_receive_file)],
        },
        fallbacks=fallbacks,
        allow_reentry=True,
    )

    calendar_conv = ConversationHandler(
        entry_points=[
            CommandHandler("calendar", khmer_calendar_cmd),
            CallbackQueryHandler(khmer_calendar_callback, pattern=r"^kcal_"),
        ],
        states={
            CALENDAR_CONVERT_WAIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, calendar_convert_receive)],
            CALENDAR_SEARCH_WAIT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, calendar_search_receive)],
        },
        fallbacks=fallbacks,
        allow_reentry=True,
    )

    for conv in [chat_conv, translate_conv, write_conv, summarize_conv,
                 explain_conv, ideas_conv, code_conv, ask_conv,
                 upscale_conv, notes_conv, add_conv, budget_conv,
                 date_conv, tag_conv, delete_conv, lang_conv, setpin_conv,
                 reminder_conv, broadcast_conv, pdf_conv, calendar_conv]:
        app.add_handler(conv)

    # ── Regular commands ──
    app.add_handler(CommandHandler("start",       start))
    app.add_handler(CommandHandler("help",        help_cmd))
    app.add_handler(CommandHandler("clearchat",   clear_chat))
    app.add_handler(CommandHandler("imagine",     imagine_cmd))
    app.add_handler(CommandHandler("today",       today))
    app.add_handler(CommandHandler("month",       month))
    app.add_handler(CommandHandler("compare",     compare))
    app.add_handler(CommandHandler("recurring",   recurring))
    app.add_handler(CommandHandler("ai",          ai_finance))
    app.add_handler(CommandHandler("pdf",         pdf_cmd))
    app.add_handler(CommandHandler("calendar",    khmer_calendar_cmd))
    app.add_handler(CommandHandler("translate",   translate_cmd))
    app.add_handler(CommandHandler("write",       write_cmd))
    app.add_handler(CommandHandler("summarize",   summarize_cmd))
    app.add_handler(CommandHandler("explain",     explain_cmd))
    app.add_handler(CommandHandler("ideas",       ideas_cmd))
    app.add_handler(CommandHandler("codehelp",    codehelp_cmd))
    app.add_handler(CommandHandler("ask",         ask_cmd))
    app.add_handler(CommandHandler("roast",       roast_cmd))
    app.add_handler(CommandHandler("stats",       stats))
    app.add_handler(CommandHandler("errorlogs",   error_logs_cmd))
    app.add_handler(CommandHandler("maintenance", maintenance_toggle))
    app.add_handler(CommandHandler("restart",     restart_info))

    # ── Admin commands (DB-aware) ──
    app.add_handler(CommandHandler("admin_help",   admin_help))
    app.add_handler(CommandHandler("botstats",     tg_botstats))
    app.add_handler(CommandHandler("ban",          tg_ban))
    app.add_handler(CommandHandler("unban",        tg_unban))
    app.add_handler(CommandHandler("userinfo",     tg_userinfo))
    app.add_handler(CommandHandler("sendmsg",      tg_sendmsg))
    app.add_handler(CommandHandler("deleteuser",   tg_deleteuser))
    app.add_handler(CommandHandler("setadmin",     tg_set_admin))
    app.add_handler(CommandHandler("removeadmin",  tg_remove_admin))
    app.add_handler(CommandHandler("topadmins",    tg_top_admins))
    app.add_handler(CommandHandler("usertop",      tg_usertop))
    app.add_handler(CommandHandler("recentusers",  tg_recent_users))
    app.add_handler(CommandHandler("dbstats",      tg_db_stats))

    app.add_handler(CallbackQueryHandler(image_style_callback,       pattern=r"^imgstyle\|"))
    app.add_handler(CallbackQueryHandler(reimagine_callback,         pattern=r"^reimagine\|"))
    app.add_handler(CallbackQueryHandler(upscale_pending_callback,   pattern=r"^upscale_pending$"))
    app.add_handler(CallbackQueryHandler(delete_note_callback,       pattern=r"^delnote\|"))
    app.add_handler(CallbackQueryHandler(note_callback,              pattern=r"^note_"))
    app.add_handler(CallbackQueryHandler(auto_pdf_extract_callback,  pattern=r"^pdf_auto_extract$"))
    app.add_handler(CallbackQueryHandler(pdf_callback,               pattern=r"^pdf_(text|image|extract)$"))
    app.add_handler(CallbackQueryHandler(translate_lang_callback,    pattern=r"^tl_"))
    app.add_handler(CallbackQueryHandler(write_format_callback,      pattern=r"^write_"))
    app.add_handler(CallbackQueryHandler(code_action_callback,       pattern=r"^code_"))
    app.add_handler(CallbackQueryHandler(ai_menu_callback,           pattern=r"^(menu_ai|ai_)"))
    app.add_handler(CallbackQueryHandler(khmer_calendar_callback,     pattern=r"^kcal_"))
    app.add_handler(CallbackQueryHandler(menu_callback,              pattern=r"^menu_|^cancel$"))

    # Auto-detect PDF files
    app.add_handler(MessageHandler(filters.Document.PDF, auto_pdf_detect))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    app.add_error_handler(error_handler)

    if app.job_queue:
        app.job_queue.run_repeating(send_reminders, interval=3600, first=60)
        logger.info("✅ Job queue: រំលឹករាល់ម៉ោង")

    return app


def create_flask_app(ptb_app):
    """បង្កើត Flask app ជាមួយ webhook route"""
    flask_app = Flask(__name__)

    # ── Register admin dashboard ──
    try:
        from dashboard import set_bot_app
        set_bot_app(ptb_app)
        register_dashboard(flask_app, super_admin_ids=ADMIN_IDS)
        logger.info("✅ Admin dashboard registered at /admin")
    except Exception as e:
        logger.warning(f"⚠️ Dashboard: {e}")

    # ✅ Health Check សម្រាប់ Render
    @flask_app.get("/ping")
    def ping():
        return "OK", 200

    # ✅ Root route
    @flask_app.get("/")
    def index():
        return "🤖 Bot is running!", 200

    @flask_app.post(WEBHOOK_PATH)
    def webhook():
        data = flask_request.get_json(force=True)
        asyncio.run_coroutine_threadsafe(
            ptb_app.process_update(Update.de_json(data, ptb_app.bot)),
            loop,
        )
        return "ok", 200

    return flask_app


loop = None


async def run_bot():
    global loop
    loop = asyncio.get_event_loop()

    logger.info("🤖 កំពុងចាប់ផ្តើម bot (Flask Webhook mode)...")

    ptb_app = build_app()
    await ptb_app.initialize()
    await ptb_app.start()

    # កំណត់ Webhook
    full_url = f"{WEBHOOK_URL}{WEBHOOK_PATH}"
    await ptb_app.bot.set_webhook(
        url=full_url,
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )
    logger.info(f"✅ Webhook: {full_url}")

    # បង្កើត Flask app
    flask_app = create_flask_app(ptb_app)

    # Run Flask នៅ thread ដាច់ដោយឡែក
    import threading
    t = threading.Thread(
        target=lambda: flask_app.run(host="0.0.0.0", port=PORT, use_reloader=False),
        daemon=True,
    )
    t.start()
    logger.info(f"✅ Flask server: port {PORT}")
    logger.info("✅ Bot កំពុងដំណើរការតាម Webhook រួចរាល់")

    await asyncio.Event().wait()  # run forever


def main():
    if not TOKEN:
        logger.error("❌ TOKEN មិនត្រូវបានកំណត់ទេ!")
        sys.exit(1)

    if not GROQ_API_KEY:
        logger.warning("⚠️ មិនមាន GROQ_API_KEY។")
    else:
        logger.info("✅ Groq AI: រួចរាល់")

    if not ADMIN_IDS:
        logger.warning("⚠️ មិនមាន ADMIN_IDS។")
    else:
        logger.info(f"✅ អ្នកគ្រប់គ្រង: {ADMIN_IDS}")

    init_db()
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()