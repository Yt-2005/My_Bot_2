"""
web/health.py — Flask health server for Render.com free hosting
Keeps the service alive and provides a status endpoint.
"""

import threading
import logging
from flask import Flask, jsonify
from datetime import datetime

logger = logging.getLogger(__name__)

app = Flask(__name__)
_start_time = datetime.utcnow()


@app.route("/")
def index():
    return "🤖 Telegram Bot is running!", 200


@app.route("/health")
def health():
    uptime = (datetime.utcnow() - _start_time).total_seconds()
    return jsonify({
        "status": "ok",
        "uptime_seconds": int(uptime),
        "started_at": _start_time.isoformat(),
    }), 200


@app.route("/ping")
def ping():
    return "pong", 200


def start_health_server(port: int = 10000):
    """Start Flask in a background daemon thread."""
    def run():
        # Suppress Flask's default request logging for cleaner output
        import logging as _logging
        _logging.getLogger("werkzeug").setLevel(_logging.ERROR)
        app.run(host="0.0.0.0", port=port, debug=False)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    logger.info(f"✅ Health server started on port {port}")
