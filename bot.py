"""
bot.py — Main entry point for the Telegram Bot
"""

import sys
import time
import logging
import asyncio

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
    CallbackQueryHandler, ConversationHandler, filters,
)
from telegram import Update
from telegram.ext import ContextTypes

from config import TOKEN, GROQ_API_KEY, ADMIN_IDS
from database import init_db
from web import start_health_server
import config as cfg

from handlers.core import start, help_cmd, cancel, clear_chat, menu_callback
from handlers.image_handler import (
    imagine_cmd, image_style_callback, reimagine_callback,
    upscale_cmd, upscale_photo_received, upscale_pending_callback,
    WAITING_FOR_UPSCALE_PHOTO,
)
from handlers.chat_handler import chat_cmd, chat_message, handle_text_message, CHATTING
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def send_reminders(ctx: ContextTypes.DEFAULT_TYPE):
    import sqlite3
    from datetime import datetime
    hour = datetime.now().strftime("%H")
    try:
        conn = sqlite3.connect("bot_data.db")
        c = conn.cursor()
        c.execute(
            "SELECT user_id FROM users WHERE daily_reminder=1 AND reminder_time LIKE ?",
            (f"{hour}:%",)
        )
        rows = c.fetchall()
        conn.close()
        for (uid,) in rows:
            try:
                await ctx.bot.send_message(
                    uid,
                    "⏰ *Daily Reminder!*\n\nDon't forget to log your expenses today! 💰\n\nUse /add to record a new expense.",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.warning(f"Reminder failed for {uid}: {e}")
    except Exception as e:
        logger.error(f"send_reminders error: {e}")


async def error_handler(update: object, ctx: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Unhandled exception: {ctx.error}", exc_info=ctx.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "❌ *Something went wrong.* Please try again or use /start.",
                parse_mode="Markdown"
            )
        except Exception:
            pass


# ── Called once after app is initialized, before polling starts ──
async def post_init(application):
    """Clear any existing webhook and pending updates from previous instance."""
    try:
        await application.bot.delete_webhook(drop_pending_updates=True)
        logger.info("✅ Webhook cleared, pending updates dropped")
    except Exception as e:
        logger.warning(f"post_init cleanup warning: {e}")


def build_app():
    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .post_init(post_init)   # ← clears old instance's polling lock
        .build()
    )

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

    # Register conversations
    for conv in [chat_conv, upscale_conv, notes_conv, add_conv, budget_conv,
                 date_conv, tag_conv, delete_conv, lang_conv, setpin_conv,
                 reminder_conv, broadcast_conv]:
        app.add_handler(conv)

    # Standalone commands
    app.add_handler(CommandHandler("start",       start))
    app.add_handler(CommandHandler("help",        help_cmd))
    app.add_handler(CommandHandler("clearchat",   clear_chat))
    app.add_handler(CommandHandler("imagine",     imagine_cmd))
    app.add_handler(CommandHandler("today",       today))
    app.add_handler(CommandHandler("month",       month))
    app.add_handler(CommandHandler("compare",     compare))
    app.add_handler(CommandHandler("recurring",   recurring))
    app.add_handler(CommandHandler("ai",          ai_finance))
    app.add_handler(CommandHandler("stats",       stats))
    app.add_handler(CommandHandler("errorlogs",   error_logs_cmd))
    app.add_handler(CommandHandler("maintenance", maintenance_toggle))
    app.add_handler(CommandHandler("restart",     restart_info))

    # Callbacks
    app.add_handler(CallbackQueryHandler(image_style_callback,     pattern=r"^imgstyle\|"))
    app.add_handler(CallbackQueryHandler(reimagine_callback,       pattern=r"^reimagine\|"))
    app.add_handler(CallbackQueryHandler(upscale_pending_callback, pattern=r"^upscale_pending$"))
    app.add_handler(CallbackQueryHandler(delete_note_callback,     pattern=r"^delnote\|"))
    app.add_handler(CallbackQueryHandler(note_callback,            pattern=r"^note_"))
    app.add_handler(CallbackQueryHandler(menu_callback,            pattern=r"^menu_|^cancel$"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    app.add_error_handler(error_handler)

    if app.job_queue:
        app.job_queue.run_repeating(send_reminders, interval=3600, first=60)
        logger.info("✅ Job queue: daily reminders scheduled")

    return app


async def run_bot():
    logger.info("🤖 Starting bot...")

    # Give the previous Render instance time to fully shut down
    # before we start polling, avoiding the Conflict error
    logger.info("⏳ Waiting 5s for previous instance to release polling lock...")
    await asyncio.sleep(5)

    app = build_app()
    await app.initialize()   # triggers post_init → delete_webhook
    await app.start()
    await app.updater.start_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )
    logger.info("✅ Bot is polling")
    await asyncio.Event().wait()  # run forever
    await app.updater.stop()
    await app.stop()
    await app.shutdown()


def main():
    if not TOKEN:
        logger.error("❌ TOKEN is not set!")
        sys.exit(1)

    if not GROQ_API_KEY:
        logger.warning("⚠️  No GROQ_API_KEY found. AI features disabled.")
    else:
        logger.info("✅ Groq AI: configured")

    if not ADMIN_IDS:
        logger.warning("⚠️  No ADMIN_IDS set.")
    else:
        logger.info(f"✅ Admins: {ADMIN_IDS}")

    from web import start_health_server
    from config import PORT
    start_health_server(PORT)
    init_db()

    asyncio.run(run_bot())


if __name__ == "__main__":
    main()