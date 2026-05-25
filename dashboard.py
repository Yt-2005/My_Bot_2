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
# ADMIN HTML — Full SPA
# ─────────────────────────────────────────────
ADMIN_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>⚡ Bot Control Panel</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Outfit:wght@400;500;600;800;900&display=swap" rel="stylesheet">
<style>
:root {
  --bg: #050810;
  --surface: #0a0e1a;
  --surface2: #101420;
  --surface3: #181e2e;
  --border: #1e2638;
  --border2: #263040;
  --accent: #4f8eff;
  --accent-glow: rgba(79,142,255,0.2);
  --accent2: #ff6b6b;
  --accent3: #00e5a0;
  --accent4: #bf7fff;
  --accent5: #ffb84f;
  --text: #dce8ff;
  --text2: #8fa3c8;
  --muted: #4a5878;
  --danger: #ff4d6d;
  --success: #00e5a0;
  --warning: #ffb84f;
  --info: #4f8eff;
}
*{margin:0;padding:0;box-sizing:border-box;}
html,body{height:100%;overflow:hidden;}
body{background:var(--bg);color:var(--text);font-family:'Outfit',sans-serif;display:flex;height:100vh;}
::-webkit-scrollbar{width:4px;height:4px;}
::-webkit-scrollbar-track{background:transparent;}
::-webkit-scrollbar-thumb{background:var(--border2);border-radius:2px;}
::-webkit-scrollbar-thumb:hover{background:var(--muted);}

/* ── GRID BACKGROUND ── */
body::before {
  content:'';position:fixed;inset:0;pointer-events:none;
  background-image:linear-gradient(var(--border) 1px,transparent 1px),linear-gradient(90deg,var(--border) 1px,transparent 1px);
  background-size:40px 40px;opacity:.15;z-index:0;
}

/* ── LOGIN ── */
#login-screen{
  position:fixed;inset:0;z-index:1000;display:flex;align-items:center;justify-content:center;
  background:var(--bg);
}
.login-card{
  width:420px;background:var(--surface);border:1px solid var(--border2);border-radius:16px;
  padding:48px 40px;position:relative;z-index:1;
  box-shadow:0 0 80px rgba(79,142,255,0.08),0 0 0 1px var(--border2);
}
.login-card::before{
  content:'';position:absolute;top:-1px;left:40px;right:40px;height:2px;
  background:linear-gradient(90deg,transparent,var(--accent),transparent);
}
.login-logo{text-align:center;margin-bottom:36px;}
.login-icon{font-size:52px;display:block;margin-bottom:14px;}
.login-logo h1{font-size:22px;font-weight:900;letter-spacing:-.5px;}
.login-logo p{font-size:11px;color:var(--muted);font-family:'JetBrains Mono',monospace;margin-top:5px;letter-spacing:.1em;}
.fl{margin-bottom:20px;}
.fl label{display:block;font-size:11px;font-weight:700;color:var(--text2);text-transform:uppercase;letter-spacing:.1em;margin-bottom:8px;font-family:'JetBrains Mono',monospace;}
.fi{
  width:100%;background:var(--surface2);border:1px solid var(--border2);border-radius:10px;
  padding:13px 16px;color:var(--text);font-size:14px;font-family:'Outfit',sans-serif;
  transition:border-color .2s,box-shadow .2s;
}
.fi:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-glow);}
.btn{padding:12px 20px;border-radius:10px;font-size:14px;font-weight:700;cursor:pointer;border:none;transition:all .15s;font-family:'Outfit',sans-serif;display:inline-flex;align-items:center;gap:8px;}
.btn-primary{background:var(--accent);color:#fff;width:100%;justify-content:center;margin-bottom:10px;}
.btn-primary:hover{background:#6ba3ff;box-shadow:0 4px 20px rgba(79,142,255,.35);transform:translateY(-1px);}
.btn-primary:active{transform:translateY(0);}
.btn-ghost{background:transparent;color:var(--text2);border:1px solid var(--border2);width:100%;justify-content:center;}
.btn-ghost:hover{border-color:var(--accent);color:var(--accent);}
.btn-sm{padding:5px 12px;font-size:12px;border-radius:7px;}
.btn-danger{background:rgba(255,77,109,.1);color:var(--danger);border:1px solid rgba(255,77,109,.25);}
.btn-danger:hover{background:rgba(255,77,109,.2);}
.btn-success{background:rgba(0,229,160,.1);color:var(--success);border:1px solid rgba(0,229,160,.25);}
.btn-success:hover{background:rgba(0,229,160,.2);}
.btn-info{background:rgba(79,142,255,.1);color:var(--accent);border:1px solid rgba(79,142,255,.25);}
.btn-info:hover{background:rgba(79,142,255,.2);}
.btn-warn{background:rgba(255,184,79,.1);color:var(--warning);border:1px solid rgba(255,184,79,.25);}
.btn-warn:hover{background:rgba(255,184,79,.2);}
.alert{padding:12px 16px;border-radius:8px;margin-bottom:16px;font-size:13px;font-family:'JetBrains Mono',monospace;}
.alert-error{background:rgba(255,77,109,.08);border:1px solid rgba(255,77,109,.3);color:var(--danger);}
.alert-success{background:rgba(0,229,160,.08);border:1px solid rgba(0,229,160,.3);color:var(--success);}
.rate-limit{text-align:center;margin-top:12px;font-size:12px;color:var(--danger);font-family:'JetBrains Mono',monospace;}

/* ── SIDEBAR ── */
#app{display:none;width:100%;height:100%;flex:1;overflow:hidden;}
.layout{display:flex;height:100vh;overflow:hidden;position:relative;z-index:1;}
.sidebar{
  width:230px;background:var(--surface);border-right:1px solid var(--border);
  display:flex;flex-direction:column;flex-shrink:0;overflow:hidden;
}
.sb-head{padding:20px 20px 14px;border-bottom:1px solid var(--border);}
.sb-head h2{font-size:15px;font-weight:900;letter-spacing:-.3px;color:var(--text);}
.sb-head p{font-size:10px;color:var(--muted);font-family:'JetBrains Mono',monospace;margin-top:3px;letter-spacing:.06em;}
.sb-status{padding:10px 20px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:8px;}
.dot{width:7px;height:7px;border-radius:50%;background:var(--success);flex-shrink:0;}
.dot.off{background:var(--danger);}
.dot-pulse{animation:dpulse 2s ease-in-out infinite;}
@keyframes dpulse{0%,100%{box-shadow:0 0 0 0 rgba(0,229,160,.4)}50%{box-shadow:0 0 0 5px rgba(0,229,160,0)}}
.sb-status span{font-size:11px;color:var(--text2);font-family:'JetBrains Mono',monospace;}
nav{flex:1;padding:8px 0;overflow-y:auto;}
.nav-group{padding:16px 20px 6px;font-size:9px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.15em;font-family:'JetBrains Mono',monospace;}
.nav-item{
  display:flex;align-items:center;gap:10px;padding:9px 20px;
  color:var(--text2);font-size:13px;font-weight:500;
  cursor:pointer;transition:all .15s;border:none;background:none;width:100%;text-align:left;
  position:relative;border-left:2px solid transparent;
}
.nav-item:hover{color:var(--text);background:rgba(79,142,255,.04);}
.nav-item.active{color:var(--accent);background:rgba(79,142,255,.08);border-left-color:var(--accent);}
.nav-icon{font-size:15px;width:20px;text-align:center;}
.nav-badge{margin-left:auto;background:var(--danger);color:#fff;font-size:9px;font-weight:800;padding:2px 6px;border-radius:10px;font-family:'JetBrains Mono',monospace;}
.sb-foot{padding:12px 16px;border-top:1px solid var(--border);}

/* ── MAIN ── */
.main{flex:1;display:flex;flex-direction:column;overflow:hidden;}
.topbar{
  height:52px;background:var(--surface);border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between;padding:0 24px;flex-shrink:0;
}
.tb-left{display:flex;align-items:center;gap:10px;}
.tb-title{font-size:14px;font-weight:700;}
.tb-breadcrumb{font-size:11px;color:var(--muted);font-family:'JetBrains Mono',monospace;}
.tb-right{display:flex;align-items:center;gap:10px;}
.uptime-chip{font-size:10px;font-family:'JetBrains Mono',monospace;color:var(--success);background:rgba(0,229,160,.06);border:1px solid rgba(0,229,160,.15);padding:4px 10px;border-radius:20px;}
.time-chip{font-size:10px;font-family:'JetBrains Mono',monospace;color:var(--muted);background:var(--surface2);border:1px solid var(--border);padding:4px 10px;border-radius:20px;}
.content{flex:1;overflow-y:auto;padding:24px;background:var(--bg);}

/* ── PAGES ── */
.page{display:none;}
.page.active{display:block;animation:fadeIn .2s ease;}
@keyframes fadeIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}
.ph{margin-bottom:24px;}
.ph h1{font-size:26px;font-weight:900;letter-spacing:-.8px;}
.ph p{font-size:11px;color:var(--muted);font-family:'JetBrains Mono',monospace;margin-top:5px;letter-spacing:.04em;}
.ph-row{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;}
.ph-actions{display:flex;gap:8px;margin-top:4px;}

/* ── STAT CARDS ── */
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px;}
@media(max-width:1100px){.cards{grid-template-columns:repeat(2,1fr);}}
.card{
  background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px;
  position:relative;overflow:hidden;transition:border-color .2s,transform .2s;cursor:default;
}
.card:hover{border-color:var(--border2);transform:translateY(-1px);}
.card-stripe{position:absolute;top:0;left:0;right:0;height:2px;}
.s-blue{background:linear-gradient(90deg,var(--accent),transparent);}
.s-red{background:linear-gradient(90deg,var(--accent2),transparent);}
.s-green{background:linear-gradient(90deg,var(--accent3),transparent);}
.s-purple{background:linear-gradient(90deg,var(--accent4),transparent);}
.s-orange{background:linear-gradient(90deg,var(--accent5),transparent);}
.card-top{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;}
.card-icon{font-size:22px;}
.card-trend{font-size:11px;font-family:'JetBrains Mono',monospace;padding:2px 8px;border-radius:20px;}
.trend-up{background:rgba(0,229,160,.1);color:var(--success);border:1px solid rgba(0,229,160,.2);}
.trend-down{background:rgba(255,77,109,.1);color:var(--danger);border:1px solid rgba(255,77,109,.2);}
.card-val{font-size:30px;font-weight:900;line-height:1;letter-spacing:-1.5px;color:var(--text);}
.card-lbl{font-size:10px;color:var(--muted);margin-top:5px;font-family:'JetBrains Mono',monospace;text-transform:uppercase;letter-spacing:.08em;}
.card-sub{font-size:11px;color:var(--text2);margin-top:6px;}

/* ── TABLES ── */
.tbl-wrap{background:var(--surface);border:1px solid var(--border);border-radius:12px;overflow:hidden;margin-bottom:16px;}
.tbl-head{padding:14px 18px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;}
.tbl-head h3{font-size:13px;font-weight:700;white-space:nowrap;}
.tbl-tools{display:flex;gap:8px;align-items:center;}
.search-input{
  background:var(--surface2);border:1px solid var(--border2);border-radius:7px;
  padding:6px 12px;color:var(--text);font-size:12px;font-family:'Outfit',sans-serif;width:180px;
}
.search-input:focus{outline:none;border-color:var(--accent);}
table{width:100%;border-collapse:collapse;}
th{
  padding:10px 14px;text-align:left;font-size:10px;font-weight:700;color:var(--muted);
  background:var(--surface2);text-transform:uppercase;letter-spacing:.08em;
  font-family:'JetBrains Mono',monospace;white-space:nowrap;
}
td{padding:10px 14px;font-size:12px;border-bottom:1px solid var(--border);vertical-align:middle;}
tr:last-child td{border-bottom:none;}
tr:hover td{background:rgba(79,142,255,.02);}
.empty-row td{text-align:center;color:var(--muted);padding:32px;font-family:'JetBrains Mono',monospace;font-size:11px;}
.badge{display:inline-block;padding:2px 8px;border-radius:5px;font-size:10px;font-weight:700;font-family:'JetBrains Mono',monospace;white-space:nowrap;}
.b-blue{background:rgba(79,142,255,.1);color:var(--accent);border:1px solid rgba(79,142,255,.2);}
.b-red{background:rgba(255,77,109,.1);color:var(--danger);border:1px solid rgba(255,77,109,.2);}
.b-green{background:rgba(0,229,160,.1);color:var(--success);border:1px solid rgba(0,229,160,.2);}
.b-purple{background:rgba(191,127,255,.1);color:var(--accent4);border:1px solid rgba(191,127,255,.2);}
.b-orange{background:rgba(255,184,79,.1);color:var(--warning);border:1px solid rgba(255,184,79,.2);}
.b-gray{background:rgba(74,88,120,.15);color:var(--text2);border:1px solid var(--border);}
code.uid{font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--accent);background:rgba(79,142,255,.08);padding:2px 6px;border-radius:4px;}

/* ── GRID ── */
.g2{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px;}
.g3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-bottom:16px;}
@media(max-width:900px){.g2,.g3{grid-template-columns:1fr;}}

/* ── SECTION ── */
.section{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px;margin-bottom:16px;}
.section h3{font-size:14px;font-weight:700;margin-bottom:4px;}
.section-sub{font-size:11px;color:var(--muted);margin-bottom:18px;font-family:'JetBrains Mono',monospace;}
.form-group{margin-bottom:16px;}
.form-label{display:block;font-size:11px;font-weight:700;color:var(--text2);text-transform:uppercase;letter-spacing:.08em;margin-bottom:7px;font-family:'JetBrains Mono',monospace;}
.form-input{
  width:100%;background:var(--surface2);border:1px solid var(--border2);border-radius:8px;
  padding:11px 14px;color:var(--text);font-size:13px;font-family:'Outfit',sans-serif;
  transition:border-color .2s;
}
.form-input:focus{outline:none;border-color:var(--accent);}
.form-textarea{
  width:100%;background:var(--surface2);border:1px solid var(--border2);border-radius:8px;
  padding:12px 14px;color:var(--text);font-size:13px;font-family:'Outfit',sans-serif;
  resize:vertical;min-height:100px;transition:border-color .2s;
}
.form-textarea:focus{outline:none;border-color:var(--accent);}
.form-select{
  width:100%;background:var(--surface2);border:1px solid var(--border2);border-radius:8px;
  padding:11px 14px;color:var(--text);font-size:13px;font-family:'Outfit',sans-serif;
  cursor:pointer;
}
.form-select:focus{outline:none;border-color:var(--accent);}

/* ── TOGGLE ── */
.toggle-row{display:flex;align-items:center;justify-content:space-between;padding:16px 18px;background:var(--surface);border:1px solid var(--border);border-radius:10px;margin-bottom:10px;}
.toggle-info h4{font-size:13px;font-weight:700;}
.toggle-info p{font-size:11px;color:var(--muted);margin-top:2px;font-family:'JetBrains Mono',monospace;}
.toggle{position:relative;width:44px;height:24px;cursor:pointer;flex-shrink:0;}
.toggle input{opacity:0;width:0;height:0;}
.slider{position:absolute;inset:0;background:var(--surface3);border-radius:24px;transition:.3s;border:1px solid var(--border2);}
.slider:before{content:'';position:absolute;height:16px;width:16px;left:3px;bottom:3px;background:var(--muted);border-radius:50%;transition:.3s;}
.toggle input:checked + .slider{background:rgba(0,229,160,.15);border-color:var(--success);}
.toggle input:checked + .slider:before{transform:translateX(20px);background:var(--success);}

/* ── TOAST ── */
#toast{
  position:fixed;bottom:24px;right:24px;padding:12px 18px;border-radius:10px;font-size:13px;
  font-weight:600;z-index:9999;transform:translateY(100px);opacity:0;
  transition:all .3s cubic-bezier(.34,1.56,.64,1);pointer-events:none;max-width:320px;
}
#toast.show{transform:translateY(0);opacity:1;}
#toast.success{background:rgba(0,229,160,.1);border:1px solid rgba(0,229,160,.3);color:var(--success);}
#toast.error{background:rgba(255,77,109,.1);border:1px solid rgba(255,77,109,.3);color:var(--danger);}
#toast.info{background:rgba(79,142,255,.1);border:1px solid rgba(79,142,255,.3);color:var(--accent);}

/* ── SPINNER ── */
.spin{display:inline-block;width:14px;height:14px;border:2px solid var(--border2);border-top-color:var(--accent);border-radius:50%;animation:spin .7s linear infinite;}
@keyframes spin{to{transform:rotate(360deg)}}
.loading{display:flex;align-items:center;justify-content:center;padding:40px;color:var(--muted);gap:10px;font-size:12px;font-family:'JetBrains Mono',monospace;}

/* ── MINI CHART ── */
.mini-bar{display:inline-block;height:16px;background:var(--accent);border-radius:2px;min-width:3px;vertical-align:middle;opacity:.8;}

/* ── SESSION INFO ── */
.session-info{font-size:11px;color:var(--muted);font-family:'JetBrains Mono',monospace;text-align:center;margin-top:12px;}

/* ── MODAL ── */
.modal-overlay{position:fixed;inset:0;background:rgba(5,8,16,.85);z-index:500;display:flex;align-items:center;justify-content:center;display:none;}
.modal-overlay.open{display:flex;}
.modal{background:var(--surface);border:1px solid var(--border2);border-radius:14px;padding:28px;width:500px;max-width:90vw;max-height:80vh;overflow-y:auto;}
.modal h3{font-size:17px;font-weight:800;margin-bottom:6px;}
.modal p{font-size:12px;color:var(--muted);margin-bottom:20px;font-family:'JetBrains Mono',monospace;}
.modal-actions{display:flex;gap:10px;justify-content:flex-end;margin-top:20px;}

/* ── PROGRESS BAR ── */
.prog-bar{height:4px;background:var(--surface3);border-radius:2px;overflow:hidden;margin-top:6px;}
.prog-fill{height:100%;border-radius:2px;transition:width .5s;}

/* ── ACTIVITY ITEMS ── */
.act-item{display:flex;gap:12px;padding:10px 0;border-bottom:1px solid var(--border);align-items:flex-start;}
.act-item:last-child{border-bottom:none;}
.act-icon{width:34px;height:34px;border-radius:9px;display:flex;align-items:center;justify-content:center;font-size:15px;flex-shrink:0;background:var(--surface2);}
.act-body strong{font-size:12px;}
.act-body p{font-size:11px;color:var(--muted);font-family:'JetBrains Mono',monospace;margin-top:1px;}

/* ── TAG INPUT ── */
.tags-wrap{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;}
.tag{display:inline-flex;align-items:center;gap:5px;background:rgba(79,142,255,.1);color:var(--accent);border:1px solid rgba(79,142,255,.2);padding:3px 10px;border-radius:5px;font-size:12px;font-family:'JetBrains Mono',monospace;}
</style>
</head>
<body>

<!-- LOGIN SCREEN -->
<div id="login-screen">
  <div class="login-card">
    <div class="login-logo">
      <span class="login-icon">🤖</span>
      <h1>Bot Control Panel</h1>
      <p>SECURE ADMIN ACCESS</p>
    </div>
    <div id="login-alert" class="alert alert-error" style="display:none"></div>
    <div class="fl">
      <label>Admin Password</label>
      <input type="password" id="login-pw" class="fi" placeholder="Enter password..." autocomplete="current-password">
    </div>
    <div class="fl" style="margin-top:-8px">
      <label style="display:flex;justify-content:space-between">
        <span>Two-Factor Token</span>
        <span style="font-size:9px;color:var(--muted)">(Optional)</span>
      </label>
      <input type="text" id="login-otp" class="fi" placeholder="Leave blank if not configured..." autocomplete="off" maxlength="6">
    </div>
    <button class="btn btn-primary" id="login-btn" onclick="doLogin()">
      <span>🔐</span> Secure Login
    </button>
    <button class="btn btn-ghost" onclick="devLogin()">⚡ Dev Bypass</button>
    <div id="rate-msg" class="rate-limit" style="display:none"></div>
    <div class="session-info" id="login-tip">Protected by rate limiting & session tokens</div>
  </div>
</div>

<!-- USER DETAIL MODAL -->
<div class="modal-overlay" id="user-modal">
  <div class="modal">
    <h3>👤 User Details</h3>
    <p id="modal-uid">—</p>
    <div id="modal-body"></div>
    <div class="modal-actions">
      <button class="btn btn-ghost btn-sm" onclick="closeModal()">Close</button>
    </div>
  </div>
</div>

<!-- APP -->
<div id="app">
  <div class="layout">
    <!-- SIDEBAR -->
    <div class="sidebar">
      <div class="sb-head">
        <h2>🤖 BotAdmin</h2>
        <p>CONTROL PANEL v3.0</p>
      </div>
      <div class="sb-status">
        <span class="dot dot-pulse" id="status-dot"></span>
        <span id="bot-status-text">Connecting...</span>
      </div>
      <nav>
        <div class="nav-group">Overview</div>
        <button class="nav-item active" id="nav-dashboard" onclick="gotoPage('dashboard')">
          <span class="nav-icon">📊</span> Dashboard
        </button>
        <button class="nav-item" id="nav-analytics" onclick="gotoPage('analytics')">
          <span class="nav-icon">📈</span> Analytics
        </button>
        <div class="nav-group">Management</div>
        <button class="nav-item" id="nav-users" onclick="gotoPage('users')">
          <span class="nav-icon">👥</span> Users
        </button>
        <button class="nav-item" id="nav-expenses" onclick="gotoPage('expenses')">
          <span class="nav-icon">💰</span> Expenses
        </button>
        <button class="nav-item" id="nav-notes" onclick="gotoPage('notes')">
          <span class="nav-icon">📝</span> Notes
        </button>
        <div class="nav-group">Operations</div>
        <button class="nav-item" id="nav-broadcast" onclick="gotoPage('broadcast')">
          <span class="nav-icon">📢</span> Broadcast
        </button>
        <button class="nav-item" id="nav-maintenance" onclick="gotoPage('maintenance')">
          <span class="nav-icon">🔧</span> Maintenance
        </button>
        <button class="nav-item" id="nav-security" onclick="gotoPage('security')">
          <span class="nav-icon">🔒</span> Security
        </button>
        <div class="nav-group">Logs</div>
        <button class="nav-item" id="nav-errors" onclick="gotoPage('errors')">
          <span class="nav-icon">⚠️</span> Error Logs
          <span class="nav-badge" id="error-badge" style="display:none">!</span>
        </button>
        <button class="nav-item" id="nav-audit" onclick="gotoPage('audit')">
          <span class="nav-icon">📋</span> Audit Log
        </button>
      </nav>
      <div class="sb-foot">
        <button class="btn btn-danger btn-sm" style="width:100%;justify-content:center" onclick="doLogout()">
          🚪 Logout
        </button>
      </div>
    </div>

    <!-- MAIN -->
    <div class="main">
      <div class="topbar">
        <div class="tb-left">
          <span class="tb-title" id="topbar-title">Dashboard</span>
          <span class="tb-breadcrumb" id="topbar-bc">/ overview</span>
        </div>
        <div class="tb-right">
          <span class="uptime-chip" id="uptime-chip">⬤ UPTIME —</span>
          <span class="time-chip" id="time-chip">—</span>
          <button class="btn btn-info btn-sm" onclick="refreshPage()">↺</button>
        </div>
      </div>
      <div class="content" id="content">

        <!-- ══════════ DASHBOARD ══════════ -->
        <div class="page active" id="page-dashboard">
          <div class="ph-row">
            <div class="ph"><h1>Dashboard</h1><p id="dash-ts">LOADING DATA...</p></div>
            <div class="ph-actions">
              <button class="btn btn-info btn-sm" onclick="exportData()">⬇ Export DB</button>
            </div>
          </div>
          <div class="cards">
            <div class="card"><div class="card-stripe s-blue"></div>
              <div class="card-top"><span class="card-icon">👥</span><span class="card-trend trend-up" id="d-u-trend">—</span></div>
              <div class="card-val" id="d-users">—</div><div class="card-lbl">Total Users</div>
            </div>
            <div class="card"><div class="card-stripe s-green"></div>
              <div class="card-top"><span class="card-icon">💰</span><span class="card-trend" id="d-e-trend">—</span></div>
              <div class="card-val" id="d-expenses">—</div><div class="card-lbl">Total Expense ($)</div>
            </div>
            <div class="card"><div class="card-stripe s-purple"></div>
              <div class="card-top"><span class="card-icon">📝</span></div>
              <div class="card-val" id="d-notes">—</div><div class="card-lbl">Notes Stored</div>
            </div>
            <div class="card"><div class="card-stripe s-red"></div>
              <div class="card-top"><span class="card-icon">⚠️</span></div>
              <div class="card-val" id="d-errors">—</div><div class="card-lbl">Error Logs</div>
            </div>
          </div>
          <div class="g2">
            <div class="tbl-wrap">
              <div class="tbl-head"><h3>🆕 New Users</h3></div>
              <table><thead><tr><th>User ID</th><th>Username</th><th>Joined</th></tr></thead>
              <tbody id="dash-ru"></tbody></table>
            </div>
            <div class="tbl-wrap">
              <div class="tbl-head"><h3>💸 Recent Expenses</h3></div>
              <table><thead><tr><th>User</th><th>Category</th><th>Amount</th><th>Date</th></tr></thead>
              <tbody id="dash-re"></tbody></table>
            </div>
          </div>
          <div class="g2">
            <div class="section">
              <h3>📊 Expense Distribution</h3>
              <p class="section-sub">BY CATEGORY (TOP 5)</p>
              <div id="cat-chart"></div>
            </div>
            <div class="section">
              <h3>⚡ Recent Activity</h3>
              <p class="section-sub">SYSTEM EVENTS</p>
              <div id="activity-feed"></div>
            </div>
          </div>
        </div>

        <!-- ══════════ ANALYTICS ══════════ -->
        <div class="page" id="page-analytics">
          <div class="ph"><h1>Analytics</h1><p>GROWTH & USAGE INSIGHTS</p></div>
          <div class="cards">
            <div class="card"><div class="card-stripe s-blue"></div>
              <div class="card-top"><span class="card-icon">📅</span></div>
              <div class="card-val" id="an-today">—</div><div class="card-lbl">Expenses Today</div>
            </div>
            <div class="card"><div class="card-stripe s-green"></div>
              <div class="card-top"><span class="card-icon">📆</span></div>
              <div class="card-val" id="an-month">—</div><div class="card-lbl">This Month ($)</div>
            </div>
            <div class="card"><div class="card-stripe s-purple"></div>
              <div class="card-top"><span class="card-icon">🔁</span></div>
              <div class="card-val" id="an-recurring">—</div><div class="card-lbl">Recurring Expenses</div>
            </div>
            <div class="card"><div class="card-stripe s-orange"></div>
              <div class="card-top"><span class="card-icon">⚙️</span></div>
              <div class="card-val" id="an-reminders">—</div><div class="card-lbl">Active Reminders</div>
            </div>
          </div>
          <div class="tbl-wrap">
            <div class="tbl-head"><h3>📅 Monthly Breakdown</h3></div>
            <table><thead><tr><th>Month</th><th>Transactions</th><th>Total ($)</th><th>Avg ($)</th><th>Visual</th></tr></thead>
            <tbody id="an-months"></tbody></table>
          </div>
          <div class="g2">
            <div class="tbl-wrap">
              <div class="tbl-head"><h3>🏷️ Top Tags</h3></div>
              <table><thead><tr><th>Tag</th><th>Uses</th><th>Total ($)</th></tr></thead>
              <tbody id="an-tags"></tbody></table>
            </div>
            <div class="tbl-wrap">
              <div class="tbl-head"><h3>🌍 Languages</h3></div>
              <table><thead><tr><th>Language</th><th>Users</th><th>%</th></tr></thead>
              <tbody id="an-langs"></tbody></table>
            </div>
          </div>
        </div>

        <!-- ══════════ USERS ══════════ -->
        <div class="page" id="page-users">
          <div class="ph-row">
            <div class="ph"><h1>Users</h1><p id="users-sub">ALL REGISTERED USERS</p></div>
            <div class="ph-actions">
              <button class="btn btn-warn btn-sm" onclick="exportUsers()">⬇ CSV</button>
            </div>
          </div>
          <div class="tbl-wrap">
            <div class="tbl-head">
              <h3>👥 All Users</h3>
              <div class="tbl-tools">
                <input class="search-input" id="user-search" placeholder="Search ID / username..." oninput="filterUsers()">
                <select class="form-select" style="width:120px;padding:6px 10px;font-size:12px" id="user-filter" onchange="filterUsers()">
                  <option value="">All</option>
                  <option value="banned">Banned</option>
                  <option value="reminder">Reminder ON</option>
                  <option value="pin">Has PIN</option>
                </select>
              </div>
            </div>
            <table>
              <thead><tr>
                <th>User ID</th><th>Username</th><th>Lang</th>
                <th>Expenses</th><th>Notes</th><th>Budget</th>
                <th>Reminder</th><th>Joined</th><th>Status</th><th>Actions</th>
              </tr></thead>
              <tbody id="users-tbody"><tr class="empty-row"><td colspan="10"><div class="loading"><div class="spin"></div>Loading users...</div></td></tr></tbody>
            </table>
          </div>
        </div>

        <!-- ══════════ EXPENSES ══════════ -->
        <div class="page" id="page-expenses">
          <div class="ph"><h1>Expenses</h1><p>FINANCIAL STATISTICS</p></div>
          <div class="g3">
            <div class="tbl-wrap">
              <div class="tbl-head"><h3>📁 By Category</h3></div>
              <table><thead><tr><th>Category</th><th>Count</th><th>Total ($)</th></tr></thead>
              <tbody id="exp-cat"></tbody></table>
            </div>
            <div class="tbl-wrap">
              <div class="tbl-head"><h3>📅 By Month</h3></div>
              <table><thead><tr><th>Month</th><th>Count</th><th>Total ($)</th></tr></thead>
              <tbody id="exp-month"></tbody></table>
            </div>
            <div class="tbl-wrap">
              <div class="tbl-head"><h3>🏆 Top Spenders</h3></div>
              <table><thead><tr><th>User</th><th>Txns</th><th>Total ($)</th></tr></thead>
              <tbody id="exp-top"></tbody></table>
            </div>
          </div>
          <div class="tbl-wrap">
            <div class="tbl-head">
              <h3>📄 All Transactions</h3>
              <div class="tbl-tools">
                <input class="search-input" id="exp-search" placeholder="Search category / note..." oninput="filterExp()">
              </div>
            </div>
            <table><thead><tr><th>ID</th><th>User</th><th>Category</th><th>Amount</th><th>Note</th><th>Tag</th><th>Recurring</th><th>Date</th></tr></thead>
            <tbody id="exp-all"></tbody></table>
          </div>
        </div>

        <!-- ══════════ NOTES ══════════ -->
        <div class="page" id="page-notes">
          <div class="ph"><h1>Notes</h1><p>USER NOTES OVERVIEW</p></div>
          <div class="tbl-wrap">
            <div class="tbl-head">
              <h3>📝 All Notes</h3>
              <div class="tbl-tools">
                <input class="search-input" id="note-search" placeholder="Search notes..." oninput="filterNotes()">
              </div>
            </div>
            <table><thead><tr><th>ID</th><th>User</th><th>Content</th><th>Created</th><th>Action</th></tr></thead>
            <tbody id="notes-tbody"></tbody></table>
          </div>
        </div>

        <!-- ══════════ BROADCAST ══════════ -->
        <div class="page" id="page-broadcast">
          <div class="ph"><h1>Broadcast</h1><p>SEND MESSAGES TO USERS</p></div>
          <div id="bc-alert" style="display:none" class="alert"></div>
          <div class="g2">
            <div class="section">
              <h3>📢 New Broadcast</h3>
              <p class="section-sub">Sending to <strong id="bc-count" style="color:var(--accent)">—</strong> users</p>
              <div class="form-group">
                <label class="form-label">Target</label>
                <select class="form-select" id="bc-target">
                  <option value="all">All Users</option>
                  <option value="active">Active Users (expenses in last 30d)</option>
                  <option value="reminder">Users with Reminders ON</option>
                  <option value="specific">Specific User ID</option>
                </select>
              </div>
              <div class="form-group" id="bc-uid-group" style="display:none">
                <label class="form-label">User ID</label>
                <input type="text" class="form-input" id="bc-uid" placeholder="123456789">
              </div>
              <div class="form-group">
                <label class="form-label">Message <span style="color:var(--muted)">(Markdown supported)</span></label>
                <textarea id="bc-msg" class="form-textarea" placeholder="*Bold* _italic_ `code`..." oninput="updatePreview()"></textarea>
              </div>
              <button class="btn btn-primary" onclick="sendBroadcast()" id="bc-btn" style="width:auto">
                <span>📤</span> Send Broadcast
              </button>
            </div>
            <div class="section">
              <h3>👀 Preview</h3>
              <p class="section-sub">HOW IT LOOKS IN TELEGRAM</p>
              <div id="bc-preview" style="background:var(--surface2);border:1px solid var(--border);border-radius:10px;padding:16px;min-height:100px;font-size:13px;line-height:1.6;white-space:pre-wrap;color:var(--text2)">
                Start typing your message...
              </div>
              <div style="margin-top:12px">
                <div class="form-group">
                  <label class="form-label">Quick Templates</label>
                  <div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:6px">
                    <button class="btn btn-ghost btn-sm" onclick="setTemplate('reminder')">📅 Daily Reminder</button>
                    <button class="btn btn-ghost btn-sm" onclick="setTemplate('update')">🚀 Update Notice</button>
                    <button class="btn btn-ghost btn-sm" onclick="setTemplate('maintenance')">🔧 Maintenance</button>
                    <button class="btn btn-ghost btn-sm" onclick="setTemplate('welcome')">👋 Welcome Back</button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- ══════════ MAINTENANCE ══════════ -->
        <div class="page" id="page-maintenance">
          <div class="ph"><h1>Maintenance</h1><p>BOT SETTINGS & SYSTEM CONTROLS</p></div>
          <div class="toggle-row">
            <div class="toggle-info">
              <h4>🔧 Maintenance Mode</h4>
              <p>Bot replies with maintenance message to all users</p>
            </div>
            <label class="toggle"><input type="checkbox" id="maint-toggle" onchange="toggleMaintenance()"><span class="slider"></span></label>
          </div>
          <div class="g2">
            <div class="section">
              <h3>🗄️ Database Stats</h3>
              <p class="section-sub">CURRENT DB COUNTS</p>
              <div id="db-info" style="font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--text2);line-height:2.2">Loading...</div>
            </div>
            <div class="section">
              <h3>🖥️ System Info</h3>
              <p class="section-sub">RUNTIME & ENVIRONMENT</p>
              <div id="sys-info" style="font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--text2);line-height:2.2">Loading...</div>
            </div>
          </div>
          <div class="section">
            <h3>⚡ Quick Actions</h3>
            <p class="section-sub">ADMIN OPERATIONS</p>
            <div style="display:flex;gap:10px;flex-wrap:wrap">
              <button class="btn btn-info btn-sm" onclick="exportData()">📦 Export Database</button>
              <button class="btn btn-warn btn-sm" onclick="clearErrorLogs()">🗑️ Clear Error Logs</button>
              <button class="btn btn-danger btn-sm" onclick="clearChatMemory()">🧹 Clear All Chat Memory</button>
            </div>
          </div>
        </div>

        <!-- ══════════ SECURITY ══════════ -->
        <div class="page" id="page-security">
          <div class="ph"><h1>Security</h1><p>ACCESS CONTROL & SESSION MANAGEMENT</p></div>
          <div class="g2">
            <div class="section">
              <h3>🔒 Banned Users</h3>
              <p class="section-sub" id="ban-count">— USERS BANNED</p>
              <div id="banned-list" style="max-height:300px;overflow-y:auto"></div>
              <div style="margin-top:14px">
                <label class="form-label">Ban User ID</label>
                <div style="display:flex;gap:8px">
                  <input type="text" class="form-input" id="ban-uid" placeholder="User ID to ban" style="flex:1">
                  <button class="btn btn-danger btn-sm" onclick="quickBan()">Ban</button>
                </div>
              </div>
            </div>
            <div class="section">
              <h3>🛡️ Rate Limiting Status</h3>
              <p class="section-sub">FAILED LOGIN ATTEMPTS BY IP</p>
              <div id="rate-status"></div>
              <div style="margin-top:16px">
                <button class="btn btn-success btn-sm" onclick="clearRateLimits()">✅ Clear All Rate Limits</button>
              </div>
            </div>
          </div>
          <div class="section">
            <h3>🔑 Active Sessions</h3>
            <p class="section-sub">CURRENTLY LOGGED IN ADMINS</p>
            <div id="sessions-list"></div>
          </div>
        </div>

        <!-- ══════════ ERRORS ══════════ -->
        <div class="page" id="page-errors">
          <div class="ph-row">
            <div class="ph"><h1>Error Logs</h1><p id="err-sub">LAST 50 ERRORS</p></div>
            <div class="ph-actions">
              <button class="btn btn-danger btn-sm" onclick="clearErrorLogs()">🗑️ Clear Logs</button>
            </div>
          </div>
          <div class="tbl-wrap">
            <div class="tbl-head">
              <h3>⚠️ Recent Errors</h3>
              <input class="search-input" id="err-search" placeholder="Search errors..." oninput="filterErrors()">
            </div>
            <table>
              <thead><tr><th>ID</th><th>User</th><th>Error</th><th>Context</th><th>Time</th></tr></thead>
              <tbody id="errors-tbody"></tbody>
            </table>
          </div>
        </div>

        <!-- ══════════ AUDIT LOG ══════════ -->
        <div class="page" id="page-audit">
          <div class="ph"><h1>Audit Log</h1><p>ADMIN ACTIONS HISTORY</p></div>
          <div class="tbl-wrap">
            <div class="tbl-head"><h3>📋 Admin Actions</h3></div>
            <table>
              <thead><tr><th>Time</th><th>Action</th><th>Detail</th><th>IP</th></tr></thead>
              <tbody id="audit-tbody"></tbody>
            </table>
          </div>
        </div>

      </div><!-- /content -->
    </div><!-- /main -->
  </div><!-- /layout -->
</div><!-- /app -->

<div id="toast"></div>

<script>
// ─────────────────────────────────────────────────
// STATE
// ─────────────────────────────────────────────────
let allUsers = [], allErrors = [], allExps = [], allNotes = [];
let currentPage = 'dashboard';

// ─────────────────────────────────────────────────
// AUTH
// ─────────────────────────────────────────────────
async function doLogin() {
  const pw = document.getElementById('login-pw').value.trim();
  const otp = document.getElementById('login-otp').value.trim();
  const alertEl = document.getElementById('login-alert');
  const btn = document.getElementById('login-btn');
  btn.disabled = true;
  btn.innerHTML = '<div class="spin"></div> Authenticating...';
  try {
    const res = await fetch('/admin/api/login', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({password:pw, otp})
    });
    if (res.ok) {
      document.getElementById('login-screen').style.display = 'none';
      document.getElementById('app').style.display = 'block';
      initApp();
    } else {
      const d = await res.json();
      alertEl.textContent = d.error || '❌ Wrong password';
      alertEl.style.display = 'block';
      if (d.locked) {
        document.getElementById('rate-msg').textContent = `🔒 Too many attempts. Try again in 5 minutes.`;
        document.getElementById('rate-msg').style.display = 'block';
        btn.disabled = true;
        setTimeout(() => { btn.disabled = false; btn.innerHTML = '<span>🔐</span> Secure Login'; }, 30000);
        return;
      }
    }
  } catch(e) {
    alertEl.textContent = '❌ Connection error';
    alertEl.style.display = 'block';
  }
  btn.disabled = false;
  btn.innerHTML = '<span>🔐</span> Secure Login';
}

function devLogin() {
  document.getElementById('login-pw').value = 'admin1234';
  doLogin();
}

async function doLogout() {
  await fetch('/admin/api/logout', {method:'POST'});
  toast('Logged out', 'info');
  setTimeout(() => location.reload(), 800);
}

// ─────────────────────────────────────────────────
// APP INIT
// ─────────────────────────────────────────────────
function initApp() {
  gotoPage('dashboard');
  startClocks();
  checkBotStatus();
}

function startClocks() {
  setInterval(() => {
    document.getElementById('time-chip').textContent =
      new Date().toISOString().slice(0,19).replace('T',' ') + ' UTC';
  }, 1000);
  setInterval(async () => {
    try {
      const r = await fetch('/health');
      const d = await r.json();
      const s = d.uptime_seconds;
      document.getElementById('uptime-chip').textContent =
        `⬤ ${Math.floor(s/3600)}h ${Math.floor((s%3600)/60)}m ${s%60}s`;
    } catch(e){}
  }, 5000);
}

async function checkBotStatus() {
  try {
    const r = await fetch('/health');
    const d = await r.json();
    const dot = document.getElementById('status-dot');
    const txt = document.getElementById('bot-status-text');
    if (d.status === 'ok') {
      dot.className = 'dot dot-pulse';
      txt.textContent = 'Bot Online';
    } else {
      dot.className = 'dot off';
      txt.textContent = 'Bot Offline';
    }
  } catch(e) {
    document.getElementById('status-dot').className = 'dot off';
    document.getElementById('bot-status-text').textContent = 'Unreachable';
  }
}

// ─────────────────────────────────────────────────
// NAVIGATION
// ─────────────────────────────────────────────────
function gotoPage(name) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  const pg = document.getElementById('page-' + name);
  const nav = document.getElementById('nav-' + name);
  if (pg) pg.classList.add('active');
  if (nav) nav.classList.add('active');
  document.getElementById('topbar-title').textContent = name.charAt(0).toUpperCase() + name.slice(1);
  document.getElementById('topbar-bc').textContent = '/ ' + name;
  currentPage = name;
  loadPage(name);
}
function refreshPage() { loadPage(currentPage); }
function loadPage(name) {
  const map = {
    dashboard: loadDashboard, analytics: loadAnalytics,
    users: loadUsers, expenses: loadExpenses, notes: loadNotes,
    broadcast: loadBroadcast, maintenance: loadMaintenance,
    security: loadSecurity, errors: loadErrors, audit: loadAudit
  };
  if (map[name]) map[name]();
}

// ─────────────────────────────────────────────────
// API
// ─────────────────────────────────────────────────
async function api(path, opts={}) {
  const res = await fetch(path, {headers:{'Content-Type':'application/json'}, ...opts});
  if (res.status === 401) { location.reload(); return null; }
  return res;
}

// ─────────────────────────────────────────────────
// TOAST
// ─────────────────────────────────────────────────
function toast(msg, type='success') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'show ' + type;
  setTimeout(() => t.className = '', 3500);
}

// ─────────────────────────────────────────────────
// DASHBOARD
// ─────────────────────────────────────────────────
async function loadDashboard() {
  document.getElementById('dash-ts').textContent =
    'LIVE OVERVIEW // ' + new Date().toISOString().slice(0,16).replace('T',' ') + ' UTC';
  const res = await api('/admin/api/dashboard');
  if (!res) return;
  const d = await res.json();
  document.getElementById('d-users').textContent = d.total_users ?? '—';
  document.getElementById('d-expenses').textContent = '$' + (d.total_expenses||0).toFixed(0);
  document.getElementById('d-notes').textContent = d.total_notes ?? '—';
  document.getElementById('d-errors').textContent = d.total_errors ?? '—';

  if (d.total_errors > 0) {
    const eb = document.getElementById('error-badge');
    eb.textContent = d.total_errors;
    eb.style.display = 'inline';
  }

  const ru = document.getElementById('dash-ru');
  ru.innerHTML = (d.recent_users||[]).length
    ? d.recent_users.map(u => `<tr>
        <td><code class="uid">${u.user_id}</code></td>
        <td>${u.username ? `<strong>@${u.username}</strong>` : '<span style="color:var(--muted)">anon</span>'}</td>
        <td style="color:var(--muted);font-size:11px">${(u.created_at||'').slice(0,10)}</td>
      </tr>`).join('')
    : '<tr class="empty-row"><td colspan="3">No users yet</td></tr>';

  const re = document.getElementById('dash-re');
  re.innerHTML = (d.recent_expenses||[]).length
    ? d.recent_expenses.map(e => `<tr>
        <td><code class="uid">${e.user_id}</code></td>
        <td><span class="badge b-orange">${e.category||'—'}</span></td>
        <td><span class="badge b-blue">$${(e.amount||0).toFixed(2)}</span></td>
        <td style="color:var(--muted);font-size:11px">${(e.date||'').slice(0,10)}</td>
      </tr>`).join('')
    : '<tr class="empty-row"><td colspan="4">No expenses yet</td></tr>';

  // Category mini chart
  if (d.expense_by_cat && d.expense_by_cat.length) {
    const max = Math.max(...d.expense_by_cat.map(c => c.total));
    document.getElementById('cat-chart').innerHTML = d.expense_by_cat.slice(0,5).map(c => `
      <div style="margin-bottom:12px">
        <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:4px">
          <span>${c.category||'Other'}</span>
          <span style="color:var(--muted);font-family:'JetBrains Mono',monospace">$${(c.total||0).toFixed(0)}</span>
        </div>
        <div class="prog-bar"><div class="prog-fill" style="width:${max?((c.total/max)*100).toFixed(0):0}%;background:var(--accent)"></div></div>
      </div>`).join('');
  } else {
    document.getElementById('cat-chart').innerHTML = '<p style="color:var(--muted);font-size:12px">No data yet</p>';
  }

  // Activity feed
  document.getElementById('activity-feed').innerHTML = `
    <div class="act-item"><div class="act-icon">👥</div><div class="act-body"><strong>${d.total_users} registered users</strong><p>Total bot users</p></div></div>
    <div class="act-item"><div class="act-icon">💰</div><div class="act-body"><strong>$${(d.total_expenses||0).toFixed(2)} tracked</strong><p>Across all users</p></div></div>
    <div class="act-item"><div class="act-icon">📝</div><div class="act-body"><strong>${d.total_notes} notes stored</strong><p>User notes database</p></div></div>
    <div class="act-item"><div class="act-icon">⚡</div><div class="act-body"><strong>Bot is running</strong><p>Health server OK</p></div></div>
  `;
}

// ─────────────────────────────────────────────────
// ANALYTICS
// ─────────────────────────────────────────────────
async function loadAnalytics() {
  const res = await api('/admin/api/analytics');
  if (!res) return;
  const d = await res.json();
  document.getElementById('an-today').textContent = d.today_count ?? '0';
  document.getElementById('an-month').textContent = '$' + (d.month_total||0).toFixed(0);
  document.getElementById('an-recurring').textContent = d.recurring_count ?? '0';
  document.getElementById('an-reminders').textContent = d.reminder_users ?? '0';

  const maxMonth = Math.max(...(d.monthly||[]).map(m => m.total||0), 1);
  document.getElementById('an-months').innerHTML = (d.monthly||[]).length
    ? d.monthly.map(m => `<tr>
        <td><span class="badge b-blue">${m.month}</span></td>
        <td>${m.count}</td>
        <td>$${(m.total||0).toFixed(2)}</td>
        <td style="color:var(--muted)">$${m.count?(m.total/m.count).toFixed(2):'0'}</td>
        <td><div class="prog-bar" style="width:120px"><div class="prog-fill" style="width:${((m.total/maxMonth)*100).toFixed(0)}%;background:var(--accent3)"></div></div></td>
      </tr>`).join('')
    : '<tr class="empty-row"><td colspan="5">No data</td></tr>';

  document.getElementById('an-tags').innerHTML = (d.top_tags||[]).length
    ? d.top_tags.map(t => `<tr>
        <td><span class="badge b-purple">${t.tag||'—'}</span></td>
        <td>${t.count}</td>
        <td>$${(t.total||0).toFixed(2)}</td>
      </tr>`).join('')
    : '<tr class="empty-row"><td colspan="3">No tags</td></tr>';

  document.getElementById('an-langs').innerHTML = (d.languages||[]).length
    ? d.languages.map(l => `<tr>
        <td><span class="badge b-green">${l.language||'km'}</span></td>
        <td>${l.count}</td>
        <td style="color:var(--muted)">${d.total_users?((l.count/d.total_users)*100).toFixed(0):0}%</td>
      </tr>`).join('')
    : '<tr class="empty-row"><td colspan="3">No data</td></tr>';
}

// ─────────────────────────────────────────────────
// USERS
// ─────────────────────────────────────────────────
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
    tbody.innerHTML = '<tr class="empty-row"><td colspan="10">No users found</td></tr>';
    return;
  }
  tbody.innerHTML = users.map(u => `<tr>
    <td><code class="uid">${u.user_id}</code></td>
    <td>${u.username ? `@${u.username}` : '<span style="color:var(--muted)">—</span>'}</td>
    <td><span class="badge b-blue">${u.language||'km'}</span></td>
    <td style="text-align:center">${u.expense_count||0}</td>
    <td style="text-align:center">${u.note_count||0}</td>
    <td style="color:var(--text2)">${u.budget ? '$'+u.budget : '—'}</td>
    <td><span class="badge ${u.daily_reminder ? 'b-green' : 'b-gray'}">${u.daily_reminder ? 'ON '+u.reminder_time : 'OFF'}</span></td>
    <td style="color:var(--muted);font-size:11px">${(u.created_at||'').slice(0,10)}</td>
    <td><span class="badge ${u.banned ? 'b-red' : 'b-green'}">${u.banned ? 'BANNED' : 'ACTIVE'}</span></td>
    <td style="display:flex;gap:4px">
      <button class="btn btn-info btn-sm" onclick="showUserDetail(${u.user_id})">👤</button>
      ${u.banned
        ? `<button class="btn btn-success btn-sm" onclick="banUser(${u.user_id},false)">Unban</button>`
        : `<button class="btn btn-danger btn-sm" onclick="banUser(${u.user_id},true)">Ban</button>`
      }
    </td>
  </tr>`).join('');
}

function filterUsers() {
  const q = document.getElementById('user-search').value.toLowerCase();
  const f = document.getElementById('user-filter').value;
  let filtered = allUsers.filter(u =>
    String(u.user_id).includes(q) || (u.username||'').toLowerCase().includes(q)
  );
  if (f === 'banned') filtered = filtered.filter(u => u.banned);
  if (f === 'reminder') filtered = filtered.filter(u => u.daily_reminder);
  if (f === 'pin') filtered = filtered.filter(u => u.pin);
  renderUsers(filtered);
}

async function banUser(uid, ban) {
  const res = await api(`/admin/api/${ban?'ban':'unban'}/${uid}`, {method:'POST'});
  if (res?.ok) { toast(ban ? `User ${uid} banned` : `User ${uid} unbanned`, ban?'error':'success'); loadUsers(); }
}

async function showUserDetail(uid) {
  const res = await api('/admin/api/user/' + uid);
  if (!res) return;
  const d = await res.json();
  document.getElementById('modal-uid').textContent = `USER ID: ${uid}`;
  document.getElementById('modal-body').innerHTML = `
    <div style="font-family:'JetBrains Mono',monospace;font-size:12px;line-height:2.2;color:var(--text2)">
      📛 Username: <strong style="color:var(--text)">${d.username||'—'}</strong><br>
      🌍 Language: <strong>${d.language||'km'}</strong><br>
      💰 Budget: <strong>$${d.budget||0}</strong><br>
      🔑 PIN set: <strong>${d.pin ? '✅ Yes' : '❌ No'}</strong><br>
      ⏰ Reminder: <strong>${d.daily_reminder ? 'ON @ '+d.reminder_time : 'OFF'}</strong><br>
      📅 Joined: <strong>${(d.created_at||'').slice(0,16)}</strong><br>
      💸 Expenses: <strong>${d.expense_count} entries / $${(d.expense_total||0).toFixed(2)}</strong><br>
      📝 Notes: <strong>${d.note_count}</strong>
    </div>
    ${d.recent_expenses && d.recent_expenses.length ? `
      <div style="margin-top:16px">
        <div class="form-label">Recent Expenses</div>
        <table style="margin-top:6px"><thead><tr><th>Category</th><th>Amount</th><th>Note</th><th>Date</th></tr></thead>
        <tbody>${d.recent_expenses.map(e=>`<tr><td><span class="badge b-orange">${e.category}</span></td><td>$${e.amount}</td><td style="color:var(--muted)">${e.note||'—'}</td><td style="font-size:11px;color:var(--muted)">${(e.date||'').slice(0,10)}</td></tr>`).join('')}</tbody>
        </table>
      </div>` : ''}
  `;
  document.getElementById('user-modal').classList.add('open');
}
function closeModal() { document.getElementById('user-modal').classList.remove('open'); }

function exportUsers() {
  const header = ['user_id','username','language','budget','expense_count','note_count','daily_reminder','created_at'];
  const rows = allUsers.map(u => header.map(k => JSON.stringify(u[k]??'')).join(','));
  const csv = [header.join(','), ...rows].join('\n');
  const a = document.createElement('a');
  a.href = 'data:text/csv;charset=utf-8,' + encodeURIComponent(csv);
  a.download = 'bot_users_' + new Date().toISOString().slice(0,10) + '.csv';
  a.click();
  toast('Users exported as CSV');
}

// ─────────────────────────────────────────────────
// EXPENSES
// ─────────────────────────────────────────────────
async function loadExpenses() {
  const res = await api('/admin/api/expenses');
  if (!res) return;
  const d = await res.json();
  allExps = d.all || [];

  document.getElementById('exp-cat').innerHTML = (d.by_category||[]).length
    ? d.by_category.map(r => `<tr><td>${r.category||'N/A'}</td><td>${r.count}</td><td><span class="badge b-blue">$${(r.total||0).toFixed(2)}</span></td></tr>`).join('')
    : '<tr class="empty-row"><td colspan="3">No data</td></tr>';

  document.getElementById('exp-month').innerHTML = (d.by_month||[]).length
    ? d.by_month.map(r => `<tr><td><span class="badge b-green">${r.month}</span></td><td>${r.count}</td><td><span class="badge b-blue">$${(r.total||0).toFixed(2)}</span></td></tr>`).join('')
    : '<tr class="empty-row"><td colspan="3">No data</td></tr>';

  document.getElementById('exp-top').innerHTML = (d.top_users||[]).length
    ? d.top_users.map(r => `<tr><td><code class="uid">${r.user_id}</code></td><td>${r.count}</td><td><span class="badge b-purple">$${(r.total||0).toFixed(2)}</span></td></tr>`).join('')
    : '<tr class="empty-row"><td colspan="3">No data</td></tr>';

  renderExpenses(allExps);
}

function renderExpenses(exps) {
  document.getElementById('exp-all').innerHTML = (exps||[]).length
    ? exps.slice(0,100).map(e => `<tr>
        <td><code class="uid">#${e.id}</code></td>
        <td><code class="uid">${e.user_id}</code></td>
        <td><span class="badge b-orange">${e.category||'—'}</span></td>
        <td><span class="badge b-blue">$${(e.amount||0).toFixed(2)}</span></td>
        <td style="color:var(--text2);max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${e.note||'—'}</td>
        <td>${e.tag ? `<span class="badge b-purple">${e.tag}</span>` : '—'}</td>
        <td>${e.is_recurring ? '<span class="badge b-green">YES</span>' : '—'}</td>
        <td style="font-size:11px;color:var(--muted)">${e.date||'—'}</td>
      </tr>`).join('')
    : '<tr class="empty-row"><td colspan="8">No expenses</td></tr>';
}

function filterExp() {
  const q = document.getElementById('exp-search').value.toLowerCase();
  renderExpenses(allExps.filter(e =>
    (e.category||'').toLowerCase().includes(q) || (e.note||'').toLowerCase().includes(q) || (e.tag||'').toLowerCase().includes(q)
  ));
}

// ─────────────────────────────────────────────────
// NOTES
// ─────────────────────────────────────────────────
async function loadNotes() {
  const res = await api('/admin/api/notes');
  if (!res) return;
  allNotes = await res.json();
  renderNotes(allNotes);
}

function renderNotes(notes) {
  document.getElementById('notes-tbody').innerHTML = (notes||[]).length
    ? notes.map(n => `<tr>
        <td><code class="uid">#${n.id}</code></td>
        <td><code class="uid">${n.user_id}</code></td>
        <td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${n.content||'—'}</td>
        <td style="font-size:11px;color:var(--muted)">${(n.created_at||'').slice(0,16)}</td>
        <td><button class="btn btn-danger btn-sm" onclick="deleteNote(${n.id})">🗑️</button></td>
      </tr>`).join('')
    : '<tr class="empty-row"><td colspan="5">No notes</td></tr>';
}

function filterNotes() {
  const q = document.getElementById('note-search').value.toLowerCase();
  renderNotes(allNotes.filter(n => (n.content||'').toLowerCase().includes(q)));
}

async function deleteNote(id) {
  if (!confirm('Delete this note?')) return;
  const res = await api('/admin/api/note/' + id, {method:'DELETE'});
  if (res?.ok) { toast('Note deleted'); loadNotes(); }
}

// ─────────────────────────────────────────────────
// BROADCAST
// ─────────────────────────────────────────────────
async function loadBroadcast() {
  const res = await api('/admin/api/dashboard');
  if (res?.ok) { const d = await res.json(); document.getElementById('bc-count').textContent = d.total_users ?? '—'; }
  document.getElementById('bc-target').addEventListener('change', e => {
    document.getElementById('bc-uid-group').style.display = e.target.value === 'specific' ? 'block' : 'none';
  });
}

function updatePreview() {
  const txt = document.getElementById('bc-msg').value;
  document.getElementById('bc-preview').textContent = txt ? '📢 Admin Announcement\n\n' + txt : 'Start typing...';
}

const TEMPLATES = {
  reminder: '⏰ *Daily Reminder!*\n\nDon\'t forget to log your expenses today! 💰\n\nUse /add to record a new expense.',
  update: '🚀 *Bot Update!*\n\nWe\'ve added new features to improve your experience.\n\nUse /help to see all available commands.',
  maintenance: '🔧 *Scheduled Maintenance*\n\nThe bot will be briefly unavailable for maintenance.\n\nWe\'ll be back shortly!',
  welcome: '👋 *Welcome Back!*\n\nHope you\'re doing great! Keep tracking your expenses and stay on budget. 💪',
};

function setTemplate(key) {
  document.getElementById('bc-msg').value = TEMPLATES[key] || '';
  updatePreview();
}

async function sendBroadcast() {
  const msg = document.getElementById('bc-msg').value.trim();
  const target = document.getElementById('bc-target').value;
  const uid = document.getElementById('bc-uid').value.trim();
  const alertEl = document.getElementById('bc-alert');
  if (!msg) { toast('Message cannot be empty', 'error'); return; }
  if (target === 'specific' && !uid) { toast('Enter a User ID', 'error'); return; }
  if (!confirm(`Send broadcast to ${target === 'specific' ? 'user '+uid : target} users?`)) return;
  const btn = document.getElementById('bc-btn');
  btn.disabled = true; btn.innerHTML = '<div class="spin"></div> Sending...';
  const res = await api('/admin/api/broadcast', {
    method:'POST', body:JSON.stringify({message:msg, target, user_id: uid||null})
  });
  btn.disabled = false; btn.innerHTML = '<span>📤</span> Send Broadcast';
  if (res?.ok) {
    const d = await res.json();
    alertEl.className = 'alert alert-success';
    alertEl.textContent = `✅ Sent to ${d.sent} users (${d.failed} failed)`;
    alertEl.style.display = 'block';
    document.getElementById('bc-msg').value = '';
    updatePreview();
    toast(`Broadcast sent to ${d.sent} users`);
  } else {
    alertEl.className = 'alert alert-error';
    alertEl.textContent = '❌ Broadcast failed. Bot may not be connected.';
    alertEl.style.display = 'block';
  }
}

// ─────────────────────────────────────────────────
// MAINTENANCE
// ─────────────────────────────────────────────────
async function loadMaintenance() {
  const res = await api('/admin/api/maintenance');
  if (!res) return;
  const d = await res.json();
  document.getElementById('maint-toggle').checked = d.maintenance_mode;
  document.getElementById('db-info').innerHTML = `
    👥 Users: <strong style="color:var(--text)">${d.users}</strong><br>
    💰 Expenses: <strong style="color:var(--text)">${d.expenses}</strong><br>
    📝 Notes: <strong style="color:var(--text)">${d.notes}</strong><br>
    💬 Chat Memory: <strong style="color:var(--text)">${d.chat_memory||0}</strong><br>
    ⚠️ Error Logs: <strong style="color:var(--text)">${d.errors}</strong>
  `;
  document.getElementById('sys-info').innerHTML = `
    🌐 Port: <strong style="color:var(--text)">${d.port}</strong><br>
    🕐 Uptime: <strong style="color:var(--text)">${d.uptime}</strong><br>
    🐍 Python: <strong style="color:var(--text)">${d.python}</strong><br>
    🔑 Token: <strong style="color:var(--text)">${d.token_status}</strong><br>
    🤖 Groq: <strong style="color:var(--text)">${d.groq_status}</strong>
  `;
}

async function toggleMaintenance() {
  const enabled = document.getElementById('maint-toggle').checked;
  const res = await api('/admin/api/maintenance/toggle', {method:'POST', body:JSON.stringify({enabled})});
  if (res?.ok) toast(enabled ? '🔧 Maintenance ON' : '✅ Maintenance OFF', enabled?'error':'success');
}

async function clearErrorLogs() {
  if (!confirm('Clear all error logs?')) return;
  const res = await api('/admin/api/errors/clear', {method:'POST'});
  if (res?.ok) { toast('Error logs cleared'); loadErrors(); }
}

async function clearChatMemory() {
  if (!confirm('Clear ALL chat memory for ALL users? This cannot be undone.')) return;
  const res = await api('/admin/api/chat/clear', {method:'POST'});
  if (res?.ok) { toast('Chat memory cleared', 'info'); }
}

async function exportData() {
  toast('Preparing export...', 'info');
  const res = await api('/admin/api/export');
  if (res?.ok) {
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'bot_export_' + new Date().toISOString().slice(0,10) + '.json';
    a.click();
    toast('Export downloaded');
  }
}

// ─────────────────────────────────────────────────
// SECURITY
// ─────────────────────────────────────────────────
async function loadSecurity() {
  const res = await api('/admin/api/security');
  if (!res) return;
  const d = await res.json();
  document.getElementById('ban-count').textContent = `${d.banned_count} USERS BANNED`;

  document.getElementById('banned-list').innerHTML = d.banned_users.length
    ? `<table style="margin-top:8px"><thead><tr><th>User ID</th><th>Action</th></tr></thead><tbody>
        ${d.banned_users.map(b=>`<tr><td><code class="uid">${b.user_id}</code></td><td><button class="btn btn-success btn-sm" onclick="banUser(${b.user_id},false)">Unban</button></td></tr>`).join('')}
       </tbody></table>`
    : '<p style="color:var(--muted);font-size:12px;margin-top:8px">No banned users 🎉</p>';

  const rs = document.getElementById('rate-status');
  const ips = Object.entries(d.rate_limits||{});
  rs.innerHTML = ips.length
    ? `<table><thead><tr><th>IP</th><th>Attempts</th><th>Status</th></tr></thead><tbody>
        ${ips.map(([ip, count])=>`<tr><td><code class="uid">${ip}</code></td><td>${count}</td><td><span class="badge ${count>=5?'b-red':'b-orange'}">${count>=5?'LOCKED':'WARNING'}</span></td></tr>`).join('')}
       </tbody></table>`
    : '<p style="color:var(--muted);font-size:12px">No suspicious activity detected</p>';

  document.getElementById('sessions-list').innerHTML = d.active_sessions.length
    ? `<table><thead><tr><th>Token</th><th>IP</th><th>Created</th><th>Expires</th></tr></thead><tbody>
        ${d.active_sessions.map(s=>`<tr>
          <td><code class="uid">${s.token_hint}</code></td>
          <td style="color:var(--text2)">${s.ip}</td>
          <td style="font-size:11px;color:var(--muted)">${s.created}</td>
          <td style="font-size:11px;color:var(--warning)">${s.expires_in}</td>
        </tr>`).join('')}
       </tbody></table>`
    : '<p style="color:var(--muted);font-size:12px">No active sessions</p>';
}

async function quickBan() {
  const uid = document.getElementById('ban-uid').value.trim();
  if (!uid || isNaN(uid)) { toast('Invalid user ID', 'error'); return; }
  await banUser(parseInt(uid), true);
  document.getElementById('ban-uid').value = '';
  loadSecurity();
}

async function clearRateLimits() {
  const res = await api('/admin/api/security/clear-rate-limits', {method:'POST'});
  if (res?.ok) { toast('Rate limits cleared'); loadSecurity(); }
}

// ─────────────────────────────────────────────────
// ERRORS
// ─────────────────────────────────────────────────
async function loadErrors() {
  const res = await api('/admin/api/errors');
  if (!res) return;
  allErrors = await res.json();
  document.getElementById('err-sub').textContent = `${allErrors.length} ERRORS LOGGED`;
  renderErrors(allErrors);
}

function renderErrors(errors) {
  document.getElementById('errors-tbody').innerHTML = errors.length
    ? errors.map(e => `<tr>
        <td><code class="uid">#${e.id}</code></td>
        <td><code class="uid">${e.user_id||'—'}</code></td>
        <td style="font-size:11px;max-width:250px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${(e.error||'').replace(/"/g,'')}">${e.error||'—'}</td>
        <td><span class="badge b-purple">${e.context||'—'}</span></td>
        <td style="font-size:11px;color:var(--muted);font-family:'JetBrains Mono',monospace">${(e.created_at||'').slice(0,16)}</td>
      </tr>`).join('')
    : '<tr class="empty-row"><td colspan="5">No errors logged 🎉</td></tr>';
}

function filterErrors() {
  const q = document.getElementById('err-search').value.toLowerCase();
  renderErrors(allErrors.filter(e =>
    (e.error||'').toLowerCase().includes(q) || (e.context||'').toLowerCase().includes(q)
  ));
}

// ─────────────────────────────────────────────────
// AUDIT
// ─────────────────────────────────────────────────
async function loadAudit() {
  const res = await api('/admin/api/audit');
  if (!res) return;
  const logs = await res.json();
  document.getElementById('audit-tbody').innerHTML = logs.length
    ? logs.map(l => `<tr>
        <td style="font-size:11px;font-family:'JetBrains Mono',monospace;color:var(--muted)">${l.time}</td>
        <td><span class="badge b-blue">${l.action}</span></td>
        <td style="font-size:12px;color:var(--text2)">${l.detail||'—'}</td>
        <td style="font-size:11px;color:var(--muted);font-family:'JetBrains Mono',monospace">${l.ip}</td>
      </tr>`).join('')
    : '<tr class="empty-row"><td colspan="4">No audit events yet</td></tr>';
}

// ─────────────────────────────────────────────────
// KEYBOARD / ENTER
// ─────────────────────────────────────────────────
document.getElementById('login-pw').addEventListener('keydown', e => { if(e.key==='Enter') doLogin(); });
document.getElementById('login-otp').addEventListener('keydown', e => { if(e.key==='Enter') doLogin(); });
document.getElementById('user-modal').addEventListener('click', e => { if(e.target===e.currentTarget) closeModal(); });

// ─────────────────────────────────────────────────
// AUTO SESSION CHECK
// ─────────────────────────────────────────────────
(async () => {
  const res = await fetch('/admin/api/check');
  if (res.ok) {
    document.getElementById('login-screen').style.display = 'none';
    document.getElementById('app').style.display = 'block';
    initApp();
  }
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