"""
dashboard.py — Admin Dashboard for Telegram Bot
Accessible at /admin — password protected
Features: Users, Expenses/Stats, Broadcast, Ban/Unban
"""

# import sqlite3  # replaced by psycopg
import logging
from functools import wraps
from datetime import datetime, timedelta
from flask import Flask, render_template_string, request, session, redirect, url_for, jsonify
from markupsafe import Markup
import threading

logger = logging.getLogger(__name__)

# ── Import bot's telegram app reference (set by bot.py) ──
_bot_app = None

def set_bot_app(app):
    global _bot_app
    _bot_app = app

# ── DB helper — Supabase PostgreSQL ──
import os
import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.environ.get("SUPABASE_DB_URL", os.environ.get("DATABASE_URL", ""))

def db():
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    return conn

# ── Auth decorator ──
DASHBOARD_PASSWORD = "admin1234"  # Change this!

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect("/admin/login")
        return f(*args, **kwargs)
    return decorated

# ── HTML TEMPLATE ──
BASE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Bot Admin</title>
<link href="https://fonts.googleapis.com/css2%sfamily=Space+Mono:wght@400;700&family=Syne:wght@400;600;800&display=swap" rel="stylesheet">
<style>
:root {
  --bg: #0a0a0f;
  --surface: #12121a;
  --surface2: #1a1a26;
  --border: #2a2a3a;
  --accent: #7c6aff;
  --accent2: #ff6a8a;
  --accent3: #6affb8;
  --text: #e8e8f0;
  --muted: #6b6b8a;
  --danger: #ff4466;
  --success: #44ff88;
  --warning: #ffaa44;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: 'Syne', sans-serif;
  min-height: 100vh;
  display: flex;
}
/* Sidebar */
.sidebar {
  width: 240px;
  background: var(--surface);
  border-right: 1px solid var(--border);
  padding: 24px 0;
  position: fixed;
  height: 100vh;
  display: flex;
  flex-direction: column;
  z-index: 100;
}
.sidebar-logo {
  padding: 0 24px 24px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 16px;
}
.sidebar-logo h1 {
  font-size: 20px;
  font-weight: 800;
  background: linear-gradient(135deg, var(--accent), var(--accent2));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}
.sidebar-logo p { font-size: 11px; color: var(--muted); font-family: 'Space Mono', monospace; margin-top: 2px; }
.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 24px;
  color: var(--muted);
  text-decoration: none;
  font-size: 14px;
  font-weight: 600;
  transition: all 0.2s;
  border-left: 3px solid transparent;
}
.nav-item:hover, .nav-item.active {
  color: var(--text);
  background: var(--surface2);
  border-left-color: var(--accent);
}
.nav-item .icon { font-size: 18px; }
.nav-logout {
  margin-top: auto;
  padding: 0 16px 16px;
}
.nav-logout a {
  display: block;
  text-align: center;
  padding: 10px;
  background: rgba(255,68,102,0.1);
  border: 1px solid rgba(255,68,102,0.3);
  border-radius: 8px;
  color: var(--danger);
  text-decoration: none;
  font-size: 13px;
  font-weight: 600;
  transition: all 0.2s;
}
.nav-logout a:hover { background: rgba(255,68,102,0.2); }
/* Main */
.main {
  margin-left: 240px;
  flex: 1;
  padding: 32px;
  min-height: 100vh;
}
.page-title {
  font-size: 28px;
  font-weight: 800;
  margin-bottom: 8px;
}
.page-sub { color: var(--muted); font-size: 13px; margin-bottom: 32px; font-family: 'Space Mono', monospace; }
/* Cards */
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 32px; }
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 20px;
  position: relative;
  overflow: hidden;
}
.card::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 2px;
}
.card.purple::before { background: linear-gradient(90deg, var(--accent), transparent); }
.card.pink::before   { background: linear-gradient(90deg, var(--accent2), transparent); }
.card.green::before  { background: linear-gradient(90deg, var(--accent3), transparent); }
.card.orange::before { background: linear-gradient(90deg, var(--warning), transparent); }
.card-icon { font-size: 28px; margin-bottom: 12px; }
.card-value { font-size: 32px; font-weight: 800; line-height: 1; }
.card-label { font-size: 12px; color: var(--muted); margin-top: 6px; font-family: 'Space Mono', monospace; }
/* Table */
.table-wrap {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
  margin-bottom: 24px;
}
.table-header {
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.table-header h3 { font-size: 15px; font-weight: 700; }
table { width: 100%; border-collapse: collapse; }
th {
  padding: 12px 16px;
  text-align: left;
  font-size: 11px;
  font-weight: 700;
  color: var(--muted);
  background: var(--surface2);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-family: 'Space Mono', monospace;
}
td {
  padding: 12px 16px;
  font-size: 13px;
  border-bottom: 1px solid var(--border);
}
tr:last-child td { border-bottom: none; }
tr:hover td { background: var(--surface2); }
/* Badges */
.badge {
  display: inline-block;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 700;
  font-family: 'Space Mono', monospace;
}
.badge-green { background: rgba(68,255,136,0.1); color: var(--accent3); border: 1px solid rgba(68,255,136,0.2); }
.badge-red   { background: rgba(255,68,102,0.1); color: var(--danger);  border: 1px solid rgba(255,68,102,0.2); }
.badge-purple{ background: rgba(124,106,255,0.1); color: var(--accent); border: 1px solid rgba(124,106,255,0.2); }
/* Buttons */
.btn {
  padding: 8px 16px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  border: none;
  transition: all 0.2s;
  font-family: 'Syne', sans-serif;
  text-decoration: none;
  display: inline-block;
}
.btn-primary { background: var(--accent); color: white; }
.btn-primary:hover { background: #6b5aee; transform: translateY(-1px); }
.btn-danger  { background: rgba(255,68,102,0.15); color: var(--danger); border: 1px solid rgba(255,68,102,0.3); }
.btn-danger:hover { background: rgba(255,68,102,0.25); }
.btn-success { background: rgba(68,255,136,0.15); color: var(--accent3); border: 1px solid rgba(68,255,136,0.3); }
.btn-success:hover { background: rgba(68,255,136,0.25); }
.btn-sm { padding: 5px 10px; font-size: 11px; }
/* Forms */
.form-group { margin-bottom: 16px; }
.form-label { display: block; font-size: 12px; font-weight: 700; color: var(--muted); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.06em; font-family: 'Space Mono', monospace; }
.form-input, .form-textarea {
  width: 100%;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  color: var(--text);
  font-size: 14px;
  font-family: 'Syne', sans-serif;
  transition: border-color 0.2s;
}
.form-input:focus, .form-textarea:focus { outline: none; border-color: var(--accent); }
.form-textarea { resize: vertical; min-height: 100px; }
/* Alert */
.alert { padding: 12px 16px; border-radius: 8px; margin-bottom: 16px; font-size: 13px; }
.alert-success { background: rgba(68,255,136,0.1); border: 1px solid rgba(68,255,136,0.3); color: var(--accent3); }
.alert-error   { background: rgba(255,68,102,0.1); border: 1px solid rgba(255,68,102,0.3); color: var(--danger); }
/* Login page */
.login-wrap {
  width: 100%;
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg);
}
.login-box {
  width: 380px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 40px;
}
.login-box h1 { font-size: 24px; font-weight: 800; margin-bottom: 4px; }
.login-box p  { color: var(--muted); font-size: 13px; margin-bottom: 28px; }
/* Responsive */
@media(max-width:768px) {
  .sidebar { width: 60px; }
  .sidebar-logo, .nav-item span { display: none; }
  .nav-item { padding: 16px; justify-content: center; }
  .main { margin-left: 60px; padding: 16px; }
}
.section { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 24px; margin-bottom: 24px; }
.section h3 { font-size: 16px; font-weight: 700; margin-bottom: 16px; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
@media(max-width:900px) { .grid-2 { grid-template-columns: 1fr; } }
</style>
</head>
<body>
{% if logged_in %}
<div class="sidebar">
  <div class="sidebar-logo">
    <h1>🤖 BotAdmin</h1>
    <p>CONTROL PANEL</p>
  </div>
  <a href="/admin" class="nav-item {% if page=='dashboard' %}active{% endif %}">
    <span class="icon">📊</span><span>Dashboard</span>
  </a>
  <a href="/admin/users" class="nav-item {% if page=='users' %}active{% endif %}">
    <span class="icon">👥</span><span>Users</span>
  </a>
  <a href="/admin/stats" class="nav-item {% if page=='stats' %}active{% endif %}">
    <span class="icon">💰</span><span>Expenses</span>
  </a>
  <a href="/admin/broadcast" class="nav-item {% if page=='broadcast' %}active{% endif %}">
    <span class="icon">📢</span><span>Broadcast</span>
  </a>
  <a href="/admin/errors" class="nav-item {% if page=='errors' %}active{% endif %}">
    <span class="icon">⚠️</span><span>Error Logs</span>
  </a>
  <div class="nav-logout">
    <a href="/admin/logout">🚪 Logout</a>
  </div>
</div>
<div class="main">
{% endif %}
  {{ content }}
{% if logged_in %}
</div>
{% endif %}
</body>
</html>"""

def render_page(content, page="", logged_in=True):
    html = BASE_HTML.replace("{{ content }}", content)
    html = html.replace("{% if logged_in %}", "" if logged_in else "<!--")
    html = html.replace("{% endif %}", "" if logged_in else "-->")
    html = html.replace("{% if page=='dashboard' %}", "")
    for p in ["dashboard","users","stats","broadcast","errors"]:
        html = html.replace(f"{{% if page=='{p}' %}}", "")
        html = html.replace(f"active{{% endif %}}", f"{'active' if page==p else ''}")
    # Simple template replacement
    return html


# ────────────────────────────────────────────────────────────────
# ROUTES
# ────────────────────────────────────────────────────────────────

def register_dashboard(flask_app: Flask, secret_key: str = "bot-secret-2024", password: str = "admin1234", super_admin_ids=None):
    super_admin_ids = list(super_admin_ids or [])
    flask_app.secret_key = secret_key
    global DASHBOARD_PASSWORD
    DASHBOARD_PASSWORD = password

    # ── LOGIN ──
    @flask_app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        error = ""
        if request.method == "POST":
            if request.form.get("password") == DASHBOARD_PASSWORD:
                session["logged_in"] = True
                return redirect("/admin")
            error = "Wrong password!"
        content = f"""
        <div class="login-wrap">
          <div class="login-box">
            <h1>🤖 Bot Admin</h1>
            <p>Enter admin password to continue</p>
            {'<div class="alert alert-error">' + error + '</div>' if error else ''}
            <form method="POST">
              <div class="form-group">
                <label class="form-label">Password</label>
                <input type="password" name="password" class="form-input" placeholder="••••••••" autofocus>
              </div>
              <button type="submit" class="btn btn-primary" style="width:100%">Login →</button>
            </form>
          </div>
        </div>"""
        return render_template_string(BASE_HTML, content=Markup(content), logged_in=False, page="")

    # ── LOGOUT ──
    @flask_app.route("/admin/logout")
    def admin_logout():
        session.clear()
        return redirect("/admin/login")

    # ── DASHBOARD HOME ──
    @flask_app.route("/admin")
    @login_required
    def admin_home():
        conn = db()
        total_users    = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()['c']
        total_expenses = conn.execute("SELECT COALESCE(SUM(amount),0) AS c FROM expenses").fetchone()['c']
        total_notes    = conn.execute("SELECT COUNT(*) AS c FROM notes").fetchone()['c']
        total_errors   = conn.execute("SELECT COUNT(*) AS c FROM error_logs").fetchone()['c']
        new_today      = conn.execute("SELECT COUNT(*) AS c FROM users WHERE created_at::date = CURRENT_DATE").fetchone()['c']
        top_categories = conn.execute("""
            SELECT category, SUM(amount) as total
            FROM expenses GROUP BY category
            ORDER BY total DESC LIMIT 5
        """).fetchall()
        recent_users = conn.execute("""
            SELECT user_id, username, language, created_at FROM users
            ORDER BY created_at DESC LIMIT 5
        """).fetchall()
        conn.close()

        cat_rows = "".join(f"""
            <tr>
              <td>{r['category'] or 'N/A'}</td>
              <td><span class="badge badge-purple">${r['total']:.2f}</span></td>
            </tr>""" for r in top_categories) or "<tr><td colspan='2' style='color:var(--muted)'>No data</td></tr>"

        user_rows = "".join(f"""
            <tr>
              <td><code style='color:var(--accent);font-size:11px'>{r['user_id']}</code></td>
              <td>{r['username'] or '—'}</td>
              <td><span class="badge badge-{'green' if r['language']=='km' else 'purple'}">{r['language']}</span></td>
              <td style='color:var(--muted);font-size:11px'>{r['created_at'][:10]}</td>
            </tr>""" for r in recent_users)

        content = f"""
        <div class="page-title">Dashboard</div>
        <div class="page-sub">OVERVIEW // {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
        <div class="cards">
          <div class="card purple">
            <div class="card-icon">👥</div>
            <div class="card-value">{total_users}</div>
            <div class="card-label">TOTAL USERS (+{new_today} today)</div>
          </div>
          <div class="card pink">
            <div class="card-icon">💰</div>
            <div class="card-value">${total_expenses:.0f}</div>
            <div class="card-label">TOTAL EXPENSES</div>
          </div>
          <div class="card green">
            <div class="card-icon">📝</div>
            <div class="card-value">{total_notes}</div>
            <div class="card-label">TOTAL NOTES</div>
          </div>
          <div class="card orange">
            <div class="card-icon">⚠️</div>
            <div class="card-value">{total_errors}</div>
            <div class="card-label">ERROR LOGS</div>
          </div>
        </div>
        <div class="grid-2">
          <div class="table-wrap">
            <div class="table-header"><h3>🏆 Top Expense Categories</h3></div>
            <table><thead><tr><th>Category</th><th>Total</th></tr></thead>
            <tbody>{cat_rows}</tbody></table>
          </div>
          <div class="table-wrap">
            <div class="table-header"><h3>🆕 Recent Users</h3></div>
            <table><thead><tr><th>ID</th><th>Username</th><th>Lang</th><th>Joined</th></tr></thead>
            <tbody>{user_rows}</tbody></table>
          </div>
        </div>"""
        return render_template_string(BASE_HTML, content=Markup(content), logged_in=True, page="dashboard")

    # ── USERS ──
    @flask_app.route("/admin/users")
    @login_required
    def admin_users():
        conn = db()
        users = conn.execute("""
            SELECT u.user_id, u.username, u.language, u.pin,
                   u.daily_reminder, u.created_at,
                   COUNT(DISTINCT e.id) as expense_count,
                   COUNT(DISTINCT n.id) as note_count
            FROM users u
            LEFT JOIN expenses e ON u.user_id = e.user_id
            LEFT JOIN notes n ON u.user_id = n.user_id
            GROUP BY u.user_id
            ORDER BY u.created_at DESC
        """).fetchall()
        banned = conn.execute("SELECT user_id FROM banned_users").fetchall() if _table_exists(conn, "banned_users") else []
        banned_ids = {r[0] for r in banned}
        conn.close()

        rows = "".join(f"""
            <tr>
              <td><code style='color:var(--accent);font-size:11px'>{u['user_id']}</code></td>
              <td>{u['username'] or '—'}</td>
              <td><span class="badge badge-{'green' if u['language']=='km' else 'purple'}">{u['language'].upper()}</span></td>
              <td style='text-align:center'>{u['expense_count']}</td>
              <td style='text-align:center'>{u['note_count']}</td>
              <td><span class="badge badge-{'green' if not u['daily_reminder'] else 'purple'}">{'ON' if u['daily_reminder'] else 'OFF'}</span></td>
              <td style='color:var(--muted);font-size:11px'>{u['created_at'][:10]}</td>
              <td>
                {'<a href="/admin/unban/'+str(u["user_id"])+'" class="btn btn-success btn-sm">Unban</a>' if u['user_id'] in banned_ids else '<a href="/admin/ban/'+str(u["user_id"])+'" class="btn btn-danger btn-sm">Ban</a>'}
              </td>
            </tr>""" for u in users)

        content = f"""
        <div class="page-title">Users</div>
        <div class="page-sub">TOTAL: {len(users)} USERS</div>
        <div class="table-wrap">
          <div class="table-header">
            <h3>👥 All Users</h3>
            <span style='color:var(--muted);font-size:12px'>{len(users)} total</span>
          </div>
          <table>
            <thead><tr>
              <th>User ID</th><th>Username</th><th>Lang</th>
              <th>Expenses</th><th>Notes</th><th>Reminder</th>
              <th>Joined</th><th>Action</th>
            </tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </div>"""
        return render_template_string(BASE_HTML, content=Markup(content), logged_in=True, page="users")

    # ── BAN / UNBAN ──
    @flask_app.route("/admin/ban/<int:uid>")
    @login_required
    def admin_ban(uid):
        conn = db()
        if not _table_exists(conn, "banned_users"):
            conn.execute("CREATE TABLE IF NOT EXISTS banned_users (user_id INTEGER PRIMARY KEY)")
            conn.commit()
        conn.execute("INSERT OR IGNORE INTO banned_users (user_id) VALUES (%s)", (uid,))
        conn.commit()
        conn.close()
        return redirect("/admin/users")

    @flask_app.route("/admin/unban/<int:uid>")
    @login_required
    def admin_unban(uid):
        conn = db()
        conn.execute("DELETE FROM banned_users WHERE user_id=%s", (uid,))
        conn.commit()
        conn.close()
        return redirect("/admin/users")

    # ── STATS ──
    @flask_app.route("/admin/stats")
    @login_required
    def admin_stats():
        conn = db()
        by_cat = conn.execute("""
            SELECT category, COUNT(*) as cnt, SUM(amount) as total
            FROM expenses GROUP BY category ORDER BY total DESC
        """).fetchall()
        by_month = conn.execute("""
            SELECT strftime('%Y-%m', date) as month, SUM(amount) as total, COUNT(*) as cnt
            FROM expenses GROUP BY month ORDER BY month DESC LIMIT 12
        """).fetchall()
        top_users = conn.execute("""
            SELECT e.user_id, u.username, SUM(e.amount) as total, COUNT(*) as cnt
            FROM expenses e LEFT JOIN users u ON e.user_id=u.user_id
            GROUP BY e.user_id ORDER BY total DESC LIMIT 10
        """).fetchall()
        conn.close()

        cat_rows = "".join(f"""
            <tr>
              <td>{r['category'] or 'N/A'}</td>
              <td style='text-align:center'>{r['cnt']}</td>
              <td><span class="badge badge-purple">${r['total']:.2f}</span></td>
            </tr>""" for r in by_cat)

        month_rows = "".join(f"""
            <tr>
              <td><span class="badge badge-green">{r['month']}</span></td>
              <td style='text-align:center'>{r['cnt']}</td>
              <td><span class="badge badge-purple">${r['total']:.2f}</span></td>
            </tr>""" for r in by_month)

        user_rows = "".join(f"""
            <tr>
              <td><code style='color:var(--accent);font-size:11px'>{r['user_id']}</code></td>
              <td>{r['username'] or '—'}</td>
              <td style='text-align:center'>{r['cnt']}</td>
              <td><span class="badge badge-pink">${r['total']:.2f}</span></td>
            </tr>""" for r in top_users)

        content = f"""
        <div class="page-title">Expenses & Stats</div>
        <div class="page-sub">FINANCIAL OVERVIEW</div>
        <div class="grid-2">
          <div class="table-wrap">
            <div class="table-header"><h3>📁 By Category</h3></div>
            <table><thead><tr><th>Category</th><th>Count</th><th>Total</th></tr></thead>
            <tbody>{cat_rows or "<tr><td colspan='3' style='color:var(--muted)'>No data</td></tr>"}</tbody></table>
          </div>
          <div class="table-wrap">
            <div class="table-header"><h3>📅 By Month</h3></div>
            <table><thead><tr><th>Month</th><th>Count</th><th>Total</th></tr></thead>
            <tbody>{month_rows or "<tr><td colspan='3' style='color:var(--muted)'>No data</td></tr>"}</tbody></table>
          </div>
        </div>
        <div class="table-wrap">
          <div class="table-header"><h3>🏆 Top Spenders</h3></div>
          <table><thead><tr><th>User ID</th><th>Username</th><th>Transactions</th><th>Total Spent</th></tr></thead>
          <tbody>{user_rows or "<tr><td colspan='4' style='color:var(--muted)'>No data</td></tr>"}</tbody></table>
        </div>"""
        return render_template_string(BASE_HTML, content=Markup(content), logged_in=True, page="stats")

    # ── BROADCAST ──
    @flask_app.route("/admin/broadcast", methods=["GET", "POST"])
    @login_required
    def admin_broadcast():
        result = ""
        if request.method == "POST":
            message = request.form.get("message", "").strip()
            if message and _bot_app:
                conn = db()
                user_ids = [r[0] for r in conn.execute("SELECT user_id FROM users").fetchall()]
                conn.close()
                sent = 0
                failed = 0
                import asyncio
                async def do_broadcast():
                    nonlocal sent, failed
                    for uid in user_ids:
                        try:
                            await _bot_app.bot.send_message(chat_id=uid, text=f"📢 *Admin Announcement*\n\n{message}", parse_mode="Markdown")
                            sent += 1
                        except Exception:
                            failed += 1
                try:
                    loop = asyncio.new_event_loop()
                    loop.run_until_complete(do_broadcast())
                    loop.close()
                    result = f'<div class="alert alert-success">✅ Sent to {sent} users ({failed} failed)</div>'
                except Exception as e:
                    result = f'<div class="alert alert-error">❌ Error: {e}</div>'
            elif not _bot_app:
                result = '<div class="alert alert-error">❌ Bot not connected to dashboard yet</div>'

        conn = db()
        user_count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()['c']
        conn.close()

        content = f"""
        <div class="page-title">Broadcast</div>
        <div class="page-sub">SEND MESSAGE TO ALL USERS</div>
        {result}
        <div class="section">
          <h3>📢 Send Broadcast Message</h3>
          <p style='color:var(--muted);font-size:13px;margin-bottom:16px'>Will be sent to all <strong style='color:var(--accent)'>{user_count}</strong> users</p>
          <form method="POST">
            <div class="form-group">
              <label class="form-label">Message</label>
              <textarea name="message" class="form-textarea" placeholder="Type your announcement here..."></textarea>
            </div>
            <button type="submit" class="btn btn-primary">📤 Send to All Users</button>
          </form>
        </div>"""
        return render_template_string(BASE_HTML, content=Markup(content), logged_in=True, page="broadcast")

    # ── ERROR LOGS ──
    @flask_app.route("/admin/errors")
    @login_required
    def admin_errors():
        conn = db()
        errors = conn.execute("""
            SELECT e.*, u.username FROM error_logs e
            LEFT JOIN users u ON e.user_id=u.user_id
            ORDER BY e.created_at DESC LIMIT 50
        """).fetchall()
        conn.close()

        rows = "".join(f"""
            <tr>
              <td><code style='color:var(--accent);font-size:11px'>{e['user_id']}</code></td>
              <td style='font-size:11px;color:var(--muted)'>{e['username'] or '—'}</td>
              <td style='font-size:12px;max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>{e['error']}</td>
              <td><span class="badge badge-purple">{e['context'] or '—'}</span></td>
              <td style='color:var(--muted);font-size:11px'>{e['created_at'][:16]}</td>
            </tr>""" for e in errors)

        content = f"""
        <div class="page-title">Error Logs</div>
        <div class="page-sub">LAST 50 ERRORS</div>
        <div class="table-wrap">
          <div class="table-header">
            <h3>⚠️ Recent Errors</h3>
            <span style='color:var(--muted);font-size:12px'>{len(errors)} entries</span>
          </div>
          <table>
            <thead><tr><th>User ID</th><th>Username</th><th>Error</th><th>Context</th><th>Time</th></tr></thead>
            <tbody>{rows or "<tr><td colspan='5' style='color:var(--muted);text-align:center;padding:24px'>No errors logged</td></tr>"}</tbody>
          </table>
        </div>"""
        return render_template_string(BASE_HTML, content=Markup(content), logged_in=True, page="errors")

    # ── API: Stats JSON ──
    @flask_app.route("/admin/api/stats")
    @login_required
    def api_stats():
        conn = db()
        data = {
            "users": conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()['c'],
            "expenses": conn.execute("SELECT COALESCE(SUM(amount),0) AS c FROM expenses").fetchone()['c'],
            "notes": conn.execute("SELECT COUNT(*) AS c FROM notes").fetchone()['c'],
        }
        conn.close()
        return jsonify(data)

    logger.info("✅ Admin dashboard registered at /admin")


def _table_exists(conn, name):
    try:
        cur = conn.cursor()
        cur.execute("SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name=%s)", (name,))
        row = cur.fetchone()
        return bool(list(row.values())[0]) if row else False
    except Exception:
        return False is not None