"""
handlers/khmer_calendar_handler.py — ប្រតិទិនខ្មែរ
Features:
  ✅ Show today's Khmer date
  ✅ Khmer lunar calendar (7-day view)
  ✅ Full month calendar with ថ្ងៃសីល markers
  ✅ Khmer public holidays & festivals
  ✅ Convert Gregorian ↔ Khmer date
"""

import logging
import math
from datetime import datetime, date, timedelta
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

# ថ្ងៃសីល — Buddhist precept days (lunar day 8, 15, 23, 29/30)
SEIL_DAYS = {8, 15, 23, 29, 30}


# ══════════════════════════════════════════════
# KHMER ERA YEAR (ព.ស.)
# ══════════════════════════════════════════════
def gregorian_to_khmer_era(d: date) -> dict:
    if d.month < 4 or (d.month == 4 and d.day < 14):
        buddhist_era = d.year + 543
    else:
        buddhist_era = d.year + 544
    return {"buddhist_era": buddhist_era, "saka_year": d.year - 78}


# ══════════════════════════════════════════════
# SIMPLE LUNAR DATE APPROXIMATION
# ══════════════════════════════════════════════
def gregorian_to_lunar(d: date) -> dict:
    ref_date = date(2023, 1, 20)
    ref_lunar_day = 1
    ref_lunar_month = 1
    ref_lunar_year = 2566
    SYNODIC_MONTH = 29.53059

    delta = (d - ref_date).days
    total_lunar_days = ref_lunar_day - 1 + delta
    lunar_month_count = int(total_lunar_days / SYNODIC_MONTH)
    day_in_month = total_lunar_days % SYNODIC_MONTH
    lunar_day_index = int(day_in_month) + 1
    lunar_day_index = max(1, min(30, lunar_day_index))

    lunar_month_index = (ref_lunar_month + lunar_month_count) % 12
    lunar_year = ref_lunar_year + (ref_lunar_month + lunar_month_count) // 12

    if lunar_day_index <= 15:
        day_str = KHMER_LUNAR_DAYS[lunar_day_index]
        phase = "🌒 កើត (ខ្នើត)"
    else:
        day_str = KHMER_LUNAR_DAYS[lunar_day_index] if lunar_day_index < len(KHMER_LUNAR_DAYS) else "១៤រោច"
        phase = "🌘 រោច (ខ្មៅ)"

    if lunar_day_index == 15:
        moon_emoji = "🌕"
        phase = "🌕 ព្រះច័ន្ទពេញ"
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

    is_seil = lunar_day_index in SEIL_DAYS

    return {
        "day": day_str,
        "day_num": lunar_day_index,
        "month": KHMER_LUNAR_MONTHS[lunar_month_index],
        "month_index": lunar_month_index,
        "year_be": lunar_year,
        "phase": phase,
        "moon_emoji": moon_emoji,
        "is_seil": is_seil,
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
    return KHMER_ZODIAC[(year_be - 4) % 12]


# ══════════════════════════════════════════════
# ថ្ងៃសីល — Get upcoming Seil days
# ══════════════════════════════════════════════
def get_seil_days_this_month(year: int, month: int) -> list:
    """Return list of dates that are ថ្ងៃសីល in the given month."""
    import calendar as cal_mod
    _, num_days = cal_mod.monthrange(year, month)
    seil_dates = []
    for day_num in range(1, num_days + 1):
        d = date(year, month, day_num)
        lunar = gregorian_to_lunar(d)
        if lunar["is_seil"]:
            seil_dates.append((d, lunar))
    return seil_dates


# ══════════════════════════════════════════════
# KHMER PUBLIC HOLIDAYS & FESTIVALS
# ══════════════════════════════════════════════
def get_khmer_holidays(year: int) -> list:
    holidays = [
        {"date": date(year, 1, 1),   "name": "ចូលឆ្នាំសាកល",                        "emoji": "🎆", "type": "public"},
        {"date": date(year, 1, 7),   "name": "ទិវាជ័យជំនះ",                           "emoji": "🏆", "type": "public"},
        {"date": date(year, 3, 8),   "name": "ទិវានារីអន្តរជាតិ",                     "emoji": "👩", "type": "public"},
        {"date": date(year, 4, 13),  "name": "ចូលឆ្នាំខ្មែរ (ថ្ងៃទី១)",              "emoji": "🎊", "type": "public"},
        {"date": date(year, 4, 14),  "name": "ចូលឆ្នាំខ្មែរ (ថ្ងៃទី២)",              "emoji": "🎊", "type": "public"},
        {"date": date(year, 4, 15),  "name": "ចូលឆ្នាំខ្មែរ (ថ្ងៃទី៣)",              "emoji": "🎊", "type": "public"},
        {"date": date(year, 4, 17),  "name": "ទិវាចងចាំប្រល័យពូជសាសន៍",             "emoji": "🕯️", "type": "public"},
        {"date": date(year, 5, 1),   "name": "ទិវាពលករអន្តរជាតិ",                    "emoji": "✊", "type": "public"},
        {"date": date(year, 5, 9),   "name": "ព្រះរាជពិធីច្រត់នាំងស្ទូង",            "emoji": "🌾", "type": "public"},
        {"date": date(year, 5, 13),  "name": "ព្រះរាជទិននៃព្រះមហាក្សត្រ",           "emoji": "👑", "type": "public"},
        {"date": date(year, 5, 14),  "name": "ព្រះរាជទិននៃព្រះមហាក្សត្រ",           "emoji": "👑", "type": "public"},
        {"date": date(year, 5, 15),  "name": "ព្រះរាជទិននៃព្រះមហាក្សត្រ",           "emoji": "👑", "type": "public"},
        {"date": date(year, 6, 1),   "name": "ទិវាកុមារអន្តរជាតិ",                   "emoji": "👶", "type": "public"},
        {"date": date(year, 6, 18),  "name": "ទិវាកំណើតអតីតស្ដេច នរោត្តម សីហនុ",   "emoji": "🌹", "type": "public"},
        {"date": date(year, 9, 24),  "name": "ទិវារដ្ឋធម្មនុញ្ញ",                    "emoji": "📜", "type": "public"},
        {"date": date(year, 10, 15), "name": "ព្រះរាជបុណ្យភ្ជុំបិណ្ឌ (ថ្ងៃទី១)",    "emoji": "🏮", "type": "festival"},
        {"date": date(year, 10, 16), "name": "ព្រះរាជបុណ្យភ្ជុំបិណ្ឌ (ថ្ងៃទី២)",    "emoji": "🏮", "type": "festival"},
        {"date": date(year, 10, 17), "name": "ព្រះរាជបុណ្យភ្ជុំបិណ្ឌ (ថ្ងៃទី៣)",    "emoji": "🏮", "type": "festival"},
        {"date": date(year, 10, 23), "name": "ទិវាសន្តិភាព ២៣ តុលា",                "emoji": "☮️", "type": "public"},
        {"date": date(year, 10, 29), "name": "ព្រះរាជទិននៃព្រះមហាក្សត្រ (ព្រះអង្គ)", "emoji": "👑", "type": "public"},
        {"date": date(year, 10, 30), "name": "ព្រះរាជទិននៃព្រះមហាក្សត្រ (ព្រះអង្គ)", "emoji": "👑", "type": "public"},
        {"date": date(year, 10, 31), "name": "ព្រះរាជទិននៃព្រះមហាក្សត្រ (ព្រះអង្គ)", "emoji": "👑", "type": "public"},
        {"date": date(year, 11, 9),  "name": "ទិវាឯករាជ្យជាតិ",                      "emoji": "🇰🇭", "type": "public"},
        {"date": date(year, 11, 10), "name": "ពិធីបុណ្យអុំទូក (ថ្ងៃទី១)",            "emoji": "🚣", "type": "festival"},
        {"date": date(year, 11, 11), "name": "ពិធីបុណ្យអុំទូក (ថ្ងៃទី២)",            "emoji": "🚣", "type": "festival"},
        {"date": date(year, 11, 12), "name": "ពិធីបុណ្យអុំទូក (ថ្ងៃទី៣)",            "emoji": "🚣", "type": "festival"},
        {"date": date(year, 12, 10), "name": "ទិវាសិទ្ធិមនុស្សអន្តរជាតិ",            "emoji": "🤝", "type": "public"},
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

    seil_badge = "\n    🙏 *ថ្ងៃសីល* — ថ្ងៃប្រតិបត្តិធម៌" if lunar["is_seil"] else ""

    text = (
        f"📅  *ថ្ងៃ{weekday_kh}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🗓  *{to_khmer_num(d.day)} {month_kh} {to_khmer_num(d.year)}*\n\n"
        f"☸️  *ព.ស.* {to_khmer_num(era['buddhist_era'])}  ·  {zodiac}\n\n"
        f"{lunar['moon_emoji']}  *ច័ន្ទគតិ*\n"
        f"    {lunar['day']} {lunar['month']}\n"
        f"    {lunar['phase']}"
        f"{seil_badge}\n"
    )

    if holiday:
        text += (
            f"\n━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{holiday['emoji']}  *{holiday['name']}*\n"
            f"    🎌 ថ្ងៃឈប់សម្រាក\n"
        )

    return text


# ══════════════════════════════════════════════
# FULL MONTH CALENDAR VIEW
# ══════════════════════════════════════════════
def format_month_calendar(year: int, month: int) -> str:
    import calendar as cal_mod

    holidays_map = {
        h["date"].day: h
        for h in get_khmer_holidays(year)
        if h["date"].month == month
    }

    month_kh = KHMER_MONTHS[month]
    era = gregorian_to_khmer_era(date(year, month, 1))
    be_year = era["buddhist_era"]
    zodiac = get_zodiac_year(be_year)
    today = date.today()

    # ── Header ────────────────────────────────
    header = (
        f"📆  *{month_kh}  {to_khmer_num(year)}*\n"
        f"    ព.ស. {to_khmer_num(be_year)}  ·  {zodiac}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    # ── Grid ──────────────────────────────────
    # Sun-first: អា ចន អ ព ព សុ សៅ
    WD = " អា  ចន  អ   ព   ព   សុ  សៅ"

    first_wd_mon, num_days = cal_mod.monthrange(year, month)
    first_wd_sun = (first_wd_mon + 1) % 7

    row_cells = ["    "] * first_wd_sun
    week_rows = []

    for day_num in range(1, num_days + 1):
        d = date(year, month, day_num)
        lunar = gregorian_to_lunar(d)
        ld = lunar["day_num"]
        wd_sun = (d.weekday() + 1) % 7

        is_today     = (d == today)
        is_holiday   = day_num in holidays_map
        is_full_moon = (ld == 15)
        is_new_moon  = (ld == 1)
        is_seil      = lunar["is_seil"]

        if is_today:
            marker = "◈"
        elif is_holiday:
            marker = "★"
        elif is_full_moon:
            marker = "●"
        elif is_new_moon:
            marker = "○"
        elif is_seil:
            marker = "☸"
        else:
            marker = " "

        cell = f"{day_num:2}{marker} "
        row_cells.append(cell)

        if wd_sun == 6 or day_num == num_days:
            while len(row_cells) < 7:
                row_cells.append("    ")
            week_rows.append(" ".join(row_cells))
            row_cells = []

    grid_body = WD + "\n" + "─" * 28 + "\n" + "\n".join(week_rows)
    legend = "◈ ថ្ងៃនេះ  ★ បុណ្យ  ● ច័ន្ទពេញ  ○ ច័ន្ទថ្មី  ☸ ថ្ងៃសីល"

    result = header + f"```\n{grid_body}\n```\n_{legend}_\n"

    # ── Event list ────────────────────────────
    events = []

    for day_num in range(1, num_days + 1):
        d = date(year, month, day_num)
        lunar = gregorian_to_lunar(d)
        wday_kh = KHMER_WEEKDAYS[d.weekday()]
        delta = (d - today).days

        if delta == 0:
            badge = "🔴 ថ្ងៃនេះ"
        elif delta == 1:
            badge = "🟡 ស្អែក"
        elif 1 < delta <= 7:
            badge = f"🟢 {to_khmer_num(delta)} ថ្ងៃ"
        else:
            badge = f"📅 {to_khmer_num(day_num)} {month_kh}"

        # Holiday
        if day_num in holidays_map:
            h = holidays_map[day_num]
            events.append(
                (d, 0,
                 f"{h['emoji']}  *{h['name']}*\n"
                 f"    {badge}  ·  {wday_kh}\n"
                 f"    🌙 {lunar['day']} {lunar['month']}")
            )

        # ថ្ងៃសីល
        if lunar["is_seil"] and delta >= 0:
            events.append(
                (d, 1,
                 f"🙏  *ថ្ងៃសីល*  ·  {lunar['moon_emoji']} {lunar['day']} {lunar['month']}\n"
                 f"    {badge}  ·  {wday_kh}")
            )

    events.sort(key=lambda x: (x[0], x[1]))

    if events:
        result += "\n*── ព្រឹត្តិការណ៍ ──*\n\n"
        result += "\n\n".join(e[2] for e in events)

    return result


def month_nav_keyboard(year: int, month: int) -> InlineKeyboardMarkup:
    prev_month = month - 1
    prev_year = year
    if prev_month < 1:
        prev_month = 12
        prev_year -= 1
    next_month = month + 1
    next_year = year
    if next_month > 12:
        next_month = 1
        next_year += 1

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("◀️ មុន",     callback_data=f"kcal_month_{prev_year}_{prev_month:02d}"),
            InlineKeyboardButton("📆 ខែនេះ",   callback_data=f"kcal_month_{date.today().year}_{date.today().month:02d}"),
            InlineKeyboardButton("បន្ទាប់ ▶️",  callback_data=f"kcal_month_{next_year}_{next_month:02d}"),
        ],
        [
            InlineKeyboardButton("🙏 ថ្ងៃសីល",  callback_data="kcal_seil"),
            InlineKeyboardButton("🔙 ត្រឡប់",   callback_data="kcal_menu"),
        ],
    ])


# ══════════════════════════════════════════════
# ថ្ងៃសីល — Format upcoming Seil days
# ══════════════════════════════════════════════
def format_seil_view() -> str:
    today = date.today()
    lines = []

    # Collect next 8 ថ្ងៃសីល from today
    found = 0
    check = today
    while found < 8:
        lunar = gregorian_to_lunar(check)
        if lunar["is_seil"]:
            delta = (check - today).days
            wday_kh = KHMER_WEEKDAYS[check.weekday()]
            month_kh = KHMER_MONTHS[check.month]

            if delta == 0:
                badge = "🔴 *ថ្ងៃនេះ!*"
            elif delta == 1:
                badge = "🟡 ស្អែក"
            elif delta <= 7:
                badge = f"🟢 {to_khmer_num(delta)} ថ្ងៃទៀត"
            else:
                badge = f"📅 {to_khmer_num(check.day)} {month_kh}"

            # Moon label
            if lunar["day_num"] == 8:
                moon_label = "🌓 ៨កើត"
            elif lunar["day_num"] == 15:
                moon_label = f"🌕 ១៥កើត — ព្រះច័ន្ទពេញ"
            elif lunar["day_num"] == 23:
                moon_label = f"🌗 ៨រោច"
            else:
                moon_label = f"🌑 {lunar['day']} — ច័ន្ទថ្មី"

            lines.append(
                f"🙏  *ថ្ងៃសីល* — {moon_label}\n"
                f"    {badge}  ·  {wday_kh} {to_khmer_num(check.day)} {month_kh}\n"
                f"    _{lunar['day']} {lunar['month']}_"
            )
            found += 1
        check += timedelta(days=1)
        if (check - today).days > 120:
            break

    return (
        "🙏  *ថ្ងៃសីល — Buddhist Precept Days*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        + "\n\n".join(lines)
    )


# ══════════════════════════════════════════════
# MENUS
# ══════════════════════════════════════════════
CALENDAR_MENU_KB = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("📅 ថ្ងៃនេះ",        callback_data="kcal_today"),
        InlineKeyboardButton("🌙 ច័ន្ទគតិ",        callback_data="kcal_lunar"),
    ],
    [
        InlineKeyboardButton("📆 ប្រតិទិនខែ",      callback_data="kcal_month_now"),
        InlineKeyboardButton("🙏 ថ្ងៃសីល",         callback_data="kcal_seil"),
    ],
    [
        InlineKeyboardButton("🎉 បុណ្យ & ថ្ងៃឈប់",  callback_data="kcal_holidays"),
        InlineKeyboardButton("🔄 បំប្លែង",          callback_data="kcal_convert"),
    ],
    [InlineKeyboardButton("🔙 ត្រឡប់ម៉ឺនុយ",       callback_data="menu_main")],
])

CALENDAR_MENU_TEXT = (
    "🗓  *ប្រតិទិនខ្មែរ*\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "📅  *ថ្ងៃនេះ* — កាលបរិច្ឆេទខ្មែរ & ព.ស.\n"
    "🌙  *ច័ន្ទគតិ* — ប្រតិទិន ៧ ថ្ងៃ\n"
    "📆  *ប្រតិទិនខែ* — ប្រតិទិនពេញខែ\n"
    "🙏  *ថ្ងៃសីល* — ថ្ងៃប្រតិបត្តិធម៌ (៨, ១៥, ២៣, ២៩/៣០)\n"
    "🎉  *បុណ្យ & ថ្ងៃឈប់* — ខ្មែរ & ជាតិ\n"
    "🔄  *បំប្លែង* — ព.ស. ↔ គ.ស."
)


# ══════════════════════════════════════════════
# /calendar — Entry point
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

    # ── Today ──────────────────────────────────
    if data == "kcal_today":
        text = format_today_khmer()
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("📆 ប្រតិទិនខែ",  callback_data="kcal_month_now"),
                    InlineKeyboardButton("🌙 ច័ន្ទគតិ",    callback_data="kcal_lunar"),
                ],
                [InlineKeyboardButton("🔙 ត្រឡប់",         callback_data="kcal_menu")],
            ]),
        )

    # ── 7-day lunar view ───────────────────────
    elif data == "kcal_lunar":
        d = date.today()
        lunar = gregorian_to_lunar(d)
        era = gregorian_to_khmer_era(d)
        zodiac = get_zodiac_year(era["buddhist_era"])

        lines = []
        for i in range(-3, 4):
            day = d + timedelta(days=i)
            l = gregorian_to_lunar(day)
            wday = KHMER_WEEKDAYS[day.weekday()]
            month_kh = KHMER_MONTHS[day.month]
            seil_tag = "  🙏" if l["is_seil"] else ""

            if i == 0:
                lines.append(
                    f"▶️  *{wday} {to_khmer_num(day.day)} {month_kh}*  ◀\n"
                    f"    {l['moon_emoji']} {l['day']} {l['month']}{seil_tag}"
                )
            else:
                lines.append(
                    f"    {l['moon_emoji']}  {wday} {to_khmer_num(day.day)} {month_kh}\n"
                    f"    _{l['day']} {l['month']}_{seil_tag}"
                )

        text = (
            f"🌙  *ប្រតិទិនច័ន្ទគតិខ្មែរ*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"ឆ្នាំ{zodiac}  ·  ព.ស. {to_khmer_num(era['buddhist_era'])}\n\n"
            + "\n\n".join(lines)
            + f"\n\n━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{lunar['phase']}"
        )
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🙏 ថ្ងៃសីល",  callback_data="kcal_seil"),
                InlineKeyboardButton("🔙 ត្រឡប់",   callback_data="kcal_menu"),
            ]]),
        )

    # ── Month calendar ─────────────────────────
    elif data == "kcal_month_now":
        today = date.today()
        text = format_month_calendar(today.year, today.month)
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=month_nav_keyboard(today.year, today.month),
        )

    elif data.startswith("kcal_month_"):
        parts = data.split("_")
        year_m, month_m = int(parts[2]), int(parts[3])
        text = format_month_calendar(year_m, month_m)
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=month_nav_keyboard(year_m, month_m),
        )

    # ── ថ្ងៃសីល ────────────────────────────────
    elif data == "kcal_seil":
        text = format_seil_view()
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("📆 ប្រតិទិនខែ",  callback_data="kcal_month_now"),
                    InlineKeyboardButton("🔙 ត្រឡប់",       callback_data="kcal_menu"),
                ],
            ]),
        )

    # ── Holidays ───────────────────────────────
    elif data == "kcal_holidays":
        upcoming = get_upcoming_holidays(10)
        today = date.today()

        lines = []
        for h in upcoming:
            delta = (h["date"] - today).days
            month_kh = KHMER_MONTHS[h["date"].month]
            if delta == 0:
                badge = "🔴 *ថ្ងៃនេះ!*"
            elif delta == 1:
                badge = "🟡 ស្អែក"
            elif delta <= 7:
                badge = f"🟢 {to_khmer_num(delta)} ថ្ងៃទៀត"
            elif delta <= 30:
                badge = f"🔵 {to_khmer_num(delta)} ថ្ងៃទៀត"
            else:
                badge = f"📅 {to_khmer_num(h['date'].day)} {month_kh}"
            lines.append(
                f"{h['emoji']}  *{h['name']}*\n"
                f"    {badge}"
            )

        text = (
            "🎉  *បុណ្យ និងថ្ងៃឈប់ជាតិ*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            + "\n\n".join(lines)
        )
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 ត្រឡប់", callback_data="kcal_menu"),
            ]]),
        )

    # ── Convert ────────────────────────────────
    elif data == "kcal_convert":
        await query.edit_message_text(
            "🔄  *បំប្លែងកាលបរិច្ឆេទ*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "វាយបញ្ចូលកាលបរិច្ឆេទ:\n\n"
            "📌  `DD/MM/YYYY`  →  ព.ស.\n"
            "📌  `BE YYYY`  →  គ.ស.\n\n"
            "ឧ.  `14/04/2025`  ឬ  `BE 2568`\n\n"
            "_វាយ /cancel ដើម្បីបោះបង់_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 ត្រឡប់", callback_data="kcal_menu"),
            ]]),
        )
        return CALENDAR_CONVERT_WAIT

    # ── Back to menu ───────────────────────────
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
                seil_note = "\n🙏  *ថ្ងៃសីល* — ថ្ងៃប្រតិបត្តិធម៌" if lunar["is_seil"] else ""

                result = (
                    f"🔄  *លទ្ធផលបំប្លែង*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"🗓  *គ.ស.* {to_khmer_num(day)} {month_kh} {to_khmer_num(year)}\n"
                    f"    {weekday_kh}\n\n"
                    f"☸️  *ព.ស.* {to_khmer_num(era['buddhist_era'])}\n"
                    f"    ឆ្នាំ{zodiac}\n\n"
                    f"{lunar['moon_emoji']}  *ច័ន្ទគតិ* {lunar['day']} {lunar['month']}\n"
                    f"    {lunar['phase']}"
                    f"{seil_note}"
                )
            else:
                raise ValueError("Invalid format")

        elif text.upper().startswith("BE"):
            be_year = int(text.upper().replace("BE", "").strip())
            greg_year_approx = be_year - 544
            zodiac = get_zodiac_year(be_year)

            result = (
                f"🔄  *លទ្ធផលបំប្លែង*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"☸️  *ព.ស.* {to_khmer_num(be_year)}\n"
                f"    ឆ្នាំ{zodiac}\n\n"
                f"🗓  *គ.ស. (ប្រហាក់ប្រហែល)*\n"
                f"    មករា–មេសា {to_khmer_num(greg_year_approx)}\n"
                f"    មេសា–ធ្នូ {to_khmer_num(greg_year_approx + 1)}"
            )
        else:
            raise ValueError("Unrecognized format")

        await update.message.reply_text(
            result,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 បំប្លែងម្ដងទៀត", callback_data="kcal_convert"),
                InlineKeyboardButton("🔙 ម៉ឺនុយ",          callback_data="kcal_menu"),
            ]]),
        )

    except Exception as e:
        logger.warning(f"Calendar convert error: {e}")
        await update.message.reply_text(
            "❌  *ទម្រង់មិនត្រឹមត្រូវ*\n\n"
            "សូមប្រើ:\n"
            "·  `DD/MM/YYYY`  (ឧ. `14/04/2025`)\n"
            "·  `BE YYYY`  (ឧ. `BE 2568`)",
            parse_mode="Markdown",
        )
        return CALENDAR_CONVERT_WAIT

    return ConversationHandler.END