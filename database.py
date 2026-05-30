import os
import psycopg
from psycopg.rows import dict_row
import logging

logger = logging.getLogger(__name__)

# ── DB — reads all possible env var names (same as dashboard.py) ────
def _get_db_url():
    return (
        os.environ.get("SUPABASE_DB_URL") or
        os.environ.get("DATABASE_URL") or
        os.environ.get("POSTGRES_URL") or
        os.environ.get("DB_URL") or
        ""
    )

def db():
    """Fresh connection — always reads env var at call time."""
    url = _get_db_url()
    if not url:
        raise RuntimeError("❌ No DB URL! Set SUPABASE_DB_URL in Render environment.")
    return psycopg.connect(url, row_factory=dict_row)

# ── Initialize database tables ─────────────────────────────────────
def init_db():
    """Create tables if they don't exist."""
    commands = [
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            language TEXT,
            budget REAL DEFAULT 0,
            pin TEXT,
            daily_reminder BOOLEAN DEFAULT FALSE,
            reminder_time TEXT DEFAULT '09:00',
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS notes (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
            content TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS expenses (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
            category TEXT,
            amount REAL,
            note TEXT,
            tag TEXT,
            date DATE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS error_logs (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id) ON DELETE SET NULL,
            error_text TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS bot_admins (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            role TEXT NOT NULL DEFAULT 'admin',
            note TEXT,
            added_at TIMESTAMPTZ DEFAULT NOW(),
            added_by TEXT DEFAULT 'dashboard'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS banned_users (
            user_id BIGINT PRIMARY KEY,
            banned_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS chat_memory (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
            message TEXT,
            is_bot BOOLEAN,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
    ]
    # Migrations for columns added after initial deploy
    migrations = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS pin TEXT",
    ]

    with db() as conn:
        with conn.cursor() as cur:
            for command in commands:
                try:
                    cur.execute(command)
                except Exception as e:
                    logger.warning(f"Init table error (maybe already exists): {e}")
            for migration in migrations:
                try:
                    cur.execute(migration)
                except Exception as e:
                    logger.warning(f"Migration error: {e}")
            conn.commit()

# ── Helper functions ───────────────────────────────────────────────
def _safe_query(conn, sql, params=None):
    """Execute a query safely, return rows or []."""
    try:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        return cur.fetchall()
    except Exception as e:
        logger.warning(f"Query error: {e}")
        return []

def _safe_one(conn, sql, params=None):
    """Execute a query safely, return one row or None."""
    try:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        return cur.fetchone()
    except Exception as e:
        logger.warning(f"Query error: {e}")
        return None

# ── User functions ─────────────────────────────────────────────────
def ensure_user(user_id):
    """Ensure a user exists in the database."""
    with db() as conn:
        # Try to insert, but ignore if already exists (using ON CONFLICT)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO users (user_id) VALUES (%s)
            ON CONFLICT (user_id) DO NOTHING
            """,
            (user_id,)
        )
        conn.commit()

# ── Note functions ─────────────────────────────────────────────────
def add_note(user_id, content):
    """Add a note for the user and return the note ID."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO notes (user_id, content) VALUES (%s, %s)
            RETURNING id
            """,
            (user_id, content)
        )
        note_id = cur.fetchone()['id']
        conn.commit()
        return note_id

def get_notes(user_id):
    """Get all notes for a user, ordered by newest first."""
    with db() as conn:
        return _safe_query(
            conn,
            """
            SELECT id, content, created_at
            FROM notes
            WHERE user_id = %s
            ORDER BY created_at DESC
            """,
            (user_id,)
        )

def delete_note(note_id, user_id):
    """Delete a note if it belongs to the user. Returns True if deleted."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            DELETE FROM notes
            WHERE id = %s AND user_id = %s
            """,
            (note_id, user_id)
        )
        deleted = cur.rowcount > 0
        conn.commit()
        return deleted

def count_notes(user_id):
    """Count the number of notes for a user."""
    with db() as conn:
        result = _safe_one(
            conn,
            """
            SELECT COUNT(*) AS c FROM notes WHERE user_id = %s
            """,
            (user_id,)
        )
        return result['c'] if result else 0

# ── Error logging ─────────────────────────────────────────────────
def log_error(user_id, error_text):
    """Log an error to the error_logs table."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO error_logs (user_id, error_text) VALUES (%s, %s)
            """,
            (user_id, error_text)
        )
        conn.commit()

# ── Reminder functions ─────────────────────────────────────────────
def send_reminders_db(hour):
    """Return list of user IDs that have reminders enabled for the given hour."""
    with db() as conn:
        rows = _safe_query(
            conn,
            """
            SELECT user_id
            FROM users
            WHERE daily_reminder = TRUE
              AND reminder_time = %s
            """,
            (hour,)
        )
        return [row['user_id'] for row in rows]

# ── User info ─────────────────────────────────────────────────────
def get_user_info(user_id):
    """Get detailed information about a user."""
    with db() as conn:
        row = _safe_one(
            conn,
            """
            SELECT user_id, username, language, budget, daily_reminder, reminder_time,
                   COALESCE(SUM(e.amount), 0) AS total_spent,
                   COUNT(e.id) AS expense_count
            FROM users u
            LEFT JOIN expenses e ON u.user_id = e.user_id
            WHERE u.user_id = %s
            GROUP BY u.user_id, u.username, u.language, u.budget, u.daily_reminder, u.reminder_time
            """,
            (user_id,)
        )
        if row:
            return {
                'user_id': row['user_id'],
                'username': row['username'],
                'language': row['language'],
                'budget': row['budget'],
                'daily_reminder': bool(row['daily_reminder']),
                'reminder_time': row['reminder_time'],
                'total_spent': float(row['total_spent']),
                'expense_count': row['expense_count']
            }
        return None

# ── Admin functions ───────────────────────────────────────────────
def ban_user(user_id):
    """Ban a user."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO banned_users (user_id) VALUES (%s)
            ON CONFLICT (user_id) DO NOTHING
            """,
            (user_id,)
        )
        conn.commit()

def unban_user(user_id):
    """Unban a user."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            DELETE FROM banned_users WHERE user_id = %s
            """,
            (user_id,)
        )
        conn.commit()

def get_bot_stats():
    """Get bot statistics."""
    with db() as conn:
        stats = {}
        # Total users
        stats['total_users'] = _safe_one(conn, "SELECT COUNT(*) AS c FROM users")['c']
        # New today
        stats['new_today'] = _safe_one(
            conn, "SELECT COUNT(*) AS c FROM users WHERE created_at::date = CURRENT_DATE"
        )['c']
        # Total spent
        stats['total_spent'] = _safe_one(
            conn, "SELECT COALESCE(SUM(amount), 0) AS c FROM expenses"
        )['c']
        # Total notes
        stats['total_notes'] = _safe_one(conn, "SELECT COUNT(*) AS c FROM notes")['c']
        # Total errors
        stats['errors'] = _safe_one(conn, "SELECT COUNT(*) AS c FROM error_logs")['c']
        # Total banned
        stats['banned'] = _safe_one(conn, "SELECT COUNT(*) AS c FROM banned_users")['c']
        # Active users (last 30 days)
        stats['active_30d'] = _safe_one(
            conn,
            "SELECT COUNT(*) AS c FROM users WHERE created_at >= CURRENT_DATE - INTERVAL '30 days'"
        )['c']
        return stats

def get_conn():
    """Return a database connection (for use in admin functions that need raw connection)."""
    return db()

# ── Chat memory functions ──────────────────────────────────────────
def get_chat_history(user_id, limit=10):
    """Get recent chat history for a user as a list of {role, content} dicts."""
    with db() as conn:
        rows = _safe_query(
            conn,
            """
            SELECT message, is_bot
            FROM chat_memory
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (user_id, limit),
        )
    # Rows come newest-first, reverse to chronological order
    rows.reverse()
    return [
        {"role": "assistant" if r["is_bot"] else "user", "content": r["message"]}
        for r in rows
    ]


def save_chat_message(user_id, role, content):
    """Save a chat message to memory. role should be 'user' or 'assistant'."""
    is_bot = role == "assistant"
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO chat_memory (user_id, message, is_bot)
            VALUES (%s, %s, %s)
            """,
            (user_id, content, is_bot),
        )
        conn.commit()


def clear_chat_history(user_id):
    """Delete all chat memory for a user."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM chat_memory WHERE user_id = %s",
            (user_id,),
        )
        conn.commit()


# ── Expense functions ─────────────────────────────────────────────
def add_expense(user_id, category, amount, note="", tag="", date=None):
    """Add an expense record. Returns the new expense ID."""
    if date is None:
        from datetime import date as date_type
        date = date_type.today()
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO expenses (user_id, category, amount, note, tag, date)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (user_id, category, amount, note, tag, date)
        )
        expense_id = cur.fetchone()['id']
        conn.commit()
        return expense_id

def delete_expense(expense_id, user_id):
    """Delete an expense if it belongs to the user. Returns True if deleted."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            DELETE FROM expenses
            WHERE id = %s AND user_id = %s
            """,
            (expense_id, user_id)
        )
        deleted = cur.rowcount > 0
        conn.commit()
        return deleted

def get_today(user_id):
    """Get all expenses for the user for today."""
    with db() as conn:
        return _safe_query(
            conn,
            """
            SELECT id, category, amount, note, tag, date
            FROM expenses
            WHERE user_id = %s AND date = CURRENT_DATE
            ORDER BY id DESC
            """,
            (user_id,)
        )

def get_monthly(user_id, year=None, month=None):
    """Get all expenses for the user for a given month (defaults to current)."""
    if year is None or month is None:
        from datetime import date
        today = date.today()
        year, month = today.year, today.month
    with db() as conn:
        return _safe_query(
            conn,
            """
            SELECT id, category, amount, note, tag, date
            FROM expenses
            WHERE user_id = %s
              AND EXTRACT(YEAR FROM date) = %s
              AND EXTRACT(MONTH FROM date) = %s
            ORDER BY date DESC, id DESC
            """,
            (user_id, year, month)
        )

def get_monthly_total(user_id, year=None, month=None):
    """Get total amount spent for a given month (defaults to current)."""
    if year is None or month is None:
        from datetime import date
        today = date.today()
        year, month = today.year, today.month
    with db() as conn:
        result = _safe_one(
            conn,
            """
            SELECT COALESCE(SUM(amount), 0) AS total
            FROM expenses
            WHERE user_id = %s
              AND EXTRACT(YEAR FROM date) = %s
              AND EXTRACT(MONTH FROM date) = %s
            """,
            (user_id, year, month)
        )
        return float(result['total']) if result else 0.0

def get_by_date(user_id, target_date):
    """Get all expenses for a specific date."""
    with db() as conn:
        return _safe_query(
            conn,
            """
            SELECT id, category, amount, note, tag, date
            FROM expenses
            WHERE user_id = %s AND date = %s
            ORDER BY id DESC
            """,
            (user_id, target_date)
        )

def get_by_tag(user_id, tag):
    """Get all expenses for a specific tag."""
    with db() as conn:
        return _safe_query(
            conn,
            """
            SELECT id, category, amount, note, tag, date
            FROM expenses
            WHERE user_id = %s AND tag = %s
            ORDER BY date DESC, id DESC
            """,
            (user_id, tag)
        )

def get_recurring(user_id):
    """Get expenses tagged as 'recurring' for the user."""
    with db() as conn:
        return _safe_query(
            conn,
            """
            SELECT id, category, amount, note, tag, date
            FROM expenses
            WHERE user_id = %s AND tag = 'recurring'
            ORDER BY date DESC, id DESC
            """,
            (user_id,)
        )

def get_budget(user_id):
    """Get the budget for a user. Returns 0 if not set."""
    with db() as conn:
        result = _safe_one(
            conn,
            "SELECT budget FROM users WHERE user_id = %s",
            (user_id,)
        )
        return float(result['budget']) if result else 0.0

def set_budget(user_id, amount):
    """Set the monthly budget for a user."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO users (user_id, budget) VALUES (%s, %s)
            ON CONFLICT (user_id) DO UPDATE SET budget = EXCLUDED.budget
            """,
            (user_id, amount)
        )
        conn.commit()

def get_pin(user_id):
    """Get the PIN for a user (returns None if not set)."""
    with db() as conn:
        result = _safe_one(
            conn,
            "SELECT pin FROM users WHERE user_id = %s",
            (user_id,)
        )
        if result and 'pin' in result:
            return result.get('pin')
        return None

def get_language(user_id):
    """Get the language preference for a user (defaults to 'en')."""
    with db() as conn:
        result = _safe_one(
            conn,
            "SELECT language FROM users WHERE user_id = %s",
            (user_id,)
        )
        return result['language'] if result and result.get('language') else 'en'


# For compatibility with dashboard.py's db() function (if needed)
def set_bot_app(app):
    """Placeholder for compatibility."""
    pass

# ── Expense functions ─────────────────────────────────────────────
def add_expense(user_id, category, amount, note="", tag="", date=None):
    """Add an expense record. Returns the new expense ID."""
    if date is None:
        from datetime import date as _date
        date = _date.today()
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO expenses (user_id, category, amount, note, tag, date)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (user_id, category, amount, note, tag, date)
        )
        expense_id = cur.fetchone()['id']
        conn.commit()
        return expense_id

def delete_expense(expense_id, user_id):
    """Delete an expense if it belongs to the user. Returns True if deleted."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM expenses WHERE id = %s AND user_id = %s",
            (expense_id, user_id)
        )
        deleted = cur.rowcount > 0
        conn.commit()
        return deleted

def get_today(user_id):
    """Get all expenses for today."""
    with db() as conn:
        return _safe_query(
            conn,
            """
            SELECT id, category, amount, note, tag, date
            FROM expenses
            WHERE user_id = %s AND date = CURRENT_DATE
            ORDER BY id DESC
            """,
            (user_id,)
        )

def get_monthly(user_id, year=None, month=None):
    """Get all expenses for a given month (defaults to current)."""
    if year is None or month is None:
        from datetime import date as _date
        _today = _date.today()
        year, month = _today.year, _today.month
    with db() as conn:
        return _safe_query(
            conn,
            """
            SELECT id, category, amount, note, tag, date
            FROM expenses
            WHERE user_id = %s
              AND EXTRACT(YEAR FROM date) = %s
              AND EXTRACT(MONTH FROM date) = %s
            ORDER BY date DESC, id DESC
            """,
            (user_id, year, month)
        )

def get_monthly_total(user_id, year=None, month=None):
    """Get total amount spent for a given month (defaults to current)."""
    if year is None or month is None:
        from datetime import date as _date
        _today = _date.today()
        year, month = _today.year, _today.month
    with db() as conn:
        result = _safe_one(
            conn,
            """
            SELECT COALESCE(SUM(amount), 0) AS total
            FROM expenses
            WHERE user_id = %s
              AND EXTRACT(YEAR FROM date) = %s
              AND EXTRACT(MONTH FROM date) = %s
            """,
            (user_id, year, month)
        )
        return float(result['total']) if result else 0.0

def get_by_date(user_id, target_date):
    """Get all expenses for a specific date."""
    with db() as conn:
        return _safe_query(
            conn,
            """
            SELECT id, category, amount, note, tag, date
            FROM expenses
            WHERE user_id = %s AND date = %s
            ORDER BY id DESC
            """,
            (user_id, target_date)
        )

def get_by_tag(user_id, tag):
    """Get all expenses filtered by tag."""
    with db() as conn:
        return _safe_query(
            conn,
            """
            SELECT id, category, amount, note, tag, date
            FROM expenses
            WHERE user_id = %s AND tag = %s
            ORDER BY date DESC, id DESC
            """,
            (user_id, tag)
        )

def get_recurring(user_id):
    """Get expenses tagged as 'recurring'."""
    with db() as conn:
        return _safe_query(
            conn,
            """
            SELECT id, category, amount, note, tag, date
            FROM expenses
            WHERE user_id = %s AND tag = 'recurring'
            ORDER BY date DESC, id DESC
            """,
            (user_id,)
        )

def get_budget(user_id):
    """Get the monthly budget for a user."""
    with db() as conn:
        result = _safe_one(
            conn, "SELECT budget FROM users WHERE user_id = %s", (user_id,)
        )
        return float(result['budget']) if result and result.get('budget') else 0.0

def set_budget(user_id, amount):
    """Set the monthly budget for a user."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO users (user_id, budget) VALUES (%s, %s)
            ON CONFLICT (user_id) DO UPDATE SET budget = EXCLUDED.budget
            """,
            (user_id, amount)
        )
        conn.commit()

def get_pin(user_id):
    """Get the PIN for a user (returns None if not set)."""
    with db() as conn:
        result = _safe_one(
            conn, "SELECT pin FROM users WHERE user_id = %s", (user_id,)
        )
        return result.get('pin') if result else None

def get_language(user_id):
    """Get the language preference for a user (defaults to 'en')."""
    with db() as conn:
        result = _safe_one(
            conn, "SELECT language FROM users WHERE user_id = %s", (user_id,)
        )
        return (result.get('language') or 'en') if result else 'en'

# ── Settings functions ────────────────────────────────────────────
def set_language(user_id, language):
    """Set the language preference for a user."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO users (user_id, language) VALUES (%s, %s)
            ON CONFLICT (user_id) DO UPDATE SET language = EXCLUDED.language
            """,
            (user_id, language)
        )
        conn.commit()

def set_pin(user_id, pin):
    """Set or clear the PIN for a user (pass None to remove)."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO users (user_id, pin) VALUES (%s, %s)
            ON CONFLICT (user_id) DO UPDATE SET pin = EXCLUDED.pin
            """,
            (user_id, pin)
        )
        conn.commit()

def set_reminder(user_id, enabled, reminder_time="09:00"):
    """Enable/disable daily reminder and set time for a user."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO users (user_id, daily_reminder, reminder_time) VALUES (%s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE
                SET daily_reminder = EXCLUDED.daily_reminder,
                    reminder_time  = EXCLUDED.reminder_time
            """,
            (user_id, enabled, reminder_time)
        )import os
import psycopg
from psycopg.rows import dict_row
import logging

logger = logging.getLogger(__name__)

# ── DB — reads all possible env var names (same as dashboard.py) ────
def _get_db_url():
    return (
        os.environ.get("SUPABASE_DB_URL") or
        os.environ.get("DATABASE_URL") or
        os.environ.get("POSTGRES_URL") or
        os.environ.get("DB_URL") or
        ""
    )

def db():
    """Fresh connection — always reads env var at call time."""
    url = _get_db_url()
    if not url:
        raise RuntimeError("❌ No DB URL! Set SUPABASE_DB_URL in Render environment.")
    return psycopg.connect(url, row_factory=dict_row)

# ── Initialize database tables ─────────────────────────────────────
def init_db():
    """Create tables if they don't exist."""
    commands = [
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            language TEXT,
            budget REAL DEFAULT 0,
            pin TEXT,
            daily_reminder BOOLEAN DEFAULT FALSE,
            reminder_time TEXT DEFAULT '09:00',
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS notes (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
            content TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS expenses (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
            category TEXT,
            amount REAL,
            note TEXT,
            tag TEXT,
            date DATE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS error_logs (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id) ON DELETE SET NULL,
            error_text TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS bot_admins (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            role TEXT NOT NULL DEFAULT 'admin',
            note TEXT,
            added_at TIMESTAMPTZ DEFAULT NOW(),
            added_by TEXT DEFAULT 'dashboard'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS banned_users (
            user_id BIGINT PRIMARY KEY,
            banned_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS chat_memory (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
            message TEXT,
            is_bot BOOLEAN,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
    ]
    # Migrations for columns added after initial deploy
    migrations = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS pin TEXT",
    ]

    with db() as conn:
        with conn.cursor() as cur:
            for command in commands:
                try:
                    cur.execute(command)
                except Exception as e:
                    logger.warning(f"Init table error (maybe already exists): {e}")
            for migration in migrations:
                try:
                    cur.execute(migration)
                except Exception as e:
                    logger.warning(f"Migration error: {e}")
            conn.commit()

# ── Helper functions ───────────────────────────────────────────────
def _safe_query(conn, sql, params=None):
    """Execute a query safely, return rows or []."""
    try:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        return cur.fetchall()
    except Exception as e:
        logger.warning(f"Query error: {e}")
        return []

def _safe_one(conn, sql, params=None):
    """Execute a query safely, return one row or None."""
    try:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        return cur.fetchone()
    except Exception as e:
        logger.warning(f"Query error: {e}")
        return None

# ── User functions ─────────────────────────────────────────────────
def ensure_user(user_id):
    """Ensure a user exists in the database."""
    with db() as conn:
        # Try to insert, but ignore if already exists (using ON CONFLICT)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO users (user_id) VALUES (%s)
            ON CONFLICT (user_id) DO NOTHING
            """,
            (user_id,)
        )
        conn.commit()

# ── Note functions ─────────────────────────────────────────────────
def add_note(user_id, content):
    """Add a note for the user and return the note ID."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO notes (user_id, content) VALUES (%s, %s)
            RETURNING id
            """,
            (user_id, content)
        )
        note_id = cur.fetchone()['id']
        conn.commit()
        return note_id

def get_notes(user_id):
    """Get all notes for a user, ordered by newest first."""
    with db() as conn:
        return _safe_query(
            conn,
            """
            SELECT id, content, created_at
            FROM notes
            WHERE user_id = %s
            ORDER BY created_at DESC
            """,
            (user_id,)
        )

def delete_note(note_id, user_id):
    """Delete a note if it belongs to the user. Returns True if deleted."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            DELETE FROM notes
            WHERE id = %s AND user_id = %s
            """,
            (note_id, user_id)
        )
        deleted = cur.rowcount > 0
        conn.commit()
        return deleted

def count_notes(user_id):
    """Count the number of notes for a user."""
    with db() as conn:
        result = _safe_one(
            conn,
            """
            SELECT COUNT(*) AS c FROM notes WHERE user_id = %s
            """,
            (user_id,)
        )
        return result['c'] if result else 0

# ── Error logging ─────────────────────────────────────────────────
def log_error(user_id, error_text):
    """Log an error to the error_logs table."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO error_logs (user_id, error_text) VALUES (%s, %s)
            """,
            (user_id, error_text)
        )
        conn.commit()

# ── Reminder functions ─────────────────────────────────────────────
def send_reminders_db(hour):
    """Return list of user IDs that have reminders enabled for the given hour."""
    with db() as conn:
        rows = _safe_query(
            conn,
            """
            SELECT user_id
            FROM users
            WHERE daily_reminder = TRUE
              AND reminder_time = %s
            """,
            (hour,)
        )
        return [row['user_id'] for row in rows]

# ── User info ─────────────────────────────────────────────────────
def get_user_info(user_id):
    """Get detailed information about a user."""
    with db() as conn:
        row = _safe_one(
            conn,
            """
            SELECT user_id, username, language, budget, daily_reminder, reminder_time,
                   COALESCE(SUM(e.amount), 0) AS total_spent,
                   COUNT(e.id) AS expense_count
            FROM users u
            LEFT JOIN expenses e ON u.user_id = e.user_id
            WHERE u.user_id = %s
            GROUP BY u.user_id, u.username, u.language, u.budget, u.daily_reminder, u.reminder_time
            """,
            (user_id,)
        )
        if row:
            return {
                'user_id': row['user_id'],
                'username': row['username'],
                'language': row['language'],
                'budget': row['budget'],
                'daily_reminder': bool(row['daily_reminder']),
                'reminder_time': row['reminder_time'],
                'total_spent': float(row['total_spent']),
                'expense_count': row['expense_count']
            }
        return None

# ── Admin functions ───────────────────────────────────────────────
def ban_user(user_id):
    """Ban a user."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO banned_users (user_id) VALUES (%s)
            ON CONFLICT (user_id) DO NOTHING
            """,
            (user_id,)
        )
        conn.commit()

def unban_user(user_id):
    """Unban a user."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            DELETE FROM banned_users WHERE user_id = %s
            """,
            (user_id,)
        )
        conn.commit()

def get_bot_stats():
    """Get bot statistics."""
    with db() as conn:
        stats = {}
        # Total users
        stats['total_users'] = _safe_one(conn, "SELECT COUNT(*) AS c FROM users")['c']
        # New today
        stats['new_today'] = _safe_one(
            conn, "SELECT COUNT(*) AS c FROM users WHERE created_at::date = CURRENT_DATE"
        )['c']
        # Total spent
        stats['total_spent'] = _safe_one(
            conn, "SELECT COALESCE(SUM(amount), 0) AS c FROM expenses"
        )['c']
        # Total notes
        stats['total_notes'] = _safe_one(conn, "SELECT COUNT(*) AS c FROM notes")['c']
        # Total errors
        stats['errors'] = _safe_one(conn, "SELECT COUNT(*) AS c FROM error_logs")['c']
        # Total banned
        stats['banned'] = _safe_one(conn, "SELECT COUNT(*) AS c FROM banned_users")['c']
        # Active users (last 30 days)
        stats['active_30d'] = _safe_one(
            conn,
            "SELECT COUNT(*) AS c FROM users WHERE created_at >= CURRENT_DATE - INTERVAL '30 days'"
        )['c']
        return stats

def get_conn():
    """Return a database connection (for use in admin functions that need raw connection)."""
    return db()

# ── Chat memory functions ──────────────────────────────────────────
def get_chat_history(user_id, limit=10):
    """Get recent chat history for a user as a list of {role, content} dicts."""
    with db() as conn:
        rows = _safe_query(
            conn,
            """
            SELECT message, is_bot
            FROM chat_memory
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (user_id, limit),
        )
    # Rows come newest-first, reverse to chronological order
    rows.reverse()
    return [
        {"role": "assistant" if r["is_bot"] else "user", "content": r["message"]}
        for r in rows
    ]


def save_chat_message(user_id, role, content):
    """Save a chat message to memory. role should be 'user' or 'assistant'."""
    is_bot = role == "assistant"
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO chat_memory (user_id, message, is_bot)
            VALUES (%s, %s, %s)
            """,
            (user_id, content, is_bot),
        )
        conn.commit()


def clear_chat_history(user_id):
    """Delete all chat memory for a user."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM chat_memory WHERE user_id = %s",
            (user_id,),
        )
        conn.commit()


# ── Expense functions ─────────────────────────────────────────────
def add_expense(user_id, category, amount, note="", tag="", date=None):
    """Add an expense record. Returns the new expense ID."""
    if date is None:
        from datetime import date as date_type
        date = date_type.today()
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO expenses (user_id, category, amount, note, tag, date)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (user_id, category, amount, note, tag, date)
        )
        expense_id = cur.fetchone()['id']
        conn.commit()
        return expense_id

def delete_expense(expense_id, user_id):
    """Delete an expense if it belongs to the user. Returns True if deleted."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            DELETE FROM expenses
            WHERE id = %s AND user_id = %s
            """,
            (expense_id, user_id)
        )
        deleted = cur.rowcount > 0
        conn.commit()
        return deleted

def get_today(user_id):
    """Get all expenses for the user for today."""
    with db() as conn:
        return _safe_query(
            conn,
            """
            SELECT id, category, amount, note, tag, date
            FROM expenses
            WHERE user_id = %s AND date = CURRENT_DATE
            ORDER BY id DESC
            """,
            (user_id,)
        )

def get_monthly(user_id, year=None, month=None):
    """Get all expenses for the user for a given month (defaults to current)."""
    if year is None or month is None:
        from datetime import date
        today = date.today()
        year, month = today.year, today.month
    with db() as conn:
        return _safe_query(
            conn,
            """
            SELECT id, category, amount, note, tag, date
            FROM expenses
            WHERE user_id = %s
              AND EXTRACT(YEAR FROM date) = %s
              AND EXTRACT(MONTH FROM date) = %s
            ORDER BY date DESC, id DESC
            """,
            (user_id, year, month)
        )

def get_monthly_total(user_id, year=None, month=None):
    """Get total amount spent for a given month (defaults to current)."""
    if year is None or month is None:
        from datetime import date
        today = date.today()
        year, month = today.year, today.month
    with db() as conn:
        result = _safe_one(
            conn,
            """
            SELECT COALESCE(SUM(amount), 0) AS total
            FROM expenses
            WHERE user_id = %s
              AND EXTRACT(YEAR FROM date) = %s
              AND EXTRACT(MONTH FROM date) = %s
            """,
            (user_id, year, month)
        )
        return float(result['total']) if result else 0.0

def get_by_date(user_id, target_date):
    """Get all expenses for a specific date."""
    with db() as conn:
        return _safe_query(
            conn,
            """
            SELECT id, category, amount, note, tag, date
            FROM expenses
            WHERE user_id = %s AND date = %s
            ORDER BY id DESC
            """,
            (user_id, target_date)
        )

def get_by_tag(user_id, tag):
    """Get all expenses for a specific tag."""
    with db() as conn:
        return _safe_query(
            conn,
            """
            SELECT id, category, amount, note, tag, date
            FROM expenses
            WHERE user_id = %s AND tag = %s
            ORDER BY date DESC, id DESC
            """,
            (user_id, tag)
        )

def get_recurring(user_id):
    """Get expenses tagged as 'recurring' for the user."""
    with db() as conn:
        return _safe_query(
            conn,
            """
            SELECT id, category, amount, note, tag, date
            FROM expenses
            WHERE user_id = %s AND tag = 'recurring'
            ORDER BY date DESC, id DESC
            """,
            (user_id,)
        )

def get_budget(user_id):
    """Get the budget for a user. Returns 0 if not set."""
    with db() as conn:
        result = _safe_one(
            conn,
            "SELECT budget FROM users WHERE user_id = %s",
            (user_id,)
        )
        return float(result['budget']) if result else 0.0

def set_budget(user_id, amount):
    """Set the monthly budget for a user."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO users (user_id, budget) VALUES (%s, %s)
            ON CONFLICT (user_id) DO UPDATE SET budget = EXCLUDED.budget
            """,
            (user_id, amount)
        )
        conn.commit()

def get_pin(user_id):
    """Get the PIN for a user (returns None if not set)."""
    with db() as conn:
        result = _safe_one(
            conn,
            "SELECT pin FROM users WHERE user_id = %s",
            (user_id,)
        )
        if result and 'pin' in result:
            return result.get('pin')
        return None

def get_language(user_id):
    """Get the language preference for a user (defaults to 'en')."""
    with db() as conn:
        result = _safe_one(
            conn,
            "SELECT language FROM users WHERE user_id = %s",
            (user_id,)
        )
        return result['language'] if result and result.get('language') else 'en'


# For compatibility with dashboard.py's db() function (if needed)
def set_bot_app(app):
    """Placeholder for compatibility."""
    pass

# ── Settings functions (used by settings_handler) ─────────────────
def set_language(user_id, language):
    """Set the language preference for a user."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO users (user_id, language) VALUES (%s, %s)
            ON CONFLICT (user_id) DO UPDATE SET language = EXCLUDED.language
            """,
            (user_id, language)
        )
        conn.commit()


def set_pin(user_id, pin):
    """Set or clear the PIN for a user (pass None to remove)."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO users (user_id, pin) VALUES (%s, %s)
            ON CONFLICT (user_id) DO UPDATE SET pin = EXCLUDED.pin
            """,
            (user_id, pin)
        )
        conn.commit()


def set_reminder(user_id, enabled, reminder_time="09:00"):
    """Enable/disable daily reminder and set time for a user."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO users (user_id, daily_reminder, reminder_time) VALUES (%s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE
                SET daily_reminder = EXCLUDED.daily_reminder,
                    reminder_time  = EXCLUDED.reminder_time
            """,
            (user_id, enabled, reminder_time)
        )
        conn.commit()


# ── Admin handler functions ────────────────────────────────────────
def count_users():
    """Return total number of registered users."""
    with db() as conn:
        result = _safe_one(conn, "SELECT COUNT(*) AS c FROM users")
        return result['c'] if result else 0


def get_all_user_ids():
    """Return a list of all user_ids (for broadcast)."""
    with db() as conn:
        rows = _safe_query(conn, "SELECT user_id FROM users ORDER BY created_at")
        return [r['user_id'] for r in rows]


def get_recent_errors(limit=20):
    """Return the most recent error log entries."""
    with db() as conn:
        return _safe_query(
            conn,
            """
            SELECT id, user_id, error_text, created_at
            FROM error_logs
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (limit,)
        )
        conn.commit()