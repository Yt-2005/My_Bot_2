"""
database.py — Supabase (PostgreSQL) database layer
រក្សាទុក data ជារៀងរហូត — មិនបាត់នៅពេល Render redeploy

Required env vars:
    SUPABASE_DB_URL  →  postgresql://postgres:[PASSWORD]@db.[PROJECT].supabase.co:5432/postgres
    (or set SUPABASE_URL + SUPABASE_KEY for the REST client fallback)
"""

import os
import logging
import psycopg

from contextlib import contextmanager
from datetime import datetime

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# CONNECTION
# ─────────────────────────────────────────────

# ដាក់នៅក្នុង .env / Render environment:
# SUPABASE_DB_URL=postgresql://postgres:[PASSWORD]@db.vbfnuuszererwamxfwao.supabase.co:5432/postgres
DATABASE_URL = os.environ.get(
    "SUPABASE_DB_URL",
    os.environ.get("DATABASE_URL", "")
)


@contextmanager
def get_conn():
    """Context manager for safe PostgreSQL connections."""
    if not DATABASE_URL:
        raise RuntimeError("❌ SUPABASE_DB_URL មិនត្រូវបានកំណត់!")
    conn = psycopg.connect(DATABASE_URL, row_factory=psycopg.rows.dict_row)
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"DB error: {e}")
        raise
    finally:
        conn.close()


# ─────────────────────────────────────────────
# INIT — CREATE TABLES (run once on startup)
# ─────────────────────────────────────────────

def init_db():
    """Create all tables if they don't exist."""
    with get_conn() as conn:
        c = conn.cursor()

        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id        BIGINT PRIMARY KEY,
                username       TEXT DEFAULT '',
                language       TEXT DEFAULT 'km',
                pin            TEXT,
                budget         REAL DEFAULT 0,
                daily_reminder INTEGER DEFAULT 0,
                reminder_time  TEXT DEFAULT '',
                created_at     TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id           SERIAL PRIMARY KEY,
                user_id      BIGINT,
                category     TEXT,
                amount       REAL,
                note         TEXT,
                tag          TEXT DEFAULT '',
                receipt      TEXT DEFAULT '',
                is_recurring INTEGER DEFAULT 0,
                interval     TEXT DEFAULT '',
                date         DATE DEFAULT CURRENT_DATE,
                created_at   TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id         SERIAL PRIMARY KEY,
                user_id    BIGINT,
                content    TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS chat_memory (
                id         SERIAL PRIMARY KEY,
                user_id    BIGINT,
                role       TEXT,
                content    TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS error_logs (
                id         SERIAL PRIMARY KEY,
                user_id    BIGINT,
                error      TEXT,
                context    TEXT DEFAULT '',
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS admin_levels (
                user_id   BIGINT PRIMARY KEY,
                username  TEXT DEFAULT '',
                level     TEXT NOT NULL DEFAULT 'moderator',
                added_by  BIGINT,
                added_at  TIMESTAMPTZ DEFAULT NOW()
            )
        """)

    logger.info("✅ Supabase DB: tables initialized")


# ─────────────────────────────────────────────
# USER FUNCTIONS
# ─────────────────────────────────────────────

def ensure_user(user_id: int, username: str = ""):
    with get_conn() as conn:
        conn.cursor().execute("""
            INSERT INTO users (user_id, username)
            VALUES (%s, %s)
            ON CONFLICT (user_id) DO NOTHING
        """, (user_id, username))


def get_user(user_id: int):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
        row = c.fetchone()
        return dict(row) if row else None


def set_language(user_id: int, lang: str):
    with get_conn() as conn:
        conn.cursor().execute(
            "UPDATE users SET language = %s WHERE user_id = %s", (lang, user_id)
        )


def get_language(user_id: int) -> str:
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT language FROM users WHERE user_id = %s", (user_id,))
        row = c.fetchone()
        return row["language"] if row else "km"


def set_pin(user_id: int, pin: str):
    with get_conn() as conn:
        conn.cursor().execute(
            "UPDATE users SET pin = %s WHERE user_id = %s", (pin, user_id)
        )


def get_pin(user_id: int):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT pin FROM users WHERE user_id = %s", (user_id,))
        row = c.fetchone()
        return row["pin"] if row else None


def set_budget(user_id: int, amount: float):
    with get_conn() as conn:
        conn.cursor().execute(
            "UPDATE users SET budget = %s WHERE user_id = %s", (amount, user_id)
        )


def get_budget(user_id: int) -> float:
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT budget FROM users WHERE user_id = %s", (user_id,))
        row = c.fetchone()
        return row["budget"] if row else 0


def set_reminder(user_id: int, enabled: bool, time_str: str = ""):
    with get_conn() as conn:
        conn.cursor().execute(
            "UPDATE users SET daily_reminder = %s, reminder_time = %s WHERE user_id = %s",
            (1 if enabled else 0, time_str, user_id)
        )


def count_users() -> int:
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) AS c FROM users")
        row = c.fetchone()
        return row["c"]


def get_all_user_ids() -> list:
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT user_id FROM users")
        return [r["user_id"] for r in c.fetchall()]


# ─────────────────────────────────────────────
# EXPENSE FUNCTIONS
# ─────────────────────────────────────────────

def add_expense(user_id, category, amount, note, tag="", receipt="", is_recurring=0, interval=""):
    with get_conn() as conn:
        conn.cursor().execute("""
            INSERT INTO expenses (user_id, category, amount, note, tag, receipt, is_recurring, interval)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (user_id, category, amount, note, tag, receipt, is_recurring, interval))


def delete_expense(expense_id: int, user_id: int):
    with get_conn() as conn:
        conn.cursor().execute(
            "DELETE FROM expenses WHERE id = %s AND user_id = %s", (expense_id, user_id)
        )


def get_today(user_id: int):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id, category, amount, note, tag
            FROM expenses
            WHERE user_id = %s AND date = CURRENT_DATE
        """, (user_id,))
        return [tuple(r.values()) for r in c.fetchall()]


def get_monthly(user_id: int, ym: str = None):
    if not ym:
        ym = datetime.now().strftime("%Y-%m")
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT category, SUM(amount)
            FROM expenses
            WHERE user_id = %s AND TO_CHAR(date, 'YYYY-MM') = %s
            GROUP BY category
        """, (user_id, ym))
        return [tuple(r.values()) for r in c.fetchall()]


def get_monthly_total(user_id: int, ym: str = None) -> float:
    if not ym:
        ym = datetime.now().strftime("%Y-%m")
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT COALESCE(SUM(amount), 0) AS total
            FROM expenses
            WHERE user_id = %s AND TO_CHAR(date, 'YYYY-MM') = %s
        """, (user_id, ym))
        return c.fetchone()["total"]


def get_by_date(user_id: int, date_str: str):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id, category, amount, note, tag
            FROM expenses
            WHERE user_id = %s AND date = %s
        """, (user_id, date_str))
        return [tuple(r.values()) for r in c.fetchall()]


def get_by_tag(user_id: int, tag: str):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id, category, amount, note, date
            FROM expenses
            WHERE user_id = %s AND tag ILIKE %s
        """, (user_id, f"%{tag}%"))
        return [tuple(r.values()) for r in c.fetchall()]


def get_recurring(user_id: int):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT category, amount, note, interval
            FROM expenses
            WHERE user_id = %s AND is_recurring = 1
        """, (user_id,))
        return [tuple(r.values()) for r in c.fetchall()]


# ─────────────────────────────────────────────
# NOTES FUNCTIONS
# ─────────────────────────────────────────────

def add_note(user_id: int, content: str) -> int:
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO notes (user_id, content) VALUES (%s, %s) RETURNING id",
            (user_id, content)
        )
        return c.fetchone()["id"]


def get_notes(user_id: int) -> list:
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id, content, created_at
            FROM notes
            WHERE user_id = %s
            ORDER BY created_at DESC
        """, (user_id,))
        return [dict(r) for r in c.fetchall()]


def delete_note(note_id: int, user_id: int) -> bool:
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "DELETE FROM notes WHERE id = %s AND user_id = %s", (note_id, user_id)
        )
        return c.rowcount > 0


def count_notes(user_id: int) -> int:
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) AS c FROM notes WHERE user_id = %s", (user_id,))
        return c.fetchone()["c"]


# ─────────────────────────────────────────────
# CHAT MEMORY FUNCTIONS
# ─────────────────────────────────────────────

def save_chat_message(user_id: int, role: str, content: str):
    with get_conn() as conn:
        conn.cursor().execute(
            "INSERT INTO chat_memory (user_id, role, content) VALUES (%s, %s, %s)",
            (user_id, role, content)
        )


def get_chat_history(user_id: int, limit: int = 10) -> list:
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT role, content FROM (
                SELECT role, content, created_at
                FROM chat_memory
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            ) sub
            ORDER BY created_at ASC
        """, (user_id, limit))
        return [{"role": r["role"], "content": r["content"]} for r in c.fetchall()]


def clear_chat_history(user_id: int):
    with get_conn() as conn:
        conn.cursor().execute(
            "DELETE FROM chat_memory WHERE user_id = %s", (user_id,)
        )


# ─────────────────────────────────────────────
# ERROR LOG FUNCTIONS
# ─────────────────────────────────────────────

def log_error(user_id: int, error: str, context: str = ""):
    with get_conn() as conn:
        conn.cursor().execute(
            "INSERT INTO error_logs (user_id, error, context) VALUES (%s, %s, %s)",
            (user_id, error[:1000], context[:500])
        )


def get_recent_errors(limit: int = 20) -> list:
    with get_conn() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT * FROM error_logs ORDER BY created_at DESC LIMIT %s", (limit,)
        )
        return [dict(r) for r in c.fetchall()]