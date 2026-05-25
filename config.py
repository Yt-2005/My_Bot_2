"""
config.py — Central configuration for the Telegram Bot
All settings loaded from environment variables via .env
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
# CORE TOKENS
# ─────────────────────────────────────────────
TOKEN = os.environ.get("TOKEN", "")
ADMIN_IDS_RAW = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_RAW.split(",") if x.strip().isdigit()]

# ─────────────────────────────────────────────
# GROQ AI (replaces Gemini — free & fast)
# Get your free key at: https://console.groq.com
# ─────────────────────────────────────────────
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

# Keep GEMINI_KEYS as empty list for backward compat
GEMINI_KEYS = []

# ─────────────────────────────────────────────
# IMAGE GENERATION
# ─────────────────────────────────────────────
# Using Pollinations AI (free, no API key needed)
POLLINATIONS_URL = "https://image.pollinations.ai/prompt/{prompt}"

IMAGE_STYLES = {
    "🌄 Realistic":  "photorealistic, ultra detailed, 8k",
    "🎌 Anime":      "anime style, vibrant colors, Studio Ghibli",
    "🌆 Cyberpunk":  "cyberpunk, neon lights, futuristic city",
    "🕹️ Pixel Art":  "pixel art, retro, 16-bit style",
    "🎲 3D Render":  "3D render, octane render, cinematic lighting",
}

# ─────────────────────────────────────────────
# SERVER
# ─────────────────────────────────────────────
PORT = int(os.environ.get("PORT", 10000))

# ─────────────────────────────────────────────
# RATE LIMITING
# ─────────────────────────────────────────────
RATE_LIMIT_SECONDS = 2       # Min seconds between messages per user
MAX_NOTES_PER_USER = 50      # Max notes a user can store
AI_CHAT_MEMORY = 10          # Number of messages to remember per user

# ─────────────────────────────────────────────
# MAINTENANCE MODE
# ─────────────────────────────────────────────
MAINTENANCE_MODE = False     # Toggle via /maintenance admin command
