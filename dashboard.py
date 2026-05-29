"""
dashboard.py — Admin Dashboard (Supabase PostgreSQL)
Fixes:
  ✅ strftime → to_char (PostgreSQL)
  ✅ banned_users table auto-created in init_db (no more UndefinedTable)
  ✅ send_reminders uses psycopg not sqlite3
  ✅ Admin check reads bot_admins DB table (not just config.py ADMIN_IDS)
New:
  ✅ Full CRUD: users, expenses, notes
  ✅ /admin/expenses — browse, edit, delete any expense
  ✅ /admin/user/<id> — detailed user profile
  ✅ /admin/notes — view/delete notes
  ✅ Telegram bot control via dashboard (send msg to user, ban via bot)
  ✅ /admin/api/* JSON endpoints for Telegram bot commands
  ✅ Export expenses as CSV
  ✅ Search users & expenses
  ✅ Charts: spending by month (line), by category (doughnut), users growth (bar)
"""

import logging
import os
import csv
import io
from functools import wraps
from datetime import datetime, timedelta

import psycopg
from psycopg.rows import dict_row
from flask import (
    Flask, render_template_string, request, session,
    redirect, url_for, jsonify, Response
)
from markupsafe import Markup

logger = logging.getLogger(__name__)

# ── Bot app reference (set by bot.py) ──
_bot_app = None

def set_bot_app(app):
    global _bot_app
    _bot_app = app

# ── DB — reads all possible env var names (same as database.py) ──
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

# ── Auth ──
DASHBOARD_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin1234")

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect("/admin/login")
        return f(*args, **kwargs)
    return decorated

# ─────────────────────────────────────────────────────────────────
# HTML BASE TEMPLATE
# ─────────────────────────────────────────────────────────────────
BASE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Bot Admin Panel</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=DM+Sans:wght@400;500;700;900&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
:root {
  --bg: #080b14;
  --surface: #0d1117;
  --surface2: #161b27;
  --surface3: #1e2535;
  --border: #232c3d;
  --accent: #4f8ef7;
  --accent2: #f74f8e;
  --accent3: #4ff7a0;
  --accent4: #f7c44f;
  --text: #e2e8f5;
  --muted: #5a6a8a;
  --danger: #f74f6a;
  --success: #4ff7a0;
  --warning: #f7c44f;
  --radius: 10px;
}
*{margin:0;padding:0;box-sizing:border-box;}
body{background:var(--bg);color:var(--text);font-family:'DM Sans',sans-serif;min-height:100vh;display:flex;}
a{color:inherit;text-decoration:none;}
code{font-family:'JetBrains Mono',monospace;}

/* ── Sidebar ── */
.sidebar{
  width:220px;background:var(--surface);border-right:1px solid var(--border);
  padding:20px 0;position:fixed;height:100vh;display:flex;flex-direction:column;z-index:100;
}
.sidebar-logo{padding:0 20px 20px;border-bottom:1px solid var(--border);margin-bottom:12px;}
.sidebar-logo h1{font-size:17px;font-weight:900;letter-spacing:-0.5px;
  background:linear-gradient(135deg,var(--accent),var(--accent2));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;}
.sidebar-logo p{font-size:10px;color:var(--muted);font-family:'JetBrains Mono',monospace;margin-top:3px;}
.nav-section{padding:8px 20px 4px;font-size:9px;font-weight:700;color:var(--muted);
  text-transform:uppercase;letter-spacing:.1em;font-family:'JetBrains Mono',monospace;}
.nav-item{
  display:flex;align-items:center;gap:10px;padding:10px 20px;color:var(--muted);
  font-size:13px;font-weight:500;transition:all .15s;border-left:3px solid transparent;
}
.nav-item:hover,.nav-item.active{color:var(--text);background:var(--surface2);border-left-color:var(--accent);}
.nav-item .ico{font-size:16px;width:20px;text-align:center;}
.nav-bottom{margin-top:auto;padding:16px;}
.nav-bottom a{
  display:block;text-align:center;padding:9px;
  background:rgba(247,79,106,.08);border:1px solid rgba(247,79,106,.2);
  border-radius:var(--radius);color:var(--danger);font-size:12px;font-weight:700;transition:all .15s;
}
.nav-bottom a:hover{background:rgba(247,79,106,.15);}

/* ── Main ── */
.main{margin-left:220px;flex:1;padding:28px 32px;min-height:100vh;}
.page-title{font-size:26px;font-weight:900;letter-spacing:-0.5px;margin-bottom:4px;}
.page-sub{color:var(--muted);font-size:11px;margin-bottom:28px;font-family:'JetBrains Mono',monospace;}

/* ── Stat Cards ── */
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin-bottom:28px;}
.card{
  background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
  padding:18px;position:relative;overflow:hidden;transition:border-color .2s;
}
.card:hover{border-color:var(--accent);}
.card::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;}
.card.blue::before{background:linear-gradient(90deg,var(--accent),transparent);}
.card.pink::before{background:linear-gradient(90deg,var(--accent2),transparent);}
.card.green::before{background:linear-gradient(90deg,var(--accent3),transparent);}
.card.yellow::before{background:linear-gradient(90deg,var(--accent4),transparent);}
.card-ico{font-size:24px;margin-bottom:10px;}
.card-val{font-size:30px;font-weight:900;letter-spacing:-1px;line-height:1;}
.card-lbl{font-size:10px;color:var(--muted);margin-top:5px;font-family:'JetBrains Mono',monospace;text-transform:uppercase;}

/* ── Charts ── */
.chart-wrap{
  background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
  padding:20px;margin-bottom:20px;
}
.chart-wrap h3{font-size:14px;font-weight:700;margin-bottom:16px;}
.chart-container{position:relative;width:100%;}
.chart-container canvas{max-width:100%;}

/* ── Table ── */
.table-wrap{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;margin-bottom:20px;}
.table-header{
  padding:14px 18px;border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;
}
.table-header h3{font-size:14px;font-weight:700;}
table{width:100%;border-collapse:collapse;}
th{
  padding:10px 14px;text-align:left;font-size:10px;font-weight:700;color:var(--muted);
  background:var(--surface2);text-transform:uppercase;letter-spacing:.08em;
  font-family:'JetBrains Mono',monospace;
}
td{padding:10px 14px;font-size:12px;border-bottom:1px solid var(--border);}
tr:last-child td{border-bottom:none;}
tr:hover td{background:var(--surface2);}

/* ── Badges ── */
.badge{
  display:inline-block;padding:2px 8px;border-radius:4px;
  font-size:10px;font-weight:700;font-family:'JetBrains Mono',monospace;
}
.bg{background:rgba(79,142,247,.1);color:var(--accent);border:1px solid rgba(79,142,247,.2);}
.br{background:rgba(247,79,106,.1);color:var(--danger);border:1px solid rgba(247,79,106,.2);}
.bg3{background:rgba(79,247,160,.1);color:var(--accent3);border:1px solid rgba(79,247,160,.2);}
.by{background:rgba(247,196,79,.1);color:var(--accent4);border:1px solid rgba(247,196,79,.2);}
.bm{background:rgba(247,79,142,.1);color:var(--accent2);border:1px solid rgba(247,79,142,.2);}

/* ── Buttons ── */
.btn{
  padding:7px 14px;border-radius:7px;font-size:12px;font-weight:700;cursor:pointer;
  border:none;transition:all .15s;font-family:'DM Sans',sans-serif;display:inline-block;
}
.btn-blue{background:var(--accent);color:#fff;}
.btn-blue:hover{background:#3d7de8;transform:translateY(-1px);}
.btn-red{background:rgba(247,79,106,.1);color:var(--danger);border:1px solid rgba(247,79,106,.25);}
.btn-red:hover{background:rgba(247,79,106,.2);}
.btn-green{background:rgba(79,247,160,.1);color:var(--accent3);border:1px solid rgba(79,247,160,.25);}
.btn-green:hover{background:rgba(79,247,160,.2);}
.btn-yellow{background:rgba(247,196,79,.1);color:var(--accent4);border:1px solid rgba(247,196,79,.25);}
.btn-yellow:hover{background:rgba(247,196,79,.2);}
.btn-sm{padding:4px 9px;font-size:10px;}
.btn-xs{padding:3px 7px;font-size:10px;}

/* ── Forms ── */
.form-group{margin-bottom:14px;}
.form-label{display:block;font-size:10px;font-weight:700;color:var(--muted);margin-bottom:5px;
  text-transform:uppercase;letter-spacing:.06em;font-family:'JetBrains Mono',monospace;}
.form-input,.form-select,.form-textarea{
  width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:7px;
  padding:9px 12px;color:var(--text);font-size:13px;font-family:'DM Sans',sans-serif;transition:border-color .2s;
}
.form-input:focus,.form-select:focus,.form-textarea:focus{outline:none;border-color:var(--accent);}
.form-select option{background:var(--surface2);}
.form-textarea{resize:vertical;min-height:90px;}

/* ── Alert ── */
.alert{padding:11px 15px;border-radius:8px;margin-bottom:14px;font-size:12px;font-weight:500;}
.alert-success{background:rgba(79,247,160,.08);border:1px solid rgba(79,247,160,.25);color:var(--accent3);}
.alert-error{background:rgba(247,79,106,.08);border:1px solid rgba(247,79,106,.25);color:var(--danger);}
.alert-info{background:rgba(79,142,247,.08);border:1px solid rgba(79,142,247,.25);color:var(--accent);}

/* ── Login ── */
.login-wrap{width:100%;height:100vh;display:flex;align-items:center;justify-content:center;}
.login-box{width:360px;background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:36px;}
.login-box h1{font-size:22px;font-weight:900;margin-bottom:4px;}
.login-box p{color:var(--muted);font-size:12px;margin-bottom:24px;}

/* ── Section / Grid ── */
.section{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:20px;margin-bottom:20px;}
.section h3{font-size:14px;font-weight:700;margin-bottom:14px;}
.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:20px;}
.grid-3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;}
@media(max-width:900px){.grid-2,.grid-3{grid-template-columns:1fr;}}

/* ── Search bar ── */
.search-bar{display:flex;gap:8px;align-items:center;}
.search-bar input{
  background:var(--surface2);border:1px solid var(--border);border-radius:7px;
  padding:7px 12px;color:var(--text);font-size:12px;font-family:'DM Sans',sans-serif;min-width:200px;
}
.search-bar input:focus{outline:none;border-color:var(--accent);}

/* ── Modal ── */
.modal-bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:500;
  align-items:center;justify-content:center;}
.modal-bg.open{display:flex;}
.modal{background:var(--surface);border:1px solid var(--border);border-radius:14px;
  padding:28px;width:460px;max-width:90vw;max-height:85vh;overflow-y:auto;}
.modal h3{font-size:16px;font-weight:800;margin-bottom:16px;}
.modal-close{float:right;background:none;border:none;color:var(--muted);
  font-size:18px;cursor:pointer;margin-top:-4px;}

/* ── Responsive ── */
@media(max-width:768px){
  .sidebar{width:54px;}
  .sidebar-logo,.nav-item span,.nav-section{display:none;}
  .nav-item{padding:14px;justify-content:center;}
  .main{margin-left:54px;padding:14px;}
}

/* ── Misc ── */
.text-muted{color:var(--muted);}
.mono{font-family:'JetBrains Mono',monospace;font-size:11px;}
.tag-chip{
  display:inline-block;padding:2px 7px;background:var(--surface3);
  border-radius:4px;font-size:10px;color:var(--muted);margin:1px;
}
.user-id{color:var(--accent);font-family:'JetBrains Mono',monospace;font-size:11px;}
.divider{border:none;border-top:1px solid var(--border);margin:16px 0;}
</style>
</head>
<body>
{% if logged_in %}
<div class="sidebar">
  <div class="sidebar-logo">
    <h1>🤖 BotAdmin</h1>
    <p>CONTROL PANEL v3</p>
  </div>
  <div class="nav-section">Overview</div>
  <a href="/admin" class="nav-item {% if page=='dashboard' %}active{% endif %}">
    <span class="ico">📊</span><span>Dashboard</span>
  </a>
  <div class="nav-section">Data</div>
  <a href="/admin/users" class="nav-item {% if page=='users' %}active{% endif %}">
    <span class="ico">👥</span><span>Users</span>
  </a>
  <a href="/admin/expenses" class="nav-item {% if page=='expenses' %}active{% endif %}">
    <span class="ico">💰</span><span>Expenses</span>
  </a>
  <a href="/admin/notes" class="nav-item {% if page=='notes' %}active{% endif %}">
    <span class="ico">📝</span><span>Notes</span>
  </a>
  <a href="/admin/stats" class="nav-item {% if page=='stats' %}active{% endif %}">
    <span class="ico">📈</span><span>Stats</span>
  </a>
  <div class="nav-section">Tools</div>
  <a href="/admin/admins" class="nav-item {% if page=='admins' %}active{% endif %}">
    <span class="ico">👑</span><span>Bot Admins</span>
  </a>
  <a href="/admin/broadcast" class="nav-item {% if page=='broadcast' %}active{% endif %}">
    <span class="ico">📢</span><span>Broadcast</span>
  </a>
  <a href="/admin/bot_control" class="nav-item {% if page=='bot_control' %}active{% endif %}">
    <span class="ico">🤖</span><span>Bot Control</span>
  </a>
  <a href="/admin/errors" class="nav-item {% if page=='errors' %}active{% endif %}">
    <span class="ico">⚠️</span><span>Error Logs</span>
  </a>
  <div class="nav-bottom">
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
    return render_template_string(BASE_HTML, content=Markup(content), logged_in=logged_in, page=page)


# ─────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────

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
    try:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        return cur.fetchone()
    except Exception as e:
        logger.warning(f"Query error: {e}")
        return None

def _send_tg(text_or_coro):
    """Run async telegram call from sync context."""
    import asyncio
    if _bot_app is None:
        return False
    try:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(text_or_coro)
        loop.close()
        return True
    except Exception as e:
        logger.warning(f"TG send error: {e}")
        return False

def _json_list(rows, key):
    """Extract a column from rows into a JSON-safe list."""
    import json
    return json.dumps([str(r[key]) if r[key] is not None else "" for r in rows])

def _json_vals(rows, key):
    """Extract numeric column from rows."""
    import json
    return json.dumps([float(r[key]) if r[key] is not None else 0 for r in rows])


# ─────────────────────────────────────────────────────────────────
# REGISTER ALL ROUTES
# ─────────────────────────────────────────────────────────────────

def register_dashboard(flask_app: Flask, secret_key: str = "bot-secret-2024",
                       password: str = "admin1234", super_admin_ids=None):
    super_admin_ids = list(super_admin_ids or [])
    flask_app.secret_key = os.environ.get("SECRET_KEY", secret_key)
    global DASHBOARD_PASSWORD
    DASHBOARD_PASSWORD = os.environ.get("ADMIN_PASSWORD", password)

    # ── LOGIN ──────────────────────────────────────────────────────
    @flask_app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        error = ""
        if request.method == "POST":
            if request.form.get("password") == DASHBOARD_PASSWORD:
                session["logged_in"] = True
                return redirect("/admin")
            error = "❌ Wrong password!"
        content = f"""
        <div class="login-wrap">
          <div class="login-box">
            <h1>🤖 Bot Admin</h1>
            <p>Enter your admin password to continue</p>
            {'<div class="alert alert-error">'+error+'</div>' if error else ''}
            <form method="POST">
              <div class="form-group">
                <label class="form-label">Password</label>
                <input type="password" name="password" class="form-input" placeholder="••••••••" autofocus>
              </div>
              <button type="submit" class="btn btn-blue" style="width:100%;margin-top:4px">Login →</button>
            </form>
          </div>
        </div>"""
        return render_page(content, logged_in=False)

    @flask_app.route("/admin/logout")
    def admin_logout():
        session.clear()
        return redirect("/admin/login")

    # ── DASHBOARD HOME ─────────────────────────────────────────────
    @flask_app.route("/admin")
    @login_required
    def admin_home():
        conn = db()
        total_users    = (_safe_one(conn, "SELECT COUNT(*) AS c FROM users") or {}).get('c', 0)
        total_expenses = (_safe_one(conn, "SELECT COALESCE(SUM(amount),0) AS c FROM expenses") or {}).get('c', 0)
        total_notes    = (_safe_one(conn, "SELECT COUNT(*) AS c FROM notes") or {}).get('c', 0)
        total_errors   = (_safe_one(conn, "SELECT COUNT(*) AS c FROM error_logs") or {}).get('c', 0)
        new_today      = (_safe_one(conn, "SELECT COUNT(*) AS c FROM users WHERE created_at::date = CURRENT_DATE") or {}).get('c', 0)
        expense_today  = (_safe_one(conn, "SELECT COALESCE(SUM(amount),0) AS c FROM expenses WHERE date = CURRENT_DATE") or {}).get('c', 0)

        top_cats  = _safe_query(conn, "SELECT category, SUM(amount) as total FROM expenses GROUP BY category ORDER BY total DESC LIMIT 6")
        recent_users = _safe_query(conn, "SELECT user_id, username, language, created_at FROM users ORDER BY created_at DESC LIMIT 8")
        recent_expenses = _safe_query(conn, """
            SELECT e.id, e.user_id, u.username, e.category, e.amount, e.note, e.date
            FROM expenses e LEFT JOIN users u ON e.user_id=u.user_id
            ORDER BY e.created_at DESC LIMIT 8
        """)

        # ── Chart data: last 7 days spending ──
        daily_data = _safe_query(conn, """
            SELECT to_char(date, 'Mon DD') as day, COALESCE(SUM(amount),0) as total
            FROM expenses
            WHERE date >= CURRENT_DATE - INTERVAL '6 days'
            GROUP BY date, day ORDER BY date ASC
        """)

        # ── Chart data: category doughnut ──
        cat_chart = _safe_query(conn, """
            SELECT category, SUM(amount) as total FROM expenses
            GROUP BY category ORDER BY total DESC LIMIT 8
        """)

        conn.close()

        # Chart JSON
        import json
        daily_labels = json.dumps([r['day'] for r in daily_data])
        daily_vals   = json.dumps([float(r['total']) for r in daily_data])
        cat_labels   = json.dumps([r['category'] or 'Other' for r in cat_chart])
        cat_vals     = json.dumps([float(r['total']) for r in cat_chart])

        cat_rows = "".join(f"""
            <tr>
              <td>{r['category'] or 'N/A'}</td>
              <td><span class="badge bg">${r['total']:.2f}</span></td>
            </tr>""" for r in top_cats) or "<tr><td colspan='2' class='text-muted'>No data</td></tr>"

        user_rows = "".join(f"""
            <tr>
              <td><a href="/admin/user/{r['user_id']}" class="user-id">{r['user_id']}</a></td>
              <td>{r['username'] or '—'}</td>
              <td><span class="badge bg3">{r['language'].upper()}</span></td>
              <td class="text-muted mono">{str(r['created_at'])[:10]}</td>
            </tr>""" for r in recent_users)

        exp_rows = "".join(f"""
            <tr>
              <td><a href="/admin/user/{r['user_id']}" class="user-id">{r['user_id']}</a></td>
              <td>{r['username'] or '—'}</td>
              <td><span class="badge by">{r['category'] or '?'}</span></td>
              <td><span class="badge bg">${r['amount']:.2f}</span></td>
              <td class="text-muted" style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{r['note'] or '—'}</td>
              <td class="text-muted mono">{str(r['date'])[:10]}</td>
              <td><a href="/admin/expense/delete/{r['id']}" class="btn btn-red btn-xs" onclick="return confirm('Delete?')">🗑</a></td>
            </tr>""" for r in recent_expenses)

        content = f"""
        <div class="page-title">Dashboard</div>
        <div class="page-sub">OVERVIEW // {datetime.now().strftime('%Y-%m-%d %H:%M')} // Bot: {'🟢 ONLINE' if _bot_app else '🔴 OFFLINE'}</div>
        <div class="cards">
          <div class="card blue">
            <div class="card-ico">👥</div>
            <div class="card-val">{total_users}</div>
            <div class="card-lbl">Total Users (+{new_today} today)</div>
          </div>
          <div class="card pink">
            <div class="card-ico">💰</div>
            <div class="card-val">${float(total_expenses):.0f}</div>
            <div class="card-lbl">All-Time Expenses (${float(expense_today):.0f} today)</div>
          </div>
          <div class="card green">
            <div class="card-ico">📝</div>
            <div class="card-val">{total_notes}</div>
            <div class="card-lbl">Total Notes</div>
          </div>
          <div class="card yellow">
            <div class="card-ico">⚠️</div>
            <div class="card-val">{total_errors}</div>
            <div class="card-lbl">Error Logs</div>
          </div>
        </div>

        <!-- ── CHARTS ROW ── -->
        <div class="grid-2" style="margin-bottom:20px">
          <div class="chart-wrap">
            <h3>📅 Spending — Last 7 Days</h3>
            <div class="chart-container" style="height:200px">
              <canvas id="dailyChart"></canvas>
            </div>
          </div>
          <div class="chart-wrap">
            <h3>🍩 Spending by Category</h3>
            <div class="chart-container" style="height:200px">
              <canvas id="catChart"></canvas>
            </div>
          </div>
        </div>

        <div class="grid-2">
          <div class="table-wrap">
            <div class="table-header"><h3>🏆 Top Categories</h3></div>
            <table><thead><tr><th>Category</th><th>Total</th></tr></thead>
            <tbody>{cat_rows}</tbody></table>
          </div>
          <div class="table-wrap">
            <div class="table-header">
              <h3>🆕 Recent Users</h3>
              <a href="/admin/users" class="btn btn-blue btn-sm">View All</a>
            </div>
            <table><thead><tr><th>ID</th><th>Username</th><th>Lang</th><th>Joined</th></tr></thead>
            <tbody>{user_rows}</tbody></table>
          </div>
        </div>
        <div class="table-wrap">
          <div class="table-header">
            <h3>💸 Recent Expenses</h3>
            <a href="/admin/expenses" class="btn btn-blue btn-sm">View All</a>
          </div>
          <table><thead><tr><th>User ID</th><th>Username</th><th>Category</th><th>Amount</th><th>Note</th><th>Date</th><th></th></tr></thead>
          <tbody>{exp_rows or "<tr><td colspan='7' class='text-muted' style='text-align:center;padding:20px'>No expenses yet</td></tr>"}</tbody>
        </table></div>

        <script>
        const CHART_DEFAULTS = {{
          responsive: true,
          maintainAspectRatio: false,
          plugins: {{ legend: {{ labels: {{ color: '#8899bb', font: {{ size: 11 }} }} }} }},
        }};

        // Daily spending line chart
        new Chart(document.getElementById('dailyChart'), {{
          type: 'line',
          data: {{
            labels: {daily_labels},
            datasets: [{{
              label: 'Spending ($)',
              data: {daily_vals},
              borderColor: '#4f8ef7',
              backgroundColor: 'rgba(79,142,247,0.12)',
              fill: true,
              tension: 0.4,
              pointBackgroundColor: '#4f8ef7',
              pointRadius: 4,
            }}]
          }},
          options: {{
            ...CHART_DEFAULTS,
            scales: {{
              x: {{ ticks: {{ color: '#5a6a8a', font: {{ size: 10 }} }}, grid: {{ color: '#1e2535' }} }},
              y: {{ ticks: {{ color: '#5a6a8a', font: {{ size: 10 }}, callback: v => '$'+v }}, grid: {{ color: '#1e2535' }} }}
            }}
          }}
        }});

        // Category doughnut
        new Chart(document.getElementById('catChart'), {{
          type: 'doughnut',
          data: {{
            labels: {cat_labels},
            datasets: [{{
              data: {cat_vals},
              backgroundColor: [
                'rgba(79,142,247,.7)','rgba(247,79,142,.7)','rgba(79,247,160,.7)',
                'rgba(247,196,79,.7)','rgba(157,79,247,.7)','rgba(247,157,79,.7)',
                'rgba(79,247,247,.7)','rgba(247,79,79,.7)'
              ],
              borderWidth: 0,
            }}]
          }},
          options: {{
            ...CHART_DEFAULTS,
            cutout: '65%',
            plugins: {{ legend: {{ position: 'right', labels: {{ color: '#8899bb', font: {{ size: 10 }}, boxWidth: 10 }} }} }}
          }}
        }});
        </script>"""

        return render_page(content, page="dashboard")

    # ── USERS LIST ─────────────────────────────────────────────────
    @flask_app.route("/admin/users")
    @login_required
    def admin_users():
        conn = db()
        q = request.args.get("q", "").strip()
        if q:
            users = _safe_query(conn, """
                SELECT u.user_id, u.username, u.language, u.daily_reminder, u.budget, u.created_at,
                       COUNT(DISTINCT e.id) as expense_count, COUNT(DISTINCT n.id) as note_count
                FROM users u
                LEFT JOIN expenses e ON u.user_id=e.user_id
                LEFT JOIN notes n ON u.user_id=n.user_id
                WHERE u.username ILIKE %s OR u.user_id::text = %s
                GROUP BY u.user_id ORDER BY u.created_at DESC
            """, (f"%{q}%", q))
        else:
            users = _safe_query(conn, """
                SELECT u.user_id, u.username, u.language, u.daily_reminder, u.budget, u.created_at,
                       COUNT(DISTINCT e.id) as expense_count, COUNT(DISTINCT n.id) as note_count
                FROM users u
                LEFT JOIN expenses e ON u.user_id=e.user_id
                LEFT JOIN notes n ON u.user_id=n.user_id
                GROUP BY u.user_id ORDER BY u.created_at DESC
            """)

        try:
            banned_rows = _safe_query(conn, "SELECT user_id FROM banned_users")
            banned_ids = {r['user_id'] for r in banned_rows}
        except Exception:
            banned_ids = set()
        conn.close()

        msg = request.args.get("msg", "")
        alert = f'<div class="alert alert-success">{msg}</div>' if msg else ""

        rows = "".join(f"""
            <tr>
              <td><a href="/admin/user/{u['user_id']}" class="user-id">{u['user_id']}</a></td>
              <td>{u['username'] or '—'}</td>
              <td><span class="badge bg3">{(u['language'] or 'km').upper()}</span></td>
              <td style='text-align:center'>{u['expense_count']}</td>
              <td style='text-align:center'>{u['note_count']}</td>
              <td><span class="badge {'bg3' if u['daily_reminder'] else 'br'}">{'ON' if u['daily_reminder'] else 'OFF'}</span></td>
              <td class="text-muted mono">{str(u['created_at'])[:10]}</td>
              <td style='display:flex;gap:4px;flex-wrap:wrap;padding:8px 14px'>
                <a href="/admin/user/{u['user_id']}" class="btn btn-blue btn-xs">👁</a>
                {'<a href="/admin/unban/'+str(u["user_id"])+'" class="btn btn-green btn-xs">✅ Unban</a>' if u['user_id'] in banned_ids else '<a href="/admin/ban/'+str(u["user_id"])+'" class="btn btn-red btn-xs">🚫 Ban</a>'}
                <a href="/admin/delete_user/{u['user_id']}" class="btn btn-red btn-xs" onclick="return confirm('Delete user {u['user_id']} and ALL their data?')">🗑</a>
              </td>
            </tr>""" for u in users)

        content = f"""
        {alert}
        <div class="page-title">Users</div>
        <div class="page-sub">TOTAL: {len(users)} USERS</div>
        <div class="table-wrap">
          <div class="table-header">
            <h3>👥 All Users</h3>
            <form method="GET" class="search-bar">
              <input name="q" value="{q}" placeholder="Search user ID or username...">
              <button type="submit" class="btn btn-blue btn-sm">Search</button>
              {'<a href="/admin/users" class="btn btn-sm" style="background:var(--surface3);color:var(--muted)">Clear</a>' if q else ''}
            </form>
          </div>
          <table>
            <thead><tr>
              <th>User ID</th><th>Username</th><th>Lang</th>
              <th>Expenses</th><th>Notes</th><th>Reminder</th>
              <th>Joined</th><th>Actions</th>
            </tr></thead>
            <tbody>{rows or "<tr><td colspan='8' class='text-muted' style='text-align:center;padding:20px'>No users found</td></tr>"}</tbody>
          </table>
        </div>"""
        return render_page(content, page="users")

    # ── USER DETAIL ────────────────────────────────────────────────
    @flask_app.route("/admin/user/<int:uid>")
    @login_required
    def admin_user_detail(uid):
        conn = db()
        user = _safe_one(conn, "SELECT * FROM users WHERE user_id=%s", (uid,))
        if not user:
            conn.close()
            return redirect("/admin/users")

        expenses = _safe_query(conn, """
            SELECT id, category, amount, note, tag, date FROM expenses
            WHERE user_id=%s ORDER BY date DESC LIMIT 30
        """, (uid,))
        notes = _safe_query(conn, "SELECT id, content, created_at FROM notes WHERE user_id=%s ORDER BY created_at DESC LIMIT 20", (uid,))
        total_spent = (_safe_one(conn, "SELECT COALESCE(SUM(amount),0) AS t FROM expenses WHERE user_id=%s", (uid,)) or {}).get('t', 0)

        # User's spending by category
        user_cats = _safe_query(conn, """
            SELECT category, SUM(amount) as total FROM expenses
            WHERE user_id=%s GROUP BY category ORDER BY total DESC LIMIT 8
        """, (uid,))

        # User's spending last 6 months
        user_monthly = _safe_query(conn, """
            SELECT to_char(date, 'Mon YY') as month, SUM(amount) as total
            FROM expenses WHERE user_id=%s
            GROUP BY to_char(date,'Mon YY'), date_trunc('month', date)
            ORDER BY date_trunc('month', date) ASC LIMIT 6
        """, (uid,))

        conn.close()

        import json
        uc_labels = json.dumps([r['category'] or 'Other' for r in user_cats])
        uc_vals   = json.dumps([float(r['total']) for r in user_cats])
        um_labels = json.dumps([r['month'] for r in user_monthly])
        um_vals   = json.dumps([float(r['total']) for r in user_monthly])

        msg = request.args.get("msg", "")
        alert = f'<div class="alert alert-success">{msg}</div>' if msg else ""

        exp_rows = "".join(f"""
            <tr>
              <td><span class="badge by">{e['category'] or '?'}</span></td>
              <td><span class="badge bg">${e['amount']:.2f}</span></td>
              <td class="text-muted" style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{e['note'] or '—'}</td>
              <td>{('<span class="tag-chip">'+e['tag']+'</span>') if e['tag'] else '—'}</td>
              <td class="text-muted mono">{str(e['date'])[:10]}</td>
              <td><a href="/admin/expense/delete/{e['id']}" class="btn btn-red btn-xs" onclick="return confirm('Delete?')">🗑</a></td>
            </tr>""" for e in expenses)

        note_rows = "".join(f"""
            <tr>
              <td style="max-width:400px">{n['content']}</td>
              <td class="text-muted mono">{str(n['created_at'])[:16]}</td>
              <td><a href="/admin/note/delete/{n['id']}?uid={uid}" class="btn btn-red btn-xs" onclick="return confirm('Delete note?')">🗑</a></td>
            </tr>""" for n in notes)

        content = f"""
        {alert}
        <div style="display:flex;align-items:center;gap:16px;margin-bottom:4px">
          <a href="/admin/users" class="btn btn-sm" style="background:var(--surface2);color:var(--muted)">← Back</a>
          <div class="page-title">User {uid}</div>
        </div>
        <div class="page-sub">@{user['username'] or 'no username'} // Joined {str(user['created_at'])[:10]}</div>

        <div class="grid-3" style="margin-bottom:20px">
          <div class="card blue"><div class="card-ico">💰</div><div class="card-val">${float(total_spent):.0f}</div><div class="card-lbl">Total Spent</div></div>
          <div class="card green"><div class="card-ico">🧾</div><div class="card-val">{len(expenses)}</div><div class="card-lbl">Expenses (last 30)</div></div>
          <div class="card yellow"><div class="card-ico">📝</div><div class="card-val">{len(notes)}</div><div class="card-lbl">Notes</div></div>
        </div>

        <!-- User charts -->
        <div class="grid-2" style="margin-bottom:20px">
          <div class="chart-wrap">
            <h3>📊 Monthly Spending</h3>
            <div class="chart-container" style="height:180px">
              <canvas id="userMonthlyChart"></canvas>
            </div>
          </div>
          <div class="chart-wrap">
            <h3>🍩 By Category</h3>
            <div class="chart-container" style="height:180px">
              <canvas id="userCatChart"></canvas>
            </div>
          </div>
        </div>

        <div class="grid-2">
          <div class="section">
            <h3>📋 User Info</h3>
            <table style="width:100%">
              <tr><td class="text-muted mono" style="padding:6px 0;width:120px">user_id</td><td><span class="user-id">{user['user_id']}</span></td></tr>
              <tr><td class="text-muted mono" style="padding:6px 0">username</td><td>@{user['username'] or '—'}</td></tr>
              <tr><td class="text-muted mono" style="padding:6px 0">language</td><td><span class="badge bg3">{(user['language'] or 'km').upper()}</span></td></tr>
              <tr><td class="text-muted mono" style="padding:6px 0">budget</td><td>${user['budget'] or 0:.2f}</td></tr>
              <tr><td class="text-muted mono" style="padding:6px 0">reminder</td><td><span class="badge {'bg3' if user['daily_reminder'] else 'br'}">{'ON' if user['daily_reminder'] else 'OFF'}</span> {user['reminder_time'] or ''}</td></tr>
              <tr><td class="text-muted mono" style="padding:6px 0">pin set</td><td>{'✅ Yes' if user['pin'] else '❌ No'}</td></tr>
            </table>
          </div>
          <div class="section">
            <h3>📨 Send Telegram Message</h3>
            <form method="POST" action="/admin/user/{uid}/send">
              <div class="form-group">
                <label class="form-label">Message to user</label>
                <textarea name="message" class="form-textarea" placeholder="Type message to send via Telegram..."></textarea>
              </div>
              <button type="submit" class="btn btn-blue">📤 Send via Telegram</button>
            </form>
            <hr class="divider">
            <div style="display:flex;gap:8px;flex-wrap:wrap">
              <a href="/admin/ban/{uid}?from=user" class="btn btn-red btn-sm">🚫 Ban User</a>
              <a href="/admin/unban/{uid}?from=user" class="btn btn-green btn-sm">✅ Unban</a>
              <a href="/admin/delete_user/{uid}" class="btn btn-red btn-sm" onclick="return confirm('Delete user and ALL data?')">🗑 Delete User</a>
            </div>
          </div>
        </div>

        <div class="table-wrap">
          <div class="table-header">
            <h3>💸 Expenses</h3>
            <a href="/admin/expenses?uid={uid}" class="btn btn-blue btn-sm">View All</a>
          </div>
          <table><thead><tr><th>Category</th><th>Amount</th><th>Note</th><th>Tag</th><th>Date</th><th></th></tr></thead>
          <tbody>{exp_rows or "<tr><td colspan='6' class='text-muted' style='text-align:center;padding:16px'>No expenses</td></tr>"}</tbody></table>
        </div>

        <div class="table-wrap">
          <div class="table-header"><h3>📝 Notes</h3></div>
          <table><thead><tr><th>Content</th><th>Created</th><th></th></tr></thead>
          <tbody>{note_rows or "<tr><td colspan='3' class='text-muted' style='text-align:center;padding:16px'>No notes</td></tr>"}</tbody></table>
        </div>

        <script>
        const CD = {{
          responsive:true, maintainAspectRatio:false,
          plugins:{{legend:{{labels:{{color:'#8899bb',font:{{size:10}}}}}}}}
        }};
        new Chart(document.getElementById('userMonthlyChart'), {{
          type:'bar',
          data:{{
            labels:{um_labels},
            datasets:[{{label:'Spending ($)',data:{um_vals},
              backgroundColor:'rgba(79,142,247,.55)',borderColor:'#4f8ef7',borderWidth:1,borderRadius:4}}]
          }},
          options:{{...CD,scales:{{
            x:{{ticks:{{color:'#5a6a8a',font:{{size:10}}}},grid:{{color:'#1e2535'}}}},
            y:{{ticks:{{color:'#5a6a8a',font:{{size:10}},callback:v=>'$'+v}},grid:{{color:'#1e2535'}}}}
          }}}}
        }});
        new Chart(document.getElementById('userCatChart'), {{
          type:'doughnut',
          data:{{
            labels:{uc_labels},
            datasets:[{{data:{uc_vals},
              backgroundColor:['rgba(79,142,247,.7)','rgba(247,79,142,.7)','rgba(79,247,160,.7)',
              'rgba(247,196,79,.7)','rgba(157,79,247,.7)','rgba(247,157,79,.7)','rgba(79,247,247,.7)','rgba(247,79,79,.7)'],
              borderWidth:0}}]
          }},
          options:{{...CD,cutout:'60%',plugins:{{legend:{{position:'right',labels:{{color:'#8899bb',font:{{size:10}},boxWidth:10}}}}}}}}
        }});
        </script>"""
        return render_page(content, page="users")

    # ── SEND MSG TO USER ───────────────────────────────────────────
    @flask_app.route("/admin/user/<int:uid>/send", methods=["POST"])
    @login_required
    def admin_send_message(uid):
        message = request.form.get("message", "").strip()
        if message and _bot_app:
            import asyncio
            async def _send():
                await _bot_app.bot.send_message(
                    chat_id=uid,
                    text=f"📬 *Message from Admin:*\n\n{message}",
                    parse_mode="Markdown"
                )
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(_send())
                loop.close()
                return redirect(f"/admin/user/{uid}?msg=✅ Message sent!")
            except Exception as e:
                return redirect(f"/admin/user/{uid}?msg=❌ Failed: {e}")
        return redirect(f"/admin/user/{uid}?msg=❌ Bot not connected or empty message")

    # ── DELETE USER ────────────────────────────────────────────────
    @flask_app.route("/admin/delete_user/<int:uid>")
    @login_required
    def admin_delete_user(uid):
        conn = db()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM expenses WHERE user_id=%s", (uid,))
            cur.execute("DELETE FROM notes WHERE user_id=%s", (uid,))
            cur.execute("DELETE FROM chat_memory WHERE user_id=%s", (uid,))
            cur.execute("DELETE FROM error_logs WHERE user_id=%s", (uid,))
            cur.execute("DELETE FROM users WHERE user_id=%s", (uid,))
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Delete user error: {e}")
        finally:
            conn.close()
        return redirect("/admin/users?msg=✅ User deleted")

    # ── BAN / UNBAN ────────────────────────────────────────────────
    @flask_app.route("/admin/ban/<int:uid>")
    @login_required
    def admin_ban(uid):
        conn = db()
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS banned_users (
                    user_id BIGINT PRIMARY KEY,
                    banned_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("INSERT INTO banned_users (user_id) VALUES (%s) ON CONFLICT DO NOTHING", (uid,))
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Ban error: {e}")
        finally:
            conn.close()
        back = request.args.get("from", "")
        return redirect(f"/admin/user/{uid}" if back == "user" else "/admin/users")

    @flask_app.route("/admin/unban/<int:uid>")
    @login_required
    def admin_unban(uid):
        conn = db()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM banned_users WHERE user_id=%s", (uid,))
            conn.commit()
        except Exception as e:
            conn.rollback()
        finally:
            conn.close()
        back = request.args.get("from", "")
        return redirect(f"/admin/user/{uid}" if back == "user" else "/admin/users")

    # ── EXPENSES LIST (CRUD) ────────────────────────────────────────
    @flask_app.route("/admin/expenses")
    @login_required
    def admin_expenses():
        conn = db()
        uid_filter = request.args.get("uid", "").strip()
        cat_filter = request.args.get("cat", "").strip()
        q = request.args.get("q", "").strip()
        page_num = int(request.args.get("page", 1))
        per_page = 50
        offset = (page_num - 1) * per_page

        where = "WHERE 1=1"
        params = []
        if uid_filter:
            where += " AND e.user_id=%s"; params.append(uid_filter)
        if cat_filter:
            where += " AND e.category ILIKE %s"; params.append(f"%{cat_filter}%")
        if q:
            where += " AND (e.note ILIKE %s OR e.tag ILIKE %s)"; params += [f"%{q}%", f"%{q}%"]

        expenses = _safe_query(conn, f"""
            SELECT e.id, e.user_id, u.username, e.category, e.amount, e.note, e.tag, e.date
            FROM expenses e LEFT JOIN users u ON e.user_id=u.user_id
            {where} ORDER BY e.date DESC, e.id DESC LIMIT %s OFFSET %s
        """, params + [per_page, offset])

        total_count = (_safe_one(conn, f"SELECT COUNT(*) AS c FROM expenses e {where}", params) or {}).get('c', 0)
        categories = _safe_query(conn, "SELECT DISTINCT category FROM expenses ORDER BY category")
        conn.close()

        msg = request.args.get("msg", "")
        alert = f'<div class="alert alert-success">{msg}</div>' if msg else ""

        cat_opts = "".join(f'<option value="{c["category"]}" {"selected" if cat_filter==c["category"] else ""}>{c["category"]}</option>' for c in categories)

        rows = "".join(f"""
            <tr>
              <td class="mono" style="color:var(--muted)">{e['id']}</td>
              <td><a href="/admin/user/{e['user_id']}" class="user-id">{e['user_id']}</a></td>
              <td>{e['username'] or '—'}</td>
              <td><span class="badge by">{e['category'] or '?'}</span></td>
              <td><span class="badge bg">${e['amount']:.2f}</span></td>
              <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{e['note'] or '—'}</td>
              <td>{('<span class="tag-chip">'+e['tag']+'</span>') if e['tag'] else '—'}</td>
              <td class="text-muted mono">{str(e['date'])[:10]}</td>
              <td style="display:flex;gap:4px">
                <a href="/admin/expense/edit/{e['id']}" class="btn btn-yellow btn-xs">✏️</a>
                <a href="/admin/expense/delete/{e['id']}" class="btn btn-red btn-xs" onclick="return confirm('Delete expense #{e['id']}?')">🗑</a>
              </td>
            </tr>""" for e in expenses)

        total_pages = (total_count + per_page - 1) // per_page
        pagination = ""
        if total_pages > 1:
            pagination = '<div style="display:flex;gap:6px;margin-top:12px;justify-content:center">'
            for p in range(1, total_pages + 1):
                active_style = "background:var(--accent);color:#fff;" if p == page_num else "background:var(--surface2);color:var(--muted);"
                pagination += f'<a href="?page={p}&uid={uid_filter}&cat={cat_filter}&q={q}" class="btn btn-xs" style="{active_style}">{p}</a>'
            pagination += '</div>'

        content = f"""
        {alert}
        <div class="page-title">Expenses</div>
        <div class="page-sub">{total_count} TOTAL RECORDS</div>

        <div class="section" style="margin-bottom:20px">
          <form method="GET" style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end">
            <div><label class="form-label">User ID</label><input name="uid" value="{uid_filter}" class="form-input" style="width:130px" placeholder="User ID"></div>
            <div><label class="form-label">Category</label>
              <select name="cat" class="form-select" style="width:140px">
                <option value="">All Categories</option>{cat_opts}
              </select>
            </div>
            <div><label class="form-label">Note / Tag</label><input name="q" value="{q}" class="form-input" style="width:160px" placeholder="Search..."></div>
            <button type="submit" class="btn btn-blue">Filter</button>
            <a href="/admin/expenses" class="btn" style="background:var(--surface2);color:var(--muted)">Clear</a>
            <a href="/admin/expenses/export?uid={uid_filter}&cat={cat_filter}&q={q}" class="btn btn-green">⬇️ Export CSV</a>
          </form>
        </div>

        <div class="table-wrap">
          <div class="table-header">
            <h3>💸 Expenses</h3>
            <span class="text-muted mono">Page {page_num}/{total_pages or 1}</span>
          </div>
          <table><thead><tr><th>#</th><th>User ID</th><th>Username</th><th>Category</th><th>Amount</th><th>Note</th><th>Tag</th><th>Date</th><th>Actions</th></tr></thead>
          <tbody>{rows or "<tr><td colspan='9' class='text-muted' style='text-align:center;padding:20px'>No expenses found</td></tr>"}</tbody></table>
        </div>
        {pagination}"""
        return render_page(content, page="expenses")

    # ── EDIT EXPENSE ───────────────────────────────────────────────
    @flask_app.route("/admin/expense/edit/<int:eid>", methods=["GET", "POST"])
    @login_required
    def admin_expense_edit(eid):
        conn = db()
        if request.method == "POST":
            try:
                cur = conn.cursor()
                cur.execute("""
                    UPDATE expenses SET category=%s, amount=%s, note=%s, tag=%s, date=%s
                    WHERE id=%s
                """, (
                    request.form.get("category"),
                    float(request.form.get("amount", 0)),
                    request.form.get("note"),
                    request.form.get("tag"),
                    request.form.get("date"),
                    eid
                ))
                conn.commit()
                conn.close()
                return redirect(f"/admin/expenses?msg=✅ Expense #{eid} updated")
            except Exception as e:
                conn.rollback()
                conn.close()
                return redirect(f"/admin/expense/edit/{eid}?msg=❌ Error: {e}")

        expense = _safe_one(conn, "SELECT * FROM expenses WHERE id=%s", (eid,))
        conn.close()
        if not expense:
            return redirect("/admin/expenses")

        msg = request.args.get("msg", "")
        alert = f'<div class="alert alert-error">{msg}</div>' if msg else ""

        content = f"""
        {alert}
        <div style="display:flex;align-items:center;gap:16px;margin-bottom:4px">
          <a href="/admin/expenses" class="btn btn-sm" style="background:var(--surface2);color:var(--muted)">← Back</a>
          <div class="page-title">Edit Expense #{eid}</div>
        </div>
        <div class="page-sub">User {expense['user_id']}</div>
        <div class="section" style="max-width:500px">
          <form method="POST">
            <div class="form-group"><label class="form-label">Category</label>
              <input name="category" value="{expense['category'] or ''}" class="form-input"></div>
            <div class="form-group"><label class="form-label">Amount ($)</label>
              <input name="amount" type="number" step="0.01" value="{expense['amount']}" class="form-input"></div>
            <div class="form-group"><label class="form-label">Note</label>
              <input name="note" value="{expense['note'] or ''}" class="form-input"></div>
            <div class="form-group"><label class="form-label">Tag</label>
              <input name="tag" value="{expense['tag'] or ''}" class="form-input"></div>
            <div class="form-group"><label class="form-label">Date</label>
              <input name="date" type="date" value="{str(expense['date'])[:10]}" class="form-input"></div>
            <button type="submit" class="btn btn-blue">💾 Save Changes</button>
          </form>
        </div>"""
        return render_page(content, page="expenses")

    # ── DELETE EXPENSE ─────────────────────────────────────────────
    @flask_app.route("/admin/expense/delete/<int:eid>")
    @login_required
    def admin_expense_delete(eid):
        conn = db()
        uid = None
        try:
            row = _safe_one(conn, "SELECT user_id FROM expenses WHERE id=%s", (eid,))
            uid = row['user_id'] if row else None
            cur = conn.cursor()
            cur.execute("DELETE FROM expenses WHERE id=%s", (eid,))
            conn.commit()
        except Exception as e:
            conn.rollback()
        finally:
            conn.close()
        back = request.referrer or "/admin/expenses"
        if uid and f"/admin/user/{uid}" in back:
            return redirect(f"/admin/user/{uid}?msg=✅ Expense deleted")
        return redirect("/admin/expenses?msg=✅ Expense deleted")

    # ── EXPORT CSV ─────────────────────────────────────────────────
    @flask_app.route("/admin/expenses/export")
    @login_required
    def admin_expenses_export():
        conn = db()
        uid_filter = request.args.get("uid", "").strip()
        cat_filter = request.args.get("cat", "").strip()
        q = request.args.get("q", "").strip()

        where = "WHERE 1=1"
        params = []
        if uid_filter:
            where += " AND e.user_id=%s"; params.append(uid_filter)
        if cat_filter:
            where += " AND e.category ILIKE %s"; params.append(f"%{cat_filter}%")
        if q:
            where += " AND (e.note ILIKE %s OR e.tag ILIKE %s)"; params += [f"%{q}%", f"%{q}%"]

        expenses = _safe_query(conn, f"""
            SELECT e.id, e.user_id, u.username, e.category, e.amount, e.note, e.tag, e.date
            FROM expenses e LEFT JOIN users u ON e.user_id=u.user_id
            {where} ORDER BY e.date DESC
        """, params)
        conn.close()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["id", "user_id", "username", "category", "amount", "note", "tag", "date"])
        for e in expenses:
            writer.writerow([e['id'], e['user_id'], e['username'], e['category'],
                             e['amount'], e['note'], e['tag'], str(e['date'])[:10]])

        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment;filename=expenses_{datetime.now().strftime('%Y%m%d')}.csv"}
        )

    # ── NOTES ──────────────────────────────────────────────────────
    @flask_app.route("/admin/notes")
    @login_required
    def admin_notes():
        conn = db()
        notes = _safe_query(conn, """
            SELECT n.id, n.user_id, u.username, n.content, n.created_at
            FROM notes n LEFT JOIN users u ON n.user_id=u.user_id
            ORDER BY n.created_at DESC LIMIT 100
        """)
        conn.close()

        msg = request.args.get("msg", "")
        alert = f'<div class="alert alert-success">{msg}</div>' if msg else ""

        rows = "".join(f"""
            <tr>
              <td><a href="/admin/user/{n['user_id']}" class="user-id">{n['user_id']}</a></td>
              <td>{n['username'] or '—'}</td>
              <td style="max-width:400px">{n['content']}</td>
              <td class="text-muted mono">{str(n['created_at'])[:16]}</td>
              <td><a href="/admin/note/delete/{n['id']}" class="btn btn-red btn-xs" onclick="return confirm('Delete?')">🗑</a></td>
            </tr>""" for n in notes)

        content = f"""
        {alert}
        <div class="page-title">Notes</div>
        <div class="page-sub">{len(notes)} NOTES (LAST 100)</div>
        <div class="table-wrap">
          <div class="table-header"><h3>📝 All Notes</h3></div>
          <table><thead><tr><th>User ID</th><th>Username</th><th>Content</th><th>Created</th><th></th></tr></thead>
          <tbody>{rows or "<tr><td colspan='5' class='text-muted' style='text-align:center;padding:20px'>No notes</td></tr>"}</tbody>
        </table></div>"""
        return render_page(content, page="notes")

    @flask_app.route("/admin/note/delete/<int:nid>")
    @login_required
    def admin_note_delete(nid):
        conn = db()
        uid = request.args.get("uid")
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM notes WHERE id=%s", (nid,))
            conn.commit()
        except Exception as e:
            conn.rollback()
        finally:
            conn.close()
        if uid:
            return redirect(f"/admin/user/{uid}?msg=✅ Note deleted")
        return redirect("/admin/notes?msg=✅ Note deleted")

    # ── STATS (with charts) ────────────────────────────────────────
    @flask_app.route("/admin/stats")
    @login_required
    def admin_stats():
        conn = db()
        by_cat = _safe_query(conn, """
            SELECT category, COUNT(*) as cnt, SUM(amount) as total
            FROM expenses GROUP BY category ORDER BY total DESC
        """)
        by_month = _safe_query(conn, """
            SELECT to_char(date, 'YYYY-MM') as month, SUM(amount) as total, COUNT(*) as cnt
            FROM expenses GROUP BY month ORDER BY month DESC LIMIT 12
        """)
        top_users = _safe_query(conn, """
            SELECT e.user_id, u.username, SUM(e.amount) as total, COUNT(*) as cnt
            FROM expenses e LEFT JOIN users u ON e.user_id=u.user_id
            GROUP BY e.user_id, u.username ORDER BY total DESC LIMIT 10
        """)
        # User growth: new users per month (last 12 months)
        user_growth = _safe_query(conn, """
            SELECT to_char(created_at, 'YYYY-MM') as month, COUNT(*) as cnt
            FROM users GROUP BY month ORDER BY month ASC LIMIT 12
        """)
        # Active users per month
        active_monthly = _safe_query(conn, """
            SELECT to_char(date, 'YYYY-MM') as month, COUNT(DISTINCT user_id) as cnt
            FROM expenses GROUP BY month ORDER BY month ASC LIMIT 12
        """)
        conn.close()

        import json
        # Monthly bar chart data (reverse so oldest first)
        months_rev = list(reversed(by_month))
        m_labels = json.dumps([r['month'] for r in months_rev])
        m_vals   = json.dumps([float(r['total']) for r in months_rev])
        m_cnts   = json.dumps([int(r['cnt']) for r in months_rev])

        # Top category bar
        cat_labels = json.dumps([r['category'] or 'N/A' for r in by_cat[:10]])
        cat_totals = json.dumps([float(r['total']) for r in by_cat[:10]])

        # User growth
        ug_labels = json.dumps([r['month'] for r in user_growth])
        ug_vals   = json.dumps([int(r['cnt']) for r in user_growth])

        # Active users per month
        au_labels = json.dumps([r['month'] for r in active_monthly])
        au_vals   = json.dumps([int(r['cnt']) for r in active_monthly])

        cat_rows = "".join(f"""
            <tr>
              <td>{r['category'] or 'N/A'}</td>
              <td style='text-align:center'>{r['cnt']}</td>
              <td><span class="badge bg">${r['total']:.2f}</span></td>
            </tr>""" for r in by_cat)

        month_rows = "".join(f"""
            <tr>
              <td><span class="badge bg3">{r['month']}</span></td>
              <td style='text-align:center'>{r['cnt']}</td>
              <td><span class="badge bg">${r['total']:.2f}</span></td>
            </tr>""" for r in by_month)

        user_rows = "".join(f"""
            <tr>
              <td><a href="/admin/user/{r['user_id']}" class="user-id">{r['user_id']}</a></td>
              <td>{r['username'] or '—'}</td>
              <td style='text-align:center'>{r['cnt']}</td>
              <td><span class="badge bm">${r['total']:.2f}</span></td>
            </tr>""" for r in top_users)

        content = f"""
        <div class="page-title">Stats & Analytics</div>
        <div class="page-sub">FINANCIAL OVERVIEW</div>

        <!-- Monthly spending chart -->
        <div class="chart-wrap">
          <h3>📅 Monthly Spending (Last 12 Months)</h3>
          <div class="chart-container" style="height:240px">
            <canvas id="monthlyChart"></canvas>
          </div>
        </div>

        <!-- Category bar + User growth side by side -->
        <div class="grid-2" style="margin-bottom:20px">
          <div class="chart-wrap">
            <h3>📁 Spending by Category</h3>
            <div class="chart-container" style="height:220px">
              <canvas id="catBarChart"></canvas>
            </div>
          </div>
          <div class="chart-wrap">
            <h3>👥 User Growth per Month</h3>
            <div class="chart-container" style="height:220px">
              <canvas id="userGrowthChart"></canvas>
            </div>
          </div>
        </div>

        <!-- Active users chart -->
        <div class="chart-wrap" style="margin-bottom:20px">
          <h3>🟢 Active Users per Month (had at least 1 expense)</h3>
          <div class="chart-container" style="height:180px">
            <canvas id="activeUsersChart"></canvas>
          </div>
        </div>

        <div class="grid-2">
          <div class="table-wrap">
            <div class="table-header"><h3>📁 By Category</h3></div>
            <table><thead><tr><th>Category</th><th>Count</th><th>Total</th></tr></thead>
            <tbody>{cat_rows or "<tr><td colspan='3' class='text-muted'>No data</td></tr>"}</tbody></table>
          </div>
          <div class="table-wrap">
            <div class="table-header"><h3>📅 By Month</h3></div>
            <table><thead><tr><th>Month</th><th>Count</th><th>Total</th></tr></thead>
            <tbody>{month_rows or "<tr><td colspan='3' class='text-muted'>No data</td></tr>"}</tbody></table>
          </div>
        </div>
        <div class="table-wrap">
          <div class="table-header"><h3>🏆 Top Spenders</h3></div>
          <table><thead><tr><th>User ID</th><th>Username</th><th>Transactions</th><th>Total Spent</th></tr></thead>
          <tbody>{user_rows or "<tr><td colspan='4' class='text-muted'>No data</td></tr>"}</tbody></table>
        </div>

        <script>
        const CD = {{
          responsive:true, maintainAspectRatio:false,
          plugins:{{legend:{{labels:{{color:'#8899bb',font:{{size:11}}}}}}}}
        }};
        const gridColor = '#1e2535';
        const tickStyle = {{color:'#5a6a8a',font:{{size:10}}}};

        // Monthly spending bar + line combo
        new Chart(document.getElementById('monthlyChart'), {{
          type:'bar',
          data:{{
            labels:{m_labels},
            datasets:[
              {{label:'Spending ($)',data:{m_vals},backgroundColor:'rgba(79,142,247,.5)',
                borderColor:'#4f8ef7',borderWidth:1,borderRadius:4,yAxisID:'y'}},
              {{label:'# Expenses',data:{m_cnts},type:'line',borderColor:'#f7c44f',
                backgroundColor:'transparent',tension:0.4,pointRadius:3,yAxisID:'y2'}}
            ]
          }},
          options:{{...CD,scales:{{
            x:{{ticks:tickStyle,grid:{{color:gridColor}}}},
            y:{{ticks:{{...tickStyle,callback:v=>'$'+v}},grid:{{color:gridColor}},position:'left'}},
            y2:{{ticks:tickStyle,grid:{{display:false}},position:'right'}}
          }}}}
        }});

        // Category horizontal bar
        new Chart(document.getElementById('catBarChart'), {{
          type:'bar',
          data:{{
            labels:{cat_labels},
            datasets:[{{label:'Total ($)',data:{cat_totals},
              backgroundColor:'rgba(247,79,142,.6)',borderColor:'#f74f8e',
              borderWidth:1,borderRadius:4}}]
          }},
          options:{{...CD,indexAxis:'y',scales:{{
            x:{{ticks:{{...tickStyle,callback:v=>'$'+v}},grid:{{color:gridColor}}}},
            y:{{ticks:tickStyle,grid:{{color:gridColor}}}}
          }}}}
        }});

        // User growth
        new Chart(document.getElementById('userGrowthChart'), {{
          type:'bar',
          data:{{
            labels:{ug_labels},
            datasets:[{{label:'New Users',data:{ug_vals},
              backgroundColor:'rgba(79,247,160,.55)',borderColor:'#4ff7a0',
              borderWidth:1,borderRadius:4}}]
          }},
          options:{{...CD,scales:{{
            x:{{ticks:tickStyle,grid:{{color:gridColor}}}},
            y:{{ticks:tickStyle,grid:{{color:gridColor}}}}
          }}}}
        }});

        // Active users line
        new Chart(document.getElementById('activeUsersChart'), {{
          type:'line',
          data:{{
            labels:{au_labels},
            datasets:[{{label:'Active Users',data:{au_vals},
              borderColor:'#f7c44f',backgroundColor:'rgba(247,196,79,.1)',
              fill:true,tension:0.4,pointRadius:4,pointBackgroundColor:'#f7c44f'}}]
          }},
          options:{{...CD,scales:{{
            x:{{ticks:tickStyle,grid:{{color:gridColor}}}},
            y:{{ticks:tickStyle,grid:{{color:gridColor}}}}
          }}}}
        }});
        </script>"""
        return render_page(content, page="stats")

    # ── BROADCAST ──────────────────────────────────────────────────
    @flask_app.route("/admin/broadcast", methods=["GET", "POST"])
    @login_required
    def admin_broadcast():
        result = ""
        if request.method == "POST":
            message = request.form.get("message", "").strip()
            target = request.form.get("target", "all")
            if message and _bot_app:
                conn = db()
                if target == "active":
                    rows = _safe_query(conn, """
                        SELECT DISTINCT user_id FROM expenses
                        WHERE date >= CURRENT_DATE - INTERVAL '30 days'
                    """)
                else:
                    rows = _safe_query(conn, "SELECT user_id FROM users")
                conn.close()
                user_ids = [r['user_id'] for r in rows]

                import asyncio
                sent = failed = 0
                async def do_broadcast():
                    nonlocal sent, failed
                    for uid in user_ids:
                        try:
                            await _bot_app.bot.send_message(
                                chat_id=uid,
                                text=f"📢 *Admin Announcement*\n\n{message}",
                                parse_mode="Markdown"
                            )
                            sent += 1
                        except Exception:
                            failed += 1
                try:
                    lp = asyncio.new_event_loop()
                    lp.run_until_complete(do_broadcast())
                    lp.close()
                    result = f'<div class="alert alert-success">✅ Sent to {sent} users ({failed} failed)</div>'
                except Exception as e:
                    result = f'<div class="alert alert-error">❌ Error: {e}</div>'
            elif not _bot_app:
                result = '<div class="alert alert-error">❌ Bot not connected to dashboard</div>'

        conn = db()
        user_count = (_safe_one(conn, "SELECT COUNT(*) AS c FROM users") or {}).get('c', 0)
        active_count = (_safe_one(conn, """
            SELECT COUNT(DISTINCT user_id) AS c FROM expenses
            WHERE date >= CURRENT_DATE - INTERVAL '30 days'
        """) or {}).get('c', 0)
        conn.close()

        content = f"""
        <div class="page-title">Broadcast</div>
        <div class="page-sub">SEND MESSAGE TO USERS</div>
        {result}
        <div class="section">
          <h3>📢 Send Broadcast</h3>
          <form method="POST">
            <div class="form-group">
              <label class="form-label">Target Audience</label>
              <select name="target" class="form-select" style="width:240px">
                <option value="all">All Users ({user_count})</option>
                <option value="active">Active last 30 days ({active_count})</option>
              </select>
            </div>
            <div class="form-group">
              <label class="form-label">Message (Markdown supported)</label>
              <textarea name="message" class="form-textarea" placeholder="*Bold*, _italic_, type your announcement..."></textarea>
            </div>
            <button type="submit" class="btn btn-blue">📤 Send Broadcast</button>
          </form>
        </div>"""
        return render_page(content, page="broadcast")

    # ── BOT CONTROL ────────────────────────────────────────────────
    @flask_app.route("/admin/bot_control", methods=["GET", "POST"])
    @login_required
    def admin_bot_control():
        result = ""
        if request.method == "POST":
            action = request.form.get("action")
            uid = request.form.get("uid", "").strip()
            msg = request.form.get("msg", "").strip()

            if action == "send" and uid and msg and _bot_app:
                import asyncio
                async def _s():
                    await _bot_app.bot.send_message(chat_id=int(uid), text=f"📬 *Admin:* {msg}", parse_mode="Markdown")
                try:
                    lp = asyncio.new_event_loop(); lp.run_until_complete(_s()); lp.close()
                    result = f'<div class="alert alert-success">✅ Sent to {uid}</div>'
                except Exception as e:
                    result = f'<div class="alert alert-error">❌ {e}</div>'

            elif action == "ban" and uid:
                conn = db()
                try:
                    cur = conn.cursor()
                    cur.execute("CREATE TABLE IF NOT EXISTS banned_users (user_id BIGINT PRIMARY KEY, banned_at TIMESTAMPTZ DEFAULT NOW())")
                    cur.execute("INSERT INTO banned_users (user_id) VALUES (%s) ON CONFLICT DO NOTHING", (int(uid),))
                    conn.commit()
                    result = f'<div class="alert alert-success">🚫 User {uid} banned</div>'
                except Exception as e:
                    conn.rollback()
                    result = f'<div class="alert alert-error">❌ {e}</div>'
                finally:
                    conn.close()

            elif action == "unban" and uid:
                conn = db()
                try:
                    cur = conn.cursor()
                    cur.execute("DELETE FROM banned_users WHERE user_id=%s", (int(uid),))
                    conn.commit()
                    result = f'<div class="alert alert-success">✅ User {uid} unbanned</div>'
                except Exception as e:
                    conn.rollback()
                    result = f'<div class="alert alert-error">❌ {e}</div>'
                finally:
                    conn.close()

        bot_status = "🟢 ONLINE" if _bot_app else "🔴 OFFLINE"
        content = f"""
        <div class="page-title">Bot Control</div>
        <div class="page-sub">BOT STATUS: {bot_status}</div>
        {result}
        <div class="grid-2">
          <div class="section">
            <h3>📨 Send Message to User</h3>
            <form method="POST">
              <input type="hidden" name="action" value="send">
              <div class="form-group"><label class="form-label">User ID</label>
                <input name="uid" class="form-input" placeholder="123456789"></div>
              <div class="form-group"><label class="form-label">Message</label>
                <textarea name="msg" class="form-textarea" placeholder="Your message..."></textarea></div>
              <button type="submit" class="btn btn-blue">📤 Send</button>
            </form>
          </div>
          <div class="section">
            <h3>🚫 Ban / Unban User</h3>
            <form method="POST" style="margin-bottom:16px">
              <input type="hidden" name="action" value="ban">
              <div class="form-group"><label class="form-label">User ID to Ban</label>
                <input name="uid" class="form-input" placeholder="123456789"></div>
              <button type="submit" class="btn btn-red">🚫 Ban User</button>
            </form>
            <hr class="divider">
            <form method="POST">
              <input type="hidden" name="action" value="unban">
              <div class="form-group"><label class="form-label">User ID to Unban</label>
                <input name="uid" class="form-input" placeholder="123456789"></div>
              <button type="submit" class="btn btn-green">✅ Unban User</button>
            </form>
          </div>
        </div>
        <div class="section">
          <h3>📋 Telegram Admin Commands Reference</h3>
          <p style="color:var(--muted);font-size:12px;margin-bottom:12px">Commands available via Telegram (role-gated):</p>
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:10px">
            {''.join(f'<div style="background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:12px"><code style="color:var(--accent);font-size:12px">{cmd}</code><p style="color:var(--muted);font-size:11px;margin-top:4px">{desc}</p><span style="font-size:10px;color:var(--warning)">Min role: {role}</span></div>' for cmd, desc, role in [
                ("/admin_help", "Show all your available admin commands", "moderator"),
                ("/botstats", "Full bot statistics from DB", "moderator"),
                ("/userinfo <id>", "User profile & total spending", "moderator"),
                ("/ban <id> [reason]", "Ban a user (notifies them)", "moderator"),
                ("/unban <id>", "Unban a user (notifies them)", "moderator"),
                ("/sendmsg <id> <text>", "Send a message to any user", "moderator"),
                ("/usertop", "Top 10 spenders", "admin"),
                ("/recentusers", "Last 10 registered users", "admin"),
                ("/topadmins", "List all bot admins", "admin"),
                ("/deleteuser <id>", "Delete user and all data", "admin"),
                ("/errorlogs", "View recent error logs", "admin"),
                ("/maintenance", "Toggle maintenance mode", "admin"),
                ("/setadmin <id> <role>", "Grant admin access", "superadmin"),
                ("/removeadmin <id>", "Revoke admin access", "superadmin"),
                ("/dbstats", "Raw DB table row counts", "superadmin"),
            ])}
          </div>
        </div>"""
        return render_page(content, page="bot_control")

    # ── ERROR LOGS ─────────────────────────────────────────────────
    @flask_app.route("/admin/errors")
    @login_required
    def admin_errors():
        conn = db()
        errors = _safe_query(conn, """
            SELECT e.id, e.user_id, u.username, e.error, e.context, e.created_at
            FROM error_logs e LEFT JOIN users u ON e.user_id=u.user_id
            ORDER BY e.created_at DESC LIMIT 100
        """)
        conn.close()

        rows = "".join(f"""
            <tr>
              <td><a href="/admin/user/{e['user_id']}" class="user-id">{e['user_id']}</a></td>
              <td>{e['username'] or '—'}</td>
              <td style='font-size:11px;max-width:320px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>{e['error']}</td>
              <td><span class="badge bg">{e['context'] or '—'}</span></td>
              <td class="text-muted mono">{str(e['created_at'])[:16]}</td>
            </tr>""" for e in errors)

        content = f"""
        <div class="page-title">Error Logs</div>
        <div class="page-sub">LAST 100 ERRORS</div>
        <div class="table-wrap">
          <div class="table-header">
            <h3>⚠️ Recent Errors</h3>
            <span class="text-muted mono">{len(errors)} entries</span>
          </div>
          <table><thead><tr><th>User ID</th><th>Username</th><th>Error</th><th>Context</th><th>Time</th></tr></thead>
          <tbody>{rows or "<tr><td colspan='5' class='text-muted' style='text-align:center;padding:24px'>No errors logged 🎉</td></tr>"}</tbody>
        </table></div>"""
        return render_page(content, page="errors")

    # ── JSON API (for Telegram bot commands) ──────────────────────
    @flask_app.route("/admin/api/stats")
    @login_required
    def api_stats():
        conn = db()
        data = {
            "users": (_safe_one(conn, "SELECT COUNT(*) AS c FROM users") or {}).get('c', 0),
            "expenses_total": float((_safe_one(conn, "SELECT COALESCE(SUM(amount),0) AS c FROM expenses") or {}).get('c', 0)),
            "notes": (_safe_one(conn, "SELECT COUNT(*) AS c FROM notes") or {}).get('c', 0),
            "errors": (_safe_one(conn, "SELECT COUNT(*) AS c FROM error_logs") or {}).get('c', 0),
            "new_today": (_safe_one(conn, "SELECT COUNT(*) AS c FROM users WHERE created_at::date=CURRENT_DATE") or {}).get('c', 0),
        }
        conn.close()
        return jsonify(data)

    @flask_app.route("/admin/api/user/<int:uid>")
    @login_required
    def api_user(uid):
        conn = db()
        user = _safe_one(conn, "SELECT user_id,username,language,budget,daily_reminder,created_at FROM users WHERE user_id=%s", (uid,))
        if not user:
            conn.close()
            return jsonify({"error": "User not found"}), 404
        spent = (_safe_one(conn, "SELECT COALESCE(SUM(amount),0) AS t FROM expenses WHERE user_id=%s", (uid,)) or {}).get('t', 0)
        user['total_spent'] = float(spent)
        conn.close()
        return jsonify(dict(user))

    @flask_app.route("/admin/api/ban/<int:uid>", methods=["POST"])
    @login_required
    def api_ban(uid):
        conn = db()
        try:
            cur = conn.cursor()
            cur.execute("CREATE TABLE IF NOT EXISTS banned_users (user_id BIGINT PRIMARY KEY, banned_at TIMESTAMPTZ DEFAULT NOW())")
            cur.execute("INSERT INTO banned_users (user_id) VALUES (%s) ON CONFLICT DO NOTHING", (uid,))
            conn.commit()
            conn.close()
            return jsonify({"ok": True, "action": "banned", "user_id": uid})
        except Exception as e:
            conn.rollback()
            conn.close()
            return jsonify({"ok": False, "error": str(e)}), 500

    # ── DB CHECK (debug) ──
    @flask_app.route("/admin/dbcheck")
    def admin_dbcheck():
        url = _get_db_url()
        url_display = (url[:50] + "...") if url else "❌ NOT SET"
        try:
            conn = db()
            users = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
            tables = conn.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public' ORDER BY table_name
            """).fetchall()
            conn.close()
            table_list = ", ".join(t["table_name"] for t in tables)
            return (
                f"<pre>DB URL: {url_display}\n"
                f"Users:  {users}\n"
                f"Tables: {table_list}\n"
                f"Status: ✅ Connected</pre>"
            )
        except Exception as e:
            return f"<pre>DB URL: {url_display}\nError: {e}</pre>", 500

    # ══════════════════════════════════════════════════════════════════
    # ADMIN ROLE MANAGEMENT  (/admin/admins)
    # ══════════════════════════════════════════════════════════════════

    def _ensure_admins_table(cur):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_admins (
                user_id   BIGINT PRIMARY KEY,
                username  TEXT,
                role      TEXT NOT NULL DEFAULT 'admin',
                note      TEXT,
                added_at  TIMESTAMPTZ DEFAULT NOW(),
                added_by  TEXT DEFAULT 'dashboard'
            )
        """)

    @flask_app.route("/admin/admins", methods=["GET", "POST"])
    @login_required
    def admin_roles():
        alert = ""
        conn = db()

        if request.method == "POST":
            action  = request.form.get("action", "")
            uid_str = request.form.get("uid", "").strip()
            uname   = request.form.get("username", "").strip()
            role    = request.form.get("role", "admin").strip()
            note    = request.form.get("note", "").strip()
            try:
                cur = conn.cursor()
                _ensure_admins_table(cur)

                if action == "add" and uid_str:
                    uid = int(uid_str)
                    cur.execute("""
                        INSERT INTO bot_admins (user_id, username, role, note)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (user_id) DO UPDATE SET
                            username=EXCLUDED.username,
                            role=EXCLUDED.role,
                            note=EXCLUDED.note
                    """, (uid, uname or None, role, note or None))
                    conn.commit()
                    alert = '<div class="alert alert-success">✅ Admin ' + str(uid) + ' (' + role + ') saved</div>'
                    if _bot_app:
                        role_labels = {"superadmin": "Super Admin 👑", "admin": "Admin 🛡️", "moderator": "Moderator 🔰"}
                        role_label = role_labels.get(role, role)
                        note_line = ("\nNote: " + note) if note else ""
                        import asyncio
                        async def _notify():
                            await _bot_app.bot.send_message(
                                chat_id=uid,
                                text=(
                                    "🎉 <b>You have been granted bot admin access!</b>\n\n"
                                    "Role: <b>" + role_label + "</b>" + note_line + "\n\n"
                                    "Use /admin_help to see your available commands."
                                ),
                                parse_mode="HTML"
                            )
                        try:
                            loop = asyncio.new_event_loop()
                            loop.run_until_complete(_notify())
                            loop.close()
                        except Exception:
                            pass

                elif action == "remove" and uid_str:
                    uid = int(uid_str)
                    cur.execute("DELETE FROM bot_admins WHERE user_id=%s", (uid,))
                    conn.commit()
                    alert = '<div class="alert alert-success">🗑 Admin ' + str(uid) + ' removed</div>'

                elif action == "change_role" and uid_str:
                    uid = int(uid_str)
                    cur.execute("UPDATE bot_admins SET role=%s WHERE user_id=%s", (role, uid))
                    conn.commit()
                    alert = '<div class="alert alert-success">✅ Role updated → ' + role + ' for ' + str(uid) + '</div>'

            except Exception as e:
                conn.rollback()
                alert = '<div class="alert alert-error">❌ ' + str(e) + '</div>'

        try:
            cur2 = conn.cursor()
            _ensure_admins_table(cur2)
            conn.commit()
        except Exception:
            pass

        admins = _safe_query(conn, "SELECT * FROM bot_admins ORDER BY added_at DESC")
        conn.close()

        def _role_badge(r):
            cls = {"superadmin": "bm", "admin": "bg", "moderator": "bg3"}.get(r, "by")
            ico = {"superadmin": "👑", "admin": "🛡️", "moderator": "🔰"}.get(r, "👤")
            return '<span class="badge ' + cls + '">' + ico + ' ' + r + '</span>'

        admin_rows_parts = []
        for a in admins:
            uid_val   = a['user_id']
            uname_val = ('@' + a['username']) if a['username'] else '—'
            note_val  = a['note'] or '—'
            added_val = str(a['added_at'])[:16]
            by_val    = a['added_by'] or '—'
            role_val  = a['role']
            badge     = _role_badge(role_val)
            admin_rows_parts.append(
                "<tr>"
                "<td><span class='user-id'>" + str(uid_val) + "</span></td>"
                "<td>" + uname_val + "</td>"
                "<td>" + badge + "</td>"
                "<td class='text-muted' style='font-size:11px;max-width:160px'>" + note_val + "</td>"
                "<td class='text-muted mono'>" + added_val + "</td>"
                "<td class='text-muted mono'>" + by_val + "</td>"
                "<td style='display:flex;gap:4px;flex-wrap:wrap;padding:8px 14px'>"
                "<button onclick=\"openChangeRole(" + str(uid_val) + ",'" + role_val + "')\" class='btn btn-yellow btn-xs'>✏️ Role</button>"
                "<form method='POST' style='display:inline' onsubmit=\"return confirm('Remove admin " + str(uid_val) + "?')\">"
                "<input type='hidden' name='action' value='remove'>"
                "<input type='hidden' name='uid' value='" + str(uid_val) + "'>"
                "<button type='submit' class='btn btn-red btn-xs'>🗑 Remove</button>"
                "</form></td></tr>"
            )
        rows_html = "".join(admin_rows_parts) if admin_rows_parts else (
            "<tr><td colspan='7' class='text-muted' style='text-align:center;padding:24px'>"
            "No admins yet — add one above</td></tr>"
        )

        perms = [
            ("/admin_help",   True,  True,  True),
            ("/botstats",     True,  True,  True),
            ("/userinfo",     True,  True,  True),
            ("/ban",          True,  True,  True),
            ("/unban",        True,  True,  True),
            ("/sendmsg",      True,  True,  True),
            ("/usertop",      True,  True,  False),
            ("/recentusers",  True,  True,  False),
            ("/topadmins",    True,  True,  False),
            ("/broadcast",    True,  True,  False),
            ("/deleteuser",   True,  True,  False),
            ("/errorlogs",    True,  True,  False),
            ("/maintenance",  True,  True,  False),
            ("/setadmin",     True,  False, False),
            ("/removeadmin",  True,  False, False),
            ("/dbstats",      True,  False, False),
        ]
        tick = "✅"
        dash = "<span style='color:var(--muted)'>—</span>"
        perm_rows = "".join(
            "<tr>"
            "<td style='padding:6px 10px'><code style='color:var(--accent);font-size:11px'>" + cmd + "</code></td>"
            "<td style='text-align:center;padding:6px 10px'>" + (tick if s else dash) + "</td>"
            "<td style='text-align:center;padding:6px 10px'>" + (tick if a else dash) + "</td>"
            "<td style='text-align:center;padding:6px 10px'>" + (tick if m else dash) + "</td>"
            "</tr>"
            for cmd, s, a, m in perms
        )

        content = (
            alert +
            """
        <div class="page-title">Bot Admin Roles</div>
        <div class="page-sub">MANAGE WHO CAN USE ADMIN COMMANDS IN THE TELEGRAM BOT</div>
        <div class="alert alert-info" style="margin-bottom:20px">
          ℹ️ Admins added here can immediately use admin commands in Telegram via /admin_help.
          The bot checks this table on every command — no restart needed.
        </div>
        <div class="grid-2" style="margin-bottom:20px">
          <div class="section">
            <h3>➕ Add / Update Admin</h3>
            <form method="POST">
              <input type="hidden" name="action" value="add">
              <div class="form-group">
                <label class="form-label">Telegram User ID <span style="color:var(--danger)">*</span></label>
                <input name="uid" class="form-input" placeholder="123456789" required>
              </div>
              <div class="form-group">
                <label class="form-label">Username (no @)</label>
                <input name="username" class="form-input" placeholder="johndoe">
              </div>
              <div class="form-group">
                <label class="form-label">Role</label>
                <select name="role" class="form-select">
                  <option value="superadmin">👑 Super Admin — full access</option>
                  <option value="admin" selected>🛡️ Admin — most commands</option>
                  <option value="moderator">🔰 Moderator — view + ban only</option>
                </select>
              </div>
              <div class="form-group">
                <label class="form-label">Note (optional)</label>
                <input name="note" class="form-input" placeholder="e.g. Night shift operator">
              </div>
              <button type="submit" class="btn btn-blue">👑 Grant Access</button>
            </form>
          </div>
          <div class="section">
            <h3>📋 Role Permissions</h3>
            <table style="width:100%;font-size:12px">
              <thead><tr>
                <th style="padding:7px 10px">Command</th>
                <th style="padding:7px 10px;text-align:center">👑 Super</th>
                <th style="padding:7px 10px;text-align:center">🛡️ Admin</th>
                <th style="padding:7px 10px;text-align:center">🔰 Mod</th>
              </tr></thead>
              <tbody>""" + perm_rows + """</tbody>
            </table>
          </div>
        </div>
        <div class="table-wrap">
          <div class="table-header">
            <h3>👑 Current Bot Admins</h3>
            <span class="text-muted mono">""" + str(len(admins)) + """ admin(s)</span>
          </div>
          <table>
            <thead><tr>
              <th>User ID</th><th>Username</th><th>Role</th>
              <th>Note</th><th>Added At</th><th>Added By</th><th>Actions</th>
            </tr></thead>
            <tbody>""" + rows_html + """</tbody>
          </table>
        </div>
        <div class="modal-bg" id="roleModal">
          <div class="modal">
            <button class="modal-close" onclick="closeRoleModal()">✕</button>
            <h3>✏️ Change Role</h3>
            <form method="POST">
              <input type="hidden" name="action" value="change_role">
              <input type="hidden" name="uid"    id="modalUid">
              <div class="form-group">
                <label class="form-label">New Role</label>
                <select name="role" id="modalRole" class="form-select">
                  <option value="superadmin">👑 Super Admin</option>
                  <option value="admin">🛡️ Admin</option>
                  <option value="moderator">🔰 Moderator</option>
                </select>
              </div>
              <button type="submit" class="btn btn-blue">💾 Save Role</button>
            </form>
          </div>
        </div>
        <script>
        function openChangeRole(uid, role) {
          document.getElementById('modalUid').value = uid;
          document.getElementById('modalRole').value = role;
          document.getElementById('roleModal').classList.add('open');
        }
        function closeRoleModal() {
          document.getElementById('roleModal').classList.remove('open');
        }
        document.getElementById('roleModal').addEventListener('click', function(e) {
          if (e.target === this) closeRoleModal();
        });
        </script>"""
        )
        return render_page(content, page="admins")

    @flask_app.route("/admin/api/admins")
    @login_required
    def api_admins():
        conn = db()
        try:
            cur = conn.cursor()
            _ensure_admins_table(cur)
            conn.commit()
        except Exception:
            pass
        rows = _safe_query(conn, "SELECT user_id, username, role FROM bot_admins ORDER BY added_at")
        conn.close()
        return jsonify([dict(r) for r in rows])

    logger.info("✅ Admin dashboard registered at /admin")