"""
web.py — Flask health server + Admin Dashboard
Health: /health /ping
Admin:  /admin (password protected)
"""

import threading
import logging
from flask import Flask
from datetime import datetime

logger = logging.getLogger(__name__)

app = Flask(__name__)
_start_time = datetime.utcnow()


@app.route("/")
def index():
    return "🤖 Telegram Bot is running! <a href='/admin'>Admin Panel</a>", 200


@app.route("/health")
def health():
    from flask import jsonify
    uptime = (datetime.utcnow() - _start_time).total_seconds()
    return jsonify({
        "status": "ok",
        "uptime_seconds": int(uptime),
        "started_at": _start_time.isoformat(),
    }), 200


@app.route("/ping")
def ping():
    return "pong", 200


def start_health_server(port: int = 10000, bot_app=None):
    """Start Flask + Admin Dashboard in a background daemon thread."""
    import os

    # Register admin dashboard
    from dashboard import register_dashboard, set_bot_app
    if bot_app:
        set_bot_app(bot_app)

    # Get password from env or use default
    admin_password = os.environ.get("ADMIN_PASSWORD", "admin1234")
    secret_key     = os.environ.get("SECRET_KEY", "bot-secret-key-2024")

    register_dashboard(app, secret_key=secret_key, password=admin_password)

    def run():
        import logging as _logging
        _logging.getLogger("werkzeug").setLevel(_logging.ERROR)
        app.run(host="0.0.0.0", port=port, debug=False)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    logger.info(f"✅ Health server started on port {port}")
    logger.info(f"✅ Admin dashboard at http://localhost:{port}/admin")