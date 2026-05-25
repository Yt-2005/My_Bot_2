"""
dashboard.py — Admin Dashboard for Telegram Bot
Accessible at /admin — password protected
Single Page Application with full JSON API
"""

import sqlite3
import logging
import os
from functools import wraps
from datetime import datetime, timedelta
from flask import request, session, redirect, jsonify, Response

logger = logging.getLogger(__name__)

_bot_app = None

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

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────────
# ADMIN HTML — Full SPA
# ─────────────────────────────────────────────
ADMIN_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>⚡ Bot Control Panel</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;700&family=Archivo:wght@400;500;700;900&display=swap" rel="stylesheet">
<style>
:root {
  --bg: #080b10;
  --surface: #0d1117;
  --surface2: #161b22;
  --surface3: #21262d;
  --border: #30363d;
  --accent: #58a6ff;
  --accent2: #f78166;
  --accent3: #3fb950;
  --accent4: #d2a8ff;
  --text: #e6edf3;
  --muted: #8b949e;
  --danger: #f85149;
  --success: #3fb950;
  --warning: #d29922;
  --glow: rgba(88,166,255,0.15);
}
*{margin:0;padding:0;box-sizing:border-box;}
html,body{height:100%;overflow:hidden;}
body{background:var(--bg);color:var(--text);font-family:'Archivo',sans-serif;display:flex;height:100vh;}

/* ── SCROLLBAR ── */
::-webkit-scrollbar{width:4px;height:4px;}
::-webkit-scrollbar-track{background:transparent;}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px;}

/* ── LOGIN ── */
#login-screen{
  position:fixed;inset:0;background:var(--bg);display:flex;align-items:center;justify-content:center;z-index:1000;
  background-image: radial-gradient(ellipse at 20% 50%, rgba(88,166,255,0.05) 0%, transparent 60%),
                    radial-gradient(ellipse at 80% 20%, rgba(247,129,102,0.05) 0%, transparent 50%);
}
.login-card{
  width:400px;background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:48px 40px;
  box-shadow:0 0 0 1px rgba(88,166,255,0.1), 0 20px 60px rgba(0,0,0,0.5);
}
.login-logo{text-align:center;margin-bottom:32px;}
.login-logo .bot-icon{font-size:48px;display:block;margin-bottom:12px;filter:drop-shadow(0 0 20px rgba(88,166,255,0.4));}
.login-logo h1{font-size:22px;font-weight:900;color:var(--text);letter-spacing:-0.5px;}
.login-logo p{font-size:12px;color:var(--muted);font-family:'IBM Plex Mono',monospace;margin-top:4px;}
.form-group{margin-bottom:20px;}
.form-label{display:block;font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;margin-bottom:8px;font-family:'IBM Plex Mono',monospace;}
.form-input{
  width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:8px;
  padding:12px 16px;color:var(--text);font-size:14px;font-family:'Archivo',sans-serif;
  transition:border-color .2s,box-shadow .2s;
}
.form-input:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px rgba(88,166,255,0.1);}
.btn{padding:11px 20px;border-radius:8px;font-size:13px;font-weight:700;cursor:pointer;border:none;transition:all .15s;font-family:'Archivo',sans-serif;display:inline-flex;align-items:center;gap:8px;}
.btn-primary{background:var(--accent);color:#0d1117;width:100%;justify-content:center;margin-bottom:10px;}
.btn-primary:hover{background:#79c0ff;transform:translateY(-1px);box-shadow:0 4px 20px rgba(88,166,255,0.3);}
.btn-ghost{background:transparent;color:var(--muted);border:1px solid var(--border);width:100%;justify-content:center;}
.btn-ghost:hover{border-color:var(--accent);color:var(--accent);}
.btn-danger{background:rgba(248,81,73,0.1);color:var(--danger);border:1px solid rgba(248,81,73,0.3);}
.btn-danger:hover{background:rgba(248,81,73,0.2);}
.btn-success{background:rgba(63,185,80,0.1);color:var(--success);border:1px solid rgba(63,185,80,0.3);}
.btn-success:hover{background:rgba(63,185,80,0.2);}
.btn-sm{padding:5px 12px;font-size:12px;}
.alert{padding:12px 16px;border-radius:8px;margin-bottom:16px;font-size:13px;font-family:'IBM Plex Mono',monospace;}
.alert-error{background:rgba(248,81,73,0.1);border:1px solid rgba(248,81,73,0.3);color:var(--danger);}
.alert-success{background:rgba(63,185,80,0.1);border:1px solid rgba(63,185,80,0.3);color:var(--success);}

/* ── SIDEBAR ── */
.sidebar{
  width:220px;background:var(--surface);border-right:1px solid var(--border);
  display:flex;flex-direction:column;flex-shrink:0;overflow:hidden;
}
.sidebar-header{padding:20px 20px 16px;border-bottom:1px solid var(--border);}
.sidebar-header h2{font-size:15px;font-weight:900;color:var(--text);letter-spacing:-.3px;}
.sidebar-header p{font-size:10px;color:var(--muted);font-family:'IBM Plex Mono',monospace;margin-top:2px;}
.sidebar-status{padding:10px 20px;border-bottom:1px solid var(--border);}
.status-dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--success);margin-right:6px;animation:pulse 2s infinite;}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.status-text{font-size:11px;color:var(--muted);font-family:'IBM Plex Mono',monospace;}
nav{flex:1;padding:8px 0;overflow-y:auto;}
.nav-group{padding:16px 16px 8px;font-size:10px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;font-family:'IBM Plex Mono',monospace;}
.nav-item{
  display:flex;align-items:center;gap:10px;padding:9px 20px;
  color:var(--muted);font-size:13px;font-weight:500;
  cursor:pointer;transition:all .15s;border:none;background:none;width:100%;text-align:left;
  position:relative;
}
.nav-item:hover{color:var(--text);background:var(--surface2);}
.nav-item.active{color:var(--accent);background:rgba(88,166,255,0.08);}
.nav-item.active::before{content:'';position:absolute;left:0;top:0;bottom:0;width:2px;background:var(--accent);}
.nav-icon{font-size:16px;width:20px;text-align:center;}
.sidebar-footer{padding:12px 16px;border-top:1px solid var(--border);}

/* ── MAIN ── */
.main{flex:1;display:flex;flex-direction:column;overflow:hidden;}
.topbar{
  height:52px;background:var(--surface);border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between;padding:0 24px;flex-shrink:0;
}
.topbar-title{font-size:14px;font-weight:700;color:var(--text);}
.topbar-right{display:flex;align-items:center;gap:12px;}
.uptime-badge{font-size:11px;font-family:'IBM Plex Mono',monospace;color:var(--muted);background:var(--surface2);border:1px solid var(--border);padding:4px 10px;border-radius:20px;}
.content{flex:1;overflow-y:auto;padding:24px;}

/* ── PAGE ── */
.page{display:none;}
.page.active{display:block;}
.page-header{margin-bottom:24px;}
.page-header h1{font-size:24px;font-weight:900;letter-spacing:-.5px;}
.page-header p{font-size:12px;color:var(--muted);font-family:'IBM Plex Mono',monospace;margin-top:4px;}

/* ── STAT CARDS ── */
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:24px;}
@media(max-width:900px){.cards{grid-template-columns:repeat(2,1fr);}}
.card{
  background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:18px 20px;
  position:relative;overflow:hidden;transition:border-color .2s;
}
.card:hover{border-color:var(--accent);}
.card-accent{position:absolute;top:0;left:0;right:0;height:2px;}
.card-accent.blue{background:linear-gradient(90deg,var(--accent),transparent);}
.card-accent.red{background:linear-gradient(90deg,var(--accent2),transparent);}
.card-accent.green{background:linear-gradient(90deg,var(--accent3),transparent);}
.card-accent.purple{background:linear-gradient(90deg,var(--accent4),transparent);}
.card-top{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;}
.card-icon{font-size:20px;}
.card-trend{font-size:10px;font-family:'IBM Plex Mono',monospace;}
.card-trend.up{color:var(--success);}
.card-value{font-size:28px;font-weight:900;line-height:1;letter-spacing:-1px;}
.card-label{font-size:11px;color:var(--muted);margin-top:4px;font-family:'IBM Plex Mono',monospace;}

/* ── TABLE ── */
.table-wrap{background:var(--surface);border:1px solid var(--border);border-radius:10px;overflow:hidden;margin-bottom:20px;}
.table-head{padding:14px 18px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;gap:12px;}
.table-head h3{font-size:13px;font-weight:700;white-space:nowrap;}
.search-box{background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:6px 12px;color:var(--text);font-size:12px;font-family:'Archivo',sans-serif;width:200px;}
.search-box:focus{outline:none;border-color:var(--accent);}
table{width:100%;border-collapse:collapse;}
th{padding:10px 14px;text-align:left;font-size:10px;font-weight:700;color:var(--muted);background:var(--surface2);text-transform:uppercase;letter-spacing:.08em;font-family:'IBM Plex Mono',monospace;white-space:nowrap;}
td{padding:11px 14px;font-size:12px;border-bottom:1px solid var(--border);vertical-align:middle;}
tr:last-child td{border-bottom:none;}
tr:hover td{background:rgba(88,166,255,0.03);}
.empty-row td{text-align:center;color:var(--muted);padding:32px;font-family:'IBM Plex Mono',monospace;font-size:11px;}
.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:700;font-family:'IBM Plex Mono',monospace;white-space:nowrap;}
.badge-blue{background:rgba(88,166,255,0.12);color:var(--accent);border:1px solid rgba(88,166,255,0.2);}
.badge-red{background:rgba(248,81,73,0.1);color:var(--danger);border:1px solid rgba(248,81,73,0.2);}
.badge-green{background:rgba(63,185,80,0.1);color:var(--success);border:1px solid rgba(63,185,80,0.2);}
.badge-purple{background:rgba(210,168,255,0.1);color:var(--accent4);border:1px solid rgba(210,168,255,0.2);}
.badge-orange{background:rgba(247,129,102,0.1);color:var(--accent2);border:1px solid rgba(247,129,102,0.2);}
code.uid{font-family:'IBM Plex Mono',monospace;font-size:11px;color:var(--accent);background:rgba(88,166,255,0.08);padding:2px 6px;border-radius:4px;}

/* ── BROADCAST SECTION ── */
.section{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:20px;margin-bottom:20px;}
.section h3{font-size:14px;font-weight:700;margin-bottom:4px;}
.section-sub{font-size:12px;color:var(--muted);margin-bottom:20px;font-family:'IBM Plex Mono',monospace;}
.form-textarea{
  width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:8px;
  padding:12px 16px;color:var(--text);font-size:13px;font-family:'Archivo',sans-serif;
  resize:vertical;min-height:120px;transition:border-color .2s;
}
.form-textarea:focus{outline:none;border-color:var(--accent);}

/* ── GRID ── */
.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:20px;}
@media(max-width:800px){.grid-2{grid-template-columns:1fr;}}

/* ── MAINTENANCE TOGGLE ── */
.toggle-row{display:flex;align-items:center;justify-content:space-between;padding:14px 18px;background:var(--surface);border:1px solid var(--border);border-radius:10px;margin-bottom:12px;}
.toggle-info h4{font-size:13px;font-weight:700;}
.toggle-info p{font-size:11px;color:var(--muted);margin-top:2px;font-family:'IBM Plex Mono',monospace;}
.toggle{position:relative;width:44px;height:24px;cursor:pointer;}
.toggle input{opacity:0;width:0;height:0;}
.toggle-slider{position:absolute;inset:0;background:var(--surface3);border-radius:24px;transition:.3s;border:1px solid var(--border);}
.toggle-slider:before{content:'';position:absolute;height:16px;width:16px;left:3px;bottom:3px;background:var(--muted);border-radius:50%;transition:.3s;}
.toggle input:checked + .toggle-slider{background:rgba(63,185,80,0.2);border-color:var(--success);}
.toggle input:checked + .toggle-slider:before{transform:translateX(20px);background:var(--success);}

/* ── LOADING ── */
.spinner{display:inline-block;width:16px;height:16px;border:2px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin .7s linear infinite;}
@keyframes spin{to{transform:rotate(360deg)}}
.loading-overlay{display:flex;align-items:center;justify-content:center;padding:40px;color:var(--muted);gap:10px;font-size:13px;font-family:'IBM Plex Mono',monospace;}

/* ── TOAST ── */
#toast{
  position:fixed;bottom:24px;right:24px;padding:12px 18px;border-radius:8px;font-size:13px;
  font-weight:600;z-index:9999;transform:translateY(100px);opacity:0;
  transition:all .3s cubic-bezier(.34,1.56,.64,1);pointer-events:none;
}
#toast.show{transform:translateY(0);opacity:1;}
#toast.success{background:rgba(63,185,80,0.15);border:1px solid rgba(63,185,80,0.4);color:var(--success);}
#toast.error{background:rgba(248,81,73,0.15);border:1px solid rgba(248,81,73,0.4);color:var(--danger);}

/* ── ACTIVITY FEED ── */
.activity-item{display:flex;gap:12px;padding:10px 0;border-bottom:1px solid var(--border);}
.activity-item:last-child{border-bottom:none;}
.activity-icon{width:32px;height:32px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:14px;flex-shrink:0;background:var(--surface2);}
.activity-text{flex:1;}
.activity-text strong{font-size:12px;color:var(--text);}
.activity-text p{font-size:11px;color:var(--muted);font-family:'IBM Plex Mono',monospace;margin-top:2px;}
</style>
</head>
<body>

<!-- LOGIN SCREEN -->
<div id="login-screen">
  <div class="login-card">
    <div class="login-logo">
      <span class="bot-icon">🤖</span>
      <h1>Bot Control Panel</h1>
      <p>ADMIN ACCESS REQUIRED</p>
    </div>
    <div id="login-alert" class="alert alert-error" style="display:none"></div>
    <div class="form-group">
      <label class="form-label">Admin Password</label>
      <input type="password" id="login-pw" class="form-input" placeholder="Enter password..." autocomplete="current-password">
    </div>
    <button class="btn btn-primary" onclick="doLogin()">
      <span>🔐</span> Login
    </button>
    <button class="btn btn-ghost" onclick="devLogin()">
      ⚡ Dev Bypass
    </button>
  </div>
</div>

<!-- APP -->
<div id="app" style="display:none;width:100%;height:100%;display:none;overflow:hidden;flex:1">

  <!-- SIDEBAR -->
  <div class="sidebar">
    <div class="sidebar-header">
      <h2>🤖 BotAdmin</h2>
      <p>CONTROL PANEL v2.0</p>
    </div>
    <div class="sidebar-status">
      <span class="status-dot"></span>
      <span class="status-text" id="bot-status">Bot Online</span>
    </div>
    <nav>
      <div class="nav-group">Main</div>
      <button class="nav-item active" id="nav-dashboard" onclick="gotoPage('dashboard')">
        <span class="nav-icon">📊</span> Dashboard
      </button>
      <button class="nav-item" id="nav-users" onclick="gotoPage('users')">
        <span class="nav-icon">👥</span> Users
      </button>
      <div class="nav-group">Finance</div>
      <button class="nav-item" id="nav-expenses" onclick="gotoPage('expenses')">
        <span class="nav-icon">💰</span> Expenses
      </button>
      <div class="nav-group">Tools</div>
      <button class="nav-item" id="nav-broadcast" onclick="gotoPage('broadcast')">
        <span class="nav-icon">📢</span> Broadcast
      </button>
      <button class="nav-item" id="nav-maintenance" onclick="gotoPage('maintenance')">
        <span class="nav-icon">🔧</span> Maintenance
      </button>
      <button class="nav-item" id="nav-errors" onclick="gotoPage('errors')">
        <span class="nav-icon">⚠️</span> Error Logs
      </button>
    </nav>
    <div class="sidebar-footer">
      <button class="btn btn-danger btn-sm" style="width:100%;justify-content:center" onclick="doLogout()">
        🚪 Logout
      </button>
    </div>
  </div>

  <!-- MAIN -->
  <div class="main">
    <div class="topbar">
      <span class="topbar-title" id="topbar-title">Dashboard</span>
      <div class="topbar-right">
        <span class="uptime-badge" id="uptime-badge">UPTIME: —</span>
        <button class="btn btn-success btn-sm" onclick="refreshPage()">↺ Refresh</button>
      </div>
    </div>
    <div class="content" id="content">

      <!-- ════ DASHBOARD PAGE ════ -->
      <div class="page active" id="page-dashboard">
        <div class="page-header">
          <h1>Dashboard</h1>
          <p id="dash-time">OVERVIEW — Loading...</p>
        </div>
        <div class="cards" id="dash-cards">
          <div class="card"><div class="card-accent blue"></div>
            <div class="card-top"><span class="card-icon">👥</span></div>
            <div class="card-value" id="d-users">—</div>
            <div class="card-label">TOTAL USERS</div>
          </div>
          <div class="card"><div class="card-accent red"></div>
            <div class="card-top"><span class="card-icon">💰</span></div>
            <div class="card-value" id="d-expenses">—</div>
            <div class="card-label">TOTAL EXPENSES ($)</div>
          </div>
          <div class="card"><div class="card-accent green"></div>
            <div class="card-top"><span class="card-icon">📝</span></div>
            <div class="card-value" id="d-notes">—</div>
            <div class="card-label">TOTAL NOTES</div>
          </div>
          <div class="card"><div class="card-accent purple"></div>
            <div class="card-top"><span class="card-icon">⚠️</span></div>
            <div class="card-value" id="d-errors">—</div>
            <div class="card-label">ERROR LOGS</div>
          </div>
        </div>
        <div class="grid-2">
          <div class="table-wrap">
            <div class="table-head"><h3>🆕 Recent Users</h3></div>
            <table><thead><tr><th>User ID</th><th>Username</th><th>Joined</th></tr></thead>
            <tbody id="dash-recent-users"><tr class="empty-row"><td colspan="3"><div class="spinner"></div></td></tr></tbody>
            </table>
          </div>
          <div class="table-wrap">
            <div class="table-head"><h3>💸 Recent Expenses</h3></div>
            <table><thead><tr><th>User</th><th>Category</th><th>Amount</th></tr></thead>
            <tbody id="dash-recent-exp"><tr class="empty-row"><td colspan="3"><div class="spinner"></div></td></tr></tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- ════ USERS PAGE ════ -->
      <div class="page" id="page-users">
        <div class="page-header">
          <h1>Users</h1>
          <p id="users-sub">ALL REGISTERED USERS</p>
        </div>
        <div class="table-wrap">
          <div class="table-head">
            <h3>👥 All Users</h3>
            <input class="search-box" id="user-search" placeholder="Search username / ID..." oninput="filterUsers()">
          </div>
          <table>
            <thead><tr>
              <th>User ID</th><th>Username</th><th>Lang</th>
              <th>Expenses</th><th>Notes</th><th>Reminder</th>
              <th>Joined</th><th>Status</th><th>Action</th>
            </tr></thead>
            <tbody id="users-tbody">
              <tr class="empty-row"><td colspan="9"><div class="spinner"></div></td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- ════ EXPENSES PAGE ════ -->
      <div class="page" id="page-expenses">
        <div class="page-header">
          <h1>Expenses</h1>
          <p>FINANCIAL STATISTICS</p>
        </div>
        <div class="grid-2">
          <div class="table-wrap">
            <div class="table-head"><h3>📁 By Category</h3></div>
            <table><thead><tr><th>Category</th><th>Count</th><th>Total ($)</th></tr></thead>
            <tbody id="exp-by-cat"><tr class="empty-row"><td colspan="3"><div class="spinner"></div></td></tr></tbody>
            </table>
          </div>
          <div class="table-wrap">
            <div class="table-head"><h3>📅 By Month</h3></div>
            <table><thead><tr><th>Month</th><th>Count</th><th>Total ($)</th></tr></thead>
            <tbody id="exp-by-month"><tr class="empty-row"><td colspan="3"><div class="spinner"></div></td></tr></tbody>
            </table>
          </div>
        </div>
        <div class="table-wrap">
          <div class="table-head"><h3>🏆 Top Spenders</h3></div>
          <table><thead><tr><th>User ID</th><th>Username</th><th>Transactions</th><th>Total ($)</th></tr></thead>
          <tbody id="exp-top-users"><tr class="empty-row"><td colspan="4"><div class="spinner"></div></td></tr></tbody>
          </table>
        </div>
      </div>

      <!-- ════ BROADCAST PAGE ════ -->
      <div class="page" id="page-broadcast">
        <div class="page-header">
          <h1>Broadcast</h1>
          <p>SEND MESSAGE TO ALL USERS</p>
        </div>
        <div id="bc-alert" style="display:none"></div>
        <div class="section">
          <h3>📢 New Broadcast</h3>
          <p class="section-sub">Will be sent to <strong id="bc-count" style="color:var(--accent)">—</strong> users via Telegram</p>
          <div class="form-group">
            <label class="form-label">Message</label>
            <textarea id="bc-msg" class="form-textarea" placeholder="Type your announcement here... Supports *bold* and _italic_ (Markdown)"></textarea>
          </div>
          <button class="btn btn-primary" onclick="sendBroadcast()" id="bc-btn" style="width:auto">
            <span>📤</span> Send to All Users
          </button>
        </div>
      </div>

      <!-- ════ MAINTENANCE PAGE ════ -->
      <div class="page" id="page-maintenance">
        <div class="page-header">
          <h1>Maintenance</h1>
          <p>BOT SETTINGS & CONTROLS</p>
        </div>
        <div class="toggle-row">
          <div class="toggle-info">
            <h4>🔧 Maintenance Mode</h4>
            <p>When ON, bot replies with maintenance message to all users</p>
          </div>
          <label class="toggle">
            <input type="checkbox" id="maint-toggle" onchange="toggleMaintenance()">
            <span class="toggle-slider"></span>
          </label>
        </div>
        <div class="section">
          <h3>🗄️ Database Info</h3>
          <p class="section-sub">Current database statistics</p>
          <div id="db-info" style="font-family:'IBM Plex Mono',monospace;font-size:12px;color:var(--muted);line-height:2">
            Loading...
          </div>
        </div>
        <div class="section">
          <h3>🔑 Bot Info</h3>
          <p class="section-sub">Runtime information</p>
          <div id="bot-info" style="font-family:'IBM Plex Mono',monospace;font-size:12px;color:var(--muted);line-height:2">
            Loading...
          </div>
        </div>
      </div>

      <!-- ════ ERRORS PAGE ════ -->
      <div class="page" id="page-errors">
        <div class="page-header">
          <h1>Error Logs</h1>
          <p>LAST 50 ERRORS</p>
        </div>
        <div class="table-wrap">
          <div class="table-head">
            <h3>⚠️ Recent Errors</h3>
            <span id="err-count" style="font-size:11px;color:var(--muted);font-family:'IBM Plex Mono',monospace">— entries</span>
          </div>
          <table>
            <thead><tr><th>User ID</th><th>Username</th><th>Error</th><th>Context</th><th>Time</th></tr></thead>
            <tbody id="errors-tbody">
              <tr class="empty-row"><td colspan="5"><div class="spinner"></div></td></tr>
            </tbody>
          </table>
        </div>
      </div>

    </div><!-- /content -->
  </div><!-- /main -->
</div><!-- /app -->

<div id="toast"></div>

<script>
// ─── STATE ───
let allUsers = [];
let currentPage = 'dashboard';

// ─── AUTH ───
async function doLogin() {
  const pw = document.getElementById('login-pw').value.trim();
  const alert = document.getElementById('login-alert');
  try {
    const res = await fetch('/admin/api/login', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({password: pw})
    });
    if (res.ok) {
      showApp();
    } else {
      alert.textContent = '❌ Wrong password';
      alert.style.display = 'block';
    }
  } catch(e) {
    alert.textContent = '❌ Connection error';
    alert.style.display = 'block';
  }
}

function devLogin() {
  document.getElementById('login-pw').value = 'admin1234';
  doLogin();
}

function showApp() {
  document.getElementById('login-screen').style.display = 'none';
  const app = document.getElementById('app');
  app.style.display = 'flex';
  loadPage('dashboard');
  startUptimeTimer();
}

async function doLogout() {
  await fetch('/admin/api/logout', {method:'POST'});
  location.reload();
}

// ─── NAVIGATION ───
function gotoPage(name) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('page-' + name).classList.add('active');
  document.getElementById('nav-' + name).classList.add('active');
  document.getElementById('topbar-title').textContent = name.charAt(0).toUpperCase() + name.slice(1);
  currentPage = name;
  loadPage(name);
}

function refreshPage() { loadPage(currentPage); }

function loadPage(name) {
  const loaders = {
    dashboard: loadDashboard,
    users: loadUsers,
    expenses: loadExpenses,
    broadcast: loadBroadcast,
    maintenance: loadMaintenance,
    errors: loadErrors,
  };
  if (loaders[name]) loaders[name]();
}

// ─── API HELPER ───
async function api(path, opts={}) {
  const res = await fetch(path, {headers:{'Content-Type':'application/json'}, ...opts});
  if (res.status === 401) { location.reload(); return null; }
  return res;
}

// ─── TOAST ───
function toast(msg, type='success') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'show ' + type;
  setTimeout(() => t.className = '', 3000);
}

// ─── UPTIME ───
let _startTime = Date.now();
function startUptimeTimer() {
  setInterval(async () => {
    try {
      const r = await fetch('/health');
      const d = await r.json();
      const s = d.uptime_seconds;
      const h = Math.floor(s/3600), m = Math.floor((s%3600)/60), sec = s%60;
      document.getElementById('uptime-badge').textContent =
        `UPTIME: ${h}h ${m}m ${sec}s`;
    } catch(e){}
  }, 5000);
}

// ─── DASHBOARD ───
async function loadDashboard() {
  document.getElementById('dash-time').textContent =
    'OVERVIEW // ' + new Date().toISOString().slice(0,16).replace('T',' ') + ' UTC';
  const res = await api('/admin/api/dashboard');
  if (!res) return;
  const d = await res.json();
  document.getElementById('d-users').textContent = d.total_users ?? '—';
  document.getElementById('d-expenses').textContent = d.total_expenses?.toFixed(2) ?? '—';
  document.getElementById('d-notes').textContent = d.total_notes ?? '—';
  document.getElementById('d-errors').textContent = d.total_errors ?? '—';

  const ru = document.getElementById('dash-recent-users');
  ru.innerHTML = (d.recent_users||[]).length
    ? d.recent_users.map(u => `<tr>
        <td><code class="uid">${u.user_id}</code></td>
        <td>${u.username || '<span style="color:var(--muted)">—</span>'}</td>
        <td style="color:var(--muted);font-size:11px">${(u.created_at||'').slice(0,10)}</td>
      </tr>`).join('')
    : '<tr class="empty-row"><td colspan="3">No users yet</td></tr>';

  const re = document.getElementById('dash-recent-exp');
  re.innerHTML = (d.recent_expenses||[]).length
    ? d.recent_expenses.map(e => `<tr>
        <td><code class="uid">${e.user_id}</code></td>
        <td><span class="badge badge-orange">${e.category||'—'}</span></td>
        <td><span class="badge badge-blue">$${(e.amount||0).toFixed(2)}</span></td>
      </tr>`).join('')
    : '<tr class="empty-row"><td colspan="3">No expenses yet</td></tr>';
}

// ─── USERS ───
async function loadUsers() {
  const res = await api('/admin/api/users');
  if (!res) return;
  allUsers = await res.json();
  document.getElementById('users-sub').textContent = `${allUsers.length} TOTAL USERS`;
  renderUsers(allUsers);
}

function renderUsers(users) {
  const tbody = document.getElementById('users-tbody');
  if (!users.length) {
    tbody.innerHTML = '<tr class="empty-row"><td colspan="9">No users found</td></tr>';
    return;
  }
  tbody.innerHTML = users.map(u => `<tr>
    <td><code class="uid">${u.user_id}</code></td>
    <td>${u.username ? `<strong>${u.username}</strong>` : '<span style="color:var(--muted)">—</span>'}</td>
    <td><span class="badge badge-blue">${u.language||'km'}</span></td>
    <td style="text-align:center">${u.expense_count||0}</td>
    <td style="text-align:center">${u.note_count||0}</td>
    <td><span class="badge ${u.daily_reminder ? 'badge-green' : 'badge-red'}">${u.daily_reminder ? 'ON' : 'OFF'}</span></td>
    <td style="color:var(--muted);font-size:11px">${(u.created_at||'').slice(0,10)}</td>
    <td><span class="badge ${u.banned ? 'badge-red' : 'badge-green'}">${u.banned ? 'BANNED' : 'ACTIVE'}</span></td>
    <td>
      ${u.banned
        ? `<button class="btn btn-success btn-sm" onclick="banUser(${u.user_id},false)">Unban</button>`
        : `<button class="btn btn-danger btn-sm" onclick="banUser(${u.user_id},true)">Ban</button>`
      }
    </td>
  </tr>`).join('');
}

function filterUsers() {
  const q = document.getElementById('user-search').value.toLowerCase();
  const filtered = allUsers.filter(u =>
    String(u.user_id).includes(q) || (u.username||'').toLowerCase().includes(q)
  );
  renderUsers(filtered);
}

async function banUser(uid, ban) {
  const res = await api(`/admin/api/${ban?'ban':'unban'}/${uid}`, {method:'POST'});
  if (res?.ok) {
    toast(ban ? `User ${uid} banned` : `User ${uid} unbanned`, ban ? 'error' : 'success');
    loadUsers();
  }
}

// ─── EXPENSES ───
async function loadExpenses() {
  const res = await api('/admin/api/expenses');
  if (!res) return;
  const d = await res.json();

  document.getElementById('exp-by-cat').innerHTML = (d.by_category||[]).length
    ? d.by_category.map(r => `<tr>
        <td>${r.category||'N/A'}</td>
        <td style="text-align:center">${r.count}</td>
        <td><span class="badge badge-blue">$${(r.total||0).toFixed(2)}</span></td>
      </tr>`).join('')
    : '<tr class="empty-row"><td colspan="3">No data</td></tr>';

  document.getElementById('exp-by-month').innerHTML = (d.by_month||[]).length
    ? d.by_month.map(r => `<tr>
        <td><span class="badge badge-green">${r.month}</span></td>
        <td style="text-align:center">${r.count}</td>
        <td><span class="badge badge-blue">$${(r.total||0).toFixed(2)}</span></td>
      </tr>`).join('')
    : '<tr class="empty-row"><td colspan="3">No data</td></tr>';

  document.getElementById('exp-top-users').innerHTML = (d.top_users||[]).length
    ? d.top_users.map(r => `<tr>
        <td><code class="uid">${r.user_id}</code></td>
        <td>${r.username||'—'}</td>
        <td style="text-align:center">${r.count}</td>
        <td><span class="badge badge-purple">$${(r.total||0).toFixed(2)}</span></td>
      </tr>`).join('')
    : '<tr class="empty-row"><td colspan="4">No data</td></tr>';
}

// ─── BROADCAST ───
async function loadBroadcast() {
  const res = await api('/admin/api/dashboard');
  if (res?.ok) {
    const d = await res.json();
    document.getElementById('bc-count').textContent = d.total_users ?? '—';
  }
}

async function sendBroadcast() {
  const msg = document.getElementById('bc-msg').value.trim();
  const alertEl = document.getElementById('bc-alert');
  if (!msg) { toast('Message cannot be empty', 'error'); return; }
  const btn = document.getElementById('bc-btn');
  btn.disabled = true;
  btn.innerHTML = '<div class="spinner"></div> Sending...';
  alertEl.style.display = 'none';
  const res = await api('/admin/api/broadcast', {
    method:'POST', body:JSON.stringify({message:msg})
  });
  btn.disabled = false;
  btn.innerHTML = '<span>📤</span> Send to All Users';
  if (res?.ok) {
    const d = await res.json();
    alertEl.className = 'alert alert-success';
    alertEl.textContent = `✅ Sent to ${d.sent} users (${d.failed} failed)`;
    alertEl.style.display = 'block';
    document.getElementById('bc-msg').value = '';
    toast(`Broadcast sent to ${d.sent} users`);
  } else {
    alertEl.className = 'alert alert-error';
    alertEl.textContent = '❌ Broadcast failed. Bot may not be connected.';
    alertEl.style.display = 'block';
  }
}

// ─── MAINTENANCE ───
async function loadMaintenance() {
  const res = await api('/admin/api/maintenance');
  if (!res) return;
  const d = await res.json();
  document.getElementById('maint-toggle').checked = d.maintenance_mode;
  document.getElementById('db-info').innerHTML = `
    👥 Users: <strong style="color:var(--text)">${d.users}</strong><br>
    💰 Expenses: <strong style="color:var(--text)">${d.expenses}</strong><br>
    📝 Notes: <strong style="color:var(--text)">${d.notes}</strong><br>
    ⚠️ Error Logs: <strong style="color:var(--text)">${d.errors}</strong>
  `;
  document.getElementById('bot-info').innerHTML = `
    🌐 Port: <strong style="color:var(--text)">${d.port}</strong><br>
    🕐 Uptime: <strong style="color:var(--text)">${d.uptime}</strong><br>
    🐍 Python: <strong style="color:var(--text)">${d.python}</strong><br>
    🔑 Bot Token: <strong style="color:var(--text)">${d.token_status}</strong>
  `;
}

async function toggleMaintenance() {
  const enabled = document.getElementById('maint-toggle').checked;
  const res = await api('/admin/api/maintenance/toggle', {
    method:'POST', body:JSON.stringify({enabled})
  });
  if (res?.ok) {
    toast(enabled ? '🔧 Maintenance mode ON' : '✅ Maintenance mode OFF', enabled ? 'error' : 'success');
  }
}

// ─── ERRORS ───
async function loadErrors() {
  const res = await api('/admin/api/errors');
  if (!res) return;
  const errors = await res.json();
  document.getElementById('err-count').textContent = `${errors.length} entries`;
  document.getElementById('errors-tbody').innerHTML = errors.length
    ? errors.map(e => `<tr>
        <td><code class="uid">${e.user_id||'—'}</code></td>
        <td style="color:var(--muted);font-size:11px">${e.username||'—'}</td>
        <td style="font-size:11px;max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${(e.error||'').replace(/"/g,'&quot;')}">${e.error||'—'}</td>
        <td><span class="badge badge-purple">${e.context||'—'}</span></td>
        <td style="color:var(--muted);font-size:11px;font-family:'IBM Plex Mono',monospace">${(e.created_at||'').slice(0,16)}</td>
      </tr>`).join('')
    : '<tr class="empty-row"><td colspan="5">No errors logged 🎉</td></tr>';
}

// ─── ENTER KEY ───
document.getElementById('login-pw').addEventListener('keydown', e => {
  if (e.key === 'Enter') doLogin();
});

// ─── AUTO-CHECK SESSION ───
(async () => {
  const res = await fetch('/admin/api/check');
  if (res.ok) showApp();
})();
</script>
</body>
</html>"""


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

    # ── LOGIN API ──
    @flask_app.route("/admin/api/login", methods=["POST"])
    def api_login():
        data = request.get_json() or {}
        if data.get("password") == DASHBOARD_PASSWORD:
            session["logged_in"] = True
            return jsonify({"ok": True})
        return jsonify({"error": "Wrong password"}), 401

    @flask_app.route("/admin/api/logout", methods=["POST"])
    def api_logout():
        session.clear()
        return jsonify({"ok": True})

    @flask_app.route("/admin/api/check")
    def api_check():
        if session.get("logged_in"):
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
            "SELECT user_id, category, amount FROM expenses ORDER BY created_at DESC LIMIT 5"
        ).fetchall()]
        conn.close()
        return jsonify({
            "total_users": total_users,
            "total_expenses": total_expenses,
            "total_notes": total_notes,
            "total_errors": total_errors,
            "recent_users": recent_users,
            "recent_expenses": recent_expenses,
        })

    # ── USERS API ──
    @flask_app.route("/admin/api/users")
    @login_required
    def api_users():
        conn = db()
        # Ensure banned_users table exists
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

    # ── BAN / UNBAN ──
    @flask_app.route("/admin/api/ban/<int:uid>", methods=["POST"])
    @login_required
    def api_ban(uid):
        conn = db()
        if not _table_exists(conn, "banned_users"):
            conn.execute("CREATE TABLE IF NOT EXISTS banned_users (user_id INTEGER PRIMARY KEY)")
        conn.execute("INSERT OR IGNORE INTO banned_users (user_id) VALUES (?)", (uid,))
        conn.commit(); conn.close()
        return jsonify({"ok": True})

    @flask_app.route("/admin/api/unban/<int:uid>", methods=["POST"])
    @login_required
    def api_unban(uid):
        conn = db()
        conn.execute("DELETE FROM banned_users WHERE user_id=?", (uid,))
        conn.commit(); conn.close()
        return jsonify({"ok": True})

    # ── EXPENSES API ──
    @flask_app.route("/admin/api/expenses")
    @login_required
    def api_expenses():
        conn = db()
        by_cat = [dict(r) for r in conn.execute("""
            SELECT category, COUNT(*) as count, SUM(amount) as total
            FROM expenses GROUP BY category ORDER BY total DESC
        """).fetchall()]
        by_month = [dict(r) for r in conn.execute("""
            SELECT strftime('%Y-%m', date) as month,
                   COUNT(*) as count, SUM(amount) as total
            FROM expenses GROUP BY month ORDER BY month DESC LIMIT 12
        """).fetchall()]
        top_users = [dict(r) for r in conn.execute("""
            SELECT e.user_id, u.username, COUNT(*) as count, SUM(e.amount) as total
            FROM expenses e LEFT JOIN users u ON e.user_id=u.user_id
            GROUP BY e.user_id ORDER BY total DESC LIMIT 10
        """).fetchall()]
        conn.close()
        return jsonify({"by_category": by_cat, "by_month": by_month, "top_users": top_users})

    # ── BROADCAST API ──
    @flask_app.route("/admin/api/broadcast", methods=["POST"])
    @login_required
    def api_broadcast():
        data = request.get_json() or {}
        message = data.get("message", "").strip()
        if not message:
            return jsonify({"error": "Empty message"}), 400
        if not _bot_app:
            return jsonify({"error": "Bot not connected"}), 503
        conn = db()
        user_ids = [r[0] for r in conn.execute("SELECT user_id FROM users").fetchall()]
        conn.close()
        sent = 0; failed = 0
        import asyncio
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
            loop = asyncio.new_event_loop()
            loop.run_until_complete(do_broadcast())
            loop.close()
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        return jsonify({"sent": sent, "failed": failed})

    # ── MAINTENANCE API ──
    @flask_app.route("/admin/api/maintenance")
    @login_required
    def api_maintenance():
        import sys, config as cfg
        conn = db()
        users    = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        expenses = conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
        notes    = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        errors   = 0
        if _table_exists(conn, "error_logs"):
            errors = conn.execute("SELECT COUNT(*) FROM error_logs").fetchone()[0]
        conn.close()
        import time
        uptime_secs = int(time.time() - _proc_start)
        h = uptime_secs // 3600; m = (uptime_secs % 3600) // 60; s = uptime_secs % 60
        return jsonify({
            "maintenance_mode": cfg.MAINTENANCE_MODE,
            "users": users, "expenses": expenses, "notes": notes, "errors": errors,
            "port": os.environ.get("PORT", "10000"),
            "uptime": f"{h}h {m}m {s}s",
            "python": sys.version.split()[0],
            "token_status": "✅ Set" if os.environ.get("TOKEN") else "❌ Not set",
        })

    @flask_app.route("/admin/api/maintenance/toggle", methods=["POST"])
    @login_required
    def api_maintenance_toggle():
        import config as cfg
        data = request.get_json() or {}
        cfg.MAINTENANCE_MODE = bool(data.get("enabled", False))
        return jsonify({"ok": True, "maintenance_mode": cfg.MAINTENANCE_MODE})

    # ── ERRORS API ──
    @flask_app.route("/admin/api/errors")
    @login_required
    def api_errors():
        conn = db()
        if not _table_exists(conn, "error_logs"):
            conn.close()
            return jsonify([])
        errors = [dict(r) for r in conn.execute("""
            SELECT e.*, u.username FROM error_logs e
            LEFT JOIN users u ON e.user_id=u.user_id
            ORDER BY e.created_at DESC LIMIT 50
        """).fetchall()]
        conn.close()
        return jsonify(errors)

    logger.info("✅ Admin dashboard registered at /admin")


import time as _time
_proc_start = _time.time()