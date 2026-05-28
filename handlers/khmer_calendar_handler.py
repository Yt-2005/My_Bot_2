"""
handlers/khmer_calendar_handler.py — ប្រតិទិនខ្មែរ
Features:
  ✅ Show today's Khmer date
  ✅ Khmer lunar calendar
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
# SHABBAT TIME CALCULATOR (Phnom Penh, Cambodia)
# ══════════════════════════════════════════════
# Phnom Penh coordinates: 11.5564° N, 104.9282° E
# UTC+7

_PP_LAT  = 11.5564
_PP_LNG  = 104.9282
_PP_UTC  = 7        # UTC offset hours


def _sun_time(d: date, lat: float, lng: float, utc_offset: int, rising: bool) -> datetime:
    """
    Sunrise/sunset via Spencer/NOAA simplified algorithm.
    Returns a timezone-naive datetime in local time.
    """
    day_of_year = d.timetuple().tm_yday
    # Solar declination
    B = math.radians(360 / 365 * (day_of_year - 81))
    decl = math.radians(23.45 * math.sin(B))
    lat_r = math.radians(lat)
    # Hour angle at sunrise/sunset (cos HA = -tan(lat)*tan(decl))
    cos_ha = -math.tan(lat_r) * math.tan(decl)
    cos_ha = max(-1.0, min(1.0, cos_ha))
    ha = math.degrees(math.acos(cos_ha))
    # Equation of time (minutes)
    eot = 9.87 * math.sin(2 * B) - 7.53 * math.cos(B) - 1.5 * math.sin(B)
    # Solar noon in local time
    noon_local = 12 - (lng - utc_offset * 15) / 15 - eot / 60
    if rising:
        t = noon_local - ha / 15
    else:
        t = noon_local + ha / 15
    h = int(t)
    m = int((t - h) * 60)
    s = int(((t - h) * 60 - m) * 60)
    return datetime(d.year, d.month, d.day, h, m, s)


def get_shabbat_times(d: date) -> dict | None:
    """
    Given any date, return the Shabbat times for the Friday–Saturday that
    contains or immediately follows that date.
    Returns a dict with friday_date, saturday_date, candle_lighting (18 min before sunset Fri),
    havdalah (42 min after sunset Sat), sunset_fri, sunset_sat.
    Returns None if d is Sunday and next Friday is > 6 days away (shouldn't happen).
    """
    weekday = d.weekday()  # 0=Mon … 4=Fri, 5=Sat, 6=Sun
    days_to_friday = (4 - weekday) % 7
    friday = d + timedelta(days=days_to_friday)
    saturday = friday + timedelta(days=1)

    sunset_fri = _sun_time(friday, _PP_LAT, _PP_LNG, _PP_UTC, rising=False)
    sunset_sat = _sun_time(saturday, _PP_LAT, _PP_LNG, _PP_UTC, rising=False)
    candle = sunset_fri - timedelta(minutes=18)
    havdalah = sunset_sat + timedelta(minutes=42)

    return {
        "friday": friday,
        "saturday": saturday,
        "candle_lighting": candle,
        "shabbat_start": sunset_fri,
        "shabbat_end": sunset_sat,
        "havdalah": havdalah,
    }


def format_shabbat_block(st: dict) -> str:
    """Format a Shabbat times block in Khmer + English."""
    fri = st["friday"]
    sat = st["saturday"]
    fri_kh = f"{to_khmer_num(fri.day)} {KHMER_MONTHS[fri.month]} {to_khmer_num(fri.year)}"
    sat_kh = f"{to_khmer_num(sat.day)} {KHMER_MONTHS[sat.month]} {to_khmer_num(sat.year)}"
    dur_total = int((st["shabbat_end"] - st["shabbat_start"]).total_seconds())
    dur_h = dur_total // 3600
    dur_m = (dur_total % 3600) // 60
    return (
        "✡️ *ពេលវេលា Shabbat — ភ្នំពេញ*\n\n"
        "🕯️ *ចំហេរទៀន (Candle Lighting)*\n"
        f"  សុក្រ {fri_kh}\n"
        f"  ម៉ោង {st['candle_lighting'].strftime('%H:%M')} (18 នាទី មុន ថ្ងៃលិច)\n\n"
        "🌅 *ថ្ងៃលិច សុក្រ (Shabbat Begins)*\n"
        f"  ម៉ោង {st['shabbat_start'].strftime('%H:%M')}\n\n"
        "🌆 *ថ្ងៃលិច សៅរ៍ (Shabbat Ends — Havdalah)*\n"
        f"  សៅរ៍ {sat_kh}\n"
        f"  ម៉ោង {st['havdalah'].strftime('%H:%M')} (42 នាទី ក្រោយ ថ្ងៃលិច)\n\n"
        f"⏱ Shabbat duration: {dur_h}h {dur_m}m"
    )


# ══════════════════════════════════════════════
# FULL MONTH CALENDAR VIEW  (matches khmer-lunar-calendar.com layout)
# ══════════════════════════════════════════════
def _sunset_pp(d: date) -> str:
    """Sunset time for Phnom Penh (11.56N, 104.93E, UTC+7)."""
    doy = d.timetuple().tm_yday
    B = math.radians(360 / 365 * (doy - 81))
    decl = math.radians(23.45 * math.sin(B))
    lat_r = math.radians(11.5564)
    cos_ha = max(-1.0, min(1.0, -math.tan(lat_r) * math.tan(decl)))
    ha = math.degrees(math.acos(cos_ha))
    eot = 9.87 * math.sin(2 * B) - 7.53 * math.cos(B) - 1.5 * math.sin(B)
    noon = 12 - (104.9282 - 7 * 15) / 15 - eot / 60
    t = noon + ha / 15
    hh = int(t)
    mm = int((t - hh) * 60)
    return f"{hh}:{mm:02d}"


def _add_minutes(time_str: str, minutes: int) -> str:
    hh, mm = map(int, time_str.split(":"))
    total = hh * 60 + mm + minutes
    return f"{total // 60}:{total % 60:02d}"


def format_month_calendar(year: int, month: int) -> str:
    """
    Full month calendar matching khmer-lunar-calendar.com layout:
    - Header: Gregorian month + Khmer BE year + Zodiac
    - 7-column grid (អាទិ ចន្ទ អង្គារ ពុធ ព្រហ សុក្រ សៅរ៍)
    - Each cell: Gregorian day + Khmer lunar day + event label
    - Right panel: ordered event list for the month
    """
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
        f"📅 *{month_kh} {to_khmer_num(year)}*\n"
        f"ព.ស.{to_khmer_num(be_year)} • ឆ្នាំ{zodiac}\n"
    )

    # ── Weekday row (Sun-first, matching reference site) ──────────────────────
    # site order: អាទិ ចន្ទ អង្គារ ពុធ ព្រហ សុក្រ សៅរ៍
    # Python weekday(): 0=Mon … 6=Sun  →  Sun=6
    # We rotate so Sunday is col 0
    WD_HEADER = "អា | ចន | អ  | ព  | ព  | សុ | សៅ"
    SEP       = "───┼───┼───┼───┼───┼───┼───"

    # first_weekday from monthrange is Mon=0; convert to Sun=0
    first_wd_mon, num_days = cal_mod.monthrange(year, month)
    first_wd_sun = (first_wd_mon + 1) % 7  # shift: Mon→1, Sun→0

    row_cells = ["   "] * first_wd_sun
    week_rows = []

    for day_num in range(1, num_days + 1):
        d = date(year, month, day_num)
        lunar = gregorian_to_lunar(d)
        ld = lunar["day_num"]
        wd_sun = (d.weekday() + 1) % 7  # Sun=0, Mon=1 … Sat=6

        is_today    = (d == today)
        is_holiday  = day_num in holidays_map
        is_friday   = (wd_sun == 5)
        is_saturday = (wd_sun == 6)
        is_sunday   = (wd_sun == 0)
        is_full_moon = (ld == 15)
        is_new_moon  = (ld == 1)

        # Suffix: today marker > holiday > moon phases > shabbat
        if is_today:
            suffix = "◉"
        elif is_holiday:
            suffix = "★"
        elif is_full_moon:
            suffix = "●"
        elif is_new_moon:
            suffix = "○"
        elif is_friday or is_saturday:
            suffix = "✡"
        else:
            suffix = " "

        cell = f"{day_num:2}{suffix}"
        row_cells.append(cell)

        if wd_sun == 6 or day_num == num_days:
            # pad last row
            while len(row_cells) < 7:
                row_cells.append("   ")
            week_rows.append(" | ".join(row_cells))
            row_cells = []

    # ── Event list (right panel equivalent, listed below grid) ───────────────
    events = []
    for day_num in sorted(holidays_map):
        h = holidays_map[day_num]
        d = date(year, month, day_num)
        lunar = gregorian_to_lunar(d)
        wday_kh = KHMER_WEEKDAYS[d.weekday()]
        events.append(
            f"  {h['emoji']} *{to_khmer_num(day_num)} {month_kh}* ({wday_kh})\n"
            f"     {h['name']}\n"
            f"     _{lunar['day']} {lunar['month']}_"
        )

    # Shabbat entries
    for day_num in range(1, num_days + 1):
        d = date(year, month, day_num)
        wd_sun = (d.weekday() + 1) % 7
        if wd_sun == 5:  # Friday
            ss = _sunset_pp(d)
            cl = _add_minutes(ss, -18)
            lunar = gregorian_to_lunar(d)
            events.append(
                f"  ✡ *{to_khmer_num(day_num)} {month_kh}* (សុក្រ) — Shabbat\n"
                f"     🕯️ ចំហេរទៀន: {cl}  🌅 ថ្ងៃលិច: {ss}\n"
                f"     _{lunar['day']} {lunar['month']}_"
            )
        elif wd_sun == 6:  # Saturday
            ss = _sunset_pp(d)
            hv = _add_minutes(ss, 42)
            lunar = gregorian_to_lunar(d)
            events.append(
                f"  ✡ *{to_khmer_num(day_num)} {month_kh}* (សៅរ៍) — Havdalah {hv}\n"
                f"     _{lunar['day']} {lunar['month']}_"
            )

    events.sort(key=lambda x: int(''.join(filter(str.isdigit, x.split('*')[1].split(month_kh)[0].strip())) or '0'))

    # ── Assemble ──────────────────────────────
    grid_lines = [WD_HEADER, SEP] + week_rows
    body = "\n".join(grid_lines)

    legend = (
        "◉ ថ្ងៃនេះ  ★ ថ្ងៃបុណ្យ  ● ព្រះច័ន្ទពេញ  ○ ខែថ្មី  ✡ Shabbat"
    )

    result = header + "```\n" + body + "\n```\n" + legend

    if events:
        result += "\n\n*━━ ព្រឹត្តិការណ៍ខែនេះ ━━*\n" + "\n\n".join(events)

    return result


def month_nav_keyboard(year: int, month: int) -> InlineKeyboardMarkup:
    """Inline keyboard for month view with prev/next navigation."""
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
            InlineKeyboardButton("⬅️ មុន", callback_data=f"kcal_month_{prev_year}_{prev_month:02d}"),
            InlineKeyboardButton("📆 ខែនេះ",  callback_data=f"kcal_month_{date.today().year}_{date.today().month:02d}"),
            InlineKeyboardButton("បន្ទាប់ ➡️", callback_data=f"kcal_month_{next_year}_{next_month:02d}"),
        ],
        [
            InlineKeyboardButton("✡️ Shabbat", callback_data="kcal_shabbat"),
            InlineKeyboardButton("🔙 ត្រឡប់", callback_data="kcal_menu"),
        ],
    ])

# ══════════════════════════════════════════════
# MENUS
# ══════════════════════════════════════════════
CALENDAR_MENU_KB = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("📅 ថ្ងៃនេះ",       callback_data="kcal_today"),
        InlineKeyboardButton("🌙 ច័ន្ទគតិ",       callback_data="kcal_lunar"),
    ],
    [
        InlineKeyboardButton("📆 ប្រតិទិនខែ",     callback_data="kcal_month_now"),
        InlineKeyboardButton("✡️ Shabbat",        callback_data="kcal_shabbat"),
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
    "📆 *ប្រតិទិនខែ* — មើលប្រតិទិនពេញមួយខែ\n"
    "✡️ *Shabbat* — ពេលវេលា Shabbat ភ្នំពេញ\n"
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

    elif data == "kcal_month_now":
        today = date.today()
        text = format_month_calendar(today.year, today.month)
        await query.edit_message_text(
            f"```\n{text}\n```",
            parse_mode="Markdown",
            reply_markup=month_nav_keyboard(today.year, today.month),
        )

    elif data.startswith("kcal_month_"):
        # kcal_month_YYYY_MM
        parts = data.split("_")
        year_m, month_m = int(parts[2]), int(parts[3])
        text = format_month_calendar(year_m, month_m)
        await query.edit_message_text(
            f"```\n{text}\n```",
            parse_mode="Markdown",
            reply_markup=month_nav_keyboard(year_m, month_m),
        )

    elif data == "kcal_shabbat":
        today = date.today()
        st = get_shabbat_times(today)
        text = format_shabbat_block(st)
        # Also show next 4 Shabbats
        extra = ["\n\n📋 *Shabbat ៤ សប្ដាហ៍ខាងមុខ:*"]
        for w in range(1, 5):
            future = today + timedelta(weeks=w)
            st2 = get_shabbat_times(future)
            fri_str = f"{to_khmer_num(st2['friday'].day)} {KHMER_MONTHS[st2['friday'].month]}"
            sat_str = f"{to_khmer_num(st2['saturday'].day)} {KHMER_MONTHS[st2['saturday'].month]}"
            extra.append(
                f"  🕯️ {fri_str} ម៉ោង{st2['candle_lighting'].strftime('%H:%M')} → "
                f"✡️ {sat_str} ម៉ោង{st2['havdalah'].strftime('%H:%M')}"
            )
        text += "\n".join(extra)
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