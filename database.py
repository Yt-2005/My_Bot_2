import os
import psycopg
from psycopg.rows import dict_row
import logging

logger = logging.getLogger(__name__)


def _get_db_url():
    return (
        os.environ.get("SUPABASE_DB_URL") or
        os.environ.get("DATABASE_URL") or
        os.environ.get("POSTGRES_URL") or
        os.environ.get("DB_URL") or
        ""
    )

def db():
    url = _get_db_url()
    if not url:
        raise RuntimeError("No DB URL set. Add SUPABASE_DB_URL in Render environment.")
    return psycopg.connect(url, row_factory=dict_row)


def init_db():
    commands = [
        """CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY, username TEXT,
            language TEXT DEFAULT 'en', budget REAL DEFAULT 0, pin TEXT,
            daily_reminder BOOLEAN DEFAULT FALSE, reminder_time TEXT DEFAULT '09:00',
            created_at TIMESTAMPTZ DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS notes (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
            content TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS expenses (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
            category TEXT, amount REAL, note TEXT, tag TEXT, date DATE
        )""",
        """CREATE TABLE IF NOT EXISTS error_logs (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id) ON DELETE SET NULL,
            error_text TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS bot_admins (
            user_id BIGINT PRIMARY KEY, username TEXT,
            role TEXT NOT NULL DEFAULT 'admin', note TEXT,
            added_at TIMESTAMPTZ DEFAULT NOW(), added_by TEXT DEFAULT 'dashboard'
        )""",
        """CREATE TABLE IF NOT EXISTS banned_users (
            user_id BIGINT PRIMARY KEY, banned_at TIMESTAMPTZ DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS chat_memory (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
            message TEXT, is_bot BOOLEAN, created_at TIMESTAMPTZ DEFAULT NOW()
        )""",
    ]
    migrations = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS pin TEXT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS language TEXT DEFAULT 'en'",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS budget REAL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_reminder BOOLEAN DEFAULT FALSE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS reminder_time TEXT DEFAULT '09:00'",
    ]
    with db() as conn:
        with conn.cursor() as cur:
            for cmd in commands:
                try:
                    cur.execute(cmd)
                except Exception as e:
                    logger.warning(f"Table init: {e}")
            for mig in migrations:
                try:
                    cur.execute(mig)
                except Exception as e:
                    logger.warning(f"Migration: {e}")
            conn.commit()


def _safe_query(conn, sql, params=None):
    try:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        return cur.fetchall()
    except Exception as e:
        logger.warning(f"Query error: {e}")
        return []

def _safe_one(conn, sql, params=None):
    try:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        return cur.fetchone()
    except Exception as e:
        logger.warning(f"Query error: {e}")
        return None


# ── Users ──────────────────────────────────────────────────────────
def ensure_user(user_id, username=None):
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (user_id, username) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET username = COALESCE(EXCLUDED.username, users.username)",
            (user_id, username)
        )
        conn.commit()


# ── Notes ──────────────────────────────────────────────────────────
def add_note(user_id, content):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO notes (user_id, content) VALUES (%s, %s) RETURNING id", (user_id, content))
        note_id = cur.fetchone()['id']
        conn.commit()
        return note_id

def get_notes(user_id):
    with db() as conn:
        return _safe_query(conn, "SELECT id, content, created_at FROM notes WHERE user_id = %s ORDER BY created_at DESC", (user_id,))

def delete_note(note_id, user_id):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM notes WHERE id = %s AND user_id = %s", (note_id, user_id))
        deleted = cur.rowcount > 0
        conn.commit()
        return deleted

def count_notes(user_id):
    with db() as conn:
        result = _safe_one(conn, "SELECT COUNT(*) AS c FROM notes WHERE user_id = %s", (user_id,))
        return result['c'] if result else 0


# ── Error logging ──────────────────────────────────────────────────
def log_error(user_id, error_text):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO error_logs (user_id, error_text) VALUES (%s, %s)", (user_id, error_text))
        conn.commit()

def get_recent_errors(limit=20):
    with db() as conn:
        return _safe_query(conn, "SELECT id, user_id, error_text, created_at FROM error_logs ORDER BY created_at DESC LIMIT %s", (limit,))


# ── Reminders ──────────────────────────────────────────────────────
def send_reminders_db(hour):
    with db() as conn:
        rows = _safe_query(conn, "SELECT user_id FROM users WHERE daily_reminder = TRUE AND reminder_time = %s", (hour,))
        return [row['user_id'] for row in rows]


# ── User info ──────────────────────────────────────────────────────
def get_user_info(user_id):
    with db() as conn:
        row = _safe_one(conn, """
            SELECT u.user_id, u.username, u.language, u.budget, u.daily_reminder, u.reminder_time, u.created_at,
                   COALESCE(SUM(e.amount), 0) AS total_spent, COUNT(e.id) AS expense_count
            FROM users u LEFT JOIN expenses e ON u.user_id = e.user_id
            WHERE u.user_id = %s
            GROUP BY u.user_id, u.username, u.language, u.budget, u.daily_reminder, u.reminder_time, u.created_at
        """, (user_id,))
        if row:
            return {
                'user_id': row['user_id'], 'username': row['username'],
                'language': row['language'], 'budget': row['budget'],
                'daily_reminder': bool(row['daily_reminder']), 'reminder_time': row['reminder_time'],
                'created_at': row['created_at'],
                'total_spent': float(row['total_spent']), 'expense_count': row['expense_count'],
            }
        return None


# ── Admin ──────────────────────────────────────────────────────────
def ban_user(user_id):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO banned_users (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING", (user_id,))
        conn.commit()

def unban_user(user_id):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM banned_users WHERE user_id = %s", (user_id,))
        conn.commit()

def get_bot_stats():
    with db() as conn:
        return {
            'total_users':    _safe_one(conn, "SELECT COUNT(*) AS c FROM users")['c'],
            'new_today':      _safe_one(conn, "SELECT COUNT(*) AS c FROM users WHERE created_at::date = CURRENT_DATE")['c'],
            'total_spent':    _safe_one(conn, "SELECT COALESCE(SUM(amount), 0) AS c FROM expenses")['c'],
            'total_expenses': _safe_one(conn, "SELECT COUNT(*) AS c FROM expenses")['c'],
            'total_notes':    _safe_one(conn, "SELECT COUNT(*) AS c FROM notes")['c'],
            'errors':         _safe_one(conn, "SELECT COUNT(*) AS c FROM error_logs")['c'],
            'banned':         _safe_one(conn, "SELECT COUNT(*) AS c FROM banned_users")['c'],
            'active_30d':     _safe_one(conn, "SELECT COUNT(*) AS c FROM users WHERE created_at >= CURRENT_DATE - INTERVAL '30 days'")['c'],
        }

def count_users():
    with db() as conn:
        result = _safe_one(conn, "SELECT COUNT(*) AS c FROM users")
        return result['c'] if result else 0

def get_all_user_ids():
    with db() as conn:
        rows = _safe_query(conn, "SELECT user_id FROM users ORDER BY created_at")
        return [r['user_id'] for r in rows]

def get_conn():
    return db()


# ── Chat memory ────────────────────────────────────────────────────
def get_chat_history(user_id, limit=10):
    with db() as conn:
        rows = _safe_query(conn, "SELECT message, is_bot FROM chat_memory WHERE user_id = %s ORDER BY created_at DESC LIMIT %s", (user_id, limit))
    rows.reverse()
    return [{"role": "assistant" if r["is_bot"] else "user", "content": r["message"]} for r in rows]

def save_chat_message(user_id, role, content):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO chat_memory (user_id, message, is_bot) VALUES (%s, %s, %s)", (user_id, content, role == "assistant"))
        conn.commit()

def clear_chat_history(user_id):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM chat_memory WHERE user_id = %s", (user_id,))
        conn.commit()


# ── Expenses ───────────────────────────────────────────────────────
def add_expense(user_id, category, amount, note="", tag="", date=None):
    if date is None:
        from datetime import date as _d
        date = _d.today()
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO expenses (user_id, category, amount, note, tag, date) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (user_id, category, amount, note, tag, date)
        )
        expense_id = cur.fetchone()['id']
        conn.commit()
        return expense_id

def delete_expense(expense_id, user_id):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM expenses WHERE id = %s AND user_id = %s", (expense_id, user_id))
        deleted = cur.rowcount > 0
        conn.commit()
        return deleted

def get_today(user_id):
    with db() as conn:
        return _safe_query(conn, "SELECT id, category, amount, note, tag, date FROM expenses WHERE user_id = %s AND date = CURRENT_DATE ORDER BY id DESC", (user_id,))

def get_monthly(user_id, year=None, month=None):
    if year is None or month is None:
        from datetime import date as _d
        t = _d.today(); year, month = t.year, t.month
    with db() as conn:
        return _safe_query(conn, "SELECT id, category, amount, note, tag, date FROM expenses WHERE user_id = %s AND EXTRACT(YEAR FROM date) = %s AND EXTRACT(MONTH FROM date) = %s ORDER BY date DESC, id DESC", (user_id, year, month))

def get_monthly_total(user_id, year=None, month=None):
    if year is None or month is None:
        from datetime import date as _d
        t = _d.today(); year, month = t.year, t.month
    with db() as conn:
        result = _safe_one(conn, "SELECT COALESCE(SUM(amount), 0) AS total FROM expenses WHERE user_id = %s AND EXTRACT(YEAR FROM date) = %s AND EXTRACT(MONTH FROM date) = %s", (user_id, year, month))
        return float(result['total']) if result else 0.0

def get_by_date(user_id, target_date):
    with db() as conn:
        return _safe_query(conn, "SELECT id, category, amount, note, tag, date FROM expenses WHERE user_id = %s AND date = %s ORDER BY id DESC", (user_id, target_date))

def get_by_tag(user_id, tag):
    with db() as conn:
        return _safe_query(conn, "SELECT id, category, amount, note, tag, date FROM expenses WHERE user_id = %s AND tag = %s ORDER BY date DESC, id DESC", (user_id, tag))

def get_recurring(user_id):
    with db() as conn:
        return _safe_query(conn, "SELECT id, category, amount, note, tag, date FROM expenses WHERE user_id = %s AND tag = 'recurring' ORDER BY date DESC, id DESC", (user_id,))

def get_budget(user_id):
    with db() as conn:
        result = _safe_one(conn, "SELECT budget FROM users WHERE user_id = %s", (user_id,))
        return float(result['budget']) if result and result.get('budget') else 0.0

def set_budget(user_id, amount):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO users (user_id, budget) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET budget = EXCLUDED.budget", (user_id, amount))
        conn.commit()

def get_pin(user_id):
    with db() as conn:
        result = _safe_one(conn, "SELECT pin FROM users WHERE user_id = %s", (user_id,))
        return result.get('pin') if result else None

def get_language(user_id):
    with db() as conn:
        result = _safe_one(conn, "SELECT language FROM users WHERE user_id = %s", (user_id,))
        return (result.get('language') or 'en') if result else 'en'


# ── Settings ───────────────────────────────────────────────────────
def set_language(user_id, language):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO users (user_id, language) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET language = EXCLUDED.language", (user_id, language))
        conn.commit()

def set_pin(user_id, pin):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO users (user_id, pin) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET pin = EXCLUDED.pin", (user_id, pin))
        conn.commit()

def set_reminder(user_id, enabled, reminder_time="09:00"):
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (user_id, daily_reminder, reminder_time) VALUES (%s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET daily_reminder = EXCLUDED.daily_reminder, reminder_time = EXCLUDED.reminder_time",
            (user_id, enabled, reminder_time)
        )
        conn.commit()


# ── Compatibility ──────────────────────────────────────────────────
def set_bot_app(app):
    pass