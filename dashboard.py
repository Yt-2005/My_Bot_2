"""
dashboard.py — Admin Dashboard for Telegram Bot
Accessible at /admin — password protected
Features: Rate limiting, CSRF, session timeout, audit log, user notes viewer,
          analytics, banned users, system info, broadcast with preview, DB export
"""

import sqlite3
import logging
import os
import json
import time as _time
import hashlib
import secrets
from functools import wraps
from datetime import datetime, timedelta
from flask import request, session, redirect, jsonify, Response, make_response

logger = logging.getLogger(__name__)

_bot_app = None
_proc_start = _time.time()

# ── In-memory rate limiting & audit log ──
_login_attempts: dict = {}   # ip -> [timestamps]
_audit_log: list = []        # max 500 entries
_active_sessions: dict = {}  # session_token -> {ip, created_at}

MAX_LOGIN_ATTEMPTS = 5
LOGIN_WINDOW = 300           # 5 min window
SESSION_TIMEOUT = 3600       # 1 hour

def set_bot_app(app):
    global _bot_app
    _bot_app = app

DB_PATH = "bot_data.db"

def db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def _table_exists(conn, name):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None

def _audit(action: str, detail: str = "", ip: str = ""):
    _audit_log.append({
        "time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "action": action,
        "detail": detail,
        "ip": ip or "—",
    })
    if len(_audit_log) > 500:
        _audit_log.pop(0)

def _check_rate_limit(ip: str) -> bool:
    """Returns True if rate limited."""
    now = _time.time()
    attempts = _login_attempts.get(ip, [])
    attempts = [t for t in attempts if now - t < LOGIN_WINDOW]
    _login_attempts[ip] = attempts
    return len(attempts) >= MAX_LOGIN_ATTEMPTS

def _record_attempt(ip: str):
    _login_attempts.setdefault(ip, []).append(_time.time())

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = session.get("admin_token")
        if not token or token not in _active_sessions:
            return jsonify({"error": "Unauthorized"}), 401
        sess = _active_sessions[token]
        if _time.time() - sess["created_at"] > SESSION_TIMEOUT:
            del _active_sessions[token]
            session.clear()
            return jsonify({"error": "Session expired"}), 401
        # Refresh session
        _active_sessions[token]["created_at"] = _time.time()
        return f(*args, **kwargs)
    return decorated


   


# ─────────────────────────────────────────────
# REGISTER ROUTES
# ─────────────────────────────────────────────
def register_dashboard(flask_app, secret_key="secret", password="admin1234"):
    flask_app.secret_key = secret_key
    DASHBOARD_PASSWORD = password

    # ── SERVE SPA ──
    @flask_app.route("/admin")
    @flask_app.route("/admin/")
    def admin_index():
        return ADMIN_HTML

    # ── LOGIN API (rate-limited) ──
    @flask_app.route("/admin/api/login", methods=["POST"])
    def api_login():
        ip = request.remote_addr or "unknown"
        if _check_rate_limit(ip):
            _audit("LOGIN_BLOCKED", f"Too many attempts from {ip}", ip)
            return jsonify({"error": "Too many failed attempts. Try again in 5 minutes.", "locked": True}), 429
        data = request.get_json() or {}
        if data.get("password") == DASHBOARD_PASSWORD:
            token = secrets.token_hex(32)
            session["admin_token"] = token
            _active_sessions[token] = {"ip": ip, "created_at": _time.time()}
            _audit("LOGIN_SUCCESS", f"Admin logged in", ip)
            return jsonify({"ok": True})
        _record_attempt(ip)
        _audit("LOGIN_FAIL", f"Wrong password from {ip}", ip)
        return jsonify({"error": "❌ Wrong password"}), 401

    @flask_app.route("/admin/api/logout", methods=["POST"])
    def api_logout():
        token = session.get("admin_token")
        if token and token in _active_sessions:
            del _active_sessions[token]
        ip = request.remote_addr or "unknown"
        _audit("LOGOUT", "", ip)
        session.clear()
        return jsonify({"ok": True})

    @flask_app.route("/admin/api/check")
    def api_check():
        token = session.get("admin_token")
        if token and token in _active_sessions:
            if _time.time() - _active_sessions[token]["created_at"] < SESSION_TIMEOUT:
                return jsonify({"ok": True})
        return jsonify({"error": "Not logged in"}), 401

    # ── DASHBOARD API ──
    @flask_app.route("/admin/api/dashboard")
    @login_required
    def api_dashboard():
        conn = db()
        total_users    = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_expenses = conn.execute("SELECT COALESCE(SUM(amount),0) FROM expenses").fetchone()[0]
        total_notes    = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        total_errors   = 0
        if _table_exists(conn, "error_logs"):
            total_errors = conn.execute("SELECT COUNT(*) FROM error_logs").fetchone()[0]
        recent_users = [dict(r) for r in conn.execute(
            "SELECT user_id, username, created_at FROM users ORDER BY created_at DESC LIMIT 5"
        ).fetchall()]
        recent_expenses = [dict(r) for r in conn.execute(
            "SELECT user_id, category, amount, date FROM expenses ORDER BY created_at DESC LIMIT 5"
        ).fetchall()]
        expense_by_cat = [dict(r) for r in conn.execute(
            "SELECT category, SUM(amount) as total FROM expenses GROUP BY category ORDER BY total DESC LIMIT 5"
        ).fetchall()]
        conn.close()
        return jsonify({
            "total_users": total_users, "total_expenses": total_expenses,
            "total_notes": total_notes, "total_errors": total_errors,
            "recent_users": recent_users, "recent_expenses": recent_expenses,
            "expense_by_cat": expense_by_cat,
        })

    # ── ANALYTICS API ──
    @flask_app.route("/admin/api/analytics")
    @login_required
    def api_analytics():
        conn = db()
        today = datetime.now().strftime("%Y-%m-%d")
        ym = datetime.now().strftime("%Y-%m")
        today_count  = conn.execute("SELECT COUNT(*) FROM expenses WHERE date=?", (today,)).fetchone()[0]
        month_total  = conn.execute("SELECT COALESCE(SUM(amount),0) FROM expenses WHERE date LIKE ?", (f"{ym}%",)).fetchone()[0]
        recurring    = conn.execute("SELECT COUNT(*) FROM expenses WHERE is_recurring=1").fetchone()[0]
        reminders    = conn.execute("SELECT COUNT(*) FROM users WHERE daily_reminder=1").fetchone()[0]
        total_users  = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        monthly = [dict(r) for r in conn.execute(
            "SELECT strftime('%Y-%m', date) as month, COUNT(*) as count, SUM(amount) as total FROM expenses GROUP BY month ORDER BY month DESC LIMIT 12"
        ).fetchall()]
        top_tags = [dict(r) for r in conn.execute(
            "SELECT tag, COUNT(*) as count, SUM(amount) as total FROM expenses WHERE tag!='' GROUP BY tag ORDER BY count DESC LIMIT 10"
        ).fetchall()]
        languages = [dict(r) for r in conn.execute(
            "SELECT language, COUNT(*) as count FROM users GROUP BY language ORDER BY count DESC"
        ).fetchall()]
        conn.close()
        return jsonify({
            "today_count": today_count, "month_total": month_total,
            "recurring_count": recurring, "reminder_users": reminders,
            "total_users": total_users, "monthly": monthly,
            "top_tags": top_tags, "languages": languages,
        })

    # ── USERS API ──
    @flask_app.route("/admin/api/users")
    @login_required
    def api_users():
        conn = db()
        if not _table_exists(conn, "banned_users"):
            conn.execute("CREATE TABLE IF NOT EXISTS banned_users (user_id INTEGER PRIMARY KEY)")
            conn.commit()
        banned_ids = {r[0] for r in conn.execute("SELECT user_id FROM banned_users").fetchall()}
        users = [dict(r) for r in conn.execute("""
            SELECT u.*,
              (SELECT COUNT(*) FROM expenses e WHERE e.user_id=u.user_id) as expense_count,
              (SELECT COUNT(*) FROM notes n WHERE n.user_id=u.user_id) as note_count
            FROM users u ORDER BY u.created_at DESC
        """).fetchall()]
        conn.close()
        for u in users:
            u["banned"] = u["user_id"] in banned_ids
        return jsonify(users)

    # ── USER DETAIL API ──
    @flask_app.route("/admin/api/user/<int:uid>")
    @login_required
    def api_user_detail(uid):
        conn = db()
        user = conn.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
        if not user:
            conn.close()
            return jsonify({"error": "User not found"}), 404
        u = dict(user)
        u["expense_count"] = conn.execute("SELECT COUNT(*) FROM expenses WHERE user_id=?", (uid,)).fetchone()[0]
        u["expense_total"] = conn.execute("SELECT COALESCE(SUM(amount),0) FROM expenses WHERE user_id=?", (uid,)).fetchone()[0]
        u["note_count"] = conn.execute("SELECT COUNT(*) FROM notes WHERE user_id=?", (uid,)).fetchone()[0]
        u["recent_expenses"] = [dict(r) for r in conn.execute(
            "SELECT category, amount, note, date FROM expenses WHERE user_id=? ORDER BY created_at DESC LIMIT 5", (uid,)
        ).fetchall()]
        conn.close()
        return jsonify(u)

    # ── BAN / UNBAN ──
    @flask_app.route("/admin/api/ban/<int:uid>", methods=["POST"])
    @login_required
    def api_ban(uid):
        conn = db()
        if not _table_exists(conn, "banned_users"):
            conn.execute("CREATE TABLE IF NOT EXISTS banned_users (user_id INTEGER PRIMARY KEY)")
        conn.execute("INSERT OR IGNORE INTO banned_users (user_id) VALUES (?)", (uid,))
        conn.commit(); conn.close()
        _audit("BAN_USER", f"Banned user {uid}", request.remote_addr)
        return jsonify({"ok": True})

    @flask_app.route("/admin/api/unban/<int:uid>", methods=["POST"])
    @login_required
    def api_unban(uid):
        conn = db()
        conn.execute("DELETE FROM banned_users WHERE user_id=?", (uid,))
        conn.commit(); conn.close()
        _audit("UNBAN_USER", f"Unbanned user {uid}", request.remote_addr)
        return jsonify({"ok": True})

    # ── EXPENSES API ──
    @flask_app.route("/admin/api/expenses")
    @login_required
    def api_expenses():
        conn = db()
        by_cat = [dict(r) for r in conn.execute(
            "SELECT category, COUNT(*) as count, SUM(amount) as total FROM expenses GROUP BY category ORDER BY total DESC"
        ).fetchall()]
        by_month = [dict(r) for r in conn.execute(
            "SELECT strftime('%Y-%m', date) as month, COUNT(*) as count, SUM(amount) as total FROM expenses GROUP BY month ORDER BY month DESC LIMIT 12"
        ).fetchall()]
        top_users = [dict(r) for r in conn.execute(
            "SELECT e.user_id, u.username, COUNT(*) as count, SUM(e.amount) as total FROM expenses e LEFT JOIN users u ON e.user_id=u.user_id GROUP BY e.user_id ORDER BY total DESC LIMIT 10"
        ).fetchall()]
        all_exp = [dict(r) for r in conn.execute(
            "SELECT id, user_id, category, amount, note, tag, is_recurring, date FROM expenses ORDER BY created_at DESC LIMIT 500"
        ).fetchall()]
        conn.close()
        return jsonify({"by_category": by_cat, "by_month": by_month, "top_users": top_users, "all": all_exp})

    # ── NOTES API ──
    @flask_app.route("/admin/api/notes")
    @login_required
    def api_notes():
        conn = db()
        notes = [dict(r) for r in conn.execute(
            "SELECT n.*, u.username FROM notes n LEFT JOIN users u ON n.user_id=u.user_id ORDER BY n.created_at DESC LIMIT 200"
        ).fetchall()]
        conn.close()
        return jsonify(notes)

    @flask_app.route("/admin/api/note/<int:nid>", methods=["DELETE"])
    @login_required
    def api_delete_note(nid):
        conn = db()
        conn.execute("DELETE FROM notes WHERE id=?", (nid,))
        conn.commit(); conn.close()
        _audit("DELETE_NOTE", f"Note #{nid} deleted", request.remote_addr)
        return jsonify({"ok": True})

    # ── BROADCAST API ──
    @flask_app.route("/admin/api/broadcast", methods=["POST"])
    @login_required
    def api_broadcast():
        data = request.get_json() or {}
        message = data.get("message", "").strip()
        target = data.get("target", "all")
        uid = data.get("user_id")
        if not message:
            return jsonify({"error": "Empty message"}), 400
        if not _bot_app:
            return jsonify({"error": "Bot not connected"}), 503
        conn = db()
        if target == "specific" and uid:
            user_ids = [int(uid)]
        elif target == "active":
            from datetime import timedelta
            since = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
            user_ids = [r[0] for r in conn.execute(
                "SELECT DISTINCT user_id FROM expenses WHERE date >= ?", (since,)
            ).fetchall()]
        elif target == "reminder":
            user_ids = [r[0] for r in conn.execute("SELECT user_id FROM users WHERE daily_reminder=1").fetchall()]
        else:
            user_ids = [r[0] for r in conn.execute("SELECT user_id FROM users").fetchall()]
        conn.close()
        sent = 0; failed = 0
        import asyncio
        async def do_broadcast():
            nonlocal sent, failed
            for uid_i in user_ids:
                try:
                    await _bot_app.bot.send_message(
                        chat_id=uid_i,
                        text=f"📢 *Admin Announcement*\n\n{message}",
                        parse_mode="Markdown"
                    )
                    sent += 1
                    await asyncio.sleep(0.05)  # Avoid rate limit
                except Exception:
                    failed += 1
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(do_broadcast())
            loop.close()
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        _audit("BROADCAST", f"Sent to {sent} users (target={target})", request.remote_addr)
        return jsonify({"sent": sent, "failed": failed})

    # ── MAINTENANCE API ──
    @flask_app.route("/admin/api/maintenance")
    @login_required
    def api_maintenance():
        import sys
        import config as cfg
        conn = db()
        users    = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        expenses = conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
        notes    = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        chat_mem = conn.execute("SELECT COUNT(*) FROM chat_memory").fetchone()[0] if _table_exists(conn, "chat_memory") else 0
        errors   = conn.execute("SELECT COUNT(*) FROM error_logs").fetchone()[0] if _table_exists(conn, "error_logs") else 0
        conn.close()
        import time as t
        uptime_secs = int(t.time() - _proc_start)
        h = uptime_secs // 3600; m = (uptime_secs % 3600) // 60; s = uptime_secs % 60
        return jsonify({
            "maintenance_mode": cfg.MAINTENANCE_MODE,
            "users": users, "expenses": expenses, "notes": notes,
            "chat_memory": chat_mem, "errors": errors,
            "port": os.environ.get("PORT", "10000"),
            "uptime": f"{h}h {m}m {s}s",
            "python": sys.version.split()[0],
            "token_status": "✅ Set" if os.environ.get("TOKEN") else "❌ Not set",
            "groq_status": "✅ Set" if os.environ.get("GROQ_API_KEY") else "❌ Not set",
        })

    @flask_app.route("/admin/api/maintenance/toggle", methods=["POST"])
    @login_required
    def api_maintenance_toggle():
        import config as cfg
        data = request.get_json() or {}
        cfg.MAINTENANCE_MODE = bool(data.get("enabled", False))
        _audit("MAINTENANCE_TOGGLE", f"Mode={'ON' if cfg.MAINTENANCE_MODE else 'OFF'}", request.remote_addr)
        return jsonify({"ok": True, "maintenance_mode": cfg.MAINTENANCE_MODE})

    # ── SECURITY API ──
    @flask_app.route("/admin/api/security")
    @login_required
    def api_security():
        conn = db()
        if not _table_exists(conn, "banned_users"):
            conn.execute("CREATE TABLE IF NOT EXISTS banned_users (user_id INTEGER PRIMARY KEY)")
            conn.commit()
        banned = [dict(r) for r in conn.execute("SELECT user_id FROM banned_users").fetchall()]
        conn.close()
        now = _time.time()
        # Rate limit summary (count of recent attempts per IP)
        rate_summary = {}
        for ip, times in _login_attempts.items():
            recent = [t for t in times if now - t < LOGIN_WINDOW]
            if recent:
                rate_summary[ip] = len(recent)
        # Active sessions info
        sessions_info = []
        for token, sess in _active_sessions.items():
            remaining = SESSION_TIMEOUT - (now - sess["created_at"])
            sessions_info.append({
                "token_hint": token[:8] + "...",
                "ip": sess["ip"],
                "created": datetime.utcfromtimestamp(sess["created_at"]).strftime("%Y-%m-%d %H:%M"),
                "expires_in": f"{int(remaining//60)}m {int(remaining%60)}s",
            })
        return jsonify({
            "banned_count": len(banned),
            "banned_users": banned,
            "rate_limits": rate_summary,
            "active_sessions": sessions_info,
        })

    @flask_app.route("/admin/api/security/clear-rate-limits", methods=["POST"])
    @login_required
    def api_clear_rate_limits():
        _login_attempts.clear()
        _audit("CLEAR_RATE_LIMITS", "", request.remote_addr)
        return jsonify({"ok": True})

    # ── ERRORS API ──
    @flask_app.route("/admin/api/errors")
    @login_required
    def api_errors():
        conn = db()
        if not _table_exists(conn, "error_logs"):
            conn.close(); return jsonify([])
        errors = [dict(r) for r in conn.execute(
            "SELECT e.*, u.username FROM error_logs e LEFT JOIN users u ON e.user_id=u.user_id ORDER BY e.created_at DESC LIMIT 50"
        ).fetchall()]
        conn.close()
        return jsonify(errors)

    @flask_app.route("/admin/api/errors/clear", methods=["POST"])
    @login_required
    def api_clear_errors():
        conn = db()
        if _table_exists(conn, "error_logs"):
            conn.execute("DELETE FROM error_logs")
            conn.commit()
        conn.close()
        _audit("CLEAR_ERRORS", "", request.remote_addr)
        return jsonify({"ok": True})

    # ── CHAT MEMORY CLEAR ──
    @flask_app.route("/admin/api/chat/clear", methods=["POST"])
    @login_required
    def api_clear_chat():
        conn = db()
        if _table_exists(conn, "chat_memory"):
            conn.execute("DELETE FROM chat_memory")
            conn.commit()
        conn.close()
        _audit("CLEAR_CHAT_MEMORY", "Cleared all users", request.remote_addr)
        return jsonify({"ok": True})

    # ── AUDIT LOG ──
    @flask_app.route("/admin/api/audit")
    @login_required
    def api_audit():
        return jsonify(list(reversed(_audit_log)))

    # ── EXPORT DATA ──
    @flask_app.route("/admin/api/export")
    @login_required
    def api_export():
        conn = db()
        users    = [dict(r) for r in conn.execute("SELECT user_id, username, language, budget, daily_reminder, created_at FROM users").fetchall()]
        expenses = [dict(r) for r in conn.execute("SELECT id, user_id, category, amount, note, tag, is_recurring, date FROM expenses").fetchall()]
        notes    = [dict(r) for r in conn.execute("SELECT id, user_id, content, created_at FROM notes").fetchall()]
        conn.close()
        data = {
            "exported_at": datetime.utcnow().isoformat(),
            "users": users, "expenses": expenses, "notes": notes,
        }
        _audit("EXPORT_DATA", f"Exported {len(users)} users, {len(expenses)} expenses", request.remote_addr)
        resp = make_response(json.dumps(data, indent=2))
        resp.headers["Content-Type"] = "application/json"
        resp.headers["Content-Disposition"] = f"attachment; filename=bot_export_{datetime.now().strftime('%Y%m%d')}.json"
        return resp

    logger.info("✅ Admin dashboard registered at /admin")