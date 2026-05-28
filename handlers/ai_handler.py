"""
handlers/ai_handler.py — Upgraded AI Features
New features:
  🤖 /chat       — AI conversation with memory
  🌐 /translate  — Translate text to any language
  ✍️  /write      — AI writing assistant (essay, email, story, poem)
  📋 /summarize  — Summarize long text
  🔎 /explain    — Explain anything simply
  💡 /ideas      — Brainstorm ideas on any topic
  🐛 /codehelp   — AI coding assistant
  😄 /joke       — Tell a joke
  🔮 /ask        — One-shot AI question (no memory)
  🧠 /roast      — Roast yourself (fun)
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import GROQ_API_KEY, AI_CHAT_MEMORY
from database import ensure_user, get_chat_history, save_chat_message, clear_chat_history

logger = logging.getLogger(__name__)

# ── States ──
CHATTING        = "CHATTING"
TRANSLATE_WAIT  = "TRANSLATE_WAIT"
WRITE_TOPIC     = "WRITE_TOPIC"
WRITE_CONTENT   = "WRITE_CONTENT"
SUMMARIZE_WAIT  = "SUMMARIZE_WAIT"
EXPLAIN_WAIT    = "EXPLAIN_WAIT"
IDEAS_WAIT      = "IDEAS_WAIT"
CODE_WAIT       = "CODE_WAIT"
ASK_WAIT        = "ASK_WAIT"

WRITE_FORMATS = ["📧 Email", "📝 Essay", "📖 Story", "🎵 Poem", "📣 Speech", "📱 Caption"]


# ══════════════════════════════════════════════
# GROQ CLIENT
# ══════════════════════════════════════════════
def _groq_chat(messages: list, system: str = "", max_tokens: int = 1024) -> str:
    """Call Groq API synchronously and return text."""
    import httpx, json
    if not GROQ_API_KEY:
        return "❌ GROQ_API_KEY not set. Get a free key at console.groq.com"

    payload = {
        "model": "llama-3.3-70b-versatile",
        "max_tokens": max_tokens,
        "messages": (
            [{"role": "system", "content": system}] if system else []
        ) + messages,
    }
    try:
        r = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"Groq error: {e}")
        return f"❌ AI error: {e}"


def _back_kb(target="menu_ai") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=target)]])


# ══════════════════════════════════════════════
# 🤖 /chat — Conversation with memory
# ══════════════════════════════════════════════
async def chat_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ensure_user(update.effective_user.id)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🧹 Clear Memory", callback_data="ai_clearchat")],
        [InlineKeyboardButton("🔙 Back", callback_data="menu_ai")],
    ])
    await update.message.reply_text(
        "🤖 *AI Chat*\n\n"
        "I remember your last conversations.\n"
        "Just send me a message!\n\n"
        "Type /cancel to exit chat mode.",
        parse_mode="Markdown",
        reply_markup=kb,
    )
    return CHATTING


async def chat_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_text = update.message.text.strip()

    thinking = await update.message.reply_text("🤔 Thinking...")

    # Load memory
    history = get_chat_history(uid, limit=AI_CHAT_MEMORY)
    history.append({"role": "user", "content": user_text})

    system = (
        "You are a helpful, friendly AI assistant inside a Telegram bot. "
        "Be concise, warm, and use emojis occasionally. "
        "If asked about expenses or finance, give practical advice."
    )

    reply = _groq_chat(history, system=system)

    # Save to memory
    save_chat_message(uid, "user", user_text)
    save_chat_message(uid, "assistant", reply)

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🧹 Clear Memory", callback_data="ai_clearchat"),
            InlineKeyboardButton("🔙 Exit Chat",    callback_data="menu_ai"),
        ]
    ])
    await thinking.edit_text(reply, reply_markup=kb)
    return CHATTING


async def handle_text_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Fallback text handler — passes to chat if no active conversation."""
    # Just route to normal chat for convenience
    uid = update.effective_user.id
    ensure_user(uid)
    text = update.message.text.strip()

    # If short/casual, respond as AI
    history = get_chat_history(uid, limit=6)
    history.append({"role": "user", "content": text})
    system = "You are a friendly Telegram bot assistant. Be brief and helpful."
    reply = _groq_chat(history, system=system, max_tokens=512)
    save_chat_message(uid, "user", text)
    save_chat_message(uid, "assistant", reply)

    await update.message.reply_text(reply)


# ══════════════════════════════════════════════
# 🌐 /translate
# ══════════════════════════════════════════════
async def translate_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # Check if text passed inline: /translate Hello → English
    args = " ".join(ctx.args) if ctx.args else ""
    if args:
        await _do_translate(update, ctx, args)
        return ConversationHandler.END

    lang_kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🇬🇧 English",  callback_data="tl_English"),
            InlineKeyboardButton("🇰🇭 Khmer",    callback_data="tl_Khmer"),
            InlineKeyboardButton("🇨🇳 Chinese",  callback_data="tl_Chinese"),
        ],
        [
            InlineKeyboardButton("🇯🇵 Japanese", callback_data="tl_Japanese"),
            InlineKeyboardButton("🇰🇷 Korean",   callback_data="tl_Korean"),
            InlineKeyboardButton("🇫🇷 French",   callback_data="tl_French"),
        ],
        [
            InlineKeyboardButton("🇪🇸 Spanish",  callback_data="tl_Spanish"),
            InlineKeyboardButton("🇹🇭 Thai",     callback_data="tl_Thai"),
            InlineKeyboardButton("🇻🇳 Vietnamese", callback_data="tl_Vietnamese"),
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="menu_ai")],
    ])
    await update.message.reply_text(
        "🌐 *Translate*\n\nChoose target language, then send your text:",
        parse_mode="Markdown",
        reply_markup=lang_kb,
    )
    return TRANSLATE_WAIT


async def translate_lang_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = query.data.replace("tl_", "")
    ctx.user_data["translate_lang"] = lang
    await query.edit_message_text(
        f"🌐 *Translate to {lang}*\n\nSend me the text to translate:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="menu_ai")]]),
    )
    return TRANSLATE_WAIT


async def translate_receive(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = ctx.user_data.get("translate_lang", "English")
    text = update.message.text.strip()
    msg = await update.message.reply_text("🌐 Translating...")
    result = _groq_chat(
        [{"role": "user", "content": f"Translate this to {lang}. Reply ONLY with the translation, no explanation:\n\n{text}"}],
        max_tokens=512,
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Translate Another", callback_data="menu_translate"),
            InlineKeyboardButton("🔙 Back", callback_data="menu_ai"),
        ]
    ])
    await msg.edit_text(
        f"🌐 *{lang} Translation:*\n\n{result}",
        parse_mode="Markdown",
        reply_markup=kb,
    )
    ctx.user_data.pop("translate_lang", None)
    return ConversationHandler.END


async def _do_translate(update, ctx, text):
    msg = await update.message.reply_text("🌐 Translating...")
    result = _groq_chat(
        [{"role": "user", "content": f"Detect the language and translate to English if not English, or to Khmer if it is English. Reply ONLY with the translation:\n\n{text}"}],
        max_tokens=512,
    )
    await msg.edit_text(f"🌐 *Translation:*\n\n{result}", parse_mode="Markdown",
                        reply_markup=_back_kb("menu_ai"))


# ══════════════════════════════════════════════
# ✍️ /write — Writing Assistant
# ══════════════════════════════════════════════
async def write_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📧 Email",   callback_data="write_Email"),
            InlineKeyboardButton("📝 Essay",   callback_data="write_Essay"),
            InlineKeyboardButton("📖 Story",   callback_data="write_Story"),
        ],
        [
            InlineKeyboardButton("🎵 Poem",    callback_data="write_Poem"),
            InlineKeyboardButton("📣 Speech",  callback_data="write_Speech"),
            InlineKeyboardButton("📱 Caption", callback_data="write_Caption"),
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="menu_ai")],
    ])
    await update.message.reply_text(
        "✍️ *AI Writing Assistant*\n\nWhat do you want to write?",
        parse_mode="Markdown",
        reply_markup=kb,
    )
    return WRITE_TOPIC


async def write_format_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    fmt = query.data.replace("write_", "")
    ctx.user_data["write_format"] = fmt
    prompts = {
        "Email":   "What is the email about? (topic + tone e.g. 'apology to client, professional')",
        "Essay":   "What topic should the essay cover?",
        "Story":   "Describe the story (genre + main idea e.g. 'sci-fi, robot falls in love')",
        "Poem":    "What should the poem be about? (topic + style e.g. 'rain, haiku')",
        "Speech":  "What is the speech for? (occasion + audience)",
        "Caption": "What is the caption for? (photo description + platform)",
    }
    await query.edit_message_text(
        f"✍️ *{fmt}*\n\n{prompts.get(fmt, 'Describe what you want:')}\n\nType /cancel to go back.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="menu_ai")]]),
    )
    return WRITE_CONTENT


async def write_receive(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    fmt = ctx.user_data.get("write_format", "Essay")
    topic = update.message.text.strip()
    msg = await update.message.reply_text(f"✍️ Writing your {fmt}...")

    system_prompts = {
        "Email":   "You are an expert email writer. Write professional, clear emails.",
        "Essay":   "You are an academic writer. Write well-structured essays with intro, body, conclusion.",
        "Story":   "You are a creative fiction writer. Write engaging, vivid stories.",
        "Poem":    "You are a poet. Write expressive, beautiful poems.",
        "Speech":  "You are a speechwriter. Write inspiring, well-paced speeches.",
        "Caption": "You are a social media expert. Write catchy, engaging captions with hashtags.",
    }

    result = _groq_chat(
        [{"role": "user", "content": f"Write a {fmt} about: {topic}"}],
        system=system_prompts.get(fmt, "You are a helpful writing assistant."),
        max_tokens=1500,
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✍️ Write Another", callback_data="menu_write"),
            InlineKeyboardButton("🔙 Back", callback_data="menu_ai"),
        ]
    ])
    await msg.edit_text(
        f"✍️ *{fmt}:*\n\n{result}",
        parse_mode="Markdown",
        reply_markup=kb,
    )
    ctx.user_data.pop("write_format", None)
    return ConversationHandler.END


# ══════════════════════════════════════════════
# 📋 /summarize
# ══════════════════════════════════════════════
async def summarize_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if ctx.args:
        text = " ".join(ctx.args)
        await _do_summarize(update, text)
        return ConversationHandler.END
    await update.message.reply_text(
        "📋 *Summarize*\n\nSend me any long text and I'll summarize it for you.\n\nType /cancel to go back.",
        parse_mode="Markdown",
        reply_markup=_back_kb("menu_ai"),
    )
    return SUMMARIZE_WAIT


async def summarize_receive(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _do_summarize(update, update.message.text.strip())
    return ConversationHandler.END


async def _do_summarize(update, text):
    msg = await update.message.reply_text("📋 Summarizing...")
    result = _groq_chat(
        [{"role": "user", "content": f"Summarize this text clearly and concisely with bullet points:\n\n{text}"}],
        system="You are an expert at summarizing. Be brief, clear, and use bullet points.",
        max_tokens=600,
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 Summarize Another", callback_data="menu_summarize"),
            InlineKeyboardButton("🔙 Back", callback_data="menu_ai"),
        ]
    ])
    await msg.edit_text(f"📋 *Summary:*\n\n{result}", parse_mode="Markdown", reply_markup=kb)


# ══════════════════════════════════════════════
# 🔎 /explain
# ══════════════════════════════════════════════
async def explain_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if ctx.args:
        await _do_explain(update, " ".join(ctx.args))
        return ConversationHandler.END
    await update.message.reply_text(
        "🔎 *Explain*\n\nSend me anything — a word, concept, or topic — and I'll explain it simply.\n\nType /cancel to go back.",
        parse_mode="Markdown",
        reply_markup=_back_kb("menu_ai"),
    )
    return EXPLAIN_WAIT


async def explain_receive(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _do_explain(update, update.message.text.strip())
    return ConversationHandler.END


async def _do_explain(update, topic):
    msg = await update.message.reply_text("🔎 Explaining...")
    result = _groq_chat(
        [{"role": "user", "content": f"Explain this simply, like I'm 12 years old:\n\n{topic}"}],
        system="You explain complex things simply. Use analogies, examples, and emojis.",
        max_tokens=700,
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔎 Explain Another", callback_data="menu_explain"),
            InlineKeyboardButton("🔙 Back", callback_data="menu_ai"),
        ]
    ])
    await msg.edit_text(f"🔎 *Explanation:*\n\n{result}", parse_mode="Markdown", reply_markup=kb)


# ══════════════════════════════════════════════
# 💡 /ideas — Brainstorm
# ══════════════════════════════════════════════
async def ideas_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if ctx.args:
        await _do_ideas(update, " ".join(ctx.args))
        return ConversationHandler.END
    await update.message.reply_text(
        "💡 *Brainstorm Ideas*\n\nWhat topic do you need ideas for?\n\nType /cancel to go back.",
        parse_mode="Markdown",
        reply_markup=_back_kb("menu_ai"),
    )
    return IDEAS_WAIT


async def ideas_receive(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _do_ideas(update, update.message.text.strip())
    return ConversationHandler.END


async def _do_ideas(update, topic):
    msg = await update.message.reply_text("💡 Brainstorming...")
    result = _groq_chat(
        [{"role": "user", "content": f"Give me 10 creative, practical ideas for: {topic}"}],
        system="You are a creative brainstorming expert. Give numbered, diverse, actionable ideas.",
        max_tokens=800,
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💡 More Ideas", callback_data="menu_ideas"),
            InlineKeyboardButton("🔙 Back", callback_data="menu_ai"),
        ]
    ])
    await msg.edit_text(f"💡 *Ideas for {topic[:30]}:*\n\n{result}", parse_mode="Markdown", reply_markup=kb)


# ══════════════════════════════════════════════
# 🐛 /codehelp — Coding Assistant
# ══════════════════════════════════════════════
async def codehelp_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🐛 Fix Bug",       callback_data="code_fix"),
            InlineKeyboardButton("💡 Explain Code",  callback_data="code_explain"),
        ],
        [
            InlineKeyboardButton("✍️ Write Code",    callback_data="code_write"),
            InlineKeyboardButton("⚡ Optimize",      callback_data="code_optimize"),
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="menu_ai")],
    ])
    await update.message.reply_text(
        "🐛 *AI Coding Assistant*\n\nWhat do you need help with?",
        parse_mode="Markdown",
        reply_markup=kb,
    )
    return CODE_WAIT


async def code_action_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data.replace("code_", "")
    ctx.user_data["code_action"] = action
    prompts = {
        "fix":      "Paste your buggy code and describe the problem:",
        "explain":  "Paste the code you want explained:",
        "write":    "Describe what code you need (language + what it should do):",
        "optimize": "Paste the code you want optimized:",
    }
    await query.edit_message_text(
        f"🐛 *Code Help — {action.title()}*\n\n{prompts.get(action, 'Send your code or question:')}\n\nType /cancel to go back.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="menu_ai")]]),
    )
    return CODE_WAIT


async def code_receive(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    action = ctx.user_data.get("code_action", "write")
    content = update.message.text.strip()
    msg = await update.message.reply_text("💻 Working on it...")

    system_map = {
        "fix":      "You are an expert debugger. Find and fix bugs. Show the fixed code with explanation.",
        "explain":  "You are a coding teacher. Explain code clearly, line by line if needed.",
        "write":    "You are an expert programmer. Write clean, well-commented code.",
        "optimize": "You are a performance expert. Optimize code for speed and readability.",
    }
    user_prompt_map = {
        "fix":      f"Fix this code and explain what was wrong:\n\n{content}",
        "explain":  f"Explain this code:\n\n{content}",
        "write":    f"Write code for this:\n\n{content}",
        "optimize": f"Optimize this code:\n\n{content}",
    }

    result = _groq_chat(
        [{"role": "user", "content": user_prompt_map.get(action, content)}],
        system=system_map.get(action, "You are a helpful coding assistant."),
        max_tokens=1500,
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🐛 More Code Help", callback_data="menu_code"),
            InlineKeyboardButton("🔙 Back", callback_data="menu_ai"),
        ]
    ])
    await msg.edit_text(result, reply_markup=kb)
    ctx.user_data.pop("code_action", None)
    return ConversationHandler.END



# ══════════════════════════════════════════════
# 🔮 /ask — Quick one-shot question
# ══════════════════════════════════════════════
async def ask_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if ctx.args:
        question = " ".join(ctx.args)
        await _do_ask(update, question)
        return ConversationHandler.END
    await update.message.reply_text(
        "🔮 *Quick Ask*\n\nSend me any question — I'll answer it directly.\n\nType /cancel to go back.",
        parse_mode="Markdown",
        reply_markup=_back_kb("menu_ai"),
    )
    return ASK_WAIT


async def ask_receive(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _do_ask(update, update.message.text.strip())
    return ConversationHandler.END


async def _do_ask(update, question):
    msg = await update.message.reply_text("🔮 Thinking...")
    result = _groq_chat(
        [{"role": "user", "content": question}],
        system="You are a knowledgeable assistant. Answer clearly and concisely.",
        max_tokens=800,
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔮 Ask Another", callback_data="menu_ask"),
            InlineKeyboardButton("🔙 Back", callback_data="menu_ai"),
        ]
    ])
    await msg.edit_text(f"🔮 *Answer:*\n\n{result}", parse_mode="Markdown", reply_markup=kb)


# ══════════════════════════════════════════════
# 🧠 /roast — Fun roast generator
# ══════════════════════════════════════════════
async def roast_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    name = user.first_name or "you"
    username = f"@{user.username}" if user.username else name
    msg = await update.message.reply_text("🔥 Roasting...")
    result = _groq_chat(
        [{"role": "user", "content": f"Give a funny, light-hearted roast of someone named {name} who uses Telegram bots a lot. Keep it friendly and funny, not mean."}],
        system="You are a comedian doing friendly roasts. Keep it fun, never hurtful.",
        max_tokens=300,
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔥 Roast Again", callback_data="ai_roast"),
            InlineKeyboardButton("🔙 Back", callback_data="menu_ai"),
        ]
    ])
    await msg.edit_text(f"🔥 *Roasting {username}:*\n\n{result}", parse_mode="Markdown", reply_markup=kb)


# ══════════════════════════════════════════════
# AI MENU CALLBACK ROUTER
# ══════════════════════════════════════════════
async def ai_menu_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle all menu_ai* and ai_* callbacks."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "menu_ai":
        await _show_ai_menu(query)
    elif data == "ai_clearchat":
        clear_chat_history(query.from_user.id)
        await query.edit_message_text(
            "🧹 *Chat memory cleared!*\n\nSend /chat to start fresh.",
            parse_mode="Markdown",
            reply_markup=_back_kb("menu_ai"),
        )
    elif data == "ai_roast":
        name = query.from_user.first_name or "you"
        await query.edit_message_text("🔥 Roasting...")
        result = _groq_chat(
            [{"role": "user", "content": f"Funny friendly roast for {name}, a Telegram bot user."}],
            system="You are a comedian doing friendly roasts.",
            max_tokens=300,
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔥 Again", callback_data="ai_roast"),
            InlineKeyboardButton("🔙 Back", callback_data="menu_ai"),
        ]])
        await query.edit_message_text(f"🔥 *Roast:*\n\n{result}", parse_mode="Markdown", reply_markup=kb)
    elif data in ("menu_translate", "menu_write", "menu_summarize",
                  "menu_explain", "menu_ideas", "menu_code", "menu_ask"):
        # Re-show the relevant sub-menu prompt
        labels = {
            "menu_translate": ("🌐", "Translate", "/translate"),
            "menu_write":     ("✍️", "Writing Assistant", "/write"),
            "menu_summarize": ("📋", "Summarize", "/summarize"),
            "menu_explain":   ("🔎", "Explain", "/explain"),
            "menu_ideas":     ("💡", "Brainstorm Ideas", "/ideas"),
            "menu_code":      ("🐛", "Code Help", "/codehelp"),
            "menu_ask":       ("🔮", "Quick Ask", "/ask"),
        }
        icon, label, cmd = labels[data]
        await query.edit_message_text(
            f"{icon} *{label}*\n\nUse {cmd} to start, or type your request directly.",
            parse_mode="Markdown",
            reply_markup=_back_kb("menu_ai"),
        )


async def _show_ai_menu(query):
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🤖 Chat",        callback_data="menu_chat"),
            InlineKeyboardButton("🌐 Translate",   callback_data="menu_translate"),
        ],
        [
            InlineKeyboardButton("✍️ Write",        callback_data="menu_write"),
            InlineKeyboardButton("📋 Summarize",   callback_data="menu_summarize"),
        ],
        [
            InlineKeyboardButton("🔎 Explain",     callback_data="menu_explain"),
            InlineKeyboardButton("💡 Ideas",        callback_data="menu_ideas"),
        ],
        [
            InlineKeyboardButton("🐛 Code Help",   callback_data="menu_code"),
            InlineKeyboardButton("🔮 Quick Ask",   callback_data="menu_ask"),
        ],
        [
            InlineKeyboardButton("🔥 Roast Me",    callback_data="ai_roast"),
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="menu_main")],
    ])
    await query.edit_message_text(
        "🤖 *AI Features*\n\n"
        "Choose an AI tool:\n\n"
        "🤖 *Chat* — Conversation with memory\n"
        "🌐 *Translate* — Any language\n"
        "✍️ *Write* — Email, essay, poem, story\n"
        "📋 *Summarize* — Shorten long text\n"
        "🔎 *Explain* — Simplify any topic\n"
        "💡 *Ideas* — Brainstorm anything\n"
        "🐛 *Code Help* — Fix, write, explain code\n"
        "🔮 *Quick Ask* — One-shot questions\n"
        "🔥 *Roast Me* — Fun roast",
        parse_mode="Markdown",
        reply_markup=kb,
    )