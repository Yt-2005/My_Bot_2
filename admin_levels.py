"""
admin_levels.py — Custom Admin Level System
Levels: super_admin, admin, moderator
Managed via /admin dashboard only
Uses PostgreSQL (psycopg) — same as the rest of the bot
"""

import logging
import os

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)


# ── DB connection (mirrors dashboard.py / database.py) ────────────────────
def _get_db_url() -> str:
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
        raise RuntimeError("❌ No DB URL set (SUPABASE_DB_URL / DATABASE_URL)")
    return psycopg.connect(url, row_factory=dict_row)


# ── Level definitions ──────────────────────────────────────────────────────
LEVELS = {
    "super_admin": {
        "label": "Super Admin 👑",
        "badge_class": "bm",          # matches dashboard CSS
        "permissions": [
            "view_stats", "view_users", "view_expenses", "view_notes",
            "ban_user", "unban_user", "delete_note", "broadcast",
            "maintenance", "clear_errors", "clear_chat", "export_data",
            "manage_admins",           # only super_admin can promote/demote
        ],
    },
    "admin": {
        "label": "Admin 🛡️",
        "badge_class": "bg",
        "permissions": [
            "view_stats", "view_users", "view_expenses", "view_notes",
            "ban_user", "unban_user", "delete_note", "broadcast",
            "clear_errors", "clear_chat",
        ],
    },
    "moderator": {
        "label": "Moderator 🔰",
        "badge_class": "bg3",
        "permissions": [
            "view_stats", "view_users", "view_notes",
            "ban_user", "unban_user", "delete_note",
        ],
    },
}

LEVEL_ORDER = ["super_admin", "admin", "moderator"]


# ── Table init (called once at bot startup) ────────────────────────────────
def init_admin_table():
    """Create bot_admins table if it doesn't exist."""
    conn = db()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_admins (
                user_id   BIGINT PRIMARY KEY,
                username  TEXT DEFAULT '',
                level     TEXT NOT NULL DEFAULT 'moderator',
                added_by  BIGINT,
                added_at  TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        conn.commit()
        logger.info("✅ bot_admins table ready")
    except Exception as e:
        conn.rollback()
        logger.error(f"init_admin_table error: {e}")
    finally:
        conn.close()


# ── Core helpers ───────────────────────────────────────────────────────────

def get_admin_level(user_id: int, super_admin_ids: list) -> str | None:
    """
    Return level string ('super_admin' | 'admin' | 'moderator') or None.
    Hardcoded super_admin_ids (from config/env) always win.
    """
    if user_id in super_admin_ids:
        return "super_admin"
    conn = db()
    try:
        row = conn.execute(
            "SELECT level FROM bot_admins WHERE user_id=%s", (user_id,)
        ).fetchone()
        return row["level"] if row else None
    except Exception as e:
        logger.warning(f"get_admin_level error: {e}")
        return None
    finally:
        conn.close()


def has_permission(user_id: int, permission: str, super_admin_ids: list) -> bool:
    """Return True if the user's level includes the given permission."""
    level = get_admin_level(user_id, super_admin_ids)
    if level is None:
        return False
    return permission in LEVELS.get(level, {}).get("permissions", [])


def list_admins() -> list:
    """Return all rows from bot_admins as list of dicts."""
    conn = db()
    try:
        rows = conn.execute(
            "SELECT user_id, username, level, added_by, added_at "
            "FROM bot_admins ORDER BY added_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"list_admins error: {e}")
        return []
    finally:
        conn.close()


def add_admin(user_id: int, username: str, level: str, added_by: int) -> bool:
    """Insert or update an admin record. Returns False for invalid level."""
    if level not in LEVELS:
        return False
    conn = db()
    try:
        conn.execute("""
            INSERT INTO bot_admins (user_id, username, level, added_by)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                username = EXCLUDED.username,
                level    = EXCLUDED.level,
                added_by = EXCLUDED.added_by,
                added_at = NOW()
        """, (user_id, username or "", level, added_by))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"add_admin error: {e}")
        return False
    finally:
        conn.close()


def remove_admin(user_id: int) -> bool:
    """Delete an admin record. Returns True even if user wasn't in table."""
    conn = db()
    try:
        conn.execute("DELETE FROM bot_admins WHERE user_id=%s", (user_id,))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"remove_admin error: {e}")
        return False
    finally:
        conn.close()


def update_level(user_id: int, new_level: str, changed_by: int) -> bool:
    """Change an existing admin's level. Returns False for invalid level."""
    if new_level not in LEVELS:
        return False
    conn = db()
    try:
        conn.execute(
            "UPDATE bot_admins SET level=%s, added_by=%s, added_at=NOW() "
            "WHERE user_id=%s",
            (new_level, changed_by, user_id)
        )
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"update_level error: {e}")
        return False
    finally:
        conn.close()


# ── Telegram decorator ─────────────────────────────────────────────────────

def require_permission(permission: str, super_admin_ids: list):
    """
    Decorator for PTB handlers. Silently rejects users without the permission.

    Usage:
        from admin_levels import require_permission
        from config import ADMIN_IDS

        @require_permission("broadcast", ADMIN_IDS)
        async def broadcast_cmd(update, ctx): ...
    """
    from functools import wraps
    def decorator(func):
        @wraps(func)
        async def wrapper(update, ctx):
            uid = update.effective_user.id if update.effective_user else 0
            if not has_permission(uid, permission, super_admin_ids):
                level = get_admin_level(uid, super_admin_ids)
                if level is None:
                    msg = "⛔ Access denied."
                else:
                    msg = f"⛔ Your role (*{LEVELS[level]['label']}*) doesn't have permission for this."
                if update.message:
                    await update.message.reply_text(msg, parse_mode="Markdown")
                elif update.callback_query:
                    await update.callback_query.answer(msg, show_alert=True)
                return
            return await func(update, ctx)
        return wrapper
    return decorator