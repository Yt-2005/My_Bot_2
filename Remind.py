# remind.py — Cron Job សម្រាប់ផ្ញើការរំលឹក + Ping Uptime
# Run នៅ Render Cron Job: python remind.py

import asyncio
import sqlite3
import logging
import os
import aiohttp
from datetime import datetime
from telegram import Bot
from config import TOKEN

# log តិចបំផុត ដើម្បីជៀសវាង "output too large"
logging.basicConfig(
    level=logging.ERROR,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ── កំណត់ URL សម្រាប់ ping ──
# ដាក់ URL របស់ Render service អ្នកនៅ Environment Variable
# ឬ កែផ្ទាល់នៅទីនេះ
UPTIME_URL = os.getenv("UPTIME_URL", "https://my-bot-2-4ayy.onrender.com/ping")


async def ping_uptime():
    """Ping health endpoint ដើម្បីរក្សា service ឱ្យដំណើរការ"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(UPTIME_URL, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    print(f"🏓 Uptime ping: OK ({resp.status})")
                else:
                    print(f"⚠️ Uptime ping: {resp.status}")
    except Exception as e:
        logger.error(f"Uptime ping បរាជ័យ: {e}")


async def send_reminders():
    """ផ្ញើការរំលឹករាល់ថ្ងៃទៅ users"""
    hour = datetime.now().strftime("%H")
    bot = Bot(token=TOKEN)

    try:
        conn = sqlite3.connect("bot_data.db")
        c = conn.cursor()
        c.execute(
            "SELECT user_id FROM users WHERE daily_reminder=1 AND reminder_time LIKE ?",
            (f"{hour}:%",)
        )
        rows = c.fetchall()
        conn.close()

        if not rows:
            print("📭 គ្មាន user ត្រូវផ្ញើរំលឹក")
            return

        sent = 0
        failed = 0

        for (uid,) in rows:
            try:
                await bot.send_message(
                    uid,
                    "⏰ *Daily Reminder!*\n\nDon't forget to log your expenses today! 💰\n\nUse /add to record a new expense.",
                    parse_mode="Markdown"
                )
                sent += 1
            except Exception as e:
                failed += 1
                logger.error(f"ផ្ញើបរាជ័យ {uid}: {e}")

        print(f"✅ ផ្ញើជោគជ័យ: {sent} | ❌ បរាជ័យ: {failed}")

    except Exception as e:
        logger.error(f"កំហុស DB: {e}")

    finally:
        await bot.close()


async def main():
    # រត់ ping និង reminder ក្នុងពេលតែមួយ
    await asyncio.gather(
        ping_uptime(),
        send_reminders(),
    )


if __name__ == "__main__":
    asyncio.run(main())