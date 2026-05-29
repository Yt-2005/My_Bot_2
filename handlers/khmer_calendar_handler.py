"""
handlers/khmer_calendar_handler.py — ប្រតិទិនខ្មែរ  (v3 — Chhankitek algorithm)

✅ Uses the same Chhankitek algorithm as khmer-lunar-calendar.com (via @thyrith/momentkh)
✅ Correct ថ្ងៃសីល: lunar days 8kert, 15kert, 8roch, last-roch (no duplicates)
✅ Added date search: user can type DD MM YYYY to look up any date
✅ Fixed duplicate 14រោច bug from alternating 29/30 day month parity
✅ Fixed 30-day month last-day label (now shows ១៥រោច correctly)
✅ Fixed moon phase label for 08រោច (was wrongly showing កើត)
✅ Correct Khmer zodiac, Buddhist Era, and lunar month names
"""

import logging
import math
import calendar as cal_mod
from datetime import datetime, date, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
import khmerdate as _khmerdate_lib

logger = logging.getLogger(__name__)

# ── Conversation states ──
CALENDAR_CONVERT_WAIT = "CALENDAR_CONVERT_WAIT"
CALENDAR_SEARCH_WAIT  = "CALENDAR_SEARCH_WAIT"


# ══════════════════════════════════════════════════════════════════
# KHMER NUMERALS & LABELS
# ══════════════════════════════════════════════════════════════════
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

# 14 lunar months (0-indexed): 12 normal + 2 leap (Pathamasadh=12, Tutiyasadh=13)
KHMER_LUNAR_MONTHS = [
    "មិគសិរ", "បុស្ស", "មាឃ", "ផល្គុន", "ចេត្រ", "ពិសាខ",
    "ជេស្ឋ", "អាសាឍ", "សាវណ", "ភទ្របទ", "អស្សុជ", "កត្តិក",
    "បឋមាសាឍ", "ទុតិយាសាឍ",
]

# Day labels: index 0 unused
# Waxing (កើត) 1-15, Waning (រោច) 1-15
KHMER_KERT_DAYS = [
    "",
    "១កើត", "២កើត", "៣កើត", "៤កើត", "៥កើត",
    "៦កើត", "៧កើត", "៨កើត", "៩កើត", "១០កើត",
    "១១កើត", "១២កើត", "១៣កើត", "១៤កើត", "១៥កើត",
]

KHMER_ROCH_DAYS = [
    "",
    "១រោច", "២រោច", "៣រោច", "៤រោច", "៥រោច",
    "៦រោច", "៧រោច", "៨រោច", "៩រោច", "១០រោច",
    "១១រោច", "១២រោច", "១៣រោច", "១៤រោច", "១៥រោច",
]


# ══════════════════════════════════════════════════════════════════
# CHHANKITEK ALGORITHM — powered by official `khmerdate` library
# pip install khmerdate
# ══════════════════════════════════════════════════════════════════

# Map lunar day strings returned by khmerdate → numeric phase_day + moon_phase
_KERT_STR_TO_NUM = {f"{n}កើត": n for n in range(1, 16)}
_ROCH_STR_TO_NUM = {f"{n}រោច": n for n in range(1, 16)}
# Also handle Khmer-numeral strings from the library
_KH_DIGITS_MAP = {"០":0,"១":1,"២":2,"៣":3,"៤":4,"៥":5,"៦":6,"៧":7,"៨":8,"៩":9}
def _kh_to_int(s: str) -> int:
    return int(''.join(str(_KH_DIGITS_MAP[c]) for c in s if c in _KH_DIGITS_MAP))

def _parse_lunar_day(day_str: str):
    """Return (phase_day:int, moon_phase:int)  0=kert 1=roch"""
    if "កើត" in day_str:
        return _kh_to_int(day_str.replace("កើត", "")), 0
    if "រោច" in day_str:
        return _kh_to_int(day_str.replace("រោច", "")), 1
    return 1, 0  # fallback


def gregorian_to_lunar(d: date) -> dict:
    """
    Convert Gregorian date → Khmer lunar date.
    Uses the official `khmerdate` library (Chhankitek / Phylypo Tum algorithm).
    """
    raw = _khmerdate_lib.gregorian_to_khmer_lunar(d.day, d.month, d.year)
    day_str   = raw["lunar_day"]    # e.g. "១៤កើត"
    month_name = raw["lunar_month"] # e.g. "ពិសាខ"
    be_str    = raw["lunar_year"]   # e.g. "២៥៧០"

    phase_day, moon_phase = _parse_lunar_day(day_str)
    be_year = _kh_to_int(be_str)

    # lunar_day_1based: kert 1-15, roch 16-29/30
    lunar_day_1based = phase_day if moon_phase == 0 else phase_day + 15

    # Month length: check tomorrow — if tomorrow is 1 kert of same or new month
    # we detect it below; approximate month_len by scanning ahead
    tmr_raw = _khmerdate_lib.gregorian_to_khmer_lunar(
        (d + timedelta(days=1)).day, (d + timedelta(days=1)).month, (d + timedelta(days=1)).year
    )
    tmr_pd, tmr_mp = _parse_lunar_day(tmr_raw["lunar_day"])
    tmr_month = tmr_raw["lunar_month"]

    is_last_roch = (moon_phase == 1) and (tmr_mp == 0) and (tmr_pd == 1)
    # month_len: if last roch = phase_day, month = 15+phase_day days
    month_len = 15 + phase_day if is_last_roch else (29 if phase_day == 14 and moon_phase == 1 else 30)

    # Moon emoji & phase label
    if moon_phase == 0:
        if phase_day == 15:
            moon_emoji, phase = "🌕", "🌕 ១៥កើត — ព្រះច័ន្ទពេញ"
        elif phase_day == 8:
            moon_emoji, phase = "🌓", "🌓 ៨កើត"
        elif phase_day < 8:
            moon_emoji, phase = "🌒", f"🌒 {day_str}"
        else:
            moon_emoji, phase = "🌔", f"🌔 {day_str}"
    else:
        if phase_day == 8:
            moon_emoji, phase = "🌗", "🌗 ៨រោច"
        elif is_last_roch:
            moon_emoji, phase = "🌑", f"🌑 {day_str} — ច័ន្ទថ្មី (ខ្មៅ)"
        elif phase_day < 8:
            moon_emoji, phase = "🌖", f"🌖 {day_str}"
        else:
            moon_emoji, phase = "🌘", f"🌘 {day_str}"

    # ថ្ងៃសីល: 8kert, 15kert, 8roch, last-roch
    is_seil = (
        (moon_phase == 0 and phase_day in {8, 15}) or
        (moon_phase == 1 and phase_day == 8) or
        is_last_roch
    )

    # month_index: find in KHMER_LUNAR_MONTHS list
    try:
        month_index = KHMER_LUNAR_MONTHS.index(month_name)
    except ValueError:
        month_index = 0

    return {
        "day":          day_str,
        "day_num":      lunar_day_1based,
        "phase_day":    phase_day,
        "moon_phase":   moon_phase,
        "month":        month_name,
        "month_index":  month_index,
        "month_len":    month_len,
        "year_be":      be_year,
        "phase":        phase,
        "moon_emoji":   moon_emoji,
        "is_seil":      is_seil,
        "is_last_roch": is_last_roch,
    }


def _quick_lunar(d: date) -> dict:
    """Return only phase_day + moon_phase for a date (used in is_last_roch check)."""
    raw = _khmerdate_lib.gregorian_to_khmer_lunar(d.day, d.month, d.year)
    pd, mp = _parse_lunar_day(raw["lunar_day"])
    return {"moon_phase": mp, "phase_day": pd}


# ══════════════════════════════════════════════════════════════════
# KHMER ERA (Buddhist Era)
# ══════════════════════════════════════════════════════════════════
def gregorian_to_khmer_era(d: date) -> dict:
    """
    Buddhist Era for Cambodia.
    The BE year increments on ១រោច ពិសាខ (1st waning day of Pisakh month).
    Approximate: before ~April 13 → year+543, from ~April 13 → year+544.
    """
    if d.month < 4 or (d.month == 4 and d.day < 13):
        buddhist_era = d.year + 543
    else:
        buddhist_era = d.year + 544
    saka_year = d.year - 78
    return {"buddhist_era": buddhist_era, "saka_year": saka_year}


# ══════════════════════════════════════════════════════════════════
# KHMER ZODIAC
# ══════════════════════════════════════════════════════════════════
KHMER_ZODIAC = [
    "ជូត 🐭", "ឆ្លូវ 🐂", "ខាល 🐯", "ថោះ 🐰",
    "រោង 🐉", "ម្សាញ់ 🐍", "មមី 🐴", "មមែ 🐑",
    "វក 🐒",  "រកា 🐓",  "ច 🐕",   "កុរ 🐗",
]

KHMER_SAK = [
    "សំរឹទ្ធស័ក", "ឯកស័ក", "ទោស័ក", "ត្រីស័ក", "ចត្វាស័ក",
    "បញ្ចស័ក", "ឆស័ក", "សប្តស័ក", "អដ្ឋស័ក", "នព្វស័ក",
]


def get_zodiac_year(be_year: int) -> str:
    # BE 2563 = ម្សាញ់ (snake, index 5). (2563 - 2563) % 12 = 0 → ជូត? No.
    # BE 2563 = ។ Let's use: BE 2560 = ច (dog, index 10)
    # (2560 - 2560) % 12 = 0 → index 10 → correct
    return KHMER_ZODIAC[(be_year - 2560 + 10) % 12]


def get_sak_year(be_year: int) -> str:
    return KHMER_SAK[(be_year - 2560) % 10]


# ══════════════════════════════════════════════════════════════════
# DYNAMIC LUNAR HOLIDAYS
# ══════════════════════════════════════════════════════════════════
def find_lunar_date_in_year(year: int, target_month_idx: int, target_day_num: int) -> date | None:
    """Find the Gregorian date for a specific lunar day+month in a Gregorian year."""
    d = date(year, 1, 1)
    end = date(year, 12, 31)
    while d <= end:
        lunar = gregorian_to_lunar(d)
        if lunar["month_index"] == target_month_idx and lunar["day_num"] == target_day_num:
            return d
        d += timedelta(days=1)
    return None


def get_vesak_date(year: int) -> date | None:
    """Vesak / Visakha Bochea = 15th waxing day of month ពិសាខ (index 5)."""
    return find_lunar_date_in_year(year, 5, 15)


def get_water_festival_dates(year: int) -> list[date]:
    """Water Festival = 14th–16th of lunar month កត្តិក (index 11)."""
    d14 = find_lunar_date_in_year(year, 11, 14)
    if d14:
        return [d14 + timedelta(days=i) for i in range(3)]
    return []


def get_pchum_ben_dates(year: int) -> list[date]:
    """Pchum Ben = 13th–15th waxing of lunar month អស្សុជ (index 10)."""
    d13 = find_lunar_date_in_year(year, 10, 13)
    if d13:
        return [d13 + timedelta(days=i) for i in range(3)]
    return []


# ══════════════════════════════════════════════════════════════════
# KHMER PUBLIC HOLIDAYS
# ══════════════════════════════════════════════════════════════════
def get_khmer_holidays(year: int) -> list:
    holidays = [
        {"date": date(year, 1, 1),   "name": "ចូលឆ្នាំសាកល",                          "emoji": "🎆", "type": "public"},
        {"date": date(year, 1, 7),   "name": "ទិវាជ័យជំនះ",                             "emoji": "🏆", "type": "public"},
        {"date": date(year, 3, 8),   "name": "ទិវានារីអន្តរជាតិ",                       "emoji": "👩", "type": "public"},
        {"date": date(year, 4, 13),  "name": "ចូលឆ្នាំខ្មែរ (ថ្ងៃទី១)",                "emoji": "🎊", "type": "public"},
        {"date": date(year, 4, 14),  "name": "ចូលឆ្នាំខ្មែរ (ថ្ងៃស្អែករ)",             "emoji": "🎊", "type": "public"},
        {"date": date(year, 4, 15),  "name": "ចូលឆ្នាំខ្មែរ (ថ្ងៃលើងសក់)",             "emoji": "🎊", "type": "public"},
        {"date": date(year, 4, 17),  "name": "ទិវាចងចាំប្រល័យពូជសាសន៍",               "emoji": "🕯️", "type": "public"},
        {"date": date(year, 5, 1),   "name": "ទិវាពលករអន្តរជាតិ",                      "emoji": "✊", "type": "public"},
        {"date": date(year, 5, 9),   "name": "ព្រះរាជពិធីច្រត់នាំងស្ទូង",              "emoji": "🌾", "type": "public"},
        {"date": date(year, 5, 13),  "name": "ព្រះរាជទិននៃព្រះមហាក្សត្រ (ថ្ងៃទី១)",   "emoji": "👑", "type": "public"},
        {"date": date(year, 5, 14),  "name": "ព្រះរាជទិននៃព្រះមហាក្សត្រ (ថ្ងៃទី២)",   "emoji": "👑", "type": "public"},
        {"date": date(year, 5, 15),  "name": "ព្រះរាជទិននៃព្រះមហាក្សត្រ (ថ្ងៃទី៣)",   "emoji": "👑", "type": "public"},
        {"date": date(year, 6, 1),   "name": "ទិវាកុមារអន្តរជាតិ",                     "emoji": "👶", "type": "public"},
        {"date": date(year, 6, 18),  "name": "ទិវាកំណើតអតីតស្ដេច នរោត្តម សីហនុ",     "emoji": "🌹", "type": "public"},
        {"date": date(year, 9, 24),  "name": "ទិវារដ្ឋធម្មនុញ្ញ",                      "emoji": "📜", "type": "public"},
        {"date": date(year, 10, 23), "name": "ទិវាសន្តិភាព ២៣ តុលា",                  "emoji": "☮️", "type": "public"},
        {"date": date(year, 10, 29), "name": "ព្រះរាជទិននៃព្រះមហាក្សត្រ (ថ្ងៃទី១)",  "emoji": "👑", "type": "public"},
        {"date": date(year, 10, 30), "name": "ព្រះរាជទិននៃព្រះមហាក្សត្រ (ថ្ងៃទី២)",  "emoji": "👑", "type": "public"},
        {"date": date(year, 10, 31), "name": "ព្រះរាជទិននៃព្រះមហាក្សត្រ (ថ្ងៃទី៣)",  "emoji": "👑", "type": "public"},
        {"date": date(year, 11, 9),  "name": "ទិវាឯករាជ្យជាតិ",                        "emoji": "🇰🇭", "type": "public"},
        {"date": date(year, 12, 10), "name": "ទិវាសិទ្ធិមនុស្សអន្តរជាតិ",              "emoji": "🤝", "type": "public"},
    ]

    vesak = get_vesak_date(year)
    if vesak:
        holidays.append({"date": vesak, "name": "ព្រះរាជពិធីវិសាខបូជា", "emoji": "☸️", "type": "festival"})

    for i, pb in enumerate(get_pchum_ben_dates(year), 1):
        holidays.append({
            "date": pb,
            "name": f"ព្រះរាជបុណ្យភ្ជុំបិណ្ឌ (ថ្ងៃទី{to_khmer_num(i)})",
            "emoji": "🏮", "type": "festival",
        })

    for i, wf in enumerate(get_water_festival_dates(year), 1):
        holidays.append({
            "date": wf,
            "name": f"ពិធីបុណ្យអុំទូក (ថ្ងៃទី{to_khmer_num(i)})",
            "emoji": "🚣", "type": "festival",
        })

    return sorted(holidays, key=lambda x: x["date"])


def get_upcoming_holidays(n: int = 5) -> list:
    today = date.today()
    year = today.year
    all_h = get_khmer_holidays(year) + get_khmer_holidays(year + 1)
    return [h for h in all_h if h["date"] >= today][:n]


def get_today_holiday(d: date) -> dict | None:
    for h in get_khmer_holidays(d.year):
        if h["date"] == d:
            return h
    return None


# ══════════════════════════════════════════════════════════════════
# ថ្ងៃសីល helpers
# ══════════════════════════════════════════════════════════════════
def get_seil_days_this_month(year: int, month: int) -> list:
    """Return list of (date, lunar_dict) for ថ្ងៃសីល in the given Gregorian month."""
    _, num_days = cal_mod.monthrange(year, month)
    result = []
    for day_num in range(1, num_days + 1):
        d = date(year, month, day_num)
        lunar = gregorian_to_lunar(d)
        if lunar["is_seil"]:
            result.append((d, lunar))
    return result


def _seil_moon_label(lunar: dict) -> str:
    """Build the moon phase label shown in the ថ្ងៃសីល list."""
    mp = lunar["moon_phase"]
    pd = lunar["phase_day"]
    if mp == 0 and pd == 8:
        return "🌓 ៨កើត"
    if mp == 0 and pd == 15:
        return "🌕 ១៥កើត — ព្រះច័ន្ទពេញ"
    if mp == 1 and pd == 8:
        return "🌗 ៨រោច"
    # last roch day: pd=14 for 29-day month, pd=15 for 30-day month
    roch_label = f"{'១៤' if pd == 14 else '១៥'}រោច" if pd in (14, 15) else lunar['day']
    return f"🌑 {roch_label} — ច័ន្ទថ្មី (ខ្មៅ)"


# ══════════════════════════════════════════════════════════════════
# FORMAT: TODAY'S FULL DATE
# ══════════════════════════════════════════════════════════════════
def format_today_khmer(d: date = None) -> str:
    if d is None:
        d = date.today()

    era     = gregorian_to_khmer_era(d)
    lunar   = gregorian_to_lunar(d)
    zodiac  = get_zodiac_year(era["buddhist_era"])
    sak     = get_sak_year(era["buddhist_era"])
    holiday = get_today_holiday(d)

    weekday_kh = KHMER_WEEKDAYS[d.weekday()]
    month_kh   = KHMER_MONTHS[d.month]
    seil_badge = "\n    🙏 *ថ្ងៃសីល* — ថ្ងៃប្រតិបត្តិធម៌" if lunar["is_seil"] else ""

    text = (
        f"📅  *ថ្ងៃ{weekday_kh}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🗓  *{to_khmer_num(d.day)} {month_kh} {to_khmer_num(d.year)}*\n\n"
        f"☸️  *ព.ស.* {to_khmer_num(era['buddhist_era'])}  ·  ឆ្នាំ{zodiac}  ·  {sak}\n\n"
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


# ══════════════════════════════════════════════════════════════════
# FORMAT: FULL MONTH CALENDAR
# ══════════════════════════════════════════════════════════════════
def format_month_calendar(year: int, month: int) -> str:
    holidays_map = {
        h["date"].day: h
        for h in get_khmer_holidays(year)
        if h["date"].month == month
    }

    month_kh = KHMER_MONTHS[month]
    era      = gregorian_to_khmer_era(date(year, month, 1))
    be_year  = era["buddhist_era"]
    zodiac   = get_zodiac_year(be_year)
    today    = date.today()

    header = (
        f"📆  *{month_kh}  {to_khmer_num(year)}*\n"
        f"    ព.ស. {to_khmer_num(be_year)}  ·  ឆ្នាំ{zodiac}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    WD = " អា  ចន  អ   ព   ព   សុ  សៅ"
    first_wd_mon, num_days = cal_mod.monthrange(year, month)
    first_wd_sun = (first_wd_mon + 1) % 7

    row_cells = ["    "] * first_wd_sun
    week_rows = []

    for day_num in range(1, num_days + 1):
        d     = date(year, month, day_num)
        lunar = gregorian_to_lunar(d)
        ld    = lunar["day_num"]

        is_today     = (d == today)
        is_holiday   = day_num in holidays_map
        is_full_moon = (lunar["moon_phase"] == 0 and lunar["phase_day"] == 15)
        is_new_moon  = lunar["is_last_roch"]
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

        row_cells.append(f"{day_num:2}{marker} ")
        wd_sun = (d.weekday() + 1) % 7

        if wd_sun == 6 or day_num == num_days:
            while len(row_cells) < 7:
                row_cells.append("    ")
            week_rows.append(" ".join(row_cells))
            row_cells = []

    grid_body = WD + "\n" + "─" * 28 + "\n" + "\n".join(week_rows)
    legend    = "◈ ថ្ងៃនេះ  ★ បុណ្យ  ● ច័ន្ទពេញ  ○ ច័ន្ទថ្មី  ☸ ថ្ងៃសីល"
    result    = header + f"```\n{grid_body}\n```\n_{legend}_\n"

    # ── Event list ──
    events = []
    for day_num in range(1, num_days + 1):
        d        = date(year, month, day_num)
        lunar    = gregorian_to_lunar(d)
        wday_kh  = KHMER_WEEKDAYS[d.weekday()]
        delta    = (d - today).days

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
            seil_label = _seil_moon_label(lunar)
            events.append((d, 1,
                f"🙏  *ថ្ងៃសីល* — {seil_label}\n"
                f"    {badge}  ·  {wday_kh}\n"
                f"    {lunar['day']} {lunar['month']}"))

    events.sort(key=lambda x: (x[0], x[1]))
    if events:
        result += "\n*── ព្រឹត្តិការណ៍ ──*\n\n"
        result += "\n\n".join(e[2] for e in events)

    return result


# ══════════════════════════════════════════════════════════════════
# FORMAT: UPCOMING ថ្ងៃសីល (next 8 precept days)
# ══════════════════════════════════════════════════════════════════
def format_seil_view() -> str:
    today = date.today()
    lines = []
    found = 0
    check = today

    while found < 8:
        lunar = gregorian_to_lunar(check)
        if lunar["is_seil"]:
            delta    = (check - today).days
            wday_kh  = KHMER_WEEKDAYS[check.weekday()]
            month_kh = KHMER_MONTHS[check.month]

            if delta == 0:
                badge = "🔴 *ថ្ងៃនេះ!*"
            elif delta == 1:
                badge = "🟡 ស្អែក"
            elif delta <= 7:
                badge = f"🟢 {to_khmer_num(delta)} ថ្ងៃទៀត"
            else:
                badge = f"📅 {to_khmer_num(check.day)} {month_kh}"

            moon_label = _seil_moon_label(lunar)
            # Sub-label: show day + month clearly (no italic wrapping to avoid Markdown issues)
            day_month = f"{lunar['day']} {lunar['month']}"
            # For last-roch on a 29-day month, add clarification
            if lunar["is_last_roch"] and lunar["month_len"] == 29:
                day_month += "  _(ខែ២៩ថ្ងៃ)_"

            lines.append(
                f"🙏  *ថ្ងៃសីល* — {moon_label}\n"
                f"    {badge}  ·  {wday_kh} {to_khmer_num(check.day)} {month_kh}\n"
                f"    {day_month}"
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


# ══════════════════════════════════════════════════════════════════
# FORMAT: DATE SEARCH RESULT (DD MM YYYY)
# ══════════════════════════════════════════════════════════════════
def format_date_search(d: date) -> str:
    era     = gregorian_to_khmer_era(d)
    lunar   = gregorian_to_lunar(d)
    zodiac  = get_zodiac_year(era["buddhist_era"])
    sak     = get_sak_year(era["buddhist_era"])
    holiday = get_today_holiday(d)
    today   = date.today()
    delta   = (d - today).days

    weekday_kh = KHMER_WEEKDAYS[d.weekday()]
    month_kh   = KHMER_MONTHS[d.month]

    if delta == 0:
        when = "🔴 ថ្ងៃនេះ"
    elif delta == 1:
        when = "🟡 ស្អែក"
    elif delta == -1:
        when = "🟣 ម្សិលមិញ"
    elif delta > 1:
        when = f"🔵 {to_khmer_num(delta)} ថ្ងៃទៀត"
    else:
        when = f"⬛ {to_khmer_num(abs(delta))} ថ្ងៃមុន"

    seil_badge = "\n🙏  *ថ្ងៃសីល* — ថ្ងៃប្រតិបត្តិធម៌" if lunar["is_seil"] else ""

    text = (
        f"🔍  *លទ្ធផលស្វែងរក*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🗓  *{to_khmer_num(d.day)} {month_kh} {to_khmer_num(d.year)}*\n"
        f"    {weekday_kh}  ·  {when}\n\n"
        f"☸️  *ព.ស.* {to_khmer_num(era['buddhist_era'])}\n"
        f"    ឆ្នាំ{zodiac}  ·  {sak}\n\n"
        f"{lunar['moon_emoji']}  *ច័ន្ទគតិ*\n"
        f"    {lunar['day']} {lunar['month']}\n"
        f"    {lunar['phase']}"
        f"{seil_badge}"
    )

    if holiday:
        text += (
            f"\n\n━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{holiday['emoji']}  *{holiday['name']}*\n"
            f"    🎌 ថ្ងៃឈប់សម្រាក"
        )

    return text


# ══════════════════════════════════════════════════════════════════
# MENUS
# ══════════════════════════════════════════════════════════════════
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
        InlineKeyboardButton("🔍 ស្វែងរកថ្ងៃ",     callback_data="kcal_search"),
        InlineKeyboardButton("🎉 បុណ្យ & ថ្ងៃឈប់",  callback_data="kcal_holidays"),
    ],
    [
        InlineKeyboardButton("🔄 បំប្លែង",          callback_data="kcal_convert"),
        InlineKeyboardButton("🔙 ត្រឡប់ម៉ឺនុយ",     callback_data="menu_main"),
    ],
])

CALENDAR_MENU_TEXT = (
    "🗓  *ប្រតិទិនខ្មែរ*\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "📅  *ថ្ងៃនេះ* — កាលបរិច្ឆេទខ្មែរ & ព.ស.\n"
    "🌙  *ច័ន្ទគតិ* — ប្រតិទិន ៧ ថ្ងៃ\n"
    "📆  *ប្រតិទិនខែ* — ប្រតិទិនពេញខែ\n"
    "🙏  *ថ្ងៃសីល* — ថ្ងៃប្រតិបត្តិធម៌ (៨, ១៥, ២៣, ខ្មៅ)\n"
    "🔍  *ស្វែងរកថ្ងៃ* — វាយ DD MM YYYY\n"
    "🎉  *បុណ្យ & ថ្ងៃឈប់* — ខ្មែរ & ជាតិ\n"
    "🔄  *បំប្លែង* — ព.ស. ↔ គ.ស."
)


def month_nav_keyboard(year: int, month: int) -> InlineKeyboardMarkup:
    prev_month = month - 1; prev_year = year
    if prev_month < 1:   prev_month = 12; prev_year -= 1
    next_month = month + 1; next_year = year
    if next_month > 12:  next_month = 1;  next_year += 1
    today = date.today()
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("◀️ មុន",    callback_data=f"kcal_month_{prev_year}_{prev_month:02d}"),
            InlineKeyboardButton("📆 ខែនេះ",  callback_data=f"kcal_month_{today.year}_{today.month:02d}"),
            InlineKeyboardButton("បន្ទាប់ ▶️", callback_data=f"kcal_month_{next_year}_{next_month:02d}"),
        ],
        [
            InlineKeyboardButton("🙏 ថ្ងៃសីល",   callback_data="kcal_seil"),
            InlineKeyboardButton("🔍 ស្វែងរក",   callback_data="kcal_search"),
            InlineKeyboardButton("🔙 ត្រឡប់",    callback_data="kcal_menu"),
        ],
    ])


# ══════════════════════════════════════════════════════════════════
# /calendar — Entry point
# ══════════════════════════════════════════════════════════════════
async def khmer_calendar_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        CALENDAR_MENU_TEXT,
        parse_mode="Markdown",
        reply_markup=CALENDAR_MENU_KB,
    )


# ══════════════════════════════════════════════════════════════════
# CALLBACK ROUTER
# ══════════════════════════════════════════════════════════════════
async def khmer_calendar_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data
    today = date.today()

    # ── Today ────────────────────────────────────────────────────────────────────
    if data == "kcal_today":
        text = format_today_khmer()
        await query.edit_message_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("📆 ប្រតិទិនខែ", callback_data="kcal_month_now"),
                    InlineKeyboardButton("🌙 ច័ន្ទគតិ",   callback_data="kcal_lunar"),
                ],
                [InlineKeyboardButton("🔙 ត្រឡប់", callback_data="kcal_menu")],
            ]),
        )

    # ── 7-day lunar view ─────────────────────────────────────────────────────────
    elif data == "kcal_lunar":
        d     = today
        lunar = gregorian_to_lunar(d)
        era   = gregorian_to_khmer_era(d)
        zodiac = get_zodiac_year(era["buddhist_era"])

        lines = []
        for i in range(-3, 4):
            day    = d + timedelta(days=i)
            l      = gregorian_to_lunar(day)
            wday   = KHMER_WEEKDAYS[day.weekday()]
            mon_kh = KHMER_MONTHS[day.month]
            seil_t = "  🙏" if l["is_seil"] else ""

            if i == 0:
                lines.append(
                    f"▶️  *{wday} {to_khmer_num(day.day)} {mon_kh}*  ◀\n"
                    f"    {l['moon_emoji']} {l['day']} {l['month']}{seil_t}"
                )
            else:
                lines.append(
                    f"    {l['moon_emoji']}  {wday} {to_khmer_num(day.day)} {mon_kh}\n"
                    f"    _{l['day']} {l['month']}_{seil_t}"
                )

        text = (
            f"🌙  *ប្រតិទិនច័ន្ទគតិខ្មែរ*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"ឆ្នាំ{zodiac}  ·  ព.ស. {to_khmer_num(era['buddhist_era'])}\n\n"
            + "\n\n".join(lines)
            + f"\n\n━━━━━━━━━━━━━━━━━━━━━━\n{lunar['phase']}"
        )
        await query.edit_message_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🙏 ថ្ងៃសីល", callback_data="kcal_seil"),
                InlineKeyboardButton("🔙 ត្រឡប់",  callback_data="kcal_menu"),
            ]]),
        )

    # ── Month calendar (current) ─────────────────────────────────────────────────
    elif data == "kcal_month_now":
        text = format_month_calendar(today.year, today.month)
        await query.edit_message_text(
            text, parse_mode="Markdown",
            reply_markup=month_nav_keyboard(today.year, today.month),
        )

    # ── Month calendar (nav) ─────────────────────────────────────────────────────
    elif data.startswith("kcal_month_"):
        try:
            suffix = data[len("kcal_month_"):]
            y_str, m_str = suffix.split("_")
            year_m, month_m = int(y_str), int(m_str)
            text = format_month_calendar(year_m, month_m)
            await query.edit_message_text(
                text, parse_mode="Markdown",
                reply_markup=month_nav_keyboard(year_m, month_m),
            )
        except Exception:
            await query.answer("❌ ទម្រង់ callback ខុស", show_alert=True)

    # ── ថ្ងៃសីល ──────────────────────────────────────────────────────────────────
    elif data == "kcal_seil":
        text = format_seil_view()
        await query.edit_message_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📆 ប្រតិទិនខែ", callback_data="kcal_month_now"),
                InlineKeyboardButton("🔙 ត្រឡប់",    callback_data="kcal_menu"),
            ]]),
        )

    # ── 🔍 Search date ───────────────────────────────────────────────────────────
    elif data == "kcal_search":
        await query.edit_message_text(
            "🔍  *ស្វែងរកថ្ងៃ*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "វាយកាលបរិច្ឆេទដែលអ្នកចង់ស្វែងរក:\n\n"
            "📌  `DD MM YYYY`\n"
            "📌  `DD/MM/YYYY`\n"
            "📌  `DD-MM-YYYY`\n\n"
            "ឧ.  `29 05 2025`  ឬ  `14/04/2025`\n\n"
            "_វាយ /cancel ដើម្បីបោះបង់_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 ត្រឡប់", callback_data="kcal_menu"),
            ]]),
        )
        return CALENDAR_SEARCH_WAIT

    # ── Holidays ─────────────────────────────────────────────────────────────────
    elif data == "kcal_holidays":
        upcoming = get_upcoming_holidays(12)

        lines = []
        for h in upcoming:
            delta    = (h["date"] - today).days
            mon_kh   = KHMER_MONTHS[h["date"].month]
            if delta == 0:
                badge = "🔴 *ថ្ងៃនេះ!*"
            elif delta == 1:
                badge = "🟡 ស្អែក"
            elif delta <= 7:
                badge = f"🟢 {to_khmer_num(delta)} ថ្ងៃទៀត"
            elif delta <= 30:
                badge = f"🔵 {to_khmer_num(delta)} ថ្ងៃទៀត"
            else:
                badge = f"📅 {to_khmer_num(h['date'].day)} {mon_kh}"
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
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 ត្រឡប់", callback_data="kcal_menu"),
            ]]),
        )

    # ── Convert ──────────────────────────────────────────────────────────────────
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

    # ── Back to menu ─────────────────────────────────────────────────────────────
    elif data == "kcal_menu":
        await query.edit_message_text(
            CALENDAR_MENU_TEXT, parse_mode="Markdown",
            reply_markup=CALENDAR_MENU_KB,
        )


# ══════════════════════════════════════════════════════════════════
# DATE PARSER (shared by search + convert)
# ══════════════════════════════════════════════════════════════════
def _parse_date_input(text: str) -> date:
    """
    Robustly parse user date input. Accepts:
      DD MM YYYY  (space-separated)
      DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY
      YYYY/MM/DD, YYYY-MM-DD
      BE YYYY / ព.ស. YYYY  →  raises ValueError("BE:YYYY") to signal BE mode
    """
    import re
    t = text.strip()

    # Buddhist Era shorthand
    be_pat = re.match(r'^(?:BE|ព\.ស\.?)\s*(\d{4})$', t, re.IGNORECASE)
    if be_pat:
        raise ValueError(f"BE:{be_pat.group(1)}")

    # Normalise separators → space
    t = re.sub(r'[\-\./]+', ' ', t)
    parts = t.split()
    if len(parts) != 3:
        raise ValueError("Invalid format: expected DD MM YYYY or DD/MM/YYYY")

    p = [x.strip() for x in parts]

    # Determine order: YYYY MM DD (ISO) vs DD MM YYYY
    if len(p[0]) == 4 and int(p[0]) > 31:
        year, month, day = int(p[0]), int(p[1]), int(p[2])
    else:
        day, month, year = int(p[0]), int(p[1]), int(p[2])
        if year < 100:
            year += 2000

    return date(year, month, day)


# ══════════════════════════════════════════════════════════════════
# SEARCH HANDLER: receive DD MM YYYY from user
# ══════════════════════════════════════════════════════════════════
async def calendar_search_receive(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text.lower() == "/cancel":
        await update.message.reply_text(
            "❌ បោះបង់ការស្វែងរក",
            reply_markup=CALENDAR_MENU_KB,
        )
        return ConversationHandler.END

    try:
        d = _parse_date_input(text)
        result = format_date_search(d)
        await update.message.reply_text(
            result,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🔍 ស្វែងរកម្ដងទៀត", callback_data="kcal_search"),
                    InlineKeyboardButton("🔙 ម៉ឺនុយ",           callback_data="kcal_menu"),
                ],
            ]),
        )
    except ValueError as ve:
        msg = str(ve)
        if msg.startswith("BE:"):
            await update.message.reply_text(
                "❌  *ការស្វែងរកតម្រូវ DD MM YYYY*\n\n"
                "សម្រាប់ BE → គ.ស. សូមប្រើ 🔄 *បំប្លែង* ជំនួស",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                "❌  *ទម្រង់មិនត្រឹមត្រូវ*\n\n"
                "សូមប្រើ:\n"
                "·  `DD MM YYYY`  (ឧ. `29 05 2025`)\n"
                "·  `DD/MM/YYYY`  (ឧ. `14/04/2025`)",
                parse_mode="Markdown",
            )
        return CALENDAR_SEARCH_WAIT

    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════
# CONVERT HANDLER: receive DD/MM/YYYY or BE YYYY from user
# ══════════════════════════════════════════════════════════════════
async def calendar_convert_receive(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text.lower() == "/cancel":
        await update.message.reply_text("❌ បោះបង់", reply_markup=CALENDAR_MENU_KB)
        return ConversationHandler.END

    try:
        try:
            d = _parse_date_input(text)
            be_mode = False
        except ValueError as ve:
            msg = str(ve)
            if msg.startswith("BE:"):
                be_mode = True
                be_year_val = int(msg.split(":")[1])
            else:
                raise ValueError(msg)

        if be_mode:
            be_year = be_year_val
            if not (1000 <= be_year <= 3000):
                raise ValueError("BE year out of range (1000–3000)")
            greg_year_approx = be_year - 544
            zodiac = get_zodiac_year(be_year)
            sak    = get_sak_year(be_year)

            result = (
                f"🔄  *លទ្ធផលបំប្លែង*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"☸️  *ព.ស.* {to_khmer_num(be_year)}\n"
                f"    ឆ្នាំ{zodiac}  ·  {sak}\n\n"
                f"🗓  *គ.ស. (ប្រហាក់ប្រហែល)*\n"
                f"    មករា–មេសា {to_khmer_num(greg_year_approx)}\n"
                f"    មេសា–ធ្នូ {to_khmer_num(greg_year_approx + 1)}"
            )
        else:
            era     = gregorian_to_khmer_era(d)
            lunar   = gregorian_to_lunar(d)
            zodiac  = get_zodiac_year(era["buddhist_era"])
            sak     = get_sak_year(era["buddhist_era"])
            wday_kh = KHMER_WEEKDAYS[d.weekday()]
            mon_kh  = KHMER_MONTHS[d.month]
            seil_note = "\n🙏  *ថ្ងៃសីល* — ថ្ងៃប្រតិបត្តិធម៌" if lunar["is_seil"] else ""
            holiday = get_today_holiday(d)
            holiday_note = f"\n{holiday['emoji']}  *{holiday['name']}*" if holiday else ""

            result = (
                f"🔄  *លទ្ធផលបំប្លែង*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🗓  *គ.ស.* {to_khmer_num(d.day)} {mon_kh} {to_khmer_num(d.year)}\n"
                f"    {wday_kh}\n\n"
                f"☸️  *ព.ស.* {to_khmer_num(era['buddhist_era'])}\n"
                f"    ឆ្នាំ{zodiac}  ·  {sak}\n\n"
                f"{lunar['moon_emoji']}  *ច័ន្ទគតិ* {lunar['day']} {lunar['month']}\n"
                f"    {lunar['phase']}"
                f"{seil_note}"
                f"{holiday_note}"
            )

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