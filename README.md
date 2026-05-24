# 🤖 Telegram AI Bot

A powerful Telegram bot with AI image generation, upscaling, smart chat, expense tracking, and notes — built for 24/7 operation on Render.com free hosting.

---

## ✨ Features

| Feature | Description |
|---|---|
| 🎨 AI Image Generator | Generate images from text with 5 art styles |
| ✨ AI Image Upscaler | Enhance photos to near-4K quality |
| 🤖 AI Chat | Smart conversations with memory per user |
| 📝 Notes | Save and manage personal reminders |
| 💰 Expenses | Full expense tracker with budget alerts |
| 🤖 AI Finance | Personalized saving tips from Gemini AI |
| 👑 Admin Panel | Broadcast, stats, error logs, maintenance mode |

---

## 🚀 Quick Start

### 1. Clone or download the project

```bash
git clone https://github.com/yourname/telegram-bot.git
cd telegram-bot
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
# Edit .env with your values:
nano .env
```

Required values in `.env`:
```
TOKEN=your_telegram_bot_token
GEMINI_KEY_1=your_gemini_api_key
ADMIN_IDS=your_telegram_user_id
```

### 4. Run locally

```bash
python bot.py
```

---

## 🌐 Deploy to Render (Free, 24/7)

### Step 1 — Create a Render account
Sign up at [render.com](https://render.com) (free).

### Step 2 — Push to GitHub

```bash
git init
git add .
git commit -m "Initial bot"
git branch -M main
git remote add origin https://github.com/yourname/yourbot.git
git push -u origin main
```

> ⚠️ Add `.env` to `.gitignore` — never push secrets!

### Step 3 — Create a Background Worker on Render

1. Click **New → Background Worker**
2. Connect your GitHub repo
3. Configure:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python bot.py`
4. Under **Environment Variables**, add:
   - `TOKEN` — your Telegram bot token
   - `GEMINI_KEY_1` — your Gemini API key
   - `ADMIN_IDS` — your Telegram user ID
   - `PORT` — `10000`
5. Click **Create Background Worker**

> 💡 Use **Background Worker** (not Web Service) — it doesn't sleep on the free plan!

### Step 4 — Get API Keys

**Telegram Bot Token:**
1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and follow instructions
3. Copy the token

**Gemini API Key (free):**
1. Go to [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
2. Create a new API key
3. Free tier: 15 requests/minute, 1500/day per key

**Your Telegram User ID:**
1. Message [@userinfobot](https://t.me/userinfobot)
2. It will reply with your user ID number

---

## 📋 All Commands

### 🤖 AI Features
| Command | Description |
|---|---|
| `/imagine <prompt>` | Generate an AI image |
| `/upscale` | Enhance a photo |
| `/chat` | Start AI conversation |
| `/clearchat` | Reset AI memory |

### 📝 Notes
| Command | Description |
|---|---|
| `/note add` | Add a new note |
| `/note list` | View all notes |
| `/note delete` | Delete a note |

### 💰 Expenses
| Command | Description |
|---|---|
| `/add` | Record a new expense |
| `/today` | Today's expenses |
| `/month` | Monthly summary |
| `/compare` | Compare months |
| `/budget` | Set monthly budget |
| `/date` | Search by date |
| `/tags` | Search by tag |
| `/delete` | Delete an expense |
| `/recurring` | Show recurring expenses |
| `/ai` | AI financial advice |

### ⚙️ Settings
| Command | Description |
|---|---|
| `/lang` | Change language (KH/EN) |
| `/setpin` | Set security PIN |
| `/reminder` | Daily reminder |

### 👑 Admin Only
| Command | Description |
|---|---|
| `/stats` | User statistics |
| `/broadcast` | Message all users |
| `/errorlogs` | Recent error log |
| `/maintenance` | Toggle maintenance mode |
| `/restart` | Restart instructions |

---

## 🏗️ Project Structure

```
telegram-bot/
│
├── bot.py              ← Main entry point, registers all handlers
├── config.py           ← All settings & env variables
│
├── handlers/           ← Telegram command & callback handlers
│   ├── core.py         ← /start, /help, menu navigation
│   ├── image_handler.py ← /imagine, /upscale
│   ├── chat_handler.py  ← /chat AI conversation
│   ├── notes_handler.py ← /note system
│   ├── expense_handler.py ← All expense commands
│   ├── settings_handler.py ← /lang, /setpin, /reminder
│   └── admin_handler.py ← Admin commands
│
├── ai/                 ← AI integrations
│   ├── gemini.py       ← Gemini text AI + key rotation
│   └── image_gen.py    ← Image generation & upscaling
│
├── database/           ← SQLite data layer
│   └── db.py           ← All DB functions
│
├── utils/              ← Shared utilities
│   └── helpers.py      ← Rate limiter, keyboards, formatters
│
├── web/                ← Health check server
│   └── health.py       ← Flask health endpoints
│
├── requirements.txt    ← Python packages
├── render.yaml         ← Render deployment config
├── Procfile            ← Alternative deploy config
├── .env.example        ← Environment variable template
└── README.md           ← This file
```

---

## 🔑 Environment Variables Reference

| Variable | Required | Description |
|---|---|---|
| `TOKEN` | ✅ Yes | Telegram Bot Token from @BotFather |
| `GEMINI_KEY_1` | ✅ For AI | Google Gemini API key |
| `GEMINI_KEY_2` | Optional | Fallback Gemini key |
| `GEMINI_KEY_3` | Optional | Second fallback key |
| `ADMIN_IDS` | Recommended | Comma-separated admin user IDs |
| `PORT` | Optional | Health server port (default: 10000) |

---

## 🐛 Troubleshooting

**Bot doesn't start:**
- Check that `TOKEN` is set correctly
- Ensure Python 3.11+ is installed

**AI features not working:**
- Verify `GEMINI_KEY_1` is set
- Check quota at [aistudio.google.com](https://aistudio.google.com)
- Bot will auto-rotate to next key if quota is exceeded

**Image generation fails:**
- Pollinations.ai may be slow — retry after 30 seconds
- Check your internet connection

**Bot sleeps on Render:**
- Make sure you created a **Background Worker**, not a Web Service
- Background workers stay alive 24/7 on free tier

---

## 📄 License

MIT License — free to use, modify, and distribute.
