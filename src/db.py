"""
database/db.py — SQLite database layer
Handles users, notes, chat memory, and expense data
"""

import sqlite3
import logging
from datetime import datetime
from contextlib import contextmanager

logger = logging.getLogger(__name__)

DB_PATH = "bot_data.db"


# ─────────────────────────────────────────────
# CONNECTION HELPER
# ─────────────────────────────────────────────

@contextmanager
def get_conn():
    """Context manager for safe database connections."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
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
# INIT — CREATE TABLES
# ─────────────────────────────────────────────

def init_db():
    """Create all tables if they don't exist."""
    with get_conn() as conn:
        c = conn.cursor()

        # Users table
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT,
                language    TEXT    DEFAULT 'km',
                pin         TEXT,
                budget      REAL    DEFAULT 0,
                daily_reminder INTEGER DEFAULT 0,
                reminder_time  TEXT,
                created_at  TEXT    DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Expenses table (kept from original)
        c.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER,
                category    TEXT,
                amount      REAL,
                note        TEXT,
                tag         TEXT,
                receipt     TEXT,
                is_recurring INTEGER DEFAULT 0,
                interval    TEXT,
                date        TEXT    DEFAULT (date('now')),
                created_at  TEXT    DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Notes table (NEW)
        c.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER,
                content     TEXT    NOT NULL,
                created_at  TEXT    DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # AI chat memory table (NEW)
        c.execute("""
            CREATE TABLE IF NOT EXISTS chat_memory (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER,
                role        TEXT,
                content     TEXT,
                created_at  TEXT    DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Error logs table (NEW)
        c.execute("""
            CREATE TABLE IF NOT EXISTS error_logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER,
                error       TEXT,
                context     TEXT,
                created_at  TEXT    DEFAULT CURRENT_TIMESTAMP
            )
        """)

    logger.info("✅ Database initialized")


# ─────────────────────────────────────────────
# USER FUNCTIONS
# ─────────────────────────────────────────────

def ensure_user(user_id: int, username: str = ""):
    """Create user if not exists."""
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
            (user_id, username)
        )


def get_user(user_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def set_language(user_id: int, lang: str):
    with get_conn() as conn:
        conn.execute("UPDATE users SET language = ? WHERE user_id = ?", (lang, user_id))


def get_language(user_id: int) -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT language FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return row["language"] if row else "km"


def set_pin(user_id: int, pin: str):
    with get_conn() as conn:
        conn.execute("UPDATE users SET pin = ? WHERE user_id = ?", (pin, user_id))


def get_pin(user_id: int) -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT pin FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return row["pin"] if row else None


def set_budget(user_id: int, amount: float):
    with get_conn() as conn:
        conn.execute("UPDATE users SET budget = ? WHERE user_id = ?", (amount, user_id))


def get_budget(user_id: int) -> float:
    with get_conn() as conn:
        row = conn.execute("SELECT budget FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return row["budget"] if row else 0


def set_reminder(user_id: int, enabled: bool, time_str: str = ""):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET daily_reminder = ?, reminder_time = ? WHERE user_id = ?",
            (1 if enabled else 0, time_str, user_id)
        )


def count_users() -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()
        return row["c"]


def get_all_user_ids() -> list:
    with get_conn() as conn:
        rows = conn.execute("SELECT user_id FROM users").fetchall()
        return [r["user_id"] for r in rows]


# ─────────────────────────────────────────────
# EXPENSE FUNCTIONS (kept from original)
# ─────────────────────────────────────────────

def add_expense(user_id, category, amount, note, tag="", receipt="", is_recurring=0, interval=""):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO expenses
               (user_id, category, amount, note, tag, receipt, is_recurring, interval)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, category, amount, note, tag, receipt, is_recurring, interval)
        )


def delete_expense(expense_id: int, user_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM expenses WHERE id = ? AND user_id = ?", (expense_id, user_id))


def get_today(user_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, category, amount, note, tag FROM expenses WHERE user_id=? AND date=date('now')",
            (user_id,)
        ).fetchall()
        return [tuple(r) for r in rows]


def get_monthly(user_id: int, ym: str = None):
    if not ym:
        ym = datetime.now().strftime("%Y-%m")
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT category, SUM(amount) FROM expenses WHERE user_id=? AND date LIKE ? GROUP BY category",
            (user_id, f"{ym}%")
        ).fetchall()
        return [tuple(r) for r in rows]


def get_monthly_total(user_id: int, ym: str = None) -> float:
    if not ym:
        ym = datetime.now().strftime("%Y-%m")
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM expenses WHERE user_id=? AND date LIKE ?",
            (user_id, f"{ym}%")
        ).fetchone()
        return row[0]


def get_by_date(user_id: int, date_str: str):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, category, amount, note, tag FROM expenses WHERE user_id=? AND date=?",
            (user_id, date_str)
        ).fetchall()
        return [tuple(r) for r in rows]


def get_by_tag(user_id: int, tag: str):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, category, amount, note, date FROM expenses WHERE user_id=? AND tag LIKE ?",
            (user_id, f"%{tag}%")
        ).fetchall()
        return [tuple(r) for r in rows]


def get_recurring(user_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT category, amount, note, interval FROM expenses WHERE user_id=? AND is_recurring=1",
            (user_id,)
        ).fetchall()
        return [tuple(r) for r in rows]


# ─────────────────────────────────────────────
# NOTES FUNCTIONS (NEW)
# ─────────────────────────────────────────────

def add_note(user_id: int, content: str) -> int:
    """Add a note for a user. Returns the new note ID."""
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO notes (user_id, content) VALUES (?, ?)",
            (user_id, content)
        )
        return cur.lastrowid


def get_notes(user_id: int) -> list:
    """Get all notes for a user."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, content, created_at FROM notes WHERE user_id=? ORDER BY created_at DESC",
            (user_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def delete_note(note_id: int, user_id: int) -> bool:
    """Delete a note by ID. Returns True if deleted."""
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM notes WHERE id=? AND user_id=?",
            (note_id, user_id)
        )
        return cur.rowcount > 0


def count_notes(user_id: int) -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) as c FROM notes WHERE user_id=?", (user_id,)).fetchone()
        return row["c"]


# ─────────────────────────────────────────────
# CHAT MEMORY FUNCTIONS (NEW)
# ─────────────────────────────────────────────

def save_chat_message(user_id: int, role: str, content: str):
    """Save a chat message to memory."""
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO chat_memory (user_id, role, content) VALUES (?, ?, ?)",
            (user_id, role, content)
        )


def get_chat_history(user_id: int, limit: int = 10) -> list:
    """Get recent chat history for a user."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT role, content FROM chat_memory
               WHERE user_id=?
               ORDER BY created_at DESC LIMIT ?""",
            (user_id, limit)
        ).fetchall()
        # Return in chronological order
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def clear_chat_history(user_id: int):
    """Clear all chat memory for a user."""
    with get_conn() as conn:
        conn.execute("DELETE FROM chat_memory WHERE user_id=?", (user_id,))


# ─────────────────────────────────────────────
# ERROR LOG FUNCTIONS (NEW)
# ─────────────────────────────────────────────

def log_error(user_id: int, error: str, context: str = ""):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO error_logs (user_id, error, context) VALUES (?, ?, ?)",
            (user_id, error[:1000], context[:500])
        )


def get_recent_errors(limit: int = 20) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM error_logs ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
