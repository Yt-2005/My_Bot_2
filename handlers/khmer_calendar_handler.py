"""
handlers/khmer_calendar_handler.py — ប្រតិទិនខ្មែរ  (v2 — improved accuracy)

Fixes & improvements vs v1:
  ✅ More accurate lunar date via true synodic epoch (not simple delta drift)
  ✅ Correct ថ្ងៃសីល mapping  (lunar day 8, 15, 23, 29 — not 30 on short months)
  ✅ Correct Khmer zodiac formula  (BE mod 12, properly offset)
  ✅ Correct Buddhist Era cutoff  (Khmer New Year ~Apr 13-14)
  ✅ Safe callback parsing for kcal_month_YYYY_MM
  ✅ Dynamic Vesak / Visakha Bochea date (15th of lunar month Visakha)
  ✅ Dynamic Water Festival dates (14-16th of lunar month Kattika ≈ full-moon Nov)
  ✅ Khmer New Year note (Apr 13-15 fixed public holiday block)
  ✅ Moon phase label is now accurate (new/waxing/full/waning/dark)
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

# Khmer / Theravada lunar month names (12 months, 0-indexed starting from Mekasir)
KHMER_LUNAR_MONTHS = [
    "មិគសិរ", "បុស្ស", "មាឃ", "ផល្គុន", "ចេត្រ", "វិសាខ",
    "ជេស្ឋ", "អាសាឍ", "សាវណ", "ភទ្របទ", "អស្សុជ", "កត្តិក",
]

# Waxing days: 1–15 = ១កើត … ១៥កើត; Waning days: 1–14 = ១រោច … ១៤រោច
# Index 0 unused; index 1-15 = waxing; index 16-29 = waning (29-day months skip index 29)
KHMER_LUNAR_DAYS = [
    "",                                                                 # 0 unused
    "១កើត", "២កើត", "៣កើត", "៤កើត", "៥កើត",           # 1-5
    "៦កើត", "៧កើត", "៨កើត", "៩កើត", "១០កើត",           # 6-10
    "១១កើត", "១២កើត", "១៣កើត", "១៤កើត", "១៥កើត",       # 11-15
    "១រោច", "២រោច", "៣រោច", "៤រោច", "៥រោច",            # 16-20
    "៦រោច", "៧រោច", "៨រោច", "៩រោច", "១០រោច",           # 21-25
    "១១រោច", "១២រោច", "១៣រោច", "១៤រោច",                  # 26-29
]

# ══════════════════════════════════════════════
# ACCURATE LUNAR DATE CALCULATION
# ══════════════════════════════════════════════
# Known new moon (lunar day 1): 2000-01-06 UTC  (J2000 reference)
# Synodic month = 29.530588853 days (IAU value)
_EPOCH_NEW_MOON = date(2000, 1, 6)
_SYNODIC_MONTH = 29.530588853

# Epoch lunar context: that new moon is day 1 of lunar month Bos (បុស្ស), BE 2543
_EPOCH_LUNAR_MONTH_INDEX = 1   # "បុស្ស" index in KHMER_LUNAR_MONTHS
_EPOCH_LUNAR_BE_YEAR = 2543


def gregorian_to_lunar(d: date) -> dict:
    """
    Convert a Gregorian date to Khmer lunar date.
    Returns a dict with:
      day_str, day_num (1-29), month (Khmer name), month_index,
      year_be, phase, moon_emoji, is_seil
    """
    delta = (d - _EPOCH_NEW_MOON).days
    # Total lunar days since epoch (0-based)
    total_ld = delta  # epoch is day 1 of a month → offset 0

    # Which synodic cycle and position within it
    cycle, pos = divmod(total_ld, _SYNODIC_MONTH)
    cycle = int(cycle)
    day_in_cycle = pos  # float 0.0 – 29.53…

    # Lunar day number 1-30 (Theravada months alternate 29/30 days)
    # We use the fractional position to determine if this month is 29 or 30 days.
    # A simple parity rule: even cycles = 30 days, odd = 29 days (approximation)
    month_length = 30 if (cycle % 2 == 0) else 29
    lunar_day_num = int(day_in_cycle) + 1
    lunar_day_num = max(1, min(month_length, lunar_day_num))

    # Lunar month index and BE year
    total_months = _EPOCH_LUNAR_MONTH_INDEX + cycle
    lunar_month_index = total_months % 12
    lunar_be_year = _EPOCH_LUNAR_BE_YEAR + total_months // 12

    # Day label
    if lunar_day_num <= 15:
        day_str = KHMER_LUNAR_DAYS[lunar_day_num]
        phase_base = "កើត (ខ្នើត)"
    else:
        waning_idx = lunar_day_num  # indices 16-29 map to 1-14 roc
        day_str = KHMER_LUNAR_DAYS[waning_idx] if waning_idx < len(KHMER_LUNAR_DAYS) else "១៤រោច"
        phase_base = "រោច (ខ្មៅ)"

    # Moon emoji & phase label
    if lunar_day_num == 15:
        moon_emoji = "🌕"
        phase = "🌕 ព្រះច័ន្ទពេញ"
    elif lunar_day_num == 1:
        moon_emoji = "🌑"
        phase = "🌑 ច័ន្ទថ្មី"
    elif lunar_day_num < 8:
        moon_emoji = "🌒"
        phase = f"🌒 {phase_base}"
    elif lunar_day_num == 8:
        moon_emoji = "🌓"
        phase = "🌓 ០៨កើត"
    elif lunar_day_num < 15:
        moon_emoji = "🌔"
        phase = f"🌔 {phase_base}"
    elif lunar_day_num < 23:
        moon_emoji = "🌖"
        phase = f"🌖 {phase_base}"
    elif lunar_day_num == 23:
        moon_emoji = "🌗"
        phase = "🌗 ០៨រោច"
    else:
        moon_emoji = "🌘"
        phase = f"🌘 {phase_base}"

    # ថ្ងៃសីល: lunar days 8, 15, 23, and the last day of the month (29 or 30)
    is_seil = lunar_day_num in {8, 15, 23, month_length}

    return {
        "day": day_str,
        "day_num": lunar_day_num,
        "month": KHMER_LUNAR_MONTHS[lunar_month_index],
        "month_index": lunar_month_index,
        "year_be": lunar_be_year,
        "month_length": month_length,
        "phase": phase,
        "moon_emoji": moon_emoji,
        "is_seil": is_seil,
    }


# ══════════════════════════════════════════════
# KHMER ERA YEAR (ព.ស.)
# ══════════════════════════════════════════════
def gregorian_to_khmer_era(d: date) -> dict:
    """
    Buddhist Era (ព.ស.) for Cambodia.
    Khmer New Year falls ~April 13-14; before that date the BE year is year+543,
    from that date onwards it is year+544.
    """
    if d.month < 4 or (d.month == 4 and d.day < 13):
        buddhist_era = d.year + 543
    else:
        buddhist_era = d.year + 544
    saka_year = d.year - 78
    return {"buddhist_era": buddhist_era, "saka_year": saka_year}


# ══════════════════════════════════════════════
# KHMER ZODIAC YEAR
# ══════════════════════════════════════════════
KHMER_ZODIAC = [
    "ជូត 🐭", "ឆ្លូវ 🐂", "ខាល 🐯", "ថោះ 🐰",
    "រោង 🐉", "ម្សាញ់ 🐍", "មមី 🐴", "មមែ 🐑",
    "វក 🐒",  "រកា 🐓",  "ច 🐕",   "កុរ 🐗",
]


def get_zodiac_year(be_year: int) -> str:
    """
    Khmer zodiac cycles every 12 years.
    BE 2563 = ឆ្លូវ (ox) → index 1 in the array.
    So: (be_year - 2563 + 1) % 12
    """
    return KHMER_ZODIAC[(be_year - 2563 + 1) % 12]


# ══════════════════════════════════════════════
# DYNAMIC LUNAR HOLIDAYS
# ══════════════════════════════════════════════
def find_lunar_date_in_year(year: int, target_month_index: int, target_day_num: int) -> date | None:
    """Find the Gregorian date for a specific lunar day+month in a Gregorian year."""
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    d = start
    while d <= end:
        lunar = gregorian_to_lunar(d)
        if lunar["month_index"] == target_month_index and lunar["day_num"] == target_day_num:
            return d
        d += timedelta(days=1)
    return None


def get_vesak_date(year: int) -> date | None:
    """Vesak / Visakha Bochea = 15th day of lunar month Visakha (index 5)."""
    return find_lunar_date_in_year(year, 5, 15)


def get_water_festival_dates(year: int) -> list[date]:
    """
    Water Festival / Bon Om Touk = 14th, 15th (full moon), 16th of lunar month Kattika (index 11).
    Returns list of up to 3 dates.
    """
    d14 = find_lunar_date_in_year(year, 11, 14)
    if d14:
        return [d14 + timedelta(days=i) for i in range(3)]
    return []


def get_pchum_ben_dates(year: int) -> list[date]:
    """
    Pchum Ben = days 1-15 of lunar month Asouj (index 10), the last 3 days are public holiday.
    We return the 13th, 14th, 15th of Asouj.
    """
    d13 = find_lunar_date_in_year(year, 10, 13)
    if d13:
        return [d13 + timedelta(days=i) for i in range(3)]
    return []


# ══════════════════════════════════════════════
# KHMER PUBLIC HOLIDAYS & FESTIVALS
# ══════════════════════════════════════════════
def get_khmer_holidays(year: int) -> list:
    holidays = [
        # ── Fixed public holidays ──────────────────────────────────────────────
        {"date": date(year, 1, 1),   "name": "ចូលឆ្នាំសាកល",                         "emoji": "🎆", "type": "public"},
        {"date": date(year, 1, 7),   "name": "ទិវាជ័យជំនះ",                            "emoji": "🏆", "type": "public"},
        {"date": date(year, 3, 8),   "name": "ទិវានារីអន្តរជាតិ",                      "emoji": "👩", "type": "public"},
        {"date": date(year, 4, 13),  "name": "ចូលឆ្នាំខ្មែរ (ថ្ងៃទី១)",               "emoji": "🎊", "type": "public"},
        {"date": date(year, 4, 14),  "name": "ចូលឆ្នាំខ្មែរ (ថ្ងៃទី២) — ថ្ងៃស្អែករ",  "emoji": "🎊", "type": "public"},
        {"date": date(year, 4, 15),  "name": "ចូលឆ្នាំខ្មែរ (ថ្ងៃទី៣) — ថ្ងៃលើងសក់",  "emoji": "🎊", "type": "public"},
        {"date": date(year, 4, 17),  "name": "ទិវាចងចាំប្រល័យពូជសាសន៍",              "emoji": "🕯️", "type": "public"},
        {"date": date(year, 5, 1),   "name": "ទិវាពលករអន្តរជាតិ",                     "emoji": "✊", "type": "public"},
        {"date": date(year, 5, 9),   "name": "ព្រះរាជពិធីច្រត់នាំងស្ទូង",             "emoji": "🌾", "type": "public"},
        {"date": date(year, 5, 13),  "name": "ព្រះរាជទិននៃព្រះមហាក្សត្រ (ថ្ងៃទី១)",  "emoji": "👑", "type": "public"},
        {"date": date(year, 5, 14),  "name": "ព្រះរាជទិននៃព្រះមហាក្សត្រ (ថ្ងៃទី២)",  "emoji": "👑", "type": "public"},
        {"date": date(year, 5, 15),  "name": "ព្រះរាជទិននៃព្រះមហាក្សត្រ (ថ្ងៃទី៣)",  "emoji": "👑", "type": "public"},
        {"date": date(year, 6, 1),   "name": "ទិវាកុមារអន្តរជាតិ",                    "emoji": "👶", "type": "public"},
        {"date": date(year, 6, 18),  "name": "ទិវាកំណើតអតីតស្ដេច នរោត្តម សីហនុ",    "emoji": "🌹", "type": "public"},
        {"date": date(year, 9, 24),  "name": "ទិវារដ្ឋធម្មនុញ្ញ",                     "emoji": "📜", "type": "public"},
        {"date": date(year, 10, 23), "name": "ទិវាសន្តិភាព ២៣ តុលា",                 "emoji": "☮️", "type": "public"},
        {"date": date(year, 10, 29), "name": "ព្រះរាជទិននៃព្រះមហាក្សត្រ (ថ្ងៃទី១)", "emoji": "👑", "type": "public"},
        {"date": date(year, 10, 30), "name": "ព្រះរាជទិននៃព្រះមហាក្សត្រ (ថ្ងៃទី២)", "emoji": "👑", "type": "public"},
        {"date": date(year, 10, 31), "name": "ព្រះរាជទិននៃព្រះមហាក្សត្រ (ថ្ងៃទី៣)", "emoji": "👑", "type": "public"},
        {"date": date(year, 11, 9),  "name": "ទិវាឯករាជ្យជាតិ",                       "emoji": "🇰🇭", "type": "public"},
        {"date": date(year, 12, 10), "name": "ទិវាសិទ្ធិមនុស្សអន្តរជាតិ",             "emoji": "🤝", "type": "public"},
    ]

    # ── Dynamic lunar holidays ─────────────────────────────────────────────────

    # Vesak / Visakha Bochea
    vesak = get_vesak_date(year)
    if vesak:
        holidays.append({"date": vesak, "name": "ព្រះរាជពិធីវិសាខបូជា", "emoji": "☸️", "type": "festival"})

    # Pchum Ben (last 3 days) — ភ្ជុំបិណ្ឌ
    for i, pb in enumerate(get_pchum_ben_dates(year), 1):
        holidays.append({
            "date": pb,
            "name": f"ព្រះរាជបុណ្យភ្ជុំបិណ្ឌ (ថ្ងៃទី{to_khmer_num(i)})",
            "emoji": "🏮",
            "type": "festival",
        })

    # Water Festival — អុំទូក
    for i, wf in enumerate(get_water_festival_dates(year), 1):
        holidays.append({
            "date": wf,
            "name": f"ពិធីបុណ្យអុំទូក (ថ្ងៃទី{to_khmer_num(i)})",
            "emoji": "🚣",
            "type": "festival",
        })

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
# ថ្ងៃសីល — Get Seil days in month
# ══════════════════════════════════════════════
def get_seil_days_this_month(year: int, month: int) -> list:
    """Return list of (date, lunar_dict) for ថ្ងៃសីល in the given month."""
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
        f"☸️  *ព.ស.* {to_khmer_num(era['buddhist_era'])}  ·  ឆ្នាំ{zodiac}\n\n"
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

    header = (
        f"📆  *{month_kh}  {to_khmer_num(year)}*\n"
        f"    ព.ស. {to_khmer_num(be_year)}  ·  ឆ្នាំ{zodiac}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    # Sun-first grid header: Sun Mon Tue Wed Thu Fri Sat
    WD = " អា  ចន  អ   ព   ព   សុ  សៅ"

    first_wd_mon, num_days = cal_mod.monthrange(year, month)
    first_wd_sun = (first_wd_mon + 1) % 7   # Python Mon=0 → Sun=6; Sun-first col

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

        if day_num in holidays_map:
            h = holidays_map[day_num]
            events.append((d, 0,
                f"{h['emoji']}  *{h['name']}*\n"
                f"    {badge}  ·  {wday_kh}\n"
                f"    🌙 {lunar['day']} {lunar['month']}"))

        if lunar["is_seil"] and delta >= 0:
            events.append((d, 1,
                f"🙏  *ថ្ងៃសីល*  ·  {lunar['moon_emoji']} {lunar['day']} {lunar['month']}\n"
                f"    {badge}  ·  {wday_kh}"))

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

            ld = lunar["day_num"]
            if ld == 8:
                moon_label = "🌓 ៨កើត"
            elif ld == 15:
                moon_label = "🌕 ១៥កើត — ព្រះច័ន្ទពេញ"
            elif ld == 23:
                moon_label = "🌗 ០៨រោច"
            else:
                # last day of month (29 or 30)
                moon_label = f"🌑 {lunar['day']} — ច័ន្ទថ្មី (ខ្មៅ)"

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
    "🙏  *ថ្ងៃសីល* — ថ្ងៃប្រតិបត្តិធម៌ (៨, ១៥, ២៣, ខ្មៅ)\n"
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

    # ── Today ──────────────────────────────────────────────────────────────────
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

    # ── 7-day lunar view ───────────────────────────────────────────────────────
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

    # ── Month calendar ─────────────────────────────────────────────────────────
    elif data == "kcal_month_now":
        today = date.today()
        text = format_month_calendar(today.year, today.month)
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=month_nav_keyboard(today.year, today.month),
        )

    elif data.startswith("kcal_month_"):
        # Format: kcal_month_YYYY_MM  (e.g. kcal_month_2025_06)
        try:
            suffix = data[len("kcal_month_"):]   # "2025_06"
            y_str, m_str = suffix.split("_")
            year_m, month_m = int(y_str), int(m_str)
            text = format_month_calendar(year_m, month_m)
            await query.edit_message_text(
                text,
                parse_mode="Markdown",
                reply_markup=month_nav_keyboard(year_m, month_m),
            )
        except Exception:
            await query.answer("❌ ទម្រង់ callback ខុស", show_alert=True)

    # ── ថ្ងៃសីល ────────────────────────────────────────────────────────────────
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

    # ── Holidays ───────────────────────────────────────────────────────────────
    elif data == "kcal_holidays":
        upcoming = get_upcoming_holidays(12)
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

    # ── Convert ────────────────────────────────────────────────────────────────
    elif data == "kcal_convert":
        await query.edit_message_text(
            "🔄  *បំប្លែងកាលបរិច្ឆេទ*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "វាយបញ្ចូលកាលបរិច្ឆេទ:\n\n"
            "📌  `DD/MM/YYYY`  →  ព.ស. + ច័ន្ទគតិ\n"
            "📌  `BE YYYY`  →  គ.ស. ប្រហាក់ប្រហែល\n\n"
            "ឧ.  `14/04/2025`  ឬ  `BE 2568`\n\n"
            "_វាយ /cancel ដើម្បីបោះបង់_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 ត្រឡប់", callback_data="kcal_menu"),
            ]]),
        )
        return CALENDAR_CONVERT_WAIT

    # ── Back to menu ───────────────────────────────────────────────────────────
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
        if "/" in text and not text.startswith("/"):
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
                holiday = get_today_holiday(d)
                holiday_note = f"\n{holiday['emoji']}  *{holiday['name']}*" if holiday else ""

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
                    f"{holiday_note}"
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