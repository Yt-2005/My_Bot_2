"""
admin_levels.py — Custom Admin Level System
Levels: super_admin, admin, moderator
Managed via /admin dashboard only
"""

import sqlite3
import logging
import os

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "bot_data.db")

# ── Level definitions ──────────────────────────────────────────────────────
LEVELS = {
    "super_admin": {
        "label": "Super Admin 👑",
        "color": "#f59e0b",
        "permissions": [
            "view_stats", "view_users", "view_expenses", "view_notes",
            "ban_user", "unban_user", "delete_note", "broadcast",
            "maintenance", "clear_errors", "clear_chat", "export_data",
            "manage_admins",  # only super_admin can promote/demote others
        ],
    },
    "admin": {
        "label": "Admin 🛡️",
        "color": "#3b82f6",
        "permissions": [
            "view_stats", "view_users", "view_expenses", "view_notes",
            "ban_user", "unban_user", "delete_note", "broadcast",
            "clear_errors", "clear_chat",
        ],
    },
    "moderator": {
        "label": "Moderator 🔰",
        "color": "#22c55e",
        "permissions": [
            "view_stats", "view_users", "view_notes",
            "ban_user", "unban_user", "delete_note",
        ],
    },
}

LEVEL_ORDER = ["super_admin", "admin", "moderator"]


def init_admin_table():
    """Create admin_levels table if not exists."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS admin_levels (
            user_id   INTEGER PRIMARY KEY,
            username  TEXT DEFAULT '',
            level     TEXT NOT NULL DEFAULT 'moderator',
            added_by  INTEGER,
            added_at  TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()


def db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# ── Core helpers ───────────────────────────────────────────────────────────

def get_admin_level(user_id: int, super_admin_ids: list) -> str | None:
    """Return level string or None if not an admin."""
    if user_id in super_admin_ids:
        return "super_admin"
    conn = db()
    row = conn.execute(
        "SELECT level FROM admin_levels WHERE user_id=?", (user_id,)
    ).fetchone()
    conn.close()
    return row["level"] if row else None


def has_permission(user_id: int, permission: str, super_admin_ids: list) -> bool:
    level = get_admin_level(user_id, super_admin_ids)
    if level is None:
        return False
    return permission in LEVELS.get(level, {}).get("permissions", [])


def list_admins() -> list:
    conn = db()
    rows = [dict(r) for r in conn.execute(
        "SELECT user_id, username, level, added_by, added_at FROM admin_levels ORDER BY added_at DESC"
    ).fetchall()]
    conn.close()
    return rows


def add_admin(user_id: int, username: str, level: str, added_by: int) -> bool:
    if level not in LEVELS:
        return False
    conn = db()
    conn.execute("""
        INSERT INTO admin_levels (user_id, username, level, added_by)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username,
            level=excluded.level,
            added_by=excluded.added_by,
            added_at=datetime('now')
    """, (user_id, username or "", level, added_by))
    conn.commit()
    conn.close()
    return True


def remove_admin(user_id: int) -> bool:
    conn = db()
    conn.execute("DELETE FROM admin_levels WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()
    return True


def update_level(user_id: int, new_level: str, changed_by: int) -> bool:
    if new_level not in LEVELS:
        return False
    conn = db()
    conn.execute(
        "UPDATE admin_levels SET level=?, added_by=?, added_at=datetime('now') WHERE user_id=?",
        (new_level, changed_by, user_id)
    )
    conn.commit()
    conn.close()
    return True