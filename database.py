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
    with db() as conn:
        with conn.cursor() as cur:
            for command in commands:
                try:
                    cur.execute(command)
                except Exception as e:
                    logger.warning(f"Init table error (maybe already exists): {e}")
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

# For compatibility with dashboard.py's db() function (if needed)
def set_bot_app(app):
    """Placeholder for compatibility."""
    pass