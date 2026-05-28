"""
handlers/khmer_calendar_handler.py — ប្រតិទិនខ្មែរ
Features:
  ✅ Show today's Khmer date
  ✅ Khmer lunar calendar
  ✅ Khmer public holidays & festivals
  ✅ Convert Gregorian ↔ Khmer date
"""

import logging
from datetime import datetime, date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

logger = logging.getLogger(__name__)

# ── Conversation states ──
CALENDAR_CONVERT_WAIT = "CALENDAR_CONVERT_WAIT"

# ══════════════════════════════════════════════
# KHMER NUMERALS & MONTH NAMES
# ══════════════════════════════════════════════
KHMER_DIGITS = {
    '0': '០', '1': '១', '2': '២', '3': '៣', '4': '៤',
    '5': '៥', '6': '៦', '7': '៧', '8': '៨', '9': '៩',
}

def to_khmer_num(n: int) -> str:
    return ''.join(KHMER_DIGITS[d] for d in str(n))

KHMER_MONTHS = [
    "", "មករា", "កុម្ភៈ", "មីនា", "មេសា", "ឧសភា", "មិថុនា",
    "កក្កដា", "សីហា", "កញ្ញា", "តុលា", "វិច្ឆិកា", "ធ្នូ",
]

KHMER_WEEKDAYS = {
    0: "ចន្ទ", 1: "អង្គារ", 2: "ពុធ", 3: "ព្រហស្បតិ៍",
    4: "សុក្រ", 5: "សៅរ៍", 6: "អាទិត្យ",
}

# Khmer lunar month names
KHMER_LUNAR_MONTHS = [
    "មិគសិរ", "បុស្ស", "មាឃ", "ផល្គុន", "ចេត្រ", "វិសាខ",
    "ជេស្ឋ", "អាសាឍ", "សាវណ", "ភទ្របទ", "អស្សុជ", "កត្តិក",
]

KHMER_LUNAR_DAYS = [
    "", "១កើត", "២កើត", "៣កើត", "៤កើត", "៥កើត",
    "៦កើត", "៧កើត", "៨កើត", "៩កើត", "១០កើត",
    "១១កើត", "១២កើត", "១៣កើត", "១៤កើត", "១៥កើត",
    "១រោច", "២រោច", "៣រោច", "៤រោច", "៥រោច",
    "៦រោច", "៧រោច", "៨រោច", "៩រោច", "១០រោច",
    "១១រោច", "១២រោច", "១៣រោច", "១៤រោច",
]


# ══════════════════════════════════════════════
# KHMER ERA YEAR (ព.ស. / សករាជ)
# ══════════════════════════════════════════════
def gregorian_to_khmer_era(d: date) -> dict:
    """
    Returns Khmer Buddhist Era year (ព.ស.) and Khmer Saka year (សករាជ).
    Khmer Buddhist Era = Gregorian year + 543 (before Khmer New Year in April) or +544 after.
    Khmer Saka year = Gregorian year - 78 (roughly).
    """
    # Buddhist Era: Khmer New Year is ~April 14
    if d.month < 4 or (d.month == 4 and d.day < 14):
        buddhist_era = d.year + 543
    else:
        buddhist_era = d.year + 544

    saka_year = d.year - 78

    return {
        "buddhist_era": buddhist_era,
        "saka_year": saka_year,
    }


# ══════════════════════════════════════════════
# SIMPLE LUNAR DATE APPROXIMATION
# ══════════════════════════════════════════════
def gregorian_to_lunar(d: date) -> dict:
    """
    Approximate Khmer lunar date.
    Uses a simplified algorithm based on the synodic month cycle.
    For production use, consider a full Khmer calendar library.
    """
    # Reference: Jan 20, 2023 = 1st Kert, Meak month, year of Rabbit
    ref_date = date(2023, 1, 20)
    ref_lunar_day = 1        # 1 Kert
    ref_lunar_month = 1      # Meak (index 1 = second in list, 0-indexed)
    ref_lunar_year = 2566    # Buddhist Era

    SYNODIC_MONTH = 29.53059  # days

    delta = (d - ref_date).days
    total_lunar_days = ref_lunar_day - 1 + delta

    lunar_month_count = int(total_lunar_days / SYNODIC_MONTH)
    day_in_month = (total_lunar_days % SYNODIC_MONTH)
    lunar_day_index = int(day_in_month) + 1  # 1-based

    if lunar_day_index > 30:
        lunar_day_index = 30
    if lunar_day_index < 1:
        lunar_day_index = 1

    lunar_month_index = (ref_lunar_month + lunar_month_count) % 12
    lunar_year = ref_lunar_year + (ref_lunar_month + lunar_month_count) // 12

    # Day phase: 1-15 = Kert (waxing), 16-30 = Roch (waning)
    if lunar_day_index <= 15:
        day_str = KHMER_LUNAR_DAYS[lunar_day_index]
        phase = "🌒 កើត (ខ្នើត)"
    else:
        day_str = KHMER_LUNAR_DAYS[lunar_day_index] if lunar_day_index < len(KHMER_LUNAR_DAYS) else "១៤រោច"
        phase = "🌘 រោច (ខ្មៅ)"

    # Moon phase emoji
    if lunar_day_index == 15:
        moon_emoji = "🌕"
        phase = "🌕 ១៥កើត (ព្រះច័ន្ទពេញ)"
    elif lunar_day_index == 1:
        moon_emoji = "🌑"
    elif lunar_day_index < 8:
        moon_emoji = "🌒"
    elif lunar_day_index < 15:
        moon_emoji = "🌓"
    elif lunar_day_index < 22:
        moon_emoji = "🌖"
    else:
        moon_emoji = "🌘"

    return {
        "day": day_str,
        "day_num": lunar_day_index,
        "month": KHMER_LUNAR_MONTHS[lunar_month_index],
        "month_index": lunar_month_index,
        "year_be": lunar_year,
        "phase": phase,
        "moon_emoji": moon_emoji,
    }


# ══════════════════════════════════════════════
# KHMER ZODIAC YEAR
# ══════════════════════════════════════════════
KHMER_ZODIAC = [
    "ជូត 🐭", "ឆ្លូវ 🐂", "ខាល 🐯", "ថោះ 🐰",
    "រោង 🐉", "ម្សាញ់ 🐍", "មមី 🐴", "មមែ 🐑",
    "វក 🐒",  "រកា 🐓",  "ច 🐕",   "កុរ 🐗",
]

def get_zodiac_year(year_be: int) -> str:
    """Get Khmer zodiac animal for a Buddhist Era year."""
    return KHMER_ZODIAC[(year_be - 4) % 12]


# ══════════════════════════════════════════════
# KHMER PUBLIC HOLIDAYS & FESTIVALS
# ══════════════════════════════════════════════
def get_khmer_holidays(year: int) -> list:
    """Return list of Khmer public holidays and festivals for a given year."""
    holidays = [
        # Fixed public holidays
        {"date": date(year, 1, 1),  "name": "ចូលឆ្នាំសាកល", "emoji": "🎆", "type": "public"},
        {"date": date(year, 1, 7),  "name": "ទិវាជ័យជំនះ", "emoji": "🏆", "type": "public"},
        {"date": date(year, 3, 8),  "name": "ទិវានារីអន្តរជាតិ", "emoji": "👩", "type": "public"},
        {"date": date(year, 4, 13), "name": "ចូលឆ្នាំខ្មែរ (ថ្ងៃទី១)", "emoji": "🎊", "type": "public"},
        {"date": date(year, 4, 14), "name": "ចូលឆ្នាំខ្មែរ (ថ្ងៃទី២)", "emoji": "🎊", "type": "public"},
        {"date": date(year, 4, 15), "name": "ចូលឆ្នាំខ្មែរ (ថ្ងៃទី៣)", "emoji": "🎊", "type": "public"},
        {"date": date(year, 4, 17), "name": "ទិវាចងចាំប្រល័យពូជសាសន៍", "emoji": "🕯️", "type": "public"},
        {"date": date(year, 5, 1),  "name": "ទិវាពលករអន្តរជាតិ", "emoji": "✊", "type": "public"},
        {"date": date(year, 5, 9),  "name": "ព្រះរាជពិធីច្រត់នាំងស្ទូង", "emoji": "🌾", "type": "public"},
        {"date": date(year, 5, 13), "name": "ព្រះរាជទិននៃព្រះមហាក្សត្រ", "emoji": "👑", "type": "public"},
        {"date": date(year, 5, 14), "name": "ព្រះរាជទិននៃព្រះមហាក្សត្រ", "emoji": "👑", "type": "public"},
        {"date": date(year, 5, 15), "name": "ព្រះរាជទិននៃព្រះមហាក្សត្រ", "emoji": "👑", "type": "public"},
        {"date": date(year, 6, 1),  "name": "ទិវាកុមារអន្តរជាតិ", "emoji": "👶", "type": "public"},
        {"date": date(year, 6, 18), "name": "ទិវាកំណើតអតីតស្ដេច នរោត្តម សីហនុ", "emoji": "🌹", "type": "public"},
        {"date": date(year, 9, 24), "name": "ទិវារដ្ឋធម្មនុញ្ញ", "emoji": "📜", "type": "public"},
        {"date": date(year, 10, 15),"name": "ព្រះរាជបុណ្យភ្ជុំបិណ្ឌ (ថ្ងៃទី១)", "emoji": "🏮", "type": "festival"},
        {"date": date(year, 10, 16),"name": "ព្រះរាជបុណ្យភ្ជុំបិណ្ឌ (ថ្ងៃទី២)", "emoji": "🏮", "type": "festival"},
        {"date": date(year, 10, 17),"name": "ព្រះរាជបុណ្យភ្ជុំបិណ្ឌ (ថ្ងៃទី៣)", "emoji": "🏮", "type": "festival"},
        {"date": date(year, 10, 23),"name": "ទិវាសន្តិភាព ២៣ តុលា", "emoji": "☮️", "type": "public"},
        {"date": date(year, 10, 29),"name": "ព្រះរាជទិននៃព្រះមហាក្សត្រ (ព្រះអង្គ)", "emoji": "👑", "type": "public"},
        {"date": date(year, 10, 30),"name": "ព្រះរាជទិននៃព្រះមហាក្សត្រ (ព្រះអង្គ)", "emoji": "👑", "type": "public"},
        {"date": date(year, 10, 31),"name": "ព្រះរាជទិននៃព្រះមហាក្សត្រ (ព្រះអង្គ)", "emoji": "👑", "type": "public"},
        {"date": date(year, 11, 9), "name": "ទិវាឯករាជ្យជាតិ", "emoji": "🇰🇭", "type": "public"},
        {"date": date(year, 11, 10),"name": "ពិធីបុណ្យអុំទូក (ថ្ងៃទី១)", "emoji": "🚣", "type": "festival"},
        {"date": date(year, 11, 11),"name": "ពិធីបុណ្យអុំទូក (ថ្ងៃទី២)", "emoji": "🚣", "type": "festival"},
        {"date": date(year, 11, 12),"name": "ពិធីបុណ្យអុំទូក (ថ្ងៃទី៣)", "emoji": "🚣", "type": "festival"},
        {"date": date(year, 12, 10),"name": "ទិវាសិទ្ធិមនុស្សអន្តរជាតិ", "emoji": "🤝", "type": "public"},
    ]
    return sorted(holidays, key=lambda x: x["date"])


def get_upcoming_holidays(n: int = 5) -> list:
    today = date.today()
    year = today.year
    all_holidays = get_khmer_holidays(year) + get_khmer_holidays(year + 1)
    upcoming = [h for h in all_holidays if h["date"] >= today]
    return upcoming[:n]


def get_today_holiday(d: date) -> dict | None:
    holidays = get_khmer_holidays(d.year)
    for h in holidays:
        if h["date"] == d:
            return h
    return None


# ══════════════════════════════════════════════
# FORMAT TODAY'S FULL DATE
# ══════════════════════════════════════════════
def format_today_khmer(d: date = None) -> str:
    if d is None:
        d = date.today()

    era = gregorian_to_khmer_era(d)
    lunar = gregorian_to_lunar(d)
    zodiac = get_zodiac_year(era["buddhist_era"])
    holiday = get_today_holiday(d)

    weekday_kh = KHMER_WEEKDAYS[d.weekday()]
    month_kh = KHMER_MONTHS[d.month]

    text = (
        f"📅 *ថ្ងៃនេះ — {weekday_kh}*\n\n"
        f"🗓 *ប្រតិទិនសាកល:*\n"
        f"  {to_khmer_num(d.day)} {month_kh} {to_khmer_num(d.year)}\n\n"
        f"☸️ *ប្រតិទិនព្រះពុទ្ធសករាជ:*\n"
        f"  ព.ស. {to_khmer_num(era['buddhist_era'])} • {zodiac}\n\n"
        f"{lunar['moon_emoji']} *ប្រតិទិនខ្មែរ (ច័ន្ទគតិ):*\n"
        f"  {lunar['day']} {lunar['month']} ព.ស.{to_khmer_num(lunar['year_be'])}\n"
        f"  {lunar['phase']}\n"
    )

    if holiday:
        text += f"\n{holiday['emoji']} *ថ្ងៃឈប់សម្រាក:* {holiday['name']}\n"

    return text


# ══════════════════════════════════════════════
# MENUS
# ══════════════════════════════════════════════
CALENDAR_MENU_KB = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("📅 ថ្ងៃនេះ",       callback_data="kcal_today"),
        InlineKeyboardButton("🌙 ច័ន្ទគតិ",       callback_data="kcal_lunar"),
    ],
    [
        InlineKeyboardButton("🎉 បុណ្យ & ថ្ងៃឈប់", callback_data="kcal_holidays"),
        InlineKeyboardButton("🔄 បំប្លែងកាលបរិច្ឆេទ", callback_data="kcal_convert"),
    ],
    [InlineKeyboardButton("🔙 ត្រឡប់", callback_data="menu_main")],
])

CALENDAR_MENU_TEXT = (
    "🗓 *ប្រតិទិនខ្មែរ*\n\n"
    "ជ្រើសរើសសកម្មភាព:\n\n"
    "📅 *ថ្ងៃនេះ* — មើលកាលបរិច្ឆេទខ្មែរថ្ងៃនេះ\n"
    "🌙 *ច័ន្ទគតិ* — ប្រតិទិនខ្មែរតាមច័ន្ទ\n"
    "🎉 *បុណ្យ & ថ្ងៃឈប់* — បុណ្យជាតិ និងព្រឹត្តិការណ៍\n"
    "🔄 *បំប្លែងកាលបរិច្ឆេទ* — បំប្លែង ព.ស. ↔ គ.ស."
)


# ══════════════════════════════════════════════
# /kh_calendar — Entry point
# ══════════════════════════════════════════════
async def khmer_calendar_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        CALENDAR_MENU_TEXT,
        parse_mode="Markdown",
        reply_markup=CALENDAR_MENU_KB,
    )


# ══════════════════════════════════════════════
# CALLBACK ROUTER
# ══════════════════════════════════════════════
async def khmer_calendar_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "kcal_today":
        text = format_today_khmer()
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 ត្រឡប់", callback_data="kcal_menu"),
            ]]),
        )

    elif data == "kcal_lunar":
        d = date.today()
        lunar = gregorian_to_lunar(d)
        era = gregorian_to_khmer_era(d)
        zodiac = get_zodiac_year(era["buddhist_era"])

        # Build 7-day lunar view
        lines = []
        for i in range(-3, 4):
            from datetime import timedelta
            day = d + timedelta(days=i)
            l = gregorian_to_lunar(day)
            wday = KHMER_WEEKDAYS[day.weekday()]
            marker = " ◀️ *ថ្ងៃនេះ*" if i == 0 else ""
            lines.append(f"  {l['moon_emoji']} {wday} {to_khmer_num(day.day)}/{to_khmer_num(day.month)} — {l['day']} {l['month']}{marker}")

        text = (
            f"🌙 *ប្រតិទិនច័ន្ទគតិខ្មែរ*\n\n"
            f"ឆ្នាំ {zodiac} ព.ស. {to_khmer_num(era['buddhist_era'])}\n\n"
            + "\n".join(lines) +
            f"\n\n{lunar['phase']}"
        )
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 ត្រឡប់", callback_data="kcal_menu"),
            ]]),
        )

    elif data == "kcal_holidays":
        upcoming = get_upcoming_holidays(10)
        today = date.today()

        lines = []
        for h in upcoming:
            delta = (h["date"] - today).days
            if delta == 0:
                when = "🔴 ថ្ងៃនេះ"
            elif delta == 1:
                when = "🟡 ថ្ងៃស្អែក"
            elif delta <= 7:
                when = f"🟢 {to_khmer_num(delta)} ថ្ងៃទៀត"
            else:
                when = f"  {to_khmer_num(h['date'].day)} {KHMER_MONTHS[h['date'].month]}"
            lines.append(f"{h['emoji']} *{h['name']}*\n    {when}")

        text = "🎉 *បុណ្យ និងថ្ងៃឈប់ខ្មែរ*\n\n" + "\n\n".join(lines)
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 ត្រឡប់", callback_data="kcal_menu"),
            ]]),
        )

    elif data == "kcal_convert":
        await query.edit_message_text(
            "🔄 *បំប្លែងកាលបរិច្ឆេទ*\n\n"
            "វាយបញ្ចូលកាលបរិច្ឆេទក្នុងទម្រង់:\n\n"
            "📌 `DD/MM/YYYY` — បំប្លែងពី គ.ស. → ព.ស.\n"
            "📌 `BE YYYY` — បំប្លែងពី ព.ស. → គ.ស.\n\n"
            "ឧទាហរណ៍: `14/04/2025` ឬ `BE 2568`\n\n"
            "វាយ /cancel ដើម្បីបោះបង់",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 ត្រឡប់", callback_data="kcal_menu"),
            ]]),
        )
        return CALENDAR_CONVERT_WAIT

    elif data == "kcal_menu":
        await query.edit_message_text(
            CALENDAR_MENU_TEXT,
            parse_mode="Markdown",
            reply_markup=CALENDAR_MENU_KB,
        )


# ══════════════════════════════════════════════
# CONVERSION: receive user input
# ══════════════════════════════════════════════
async def calendar_convert_receive(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    try:
        # Mode 1: DD/MM/YYYY — Gregorian to Khmer
        if "/" in text:
            parts = text.split("/")
            if len(parts) == 3:
                day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
                d = date(year, month, day)
                era = gregorian_to_khmer_era(d)
                lunar = gregorian_to_lunar(d)
                zodiac = get_zodiac_year(era["buddhist_era"])
                weekday_kh = KHMER_WEEKDAYS[d.weekday()]
                month_kh = KHMER_MONTHS[d.month]

                result = (
                    f"🔄 *លទ្ធផលបំប្លែង*\n\n"
                    f"📅 *គ.ស.:* {to_khmer_num(day)} {month_kh} {to_khmer_num(year)} ({weekday_kh})\n\n"
                    f"☸️ *ព.ស.:* {to_khmer_num(era['buddhist_era'])}\n"
                    f"🐾 *ឆ្នាំ:* {zodiac}\n\n"
                    f"{lunar['moon_emoji']} *ច័ន្ទគតិ:* {lunar['day']} {lunar['month']} ព.ស.{to_khmer_num(lunar['year_be'])}\n"
                    f"  {lunar['phase']}"
                )
            else:
                raise ValueError("Invalid format")

        # Mode 2: BE YYYY — Buddhist Era to Gregorian
        elif text.upper().startswith("BE"):
            be_year = int(text.upper().replace("BE", "").strip())
            # BE year to approximate Gregorian year range
            greg_year_approx = be_year - 544
            zodiac = get_zodiac_year(be_year)

            result = (
                f"🔄 *លទ្ធផលបំប្លែង*\n\n"
                f"☸️ *ព.ស.:* {to_khmer_num(be_year)}\n\n"
                f"📅 *គ.ស. (ប្រហាក់ប្រហែល):*\n"
                f"  មករា–មេសា {to_khmer_num(greg_year_approx)}\n"
                f"  មេសា–ធ្នូ {to_khmer_num(greg_year_approx + 1)}\n\n"
                f"🐾 *ឆ្នាំ:* {zodiac}"
            )
        else:
            raise ValueError("Unrecognized format")

        await update.message.reply_text(
            result,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 បំប្លែងម្ដងទៀត", callback_data="kcal_convert"),
                InlineKeyboardButton("🔙 ម៉ឺនុយ", callback_data="kcal_menu"),
            ]]),
        )

    except Exception as e:
        logger.warning(f"Calendar convert error: {e}")
        await update.message.reply_text(
            "❌ *ទម្រង់មិនត្រឹមត្រូវ!*\n\n"
            "សូមប្រើ:\n"
            "• `DD/MM/YYYY` (ឧ. `14/04/2025`)\n"
            "• `BE YYYY` (ឧ. `BE 2568`)",
            parse_mode="Markdown",
        )
        return CALENDAR_CONVERT_WAIT

    return ConversationHandler.END