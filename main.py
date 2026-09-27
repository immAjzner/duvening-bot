import requests
import os
import json
import base64
import html
import re
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from convertdate import hebrew
from pyluach import dates, parshios

# ============================================================================
# NOTE TO CONTRIBUTORS:
# All source-code comments in this file must be written in English only.
# Do not add Hebrew comments.
# ============================================================================


# ===== CONFIG =====
TOKEN = os.environ["BOT_TOKEN"]
BASE_URL = f"https://api.telegram.org/bot{TOKEN}"

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
REPO = os.environ["GITHUB_REPOSITORY"]

USERS_FILE = "users.json"
LAST_RUN_FILE = "last_run.json"
MY_CHAT_ID = "5474184664"

TZ = ZoneInfo("Asia/Jerusalem")


def today_jerusalem():
    """Gregorian date in Asia/Jerusalem.

    GitHub Actions and other hosts run in UTC; `date.today()` is the machine's
    calendar day. Early morning in Israel (e.g. 0:00–02:59) is still "yesterday"
    in UTC, which made the digest one civil day behind `should_send_now()` (which
    already uses `datetime.now(TZ).date()`).
    """
    return datetime.now(TZ).date()


def parse_force_send_count():
    """How many preview messages to send only to MY_CHAT_ID. 0 = off (normal run).

    Supports FORCE_SEND=1 as before (one message for the current day).
    """
    raw = (os.environ.get("FORCE_SEND") or "").strip()
    if not raw:
        return 0
    try:
        n = int(raw, 10)
    except ValueError:
        return 0
    return n if n > 0 else 0


def parse_preview_date():
    """Optional ISO date for a manual preview sent only to MY_CHAT_ID."""
    raw = (os.environ.get("PREVIEW_DATE") or "").strip()
    if not raw:
        return False, None
    try:
        return True, date.fromisoformat(raw)
    except ValueError:
        return True, None


def is_manual_dispatch_run():
    """True when GitHub Actions workflow_dispatch sets MANUAL_RUN=1.

    Scheduled runs do not set it; they retain the normal morning-window and
    last-run behavior.
    """
    value = (os.environ.get("MANUAL_RUN") or "").strip().lower()
    if value in ("1", "true", "yes"):
        return True

    return (
        os.environ.get("GITHUB_EVENT_NAME") or ""
    ).strip() == "workflow_dispatch"


# Day zmanim and Shabbat times from yeshiva.org — place id 173 is Netanya.
YESHIVA_PLACE_ID = os.environ.get("YESHIVA_PLACE_ID", "173")

# Browser-like headers are required because the site may otherwise return
# an HTML error response instead of the expected content.
YESHIVA_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*;q=0.01",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.yeshiva.org.il/calendar/timesday",
}

# Labels as they appear in JSON and HTML, including alternate abbreviations.
YI_NAMES_SOF_ZMAN_SHMA_GRA = (
    'סוף זמן קריאת שמע לגר"א',
    'סוף זמן ק"ש לגר"א',
)
YI_NAMES_SHKIA = ("שקיעה",)
YI_NAMES_TZEIT = ("צאת הכוכבים",)
YI_NAMES_TSET_SHABBAT = ("צאת שבת", "יציאת שבת")
YI_NAMES_FAST_START = ("כניסת הצום", "תחילת הצום")
YI_NAMES_FAST_END = ("צאת הצום", "יציאת הצום", "סיום הצום")
YI_NAMES_YOM_KIPPUR_START = ("כניסת החג", "כניסת יום כיפור")
YI_NAMES_YOM_KIPPUR_END = (
    "צאת החג",
    "יציאת החג",
    "צאת יום כיפור",
)

HEBREW_MONTH_NAMES = (
    "",
    "ניסן",
    "אייר",
    "סיון",
    "תמוז",
    "אב",
    "אלול",
    "תשרי",
    "חשוון",
    "כסלו",
    "טבת",
    "שבט",
    "אדר",
    "אדר ב׳",
)

HEBREW_WEEKDAY_NAMES = (
    "שני",
    "שלישי",
    "רביעי",
    "חמישי",
    "שישי",
    "שבת",
    "ראשון",
)

RC_FULL_DAYS = frozenset({"day1", "day2"})
EXTRA_DIGEST_MAX_OFFSET = 4
SUKKOT_MUSAF_U_BAYOM_DAYS = (
    "השני",
    "השלישי",
    "הרביעי",
    "החמישי",
    "השישי",
)

# The six entries correspond to 15–20 Tishrei.
# Python weekday values are Monday=0, Tuesday=1, Thursday=3, Shabbat=5.
RINAT_YISRAEL_HOSHANOT_BY_FIRST_DAY_WEEKDAY = {
    0: (
        "למען אמתך",
        "אבן שתיה",
        "אערוך שועי",
        "אום אני חומה",
        "אל למושעות",
        "אום נצורה",
    ),
    1: (
        "למען אמתך",
        "אבן שתיה",
        "אערוך שועי",
        "אל למושעות",
        "אום נצורה",
        "אדון המושיע",
    ),
    3: (
        "למען אמתך",
        "אבן שתיה",
        "אום נצורה",
        "אערוך שועי",
        "אל למושעות",
        "אדון המושיע",
    ),
    5: (
        "אום נצורה",
        "למען אמתך",
        "אערוך שועי",
        "אבן שתיה",
        "אל למושעות",
        "אדון המושיע",
    ),
}

GITHUB_AUTH_HEADER = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
}


def resolve_gregorian(for_date=None):
    return for_date if for_date is not None else today_jerusalem()


def hebrew_triple(for_date=None):
    gregorian_date = resolve_gregorian(for_date)
    return hebrew.from_gregorian(
        gregorian_date.year,
        gregorian_date.month,
        gregorian_date.day,
    )


def is_hebrew_leap_year(year):
    leap_fn = getattr(hebrew, "leap", None)
    if leap_fn is not None:
        return bool(leap_fn(year))

    return ((7 * year + 1) % 19) < 7


def is_purim_day(year, month, day):
    if day != 14:
        return False

    if is_hebrew_leap_year(year):
        return month == 13

    return month == 12


def is_shushan_purim_day(year, month, day):
    if day != 15:
        return False

    if is_hebrew_leap_year(year):
        return month == 13

    return month == 12


def is_purim_katan_day(year, month, day):
    return (
        is_hebrew_leap_year(year)
        and month == 12
        and day in (14, 15)
    )


# ===== GITHUB =====
def get_file(path):
    url = f"https://api.github.com/repos/{REPO}/contents/{path}"
    response = requests.get(url, headers=GITHUB_AUTH_HEADER, timeout=20)

    if response.status_code != 200:
        return None, None

    data = response.json()
    content = base64.b64decode(data["content"]).decode("utf-8")
    return json.loads(content), data["sha"]


def save_file(path, content_obj, sha, message):
    url = f"https://api.github.com/repos/{REPO}/contents/{path}"

    content = json.dumps(
        content_obj,
        ensure_ascii=False,
        indent=2,
    )
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")

    payload = {
        "message": message,
        "content": encoded,
    }

    if sha:
        payload["sha"] = sha

    response = requests.put(
        url,
        headers=GITHUB_AUTH_HEADER,
        json=payload,
        timeout=20,
    )
    response.raise_for_status()


# ===== USERS =====
def get_users():
    data, sha = get_file(USERS_FILE)
    return (data or []), sha


def add_user(chat_id):
    users, sha = get_users()

    if chat_id in users:
        return False

    users.append(chat_id)
    save_file(USERS_FILE, users, sha, "add user")
    return True


# ===== LAST RUN =====
def get_last_run():
    return get_file(LAST_RUN_FILE)


def save_last_run(today_str, sha):
    save_file(
        LAST_RUN_FILE,
        {"date": today_str},
        sha,
        "update last run",
    )


# ===== SCHEDULING =====
def should_send_now():
    now = datetime.now(TZ)

    if not (2 <= now.hour <= 10):
        return False

    today_str = now.date().isoformat()
    last_run, sha = get_last_run()

    if last_run and last_run.get("date") == today_str:
        return False

    save_last_run(today_str, sha)
    return True


# ===== TELEGRAM =====
def send(chat_id, msg):
    if "⏰ תזכורת:" in msg:
        rich_html = f"<p>{msg.replace(chr(10), '<br>')}</p>"
        requests.post(
            f"{BASE_URL}/sendRichMessage",
            json={
                "chat_id": chat_id,
                "rich_message": {
                    "html": rich_html,
                    "is_rtl": True,
                },
            },
            timeout=20,
        )
        return

    response = requests.post(
        f"{BASE_URL}/sendMessage",
        data={
            "chat_id": chat_id,
            "text": msg,
            "parse_mode": "HTML",
        },
        timeout=20,
    )
    response.raise_for_status()


def broadcast(msg):
    users, _ = get_users()

    for user in users:
        send(user, msg)


# ===== FORMAT =====
def hebrew_number(number):
    units = [
        "",
        "א",
        "ב",
        "ג",
        "ד",
        "ה",
        "ו",
        "ז",
        "ח",
        "ט",
    ]
    tens = [
        "",
        "י",
        "כ",
        "ל",
        "מ",
        "נ",
        "ס",
        "ע",
        "פ",
        "צ",
    ]

    if number == 15:
        return "ט״ו"

    if number == 16:
        return "ט״ז"

    if number < 10:
        return units[number] + "׳"

    tens_letter = tens[number // 10]
    units_letter = units[number % 10]

    if units_letter:
        return f"{tens_letter}״{units_letter}"

    return f"{tens_letter}׳"


def hebrew_year(year):
    year %= 1000

    mapping = [
        (400, "ת"),
        (300, "ש"),
        (200, "ר"),
        (100, "ק"),
        (90, "צ"),
        (80, "פ"),
        (70, "ע"),
        (60, "ס"),
        (50, "נ"),
        (40, "מ"),
        (30, "ל"),
        (20, "כ"),
        (10, "י"),
        (9, "ט"),
        (8, "ח"),
        (7, "ז"),
        (6, "ו"),
        (5, "ה"),
        (4, "ד"),
        (3, "ג"),
        (2, "ב"),
        (1, "א"),
    ]

    result = ""

    for value, letter in mapping:
        while year >= value:
            result += letter
            year -= value

    return result[:-1] + "״" + result[-1]


# ===== DATE =====
def get_hebrew_date(for_date=None):
    for_date = resolve_gregorian(for_date)
    year, month, day = hebrew_triple(for_date)
    weekday = for_date.weekday()

    return (
        f"יום {HEBREW_WEEKDAY_NAMES[weekday]}, "
        f"{hebrew_number(day)} "
        f"ב{HEBREW_MONTH_NAMES[month]} "
        f"ה{hebrew_year(year)}"
    )


# ===== OMER =====
def calculate_omer(for_date=None):
    _, month, day = hebrew_triple(for_date)

    if month == 1 and day >= 16:
        return day - 15

    if month == 2:
        return 15 + day

    if month == 3 and day <= 5:
        return 44 + day

    return None


def say_tzidkatcha(for_date=None):
    for_date = resolve_gregorian(for_date)

    if not is_shabbat_date(for_date):
        return True

    _, mincha, _, _ = calculate_tachanun(for_date)
    return mincha != "לא"


def tzidkatcha_omit_reason(for_date=None):
    for_date = resolve_gregorian(for_date)

    if not is_shabbat_date(for_date):
        return None

    _, min_tachanun, _, mincha_skip_note = calculate_tachanun(for_date)

    if min_tachanun == "לא":
        return mincha_skip_note or "אין תחנון"

    return None


def hebrew_month_name(year, month):
    if month == 12 and is_hebrew_leap_year(year):
        return "אדר א׳"

    return HEBREW_MONTH_NAMES[month]


def is_shabbat_mevarchim(for_date=None):
    for_date = resolve_gregorian(for_date)

    if not is_shabbat_date(for_date):
        return False

    _, month, _ = hebrew_triple(for_date)

    if month == 6:
        return False

    for offset in range(1, 8):
        future = for_date + timedelta(days=offset)
        _, _, future_day = hebrew_triple(future)

        if future_day == 1:
            return True

    return False


def upcoming_rosh_chodesh_dates_after_shabbat(shabbat_date):
    rosh_chodesh_dates = []

    for offset in range(1, 8):
        target_date = shabbat_date + timedelta(days=offset)
        _, _, hebrew_day = hebrew_triple(target_date)

        if hebrew_day in (1, 30):
            rosh_chodesh_dates.append(target_date)

    return rosh_chodesh_dates


def shabbat_mevarchim_line(for_date=None):
    for_date = resolve_gregorian(for_date)

    if not is_shabbat_date(for_date):
        return None

    if not is_shabbat_mevarchim(for_date):
        return None

    rosh_chodesh_dates = upcoming_rosh_chodesh_dates_after_shabbat(
        for_date
    )

    if not rosh_chodesh_dates:
        return None

    month_date = next(
        (
            target_date
            for target_date in rosh_chodesh_dates
            if hebrew_triple(target_date)[2] == 1
        ),
        rosh_chodesh_dates[-1],
    )

    rosh_chodesh_year, rosh_chodesh_month, _ = hebrew_triple(
        month_date
    )
    month_name = hebrew_month_name(
        rosh_chodesh_year,
        rosh_chodesh_month,
    )

    weekdays = [
        HEBREW_WEEKDAY_NAMES[target_date.weekday()]
        for target_date in rosh_chodesh_dates
    ]

    if len(weekdays) == 1:
        days_text = f"ביום {weekdays[0]}"
    else:
        days_text = "בימים " + "-".join(weekdays)

    return f"ר״ח {month_name} יהיה {days_text}"


# ===== HOLIDAYS =====
def is_rosh_hashana(month, day):
    return month == 7 and day in (1, 2)


def is_erev_rosh_hashana(month, day):
    return month == 6 and day == 29


def is_yom_kippur(month, day):
    return month == 7 and day == 10


def is_erev_yom_kippur(month, day):
    return month == 7 and day == 9


def is_pesach_first_day(month, day):
    return month == 1 and day == 15


def is_pesach_seventh_day(month, day):
    return month == 1 and day == 21


def is_pesach_yom_tov(month, day):
    return (
        is_pesach_first_day(month, day)
        or is_pesach_seventh_day(month, day)
    )


def is_pesach_from_first_day(month, day):
    return month == 1 and 15 <= day <= 21


def is_pesach_hallel_dilug_range(month, day):
    return month == 1 and 16 <= day <= 20


def is_erev_pesach_seder(month, day):
    return month == 1 and day == 14


def is_pesach_sheni(month, day):
    return month == 2 and day == 14


def is_tu_bav(month, day):
    return month == 5 and day == 15


def is_tu_bishvat(month, day):
    return month == 11 and day == 15


def is_shavuot(month, day):
    return month == 3 and day == 6


def is_isru_chag(month, day):
    return (month, day) in (
        (1, 22),
        (3, 7),
        (7, 23),
    )


def is_sivan_shabbat_before_shavuot(month, day):
    return month == 3 and day in (4, 5)


def is_erev_shavuot(month, day):
    return month == 3 and day == 5


def is_sukkot_yom_tov(month, day):
    return month == 7 and day in (15, 22)


def is_sukkot_from_first_day(month, day):
    return month == 7 and 15 <= day <= 22


def is_erev_sukkot(month, day):
    return month == 7 and day == 14


def is_sukkot_days_16_to_20(month, day):
    return month == 7 and 16 <= day <= 20


def is_sukkot_hallel_through_shemini(month, day):
    return month == 7 and 15 <= day <= 22


def gregorian_from_hebrew(year, month, day):
    return date(
        *hebrew.to_gregorian(
            year,
            month,
            day,
        )
    )


def rinat_yisrael_hoshanot_names(for_date=None):
    """Return the daily Hoshanah for 15–20 Tishrei.

    The order follows the Rinat Yisrael Ashkenaz table and depends on the
    weekday on which the first day of Sukkot falls.
    """
    for_date = resolve_gregorian(for_date)
    year, month, day = hebrew_triple(for_date)

    if month != 7 or not 15 <= day <= 20:
        return ()

    sukkot_first_day = gregorian_from_hebrew(
        year,
        7,
        15,
    )

    order = RINAT_YISRAEL_HOSHANOT_BY_FIRST_DAY_WEEKDAY.get(
        sukkot_first_day.weekday()
    )

    if order is None:
        return ()

    return (order[day - 15],)


def rinat_yisrael_hoshanot_line(for_date=None):
    """Return the Telegram HTML line for the day's Hoshanot."""
    for_date = resolve_gregorian(for_date)
    _, month, day = hebrew_triple(for_date)

    if month == 7 and day == 21:
        return "הושענות <b>של הושענא רבא</b>"

    names = rinat_yisrael_hoshanot_names(for_date)

    if not names:
        return None

    names_text = " · ".join(
        html.escape(name)
        for name in names
    )

    return f"הושענות <b>{names_text}</b>"


def is_yom_haatzmaut(year, month, day):
    actual = gregorian_from_hebrew(
        year,
        2,
        5,
    )

    if actual.weekday() == 4:
        observed = actual - timedelta(days=1)
    elif actual.weekday() == 5:
        observed = actual - timedelta(days=2)
    elif actual.weekday() == 0:
        observed = actual + timedelta(days=1)
    else:
        observed = actual

    return hebrew_triple(observed) == (
        year,
        month,
        day,
    )


def is_yom_yerushalayim(month, day):
    return month == 2 and day == 28


def is_modern_israel_festivals(year, month, day):
    return (
        is_yom_haatzmaut(year, month, day)
        or is_yom_yerushalayim(month, day)
    )


def is_tzom_gedaliah_observed(for_date=None):
    for_date = resolve_gregorian(for_date)
    year, month, _ = hebrew_triple(for_date)

    if month != 7:
        return False

    fast = gregorian_from_hebrew(
        year,
        7,
        3,
    )

    if fast.weekday() == 5:
        fast += timedelta(days=1)

    return for_date == fast


def is_asara_btevet_observed(for_date=None):
    for_date = resolve_gregorian(for_date)
    year, _, _ = hebrew_triple(for_date)

    return for_date == gregorian_from_hebrew(
        year,
        10,
        10,
    )


def is_shiva_asar_btammuz_observed(for_date=None):
    for_date = resolve_gregorian(for_date)
    year, _, _ = hebrew_triple(for_date)

    fast = gregorian_from_hebrew(
        year,
        4,
        17,
    )

    if fast.weekday() == 5:
        fast += timedelta(days=1)

    return for_date == fast


def is_tisha_bav_observed(for_date=None):
    for_date = resolve_gregorian(for_date)
    year, _, _ = hebrew_triple(for_date)

    fast = gregorian_from_hebrew(
        year,
        5,
        9,
    )

    if fast.weekday() == 5:
        fast += timedelta(days=1)

    return for_date == fast


def is_taanit_esther_observed(for_date=None):
    for_date = resolve_gregorian(for_date)
    year, _, _ = hebrew_triple(for_date)

    adar = 13 if is_hebrew_leap_year(year) else 12

    fast = gregorian_from_hebrew(
        year,
        adar,
        13,
    )

    if fast.weekday() == 5:
        fast -= timedelta(days=2)

    return for_date == fast


def is_public_fast_observed(for_date=None):
    return (
        is_tzom_gedaliah_observed(for_date)
        or is_asara_btevet_observed(for_date)
        or is_shiva_asar_btammuz_observed(for_date)
        or is_tisha_bav_observed(for_date)
        or is_taanit_esther_observed(for_date)
    )


def is_yom_kippur_date(for_date=None):
    _, month, day = hebrew_triple(for_date)
    return is_yom_kippur(month, day)


def is_fast_with_published_times(for_date=None):
    return (
        is_public_fast_observed(for_date)
        or is_yom_kippur_date(for_date)
    )


def is_previous_evening_fast(for_date=None):
    return (
        is_tisha_bav_observed(for_date)
        or is_yom_kippur_date(for_date)
    )


def say_avinu_malkeinu_on_public_fast(for_date=None):
    return (
        is_public_fast_observed(for_date)
        and not is_tisha_bav_observed(for_date)
    )


def avinu_malkeinu_public_fast_mincha_omit_reason(
    for_date=None,
):
    """Return the reason Avinu Malkeinu is omitted at Mincha."""
    for_date = resolve_gregorian(for_date)

    if not say_avinu_malkeinu_on_public_fast(for_date):
        return None

    if for_date.weekday() == 4:
        return "ערב שבת"

    _, _, day = hebrew_triple(for_date)

    if is_taanit_esther_observed(for_date) and day == 13:
        return "ערב פורים"

    return None


def say_avinu_malkeinu_on_public_fast_mincha(
    for_date=None,
):
    return (
        say_avinu_malkeinu_on_public_fast(for_date)
        and avinu_malkeinu_public_fast_mincha_omit_reason(
            for_date
        ) is None
    )


def get_fast_name(for_date=None):
    if is_tzom_gedaliah_observed(for_date):
        return "צום גדליה"

    if is_asara_btevet_observed(for_date):
        return "עשרה בטבת"

    if is_taanit_esther_observed(for_date):
        return "תענית אסתר"

    if is_shiva_asar_btammuz_observed(for_date):
        return "שבעה עשר בתמוז"

    if is_tisha_bav_observed(for_date):
        return "תשעה באב"

    return None


def is_aseret_yemei_teshuva(month, day):
    return month == 7 and 1 <= day <= 10


def avinu_malkeinu_line(for_date=None):
    for_date = resolve_gregorian(for_date)
    _, month, day = hebrew_triple(for_date)

    if is_aseret_yemei_teshuva(month, day):
        return "אבינו מלכנו (עשי״ת)"

    if is_public_fast_observed(for_date):
        return "אבינו מלכנו (תענית ציבור)"

    return "אבינו מלכנו"


SELICHOT_DAY_NAMES = (
    "ראשון",
    "שני",
    "שלישי",
    "רביעי",
    "חמישי",
    "שישי",
    "שביעי",
)


def ashkenaz_selichot_start_date(rosh_hashana_year):
    rosh_hashana = gregorian_from_hebrew(
        rosh_hashana_year,
        7,
        1,
    )

    days_since_sunday = (
        rosh_hashana.weekday() - 6
    ) % 7

    start = rosh_hashana - timedelta(
        days=days_since_sunday
    )

    if (rosh_hashana - start).days < 4:
        start -= timedelta(days=7)

    return start


def selichot_day_number(start_date, target_date):
    number = 0
    current = start_date

    while current <= target_date:
        if current.weekday() != 5:
            number += 1
        current += timedelta(days=1)

    return number


def ashkenaz_selichot_line(for_date=None):
    evening_date = (
        resolve_gregorian(for_date)
        + timedelta(days=1)
    )

    year, month, day = hebrew_triple(evening_date)
    rosh_hashana_year = (
        year + 1
        if month <= 6
        else year
    )

    start = ashkenaz_selichot_start_date(
        rosh_hashana_year
    )

    erev_yom_kippur = gregorian_from_hebrew(
        rosh_hashana_year,
        7,
        9,
    )

    if not start <= evening_date <= erev_yom_kippur:
        return None

    if evening_date.weekday() == 5:
        return None

    if month == 7 and day in (1, 2):
        return None

    if is_tzom_gedaliah_observed(evening_date):
        return "סליחות של צום גדליה"

    if month == 6 and day == 29:
        return "סליחות ערב ראש השנה"

    if month == 7 and day == 9:
        return "סליחות ערב יו״כ"

    if month == 7 and 3 <= day <= 8:
        day_name = SELICHOT_DAY_NAMES[day - 3]
        return f"סליחות יום {day_name} דעשי״ת"

    if month == 6:
        day_number = selichot_day_number(
            start,
            evening_date,
        )

        if 1 <= day_number <= len(SELICHOT_DAY_NAMES):
            return (
                "סליחות יום "
                f"{SELICHOT_DAY_NAMES[day_number - 1]}"
            )

    return None


def is_moed_window_vihi_pesach_or_sukkot(month, day):
    return (
        is_pesach_hallel_dilug_range(month, day)
        or is_sukkot_days_16_to_20(month, day)
    )


def is_yomtov(month, day):
    return (
        is_rosh_hashana(month, day)
        or is_yom_kippur(month, day)
        or is_pesach_yom_tov(month, day)
        or is_shavuot(month, day)
        or is_sukkot_yom_tov(month, day)
    )


def is_shabbat():
    return datetime.now(TZ).weekday() == 5


def is_shabbat_date(for_date):
    return for_date.weekday() == 5


def is_yomtov_today():
    _, month, day = hebrew_triple(
        today_jerusalem()
    )
    return is_yomtov(month, day)


def day_is_shabbat_or_yomtov(gregorian_date):
    _, month, day = hebrew_triple(gregorian_date)

    return (
        is_shabbat_date(gregorian_date)
        or is_yomtov(month, day)
    )


def need_multi_day_digest(today):
    if today.weekday() == 4:
        return True

    return day_is_shabbat_or_yomtov(
        today + timedelta(days=1)
    )


def multi_day_digest_dates(today):
    if not need_multi_day_digest(today):
        return []

    output = []

    for offset in range(
        1,
        EXTRA_DIGEST_MAX_OFFSET + 1,
    ):
        target_date = today + timedelta(days=offset)

        if not day_is_shabbat_or_yomtov(target_date):
            break

        output.append(target_date)

    return output


def say_av_harachamim(for_date=None):
    for_date = resolve_gregorian(for_date)

    if not is_shabbat_date(for_date):
        return False

    year, month, day = hebrew_triple(for_date)

    if is_sivan_shabbat_before_shavuot(month, day):
        return True

    if month == 5 and day in (7, 8):
        return True

    shacharit, _, shacharit_note, _ = calculate_tachanun(
        for_date
    )

    if (
        shacharit == "לא"
        and shacharit_note != "חודש סיון"
    ):
        return False

    if is_shabbat_mevarchim(for_date):
        if month in (2, 3):
            return True

        return False

    if is_four_parshiyot(for_date):
        return False

    if is_chanukah(year, month, day):
        return False

    if is_purim_day(year, month, day):
        return False

    if month == 11 and day == 15:
        return False

    if month == 2 and day == 18:
        return False

    if is_isru_chag(month, day):
        return False

    tomorrow = for_date + timedelta(days=1)
    _, tomorrow_month, tomorrow_day = hebrew_triple(
        tomorrow
    )

    if is_yomtov(tomorrow_month, tomorrow_day):
        return False

    return True


def av_harachamim_omit_reason(for_date=None):
    for_date = resolve_gregorian(for_date)
    year, month, day = hebrew_triple(for_date)

    (
        shacharit_tachanun,
        _,
        shacharit_note,
        _,
    ) = calculate_tachanun(for_date)

    if (
        shacharit_tachanun == "לא"
        and shacharit_note != "חודש סיון"
    ):
        return shacharit_note or "אין תחנון"

    if (
        is_shabbat_mevarchim(for_date)
        and month not in (2, 3)
    ):
        return "שבת מברכים"

    if is_four_parshiyot(for_date):
        return "ארבע פרשיות"

    if is_chanukah(year, month, day):
        return "חנוכה"

    if is_purim_day(year, month, day):
        return "פורים"

    if month == 11 and day == 15:
        return "ט״ו בשבט"

    if month == 2 and day == 18:
        return "ל״ג בעומר"

    if is_isru_chag(month, day):
        return "איסרו חג"

    tomorrow = for_date + timedelta(days=1)
    _, tomorrow_month, tomorrow_day = hebrew_triple(
        tomorrow
    )

    if is_yomtov(tomorrow_month, tomorrow_day):
        return "ערב יו״ט"

    return "כללים"


def four_parshiyot_name(for_date=None):
    for_date = resolve_gregorian(for_date)

    if not is_shabbat_date(for_date):
        return None

    hebrew_date = dates.GregorianDate(
        for_date.year,
        for_date.month,
        for_date.day,
    ).to_heb()

    hebrew_year_value = hebrew_date.year
    is_leap = (
        (7 * hebrew_year_value + 1) % 19
    ) < 7

    adar_month = 13 if is_leap else 12

    def shabbat_on_or_before(target_date):
        weekday = target_date.weekday()

        if weekday == 7:
            return target_date

        return target_date - weekday

    rosh_chodesh_adar = dates.HebrewDate(
        hebrew_year_value,
        adar_month,
        1,
    )
    purim = dates.HebrewDate(
        hebrew_year_value,
        adar_month,
        14,
    )
    rosh_chodesh_nisan = dates.HebrewDate(
        hebrew_year_value,
        1,
        1,
    )

    shekalim = shabbat_on_or_before(
        rosh_chodesh_adar
    )

    zachor = (
        purim
        if purim.weekday() == 7
        else purim - purim.weekday()
    )

    hachodesh = shabbat_on_or_before(
        rosh_chodesh_nisan
    )
    parah = hachodesh - 7

    names_by_date = (
        (shekalim, "שבת שקלים"),
        (zachor, "שבת זכור"),
        (parah, "שבת פרה"),
        (hachodesh, "שבת החודש"),
    )

    return next(
        (
            name
            for special_date, name in names_by_date
            if hebrew_date == special_date
        ),
        None,
    )


def is_four_parshiyot(for_date=None):
    return four_parshiyot_name(for_date) is not None


# ===== Lamenatzeach (intro psalm) =====
def has_lamenatzeach(year, month, day):
    if day in (1, 30):
        return False

    if is_erev_yom_kippur(month, day):
        return False

    if is_erev_pesach_seder(month, day):
        return False

    if is_erev_shavuot(month, day):
        return False

    if is_erev_sukkot(month, day):
        return False

    if is_hoshana_raba(month, day):
        return False

    if is_chanukah(year, month, day):
        return False

    if is_purim_day(year, month, day):
        return False

    if is_purim_katan_day(year, month, day):
        return False

    if is_isru_chag(month, day):
        return False

    if is_pesach_hallel_dilug_range(month, day):
        return False

    if is_sukkot_days_16_to_20(month, day):
        return False

    if (
        is_pesach_seventh_day(month, day)
        or is_shavuot(month, day)
    ):
        return False

    if is_modern_israel_festivals(
        year,
        month,
        day,
    ):
        return False

    if month == 5 and day == 9:
        return False

    if month == 5 and day == 15:
        return False

    if month == 11 and day == 15:
        return False

    return True


def lamenatzeach_omit_reason(year, month, day):
    if day in (1, 30):
        return "ר״ח"

    if is_erev_yom_kippur(month, day):
        return "ערב יום כיפור"

    if is_erev_pesach_seder(month, day):
        return "ערב פסח"

    if is_erev_shavuot(month, day):
        return "ערב שבועות"

    if is_erev_sukkot(month, day):
        return "ערב סוכות"

    if is_hoshana_raba(month, day):
        return "הושענא רבה"

    if is_chanukah(year, month, day):
        return "חנוכה"

    if is_purim_day(year, month, day):
        return "פורים"

    if is_purim_katan_day(year, month, day):
        return "פורים קטן"

    if is_isru_chag(month, day):
        return "איסרו חג"

    if is_pesach_hallel_dilug_range(month, day):
        return "חוה״מ פסח"

    if is_sukkot_days_16_to_20(month, day):
        return "חוה״מ סוכות"

    if is_pesach_seventh_day(month, day):
        return "שביעי של פסח"

    if is_shavuot(month, day):
        return "שבועות"

    if is_modern_israel_festivals(
        year,
        month,
        day,
    ):
        if is_yom_haatzmaut(year, month, day):
            return "יום העצמאות"

        return "יום ירושלים"

    if month == 5 and day == 9:
        return "תשעה באב"

    if month == 5 and day == 15:
        return "ט״ו באב"

    if month == 11 and day == 15:
        return "ט״ו בשבט"

    return "כללים"


def say_ledavid_hashem(year, month, day):
    return (
        month == 6
        or (month == 7 and day <= 21)
    )


def say_ledavid_hashem_arvit(for_date=None):
    evening_date = (
        resolve_gregorian(for_date)
        + timedelta(days=1)
    )

    _, month, day = hebrew_triple(evening_date)

    return (
        month == 6
        or (month == 7 and day <= 20)
    )


# ===== TACHANUN =====
def tachanun_day_omission_reason(for_date=None):
    for_date = resolve_gregorian(for_date)
    year, month, day = hebrew_triple(for_date)

    if day in (1, 30):
        return "ר״ח"

    if is_yomtov(month, day):
        return (
            get_day_name(year, month, day)
            or "יום טוב"
        )

    if is_tisha_bav_observed(for_date):
        return "תשעה באב"

    if is_erev_rosh_hashana(month, day):
        return "ערב ראש השנה"

    if is_erev_yom_kippur(month, day):
        return "ערב יום כיפור"

    if is_purim_day(year, month, day):
        return "פורים"

    if is_shushan_purim_day(year, month, day):
        return "שושן פורים"

    if is_purim_katan_day(year, month, day):
        return "פורים קטן"

    if is_chanukah(year, month, day):
        return "חנוכה"

    if month == 1:
        return "חודש ניסן"

    if is_pesach_sheni(month, day):
        return "פסח שני"

    if month == 2 and day == 18:
        return "ל״ג בעומר"

    if month == 3 and day < 13:
        return "חודש סיון"

    if is_tu_bav(month, day):
        return "ט״ו באב"

    if is_tu_bishvat(month, day):
        return "ט״ו בשבט"

    if month == 7 and day >= 11:
        return "חודש תשרי"

    if is_isru_chag(month, day):
        return "איסרו חג"

    if is_modern_israel_festivals(
        year,
        month,
        day,
    ):
        if is_yom_haatzmaut(year, month, day):
            return "יום העצמאות"

        return "יום ירושלים"

    return None


def mincha_eve_omission_reason(
    for_date,
    tomorrow_year,
    tomorrow_month,
    tomorrow_day,
):
    for_date = resolve_gregorian(for_date)

    if (
        is_pesach_sheni(
            tomorrow_month,
            tomorrow_day,
        )
        or is_erev_rosh_hashana(
            tomorrow_month,
            tomorrow_day,
        )
        or is_erev_yom_kippur(
            tomorrow_month,
            tomorrow_day,
        )
    ):
        return None

    if (
        tomorrow_month == 2
        and tomorrow_day == 18
    ):
        return "ערב ל״ג בעומר"

    if is_yom_yerushalayim(
        tomorrow_month,
        tomorrow_day,
    ):
        return "ערב יום ירושלים"

    if is_purim_day(
        tomorrow_year,
        tomorrow_month,
        tomorrow_day,
    ):
        return "ערב פורים"

    if is_rosh_hashana(
        tomorrow_month,
        tomorrow_day,
    ):
        return "ערב ראש השנה"

    if is_yom_kippur(
        tomorrow_month,
        tomorrow_day,
    ):
        return "ערב יום כיפור"

    if (
        tomorrow_month == 7
        and tomorrow_day == 15
    ):
        return "ערב סוכות"

    if (
        tomorrow_month == 7
        and tomorrow_day == 16
    ):
        return "ערב יו״ט סוכות"

    if (
        tomorrow_month == 7
        and tomorrow_day == 22
    ):
        return "ערב שמיני עצרת"

    if is_pesach_first_day(
        tomorrow_month,
        tomorrow_day,
    ):
        return "ערב פסח"

    if is_shavuot(
        tomorrow_month,
        tomorrow_day,
    ):
        return "ערב שבועות"

    if is_yom_haatzmaut(
        tomorrow_year,
        tomorrow_month,
        tomorrow_day,
    ):
        return "ערב יום העצמאות"

    tomorrow = for_date + timedelta(days=1)

    if is_tisha_bav_observed(tomorrow):
        return "ערב תשעה באב"

    if is_shabbat_date(tomorrow):
        return "ערב שבת"

    tomorrow_reason = tachanun_day_omission_reason(
        tomorrow
    )

    if tomorrow_reason:
        return f"ערב {tomorrow_reason}"

    return None


def calculate_tachanun(for_date=None):
    for_date = resolve_gregorian(for_date)
    weekday = for_date.weekday()

    day_reason = tachanun_day_omission_reason(
        for_date
    )

    if day_reason:
        return (
            "לא",
            "לא",
            day_reason,
            day_reason,
        )

    tomorrow = for_date + timedelta(days=1)
    (
        tomorrow_year,
        tomorrow_month,
        tomorrow_day,
    ) = hebrew_triple(tomorrow)

    if get_rosh_chodesh_state(for_date) == "erev":
        shacharit = (
            "ארוך"
            if weekday in (0, 3)
            else "רגיל"
        )

        return (
            shacharit,
            "לא",
            None,
            "ערב ר״ח",
        )

    eve_reason = mincha_eve_omission_reason(
        for_date,
        tomorrow_year,
        tomorrow_month,
        tomorrow_day,
    )

    if eve_reason:
        shacharit = (
            "ארוך"
            if weekday in (0, 3)
            else "רגיל"
        )

        return (
            shacharit,
            "לא",
            None,
            eve_reason,
        )

    if weekday in (0, 3):
        return (
            "ארוך",
            "רגיל",
            None,
            None,
        )

    return (
        "רגיל",
        "רגיל",
        None,
        None,
    )


def say_vihi_noam(for_date=None):
    for_date = resolve_gregorian(for_date)

    if not is_shabbat_date(for_date):
        return True

    _, month, day = hebrew_triple(for_date)

    if is_yomtov(month, day):
        return False

    if month == 1 and 8 <= day <= 14:
        return False

    if is_tisha_bav_observed(
        for_date + timedelta(days=1)
    ):
        return False

    for offset in range(1, 7):
        future = for_date + timedelta(days=offset)
        _, future_month, future_day = hebrew_triple(
            future
        )

        if is_yomtov(
            future_month,
            future_day,
        ):
            return False

        if is_intermediate_moed_window_vihi(
            future_month,
            future_day,
        ):
            return False

    return True


def rosh_chodesh_header_name(year, month, day):
    if is_rosh_hashana(month, day):
        return None

    if day == 1:
        return (
            "ראש חודש "
            f"{hebrew_month_name(year, month)}"
        )

    if day == 30:
        tomorrow = (
            gregorian_from_hebrew(
                year,
                month,
                day,
            )
            + timedelta(days=1)
        )

        (
            tomorrow_year,
            tomorrow_month,
            tomorrow_day,
        ) = hebrew_triple(tomorrow)

        if tomorrow_day != 1:
            return None

        if is_rosh_hashana(
            tomorrow_month,
            tomorrow_day,
        ):
            return None

        return (
            "ראש חודש "
            f"{hebrew_month_name(tomorrow_year, tomorrow_month)}"
        )

    return None


def rosh_chodesh_yaale_month_suffix(
    year,
    month,
    day,
    for_date=None,
):
    for_date = resolve_gregorian(for_date)

    if day == 1:
        return (
            "ר״ח "
            f"{hebrew_month_name(year, month)}"
        )

    if day == 30:
        tomorrow = for_date + timedelta(days=1)
        (
            tomorrow_year,
            tomorrow_month,
            tomorrow_day,
        ) = hebrew_triple(tomorrow)

        if tomorrow_day == 1:
            return (
                "ר״ח "
                f"{hebrew_month_name(tomorrow_year, tomorrow_month)}"
            )

    return "ר״ח"


def yaale_erev_rc_suffix(for_date=None):
    for_date = resolve_gregorian(for_date)
    tomorrow = for_date + timedelta(days=1)

    (
        tomorrow_year,
        tomorrow_month,
        tomorrow_day,
    ) = hebrew_triple(tomorrow)

    if tomorrow_day == 1:
        return (
            "ר״ח "
            f"{hebrew_month_name(tomorrow_year, tomorrow_month)}"
        )

    if tomorrow_day == 30:
        next_day = tomorrow + timedelta(days=1)
        (
            next_year,
            next_month,
            next_hebrew_day,
        ) = hebrew_triple(next_day)

        if next_hebrew_day == 1:
            return (
                "ר״ח "
                f"{hebrew_month_name(next_year, next_month)}"
            )

    return "ר״ח"


def get_day_name(year, month, day):
    if is_pesach_sheni(month, day):
        return "פסח שני"

    if is_isru_chag(month, day):
        return "איסרו חג"

    if is_tu_bav(month, day):
        return "ט״ו באב"

    if is_tu_bishvat(month, day):
        return "ט״ו בשבט"

    if month == 2 and day == 18:
        return "ל״ג בעומר"

    if is_purim_day(year, month, day):
        return "פורים"

    rosh_chodesh_header = rosh_chodesh_header_name(
        year,
        month,
        day,
    )

    if rosh_chodesh_header:
        return rosh_chodesh_header

    if is_chanukah(year, month, day):
        return "חנוכה"

    if is_rosh_hashana(month, day):
        return "ראש השנה"

    if is_yom_kippur(month, day):
        return "יום כיפור"

    if month == 7 and day == 22:
        return "שמיני עצרת ושמחת תורה"

    if is_pesach_seventh_day(month, day):
        return "שביעי של פסח"

    if is_pesach_from_first_day(month, day):
        return "פסח"

    if is_shavuot(month, day):
        return "שבועות"

    if is_sukkot_from_first_day(month, day):
        return "סוכות"

    if is_yom_haatzmaut(year, month, day):
        return "יום העצמאות"

    if is_yom_yerushalayim(month, day):
        return "יום ירושלים"

    return None


def vihi_noam_omit_reason(for_date=None):
    for_date = resolve_gregorian(for_date)

    if not is_shabbat_date(for_date):
        return None

    year, month, day = hebrew_triple(for_date)

    if is_yomtov(month, day):
        return (
            get_day_name(year, month, day)
            or "יו״ט"
        )

    if month == 1 and 8 <= day <= 14:
        return "שבת הגדול"

    if is_tisha_bav_observed(
        for_date + timedelta(days=1)
    ):
        return "תשעה באב"

    for offset in range(1, 7):
        future = for_date + timedelta(days=offset)
        (
            future_year,
            future_month,
            future_day,
        ) = hebrew_triple(future)

        if is_yomtov(
            future_month,
            future_day,
        ):
            return (
                get_day_name(
                    future_year,
                    future_month,
                    future_day,
                )
                or "יו״ט"
            )

        if is_intermediate_moed_window_vihi(
            future_month,
            future_day,
        ):
            return "חוה״מ פסח/סוכות"

    return "כללים"


def is_chanukah(year, month, day):
    if month not in (9, 10):
        return False

    current_day = gregorian_from_hebrew(
        year,
        month,
        day,
    )

    first_day = gregorian_from_hebrew(
        year,
        9,
        25,
    )

    return (
        0
        <= (current_day - first_day).days
        <= 7
    )


def is_chanukah_date(for_date=None):
    for_date = resolve_gregorian(for_date)
    year, month, day = hebrew_triple(for_date)

    return is_chanukah(
        year,
        month,
        day,
    )


def needs_al_hanissim(year, month, day):
    return (
        is_chanukah(year, month, day)
        or is_purim_day(year, month, day)
    )


def is_chol_hamoed_pesach(month, day):
    return month == 1 and 16 <= day <= 20


def is_chol_hamoed_sukkot(month, day):
    return month == 7 and 16 <= day <= 21


def is_chol_hamoed(month, day):
    return (
        is_chol_hamoed_pesach(month, day)
        or is_chol_hamoed_sukkot(month, day)
    )


def chol_sukkot_musaf_u_bayom(month, day):
    if not is_sukkot_days_16_to_20(
        month,
        day,
    ):
        return None

    day_name = SUKKOT_MUSAF_U_BAYOM_DAYS[
        day - 16
    ]

    return f"וביום {day_name}"


def is_hoshana_raba(month, day):
    return month == 7 and day == 21


def is_intermediate_moed_window_vihi(
    month,
    day,
):
    return is_moed_window_vihi_pesach_or_sukkot(
        month,
        day,
    )


def day_has_chag_greeting(
    year,
    month,
    day,
    for_date=None,
):
    for_date = resolve_gregorian(for_date)

    if is_yomtov(month, day):
        return True

    return bool(
        get_day_name(
            year,
            month,
            day,
        )
    )


def get_greeting(
    year,
    month,
    day,
    for_date=None,
):
    for_date = resolve_gregorian(for_date)
    weekday = for_date.weekday()

    if is_rosh_hashana(month, day):
        greeting = "שנה טובה!"
    elif is_yom_kippur(month, day):
        greeting = "גמר חתימה טובה!"
    elif get_fast_name(for_date):
        greeting = "צום קל"
    elif (
        day in (1, 30)
        and not is_rosh_hashana(month, day)
    ):
        greeting = "חודש טוב!"
    elif get_day_name(year, month, day):
        greeting = "חג שמח!"
    else:
        greeting = ""

    if weekday == 5:
        yesterday = for_date - timedelta(days=1)
        (
            yesterday_year,
            yesterday_month,
            yesterday_day,
        ) = hebrew_triple(yesterday)

        if day_has_chag_greeting(
            yesterday_year,
            yesterday_month,
            yesterday_day,
            yesterday,
        ):
            return "שבת שלום!"

        if greeting:
            return f"שבת שלום ו{greeting}"

        return "שבת שלום!"

    return greeting


def get_rosh_chodesh_state(for_date=None):
    today = resolve_gregorian(for_date)
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)

    _, _, today_day = hebrew_triple(today)
    _, _, yesterday_day = hebrew_triple(yesterday)
    _, _, tomorrow_day = hebrew_triple(tomorrow)

    if today_day == 1:
        return "day1"

    if today_day == 30:
        return "day2"

    if tomorrow_day in (1, 30):
        return "erev"

    if yesterday_day == 30:
        return "day1"

    return None


def needs_yaale_veyavo(for_date=None):
    _, month, day = hebrew_triple(for_date)

    if day in (1, 30):
        return True

    if is_pesach_from_first_day(month, day):
        return True

    if is_shavuot(month, day):
        return True

    if is_sukkot_from_first_day(month, day):
        return True

    return False


def hallel_shacharit_line(for_date=None):
    for_date = resolve_gregorian(for_date)
    year, month, day = hebrew_triple(for_date)

    rosh_chodesh_state = get_rosh_chodesh_state(
        for_date
    )

    chanukah = is_chanukah(
        year,
        month,
        day,
    )

    if (
        chanukah
        and rosh_chodesh_state in RC_FULL_DAYS
        and not is_rosh_hashana(month, day)
    ):
        return "הלל שלם"

    if is_rosh_hashana(month, day):
        return "הלל שלם"

    if is_pesach_first_day(month, day):
        return "הלל שלם"

    if (
        is_pesach_seventh_day(month, day)
        or is_pesach_hallel_dilug_range(
            month,
            day,
        )
    ):
        return "הלל בדילוג"

    if is_shavuot(month, day):
        return "הלל שלם"

    if is_sukkot_hallel_through_shemini(
        month,
        day,
    ):
        return "הלל שלם"

    if chanukah:
        return "הלל שלם"

    if is_modern_israel_festivals(
        year,
        month,
        day,
    ):
        return "הלל שלם"

    if rosh_chodesh_state in RC_FULL_DAYS:
        return "הלל בדילוג"

    return None


def insert_hallel_shacharit(
    shacharit,
    for_date,
):
    hallel_line = hallel_shacharit_line(
        for_date
    )

    if (
        not hallel_line
        or hallel_line in shacharit
    ):
        return

    if "ברכי נפשי" in shacharit:
        shacharit.insert(
            shacharit.index("ברכי נפשי"),
            hallel_line,
        )
        return

    yaale_indices = [
        index
        for index, value in enumerate(shacharit)
        if (
            value == "יעלה ויבוא"
            or value.startswith("יעלה ויבוא (")
        )
    ]

    if yaale_indices:
        shacharit.insert(
            yaale_indices[-1] + 1,
            hallel_line,
        )
        return

    for prefix in (
        "אין למנצח",
        "אין אב הרחמים",
    ):
        for index, line in enumerate(shacharit):
            if (
                line == prefix
                or line.startswith(prefix + " (")
            ):
                shacharit.insert(
                    index,
                    hallel_line,
                )
                return

    shacharit.append(hallel_line)


def arvit_hallel_leil_pesach_lines(
    for_date=None,
):
    for_date = resolve_gregorian(for_date)
    _, month, day = hebrew_triple(for_date)

    if month != 1:
        return []

    if is_erev_pesach_seder(month, day):
        return ["הלל שלם (ליל פסח)"]

    return []


# ===== ZMANIM =====
_YI_PAIR_RE = re.compile(
    r"<span[^>]*\bclass\s*=\s*['\"]?(timesName)['\"]?[^>]*>"
    r"(.*?)</span>\s*"
    r"<span[^>]*\bclass\s*=\s*['\"]?(timesVal)['\"]?[^>]*>"
    r"(.*?)</span>",
    re.IGNORECASE | re.DOTALL,
)


def _normalize_hhmm(value):
    if not value or not isinstance(value, str):
        return None

    value = value.strip()

    if not value:
        return None

    parts = value.split(":")

    if len(parts) != 2:
        return None

    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return None

    return f"{hour:02d}:{minute:02d}"


def _shift_hhmm(hhmm, minutes_delta):
    hhmm = _normalize_hhmm(hhmm)

    if not hhmm:
        return None

    hour, minute = (
        int(part)
        for part in hhmm.split(":")
    )

    total = (
        hour * 60
        + minute
        + minutes_delta
    ) % (24 * 60)

    return (
        f"{total // 60:02d}:"
        f"{total % 60:02d}"
    )


def _yeshiva_hebrew_month(
    hebrew_year_value,
    hebrew_month_value,
):
    if hebrew_month_value >= 7:
        return hebrew_month_value - 6

    return hebrew_month_value + (
        7
        if hebrew.leap(hebrew_year_value)
        else 6
    )


def _yeshiva_strip_html_fragment(fragment):
    if not fragment:
        return ""

    text = re.sub(
        r"<[^>]+>",
        " ",
        fragment,
    )

    return html.unescape(text)


def _norm_zman_title(value):
    value = _yeshiva_strip_html_fragment(value)
    value = re.sub(
        r"\s+",
        " ",
        value,
    ).strip()

    value = (
        value
        .replace("״", '"')
        .replace("\u201c", '"')
        .replace("\u201d", '"')
    )

    return value.rstrip(":：").strip()


def _yeshiva_extract_time_pairs(
    html_fragment,
):
    rows = []

    for match in _YI_PAIR_RE.finditer(
        html_fragment or ""
    ):
        name = _norm_zman_title(
            match.group(2)
        )
        value = _norm_zman_title(
            match.group(4)
        )

        if name and value:
            rows.append({
                "name": name,
                "value": value,
            })

    return rows


_SHABAT_TIME_NAME_PREFIXES = (
    "כניסת שבת",
    "יציאת שבת",
    "יציאת השבת",
    "צאת שבת",
    "צאת השבת",
    "שעה עשירית",
)


def _is_shabat_time_name(name):
    normalized = _norm_zman_title(name)

    return any(
        normalized.startswith(prefix)
        for prefix in _SHABAT_TIME_NAME_PREFIXES
    )


def _yeshiva_html_to_payload(page_html):
    daily_times = []
    shabbat_times = []

    for row in _yeshiva_extract_time_pairs(
        page_html
    ):
        target = (
            shabbat_times
            if _is_shabat_time_name(row["name"])
            else daily_times
        )
        target.append(row)

    place_name = ""

    place_match = re.search(
        r"<div\s+class\s*=\s*['\"]?DayPlace['\"]?\s*>"
        r"([^<]*)</div>",
        page_html,
        re.IGNORECASE,
    )

    if place_match:
        place_name = _norm_zman_title(
            place_match.group(1)
        )

    return {
        "times": daily_times,
        "shabat": {
            "times": shabbat_times,
        },
        "place": (
            {"name": place_name}
            if place_name
            else {}
        ),
    }


def _yeshiva_parse_calaj_body(raw_text):
    text = raw_text.lstrip("\ufeff").strip()

    if text.startswith("{") or text.startswith("["):
        try:
            data = json.loads(text)

            if (
                isinstance(data, dict)
                and isinstance(data.get("day"), dict)
            ):
                inner = data["day"]

                if (
                    "times" in inner
                    or "shabat" in inner
                ):
                    return inner

            return (
                data
                if isinstance(data, dict)
                else {}
            )
        except json.JSONDecodeError:
            pass

    return _yeshiva_html_to_payload(text)


def _yeshiva_payload_has_times(payload):
    if not payload:
        return False

    if payload.get("times"):
        return True

    shabbat_times = (
        payload.get("shabat") or {}
    ).get("times")

    return bool(shabbat_times)


_yeshiva_day_cache = {}


def yeshiva_day_payload(for_date=None):
    for_date = resolve_gregorian(for_date)
    key = for_date.isoformat()

    if key in _yeshiva_day_cache:
        return _yeshiva_day_cache[key]

    place_id = YESHIVA_PLACE_ID

    (
        hebrew_year_value,
        hebrew_month_value,
        hebrew_day_value,
    ) = hebrew.from_gregorian(
        for_date.year,
        for_date.month,
        for_date.day,
    )

    yeshiva_month = _yeshiva_hebrew_month(
        hebrew_year_value,
        hebrew_month_value,
    )

    url = (
        "https://www.yeshiva.org.il/calendar/"
        "timesDayPrint.aspx"
        f"?hy={hebrew_year_value}"
        f"&hm={yeshiva_month}"
        f"&hd={hebrew_day_value}"
        f"&place={place_id}"
    )

    result = {}

    try:
        response = requests.get(
            url,
            timeout=20,
            headers=YESHIVA_HTTP_HEADERS,
        )
        response.raise_for_status()

        if response.text.strip():
            data = _yeshiva_parse_calaj_body(
                response.text
            )

            result = (
                data
                if isinstance(data, dict)
                else {}
            )
    except (
        requests.RequestException,
        ValueError,
        TypeError,
    ):
        pass

    if _yeshiva_payload_has_times(result):
        _yeshiva_day_cache[key] = result

    return result


def _yeshiva_time_by_names(
    payload,
    accepted_names,
):
    wanted = {
        _norm_zman_title(name)
        for name in accepted_names
    }

    for row in payload.get("times") or []:
        if _norm_zman_title(
            row.get("name", "")
        ) in wanted:
            time_value = _normalize_hhmm(
                row.get("value")
            )

            if time_value:
                return time_value

    return None


def _yeshiva_shabat_time_by_names(
    payload,
    accepted_names,
):
    wanted = {
        _norm_zman_title(name)
        for name in accepted_names
    }

    shabbat_data = payload.get("shabat") or {}

    for row in shabbat_data.get("times") or []:
        if _norm_zman_title(
            row.get("name", "")
        ) in wanted:
            time_value = _normalize_hhmm(
                row.get("value")
            )

            if time_value:
                return time_value

    return None


def _yeshiva_time_by_names_anywhere(
    payload,
    accepted_names,
):
    return (
        _yeshiva_time_by_names(
            payload,
            accepted_names,
        )
        or _yeshiva_shabat_time_by_names(
            payload,
            accepted_names,
        )
    )


def yeshiva_fast_zmanim_hhmm(
    for_date=None,
):
    fast_date = resolve_gregorian(for_date)

    source_date = (
        fast_date - timedelta(days=1)
        if is_previous_evening_fast(fast_date)
        else fast_date
    )

    payload = yeshiva_day_payload(source_date)
    is_yom_kippur_fast = is_yom_kippur_date(
        fast_date
    )

    start_names = (
        YI_NAMES_FAST_START
        + YI_NAMES_YOM_KIPPUR_START
        if is_yom_kippur_fast
        else YI_NAMES_FAST_START
    )

    end_names = (
        YI_NAMES_FAST_END
        + YI_NAMES_YOM_KIPPUR_END
        if is_yom_kippur_fast
        else YI_NAMES_FAST_END
    )

    return (
        _yeshiva_time_by_names_anywhere(
            payload,
            start_names,
        ),
        _yeshiva_time_by_names_anywhere(
            payload,
            end_names,
        ),
    )


def yeshiva_fast_zmanim_lines(
    for_date=None,
):
    start, end = yeshiva_fast_zmanim_hhmm(
        for_date
    )

    nbsp = "\u00a0"

    return (
        (
            f"תחילת הצום:{nbsp}{start}"
            if start
            else ""
        ),
        (
            f"צאת הצום:{nbsp}{end}"
            if end
            else ""
        ),
    )


def fast_zmanim_lines_for_message(
    for_date=None,
):
    for_date = resolve_gregorian(for_date)

    morning_start = ""
    evening_start = ""
    fast_end = ""

    if is_fast_with_published_times(for_date):
        current_start, fast_end = (
            yeshiva_fast_zmanim_lines(for_date)
        )

        if not is_previous_evening_fast(for_date):
            morning_start = current_start

    tomorrow = for_date + timedelta(days=1)

    if is_previous_evening_fast(tomorrow):
        evening_start, _ = (
            yeshiva_fast_zmanim_lines(tomorrow)
        )

    return (
        morning_start,
        evening_start,
        fast_end,
    )


def minor_fast_reminder_line(for_date=None):
    tomorrow = (
        resolve_gregorian(for_date)
        + timedelta(days=1)
    )

    if (
        not is_public_fast_observed(tomorrow)
        or is_previous_evening_fast(tomorrow)
    ):
        return ""

    start, _ = yeshiva_fast_zmanim_hhmm(
        tomorrow
    )

    fast_name = get_fast_name(tomorrow)

    if not start or not fast_name:
        return ""

    if fast_name.startswith("צום "):
        fast_name = fast_name[len("צום "):]

    return (
        "⏰ תזכורת: מחר צום "
        f"<b>{fast_name}</b> "
        f"יתחיל בשעה {start}"
    )


def yeshiva_zmanim_lines(for_date=None):
    payload = yeshiva_day_payload(for_date)
    nbsp = "\u00a0"

    def line(label, names):
        time_value = _yeshiva_time_by_names(
            payload,
            names,
        )

        if not time_value:
            return ""

        return f"{label}:{nbsp}{time_value}"

    return (
        line(
            "סוף זמן ק״ש",
            YI_NAMES_SOF_ZMAN_SHMA_GRA,
        ),
        line(
            "שקיעה",
            YI_NAMES_SHKIA,
        ),
        line(
            "צאת הכוכבים",
            YI_NAMES_TZEIT,
        ),
    )


def yeshiva_shabbat_candles_havdalah_hhmm(
    for_date=None,
):
    payload = yeshiva_day_payload(for_date)

    sunset = _yeshiva_time_by_names(
        payload,
        YI_NAMES_SHKIA,
    )

    return (
        _shift_hhmm(sunset, -18),
        _yeshiva_shabat_time_by_names(
            payload,
            YI_NAMES_TSET_SHABBAT,
        ),
    )


def get_shabbat_parsha_parts(for_date=None):
    for_date = resolve_gregorian(for_date)

    if not is_shabbat_date(for_date):
        return []

    hebrew_date = dates.GregorianDate(
        for_date.year,
        for_date.month,
        for_date.day,
    ).to_heb()

    parsha = parshios.getparsha_string(
        hebrew_date,
        hebrew=True,
        israel=True,
    )

    if not parsha:
        return []

    return [
        part.strip()
        for part in parsha.split(",")
        if part.strip()
    ]


def get_shabbat_parsha_line(for_date):
    parts = get_shabbat_parsha_parts(
        for_date
    )

    if not parts:
        return None

    if len(parts) >= 2:
        return (
            "פרשות השבוע: "
            f"<b>{'-'.join(parts)}</b>"
        )

    return f"פרשת השבוע: <b>{parts[0]}</b>"


def special_shabbat_header_names(
    for_date=None,
):
    for_date = resolve_gregorian(for_date)

    if not is_shabbat_date(for_date):
        return []

    year, month, day = hebrew_triple(for_date)
    parsha_parts = get_shabbat_parsha_parts(
        for_date
    )

    names = []

    if month == 7 and 3 <= day <= 9:
        names.append("שבת שובה")

    if "בראשית" in parsha_parts:
        names.append("שבת בראשית")

    if is_chanukah_date(for_date):
        names.append("שבת חנוכה")

    if "בשלח" in parsha_parts:
        names.append("שבת שירה")

    four_parshiyot = four_parshiyot_name(
        for_date
    )

    if four_parshiyot:
        names.append(four_parshiyot)

    if month == 1 and 8 <= day <= 14:
        names.append("שבת הגדול")

    tisha_bav = gregorian_from_hebrew(
        year,
        5,
        9,
    )

    days_before_tisha_bav = (
        tisha_bav - for_date
    ).days

    if 0 <= days_before_tisha_bav <= 6:
        names.append("שבת חזון")

    days_after_tisha_bav = (
        for_date - tisha_bav
    ).days

    if 1 <= days_after_tisha_bav <= 7:
        names.append("שבת נחמו")

    if (
        month == 1
        and 16 <= day <= 20
    ):
        names.append("שבת חוה״מ פסח")
    elif (
        month == 7
        and 16 <= day <= 20
    ):
        names.append("שבת חוה״מ סוכות")

    rosh_chodesh_name = (
        rosh_chodesh_header_name(
            year,
            month,
            day,
        )
    )

    if rosh_chodesh_name:
        names.append(
            f"שבת {rosh_chodesh_name}"
        )

    tomorrow = for_date + timedelta(days=1)

    (
        _,
        tomorrow_month,
        tomorrow_day,
    ) = hebrew_triple(tomorrow)

    if (
        tomorrow_day in (1, 30)
        and not is_rosh_hashana(
            tomorrow_month,
            tomorrow_day,
        )
        and not rosh_chodesh_name
        and not four_parshiyot
        and not is_chanukah_date(for_date)
    ):
        names.append("שבת מחר חודש")

    if is_shabbat_mevarchim(for_date):
        names.append("שבת מברכים")

    return names


def format_section(name, items):
    name = name.strip()

    if not items:
        return name

    return f"{name}:\n" + "\n".join(items)


def musaf_header_line(
    year,
    month,
    day,
    rosh_chodesh_state,
    is_shabbat,
):
    if is_rosh_hashana(month, day):
        return "מוסף של ראש השנה 🕍"

    if is_yom_kippur(month, day):
        return "מוסף של יום כיפור 🕍"

    is_rosh_chodesh = (
        rosh_chodesh_state in RC_FULL_DAYS
    )

    is_regalim = (
        is_pesach_from_first_day(month, day)
        or is_shavuot(month, day)
        or is_sukkot_from_first_day(month, day)
        or is_chol_hamoed(month, day)
        or is_hoshana_raba(month, day)
    )

    if is_rosh_chodesh and is_regalim:
        return "מוסף ראש חודש ושלוש רגלים 🕍"

    if is_rosh_chodesh and is_shabbat:
        return "מוסף שבת ראש חודש 🕍"

    if is_rosh_chodesh:
        return "מוסף ראש חודש 🕍"

    if is_regalim and is_shabbat:
        return "מוסף שבת ושלוש רגלים 🕍"

    if is_regalim:
        return "מוסף שלוש רגלים 🕍"

    if is_shabbat:
        return "מוסף שבת 🕍"

    if is_yomtov(month, day):
        return "מוסף יום טוב 🕍"

    return "מוסף 🕍"


def mincha_header_line(
    year,
    month,
    day,
    is_shabbat,
):
    if is_rosh_hashana(month, day):
        return "מנחה של ראש השנה 🌇"

    if is_yom_kippur(month, day):
        return "מנחה של יום כיפור 🌇"

    if is_erev_yom_kippur(month, day):
        return "מנחה של ערב יום כיפור 🌇"

    if (
        is_shabbat
        or not is_yomtov(month, day)
    ):
        return None

    if (
        is_pesach_yom_tov(month, day)
        or is_shavuot(month, day)
        or is_sukkot_yom_tov(month, day)
    ):
        return "מנחה שלוש רגלים 🌇"

    return None


def is_regalim_opening_hebrew_date(
    month,
    day,
):
    return (
        is_pesach_first_day(month, day)
        or is_shavuot(month, day)
        or (month == 7 and day == 15)
    )


def arvit_header_line(for_date=None):
    for_date = resolve_gregorian(for_date)
    evening = for_date + timedelta(days=1)
    _, month, day = hebrew_triple(evening)

    if is_rosh_hashana(month, day):
        return "ערבית של ראש השנה 🌙"

    if is_yom_kippur(month, day):
        return "ערבית של יום כיפור 🌙"

    if is_regalim_opening_hebrew_date(
        month,
        day,
    ):
        return "ערבית שלוש רגלים 🌙"

    return None


def short_kabbalat_shabbat_reason(
    for_date=None,
):
    for_date = resolve_gregorian(for_date)

    if for_date.weekday() != 4:
        return None

    year, month, day = hebrew_triple(
        for_date
    )

    if is_chol_hamoed(month, day):
        return yaale_vehavo_chag_reason(
            year,
            month,
            day,
        )

    if is_yomtov(month, day):
        return (
            get_day_name(year, month, day)
            or yaale_vehavo_chag_reason(
                year,
                month,
                day,
            )
            or "יום טוב"
        )

    tomorrow = for_date + timedelta(days=1)

    (
        tomorrow_year,
        tomorrow_month,
        tomorrow_day,
    ) = hebrew_triple(tomorrow)

    if (
        is_rosh_hashana(
            tomorrow_month,
            tomorrow_day,
        )
        or is_yom_kippur(
            tomorrow_month,
            tomorrow_day,
        )
    ):
        return None

    if is_yomtov(
        tomorrow_month,
        tomorrow_day,
    ):
        return (
            mincha_eve_omission_reason(
                for_date,
                tomorrow_year,
                tomorrow_month,
                tomorrow_day,
            )
            or "ערב יום טוב"
        )

    return None


def append_once(items, value):
    if value not in items:
        items.append(value)


def replace_no_changes_placeholder(items):
    if len(items) <= 1:
        return

    if items[0] == "אין שינויים (והוא רחום)":
        items[0] = "תחנון והוא רחום"
    elif items[0] == "אין שינויים":
        items.pop(0)


def format_ain_tachanun(note):
    if not note:
        raise ValueError(
            "A reason is required when Tachanun is omitted"
        )

    return f"אין תחנון ({note})"


def format_with_reason(phrase, note=None):
    if note:
        return f"{phrase} ({note})"

    return phrase


def yaale_vehavo_chag_reason(
    year,
    month,
    day,
):
    if is_pesach_from_first_day(month, day):
        if is_pesach_yom_tov(month, day):
            return "פסח"

        if is_chol_hamoed_pesach(
            month,
            day,
        ):
            return "חוה״מ פסח"

        return "חוה״מ פסח"

    if is_shavuot(month, day):
        return "שבועות"

    if is_hoshana_raba(month, day):
        return "הושענא רבה"

    if month == 7 and day == 22:
        return "שמיני עצרת"

    if is_sukkot_from_first_day(
        month,
        day,
    ):
        if is_sukkot_yom_tov(
            month,
            day,
        ):
            return "סוכות"

        if is_chol_hamoed_sukkot(
            month,
            day,
        ):
            return "חוה״מ סוכות"

        return "סוכות"

    return "חג"


def hebrew_date_range_has_shabbat(
    year,
    month,
    first_day,
    last_day,
):
    return any(
        gregorian_from_hebrew(
            year,
            month,
            day,
        ).weekday() == 5
        for day in range(
            first_day,
            last_day + 1,
        )
    )


def festival_shabbat_megillah_line(
    for_date=None,
):
    for_date = resolve_gregorian(for_date)
    year, month, day = hebrew_triple(
        for_date
    )

    if (
        month == 1
        and is_shabbat_date(for_date)
        and 15 <= day <= 21
    ):
        return "מגילת שיר השירים"

    if month == 7:
        if (
            is_shabbat_date(for_date)
            and 16 <= day <= 20
        ):
            return "מגילת קהלת"

        if (
            day == 15
            and not hebrew_date_range_has_shabbat(
                year,
                month,
                16,
                20,
            )
        ):
            return "מגילת קהלת"

    return None


def shacharit_megillah_line(for_date=None):
    for_date = resolve_gregorian(for_date)
    year, month, day = hebrew_triple(
        for_date
    )

    if is_purim_day(year, month, day):
        return "מגילת אסתר"

    if is_shavuot(month, day):
        return "מגילת רות"

    return festival_shabbat_megillah_line(
        for_date
    )


def arvit_megillah_line(for_date=None):
    evening_date = (
        resolve_gregorian(for_date)
        + timedelta(days=1)
    )

    year, month, day = hebrew_triple(
        evening_date
    )

    if is_purim_day(year, month, day):
        return "מגילת אסתר"

    if is_tisha_bav_observed(evening_date):
        return "מגילת איכה"

    return None


# ===== MESSAGE =====
def build_message(for_date=None):
    for_date = resolve_gregorian(for_date)

    header = get_hebrew_date(for_date)
    year, month, day = hebrew_triple(
        for_date
    )

    day_name = (
        get_day_name(year, month, day)
        or get_fast_name(for_date)
    )

    header_names = special_shabbat_header_names(
        for_date
    )

    if day_name and not any(
        name == day_name
        or name.endswith(f" {day_name}")
        for name in header_names
    ):
        header_names.append(day_name)

    if header_names:
        header += " - " + " - ".join(
            f"<b>{name}</b>"
            for name in header_names
        )

    (
        shacharit_tachanun,
        mincha_tachanun,
        shacharit_skip_note,
        mincha_skip_note,
    ) = calculate_tachanun(for_date)

    arvit_evening_date = (
        for_date + timedelta(days=1)
    )

    (
        arvit_year,
        arvit_month,
        arvit_day,
    ) = hebrew_triple(arvit_evening_date)

    shacharit = []

    rosh_chodesh_state = (
        get_rosh_chodesh_state(for_date)
    )

    is_shabbat = is_shabbat_date(for_date)
    is_rosh_hashana_day = is_rosh_hashana(
        month,
        day,
    )
    is_yom_kippur_day = is_yom_kippur(
        month,
        day,
    )
    is_yom_tov = is_yomtov(
        month,
        day,
    )
    is_tisha_bav = is_tisha_bav_observed(
        for_date
    )

    mincha_header = mincha_header_line(
        year,
        month,
        day,
        is_shabbat,
    )

    arvit_header = arvit_header_line(
        for_date
    )

    is_special_day = (
        is_shabbat
        or is_yom_tov
    )

    if (
        is_rosh_hashana_day
        or is_yom_kippur_day
    ):
        shacharit = []

    elif (
        not is_special_day
        and is_modern_israel_festivals(
            year,
            month,
            day,
        )
    ):
        if is_yom_yerushalayim(
            month,
            day,
        ):
            shacharit.append(
                format_ain_tachanun(
                    "יום ירושלים"
                )
            )
        else:
            shacharit.append(
                format_ain_tachanun(
                    "יום העצמאות"
                )
            )

    elif rosh_chodesh_state in RC_FULL_DAYS:
        shacharit.append(
            format_ain_tachanun(
                rosh_chodesh_yaale_month_suffix(
                    year,
                    month,
                    day,
                    for_date,
                )
            )
        )
        shacharit.append("יעלה ויבוא")
        shacharit.append("ברכי נפשי")

    elif needs_yaale_veyavo(for_date):
        if not is_yom_tov:
            shacharit.append(
                format_ain_tachanun(
                    yaale_vehavo_chag_reason(
                        year,
                        month,
                        day,
                    )
                )
            )

        shacharit.append("יעלה ויבוא")

    elif not is_special_day:
        if shacharit_tachanun == "לא":
            shacharit.append(
                format_ain_tachanun(
                    shacharit_skip_note
                )
            )

        elif shacharit_tachanun == "ארוך":
            shacharit.append(
                "אין שינויים (והוא רחום)"
            )

        else:
            if not hallel_shacharit_line(
                for_date
            ):
                shacharit.append(
                    "אין שינויים"
                )

    if is_erev_yom_kippur(month, day):
        shacharit.insert(
            0,
            format_with_reason(
                "אין מזמור לתודה",
                "ערב יום כיפור",
            ),
        )

    if (
        not is_rosh_hashana_day
        and not is_yom_kippur_day
    ):
        insert_hallel_shacharit(
            shacharit,
            for_date,
        )

    hoshanot_line = rinat_yisrael_hoshanot_line(
        for_date
    )

    if hoshanot_line:
        shacharit.append(hoshanot_line)

    if not is_special_day:
        if not has_lamenatzeach(
            year,
            month,
            day,
        ):
            shacharit.append(
                format_with_reason(
                    "אין למנצח",
                    lamenatzeach_omit_reason(
                        year,
                        month,
                        day,
                    ),
                )
            )

    if (
        is_shabbat
        and not is_rosh_hashana_day
        and not is_yom_kippur_day
    ):
        if not say_av_harachamim(for_date):
            shacharit.append(
                format_with_reason(
                    "אין אב הרחמים",
                    av_harachamim_omit_reason(
                        for_date
                    ),
                )
            )

    if needs_al_hanissim(
        year,
        month,
        day,
    ):
        shacharit.append("על הניסים")

    shacharit_megillah = (
        shacharit_megillah_line(for_date)
    )

    if shacharit_megillah:
        shacharit.append(
            shacharit_megillah
        )

    if (
        is_aseret_yemei_teshuva(
            month,
            day,
        )
        and not is_rosh_hashana_day
        and not is_yom_kippur_day
    ):
        append_once(
            shacharit,
            "שיר המעלות ממעמקים",
        )

        if not is_shabbat:
            yom_kippur_is_shabbat = (
                is_shabbat_date(
                    for_date
                    + timedelta(days=1)
                )
            )

            if (
                not is_erev_yom_kippur(
                    month,
                    day,
                )
                or yom_kippur_is_shabbat
            ):
                append_once(
                    shacharit,
                    avinu_malkeinu_line(
                        for_date
                    ),
                )
            else:
                append_once(
                    shacharit,
                    format_with_reason(
                        "אין אבינו מלכנו",
                        "ערב יום כיפור",
                    ),
                )

    if (
        say_avinu_malkeinu_on_public_fast(
            for_date
        )
        and not is_shabbat
    ):
        if for_date.weekday() == 4:
            append_once(
                shacharit,
                "תחנון",
            )

        append_once(
            shacharit,
            avinu_malkeinu_line(for_date),
        )

    if (
        say_ledavid_hashem(
            year,
            month,
            day,
        )
        and not is_rosh_hashana_day
        and not is_yom_kippur_day
    ):
        shacharit.append("לדוד ה׳")

    if is_erev_yom_kippur(month, day):
        yom_kippur_is_shabbat = (
            is_shabbat_date(
                for_date + timedelta(days=1)
            )
        )

        erev_yom_kippur_omissions = [
            "<b>ללא:</b>",
            "מזמור לתודה",
            "תחנון",
            "למנצח",
        ]

        if not yom_kippur_is_shabbat:
            erev_yom_kippur_omissions.append(
                "אבינו מלכנו"
            )

        omission_line_prefixes = (
            "אין מזמור לתודה",
            "אין תחנון",
            "אין למנצח",
            "אין אבינו מלכנו",
        )

        remaining_shacharit_lines = [
            line
            for line in shacharit
            if not line.startswith(
                omission_line_prefixes
            )
        ]

        shacharit = (
            remaining_shacharit_lines
            + erev_yom_kippur_omissions
        )

    if is_tisha_bav:
        shacharit = [
            "<b>ללא:</b>",
            "טלית ותפילין",
            "אבינו מלכנו",
            "תחנון",
            "למנצח",
            "שיר של יום",
            "אין כאלוקינו",
        ]

    if is_shabbat:
        shacharit = [
            line
            for line in shacharit
            if (
                line != "אין תחנון"
                and not line.startswith(
                    "אין תחנון ("
                )
            )
        ]

    replace_no_changes_placeholder(
        shacharit
    )

    if mincha_header:
        mincha = []

    elif (
        rosh_chodesh_state in RC_FULL_DAYS
        or needs_yaale_veyavo(for_date)
    ):
        if rosh_chodesh_state in RC_FULL_DAYS:
            yaale_note = (
                rosh_chodesh_yaale_month_suffix(
                    year,
                    month,
                    day,
                    for_date,
                )
            )
            no_tachanun_note = yaale_note
        else:
            no_tachanun_note = (
                yaale_vehavo_chag_reason(
                    year,
                    month,
                    day,
                )
            )
            yaale_note = no_tachanun_note

        mincha = [
            format_ain_tachanun(
                no_tachanun_note
            ),
            format_with_reason(
                "יעלה ויבוא",
                yaale_note,
            ),
        ]

    elif is_erev_rosh_hashana(
        month,
        day,
    ):
        mincha = [
            format_ain_tachanun(
                "ערב ראש השנה"
            )
        ]

    elif not is_special_day:
        mincha = (
            [
                format_ain_tachanun(
                    mincha_skip_note
                )
            ]
            if mincha_tachanun == "לא"
            else ["אין שינויים"]
        )

    else:
        mincha = ["אין שינויים"]

    if is_shabbat:
        mincha = [
            line
            for line in mincha
            if (
                line != "אין תחנון"
                and not line.startswith(
                    "אין תחנון ("
                )
            )
        ]

        if not mincha:
            mincha = ["אין שינויים"]

    if (
        is_shabbat
        and not mincha_header
    ):
        if not say_tzidkatcha(for_date):
            if mincha == ["אין שינויים"]:
                mincha = []

            mincha.append(
                format_with_reason(
                    "אין צדקתך",
                    tzidkatcha_omit_reason(
                        for_date
                    ),
                )
            )

    if not mincha_header:
        if needs_al_hanissim(
            year,
            month,
            day,
        ):
            mincha.append("על הניסים")

        if is_public_fast_observed(
            for_date
        ):
            mincha.append("עננו ה׳ עננו")

            if (
                say_avinu_malkeinu_on_public_fast_mincha(
                    for_date
                )
            ):
                append_once(
                    mincha,
                    avinu_malkeinu_line(
                        for_date
                    ),
                )
            else:
                omit_reason = (
                    avinu_malkeinu_public_fast_mincha_omit_reason(
                        for_date
                    )
                )

                if omit_reason:
                    append_once(
                        mincha,
                        format_with_reason(
                            "אין אבינו מלכנו",
                            omit_reason,
                        ),
                    )

        if (
            is_aseret_yemei_teshuva(
                month,
                day,
            )
            and not is_shabbat
            and not is_rosh_hashana(
                month,
                day,
            )
            and not is_erev_yom_kippur(
                month,
                day,
            )
            and not is_yom_kippur(
                month,
                day,
            )
        ):
            append_once(
                mincha,
                avinu_malkeinu_line(
                    for_date
                ),
            )

        if is_tisha_bav:
            mincha = [
                "טלית ותפילין",
                "שיר של יום",
                "אין כאלוקינו",
                "נחם",
                "עננו ה׳ עננו",
                format_ain_tachanun(
                    "תשעה באב"
                ),
                "אין אבינו מלכנו",
            ]

    replace_no_changes_placeholder(
        mincha
    )

    arvit = arvit_hallel_leil_pesach_lines(
        for_date
    )

    if not arvit_header:
        if is_shabbat:
            if not say_vihi_noam(for_date):
                arvit.append(
                    format_with_reason(
                        "אין ויהי נעם",
                        vihi_noam_omit_reason(
                            for_date
                        ),
                    )
                )

        if rosh_chodesh_state == "erev":
            arvit.append(
                format_with_reason(
                    "יעלה ויבוא",
                    yaale_erev_rc_suffix(
                        for_date
                    ),
                )
            )

        elif needs_yaale_veyavo(
            arvit_evening_date
        ):
            evening_rosh_chodesh_state = (
                get_rosh_chodesh_state(
                    arvit_evening_date
                )
            )

            if (
                evening_rosh_chodesh_state
                in RC_FULL_DAYS
            ):
                yaale_note = (
                    rosh_chodesh_yaale_month_suffix(
                        arvit_year,
                        arvit_month,
                        arvit_day,
                        arvit_evening_date,
                    )
                )
            else:
                yaale_note = (
                    yaale_vehavo_chag_reason(
                        arvit_year,
                        arvit_month,
                        arvit_day,
                    )
                )

            arvit.append(
                format_with_reason(
                    "יעלה ויבוא",
                    yaale_note,
                )
            )

        omer = calculate_omer(
            arvit_evening_date
        )

        if omer:
            arvit.append(
                f"ספירת העומר: היום {omer} לעומר"
            )

        if needs_al_hanissim(
            arvit_year,
            arvit_month,
            arvit_day,
        ):
            arvit.append("על הניסים")

        arvit_megillah = (
            arvit_megillah_line(for_date)
        )

        if arvit_megillah:
            arvit.append(arvit_megillah)

        if say_ledavid_hashem_arvit(
            for_date
        ):
            arvit.append("לדוד ה׳")

        if not arvit:
            arvit = ["אין שינויים"]

    musaf_extras = []

    has_musaf = (
        rosh_chodesh_state in RC_FULL_DAYS
        or is_shabbat
        or is_yomtov(month, day)
        or is_chol_hamoed(month, day)
        or is_hoshana_raba(month, day)
    )

    if (
        rosh_chodesh_state in RC_FULL_DAYS
        and is_shabbat
        and not is_rosh_hashana_day
    ):
        musaf_extras.append("אתה יצרת")

    u_bayom = chol_sukkot_musaf_u_bayom(
        month,
        day,
    )

    if u_bayom:
        musaf_extras.append(u_bayom)

    if is_hoshana_raba(month, day):
        musaf_extras.append("הושענא רבה")

    if (
        has_musaf
        and is_chanukah(
            year,
            month,
            day,
        )
    ):
        musaf_extras.append("על הניסים")

    if (
        not shacharit
        and not is_rosh_hashana_day
        and not is_yom_kippur_day
    ):
        shacharit = ["אין שינויים"]

    (
        end_shema,
        sunset,
        nightfall,
    ) = yeshiva_zmanim_lines(for_date)

    (
        fast_start_morning,
        fast_start_evening,
        fast_end,
    ) = fast_zmanim_lines_for_message(
        for_date
    )

    fast_reminder = minor_fast_reminder_line(
        for_date
    )

    (
        candles,
        havdalah,
    ) = yeshiva_shabbat_candles_havdalah_hhmm(
        for_date
    )

    nbsp = "\u00a0"

    msg = f"{header} 📅"

    if fast_start_morning:
        msg += f"\n\n{fast_start_morning}"

    parsha_line = get_shabbat_parsha_line(
        for_date
    )

    if parsha_line:
        msg += f"\n\n{parsha_line}"

    mevarchim_line = shabbat_mevarchim_line(
        for_date
    )

    if mevarchim_line:
        msg += f"\n\n{mevarchim_line}"

    if is_aseret_yemei_teshuva(
        month,
        day,
    ):
        msg += "\n\n<b>עשרת ימי תשובה</b>"

    shacharit_header = (
        "שחרית של ראש השנה 🌅"
        if is_rosh_hashana_day
        else "שחרית 🌅"
    )

    if is_yom_kippur_day:
        shacharit_header = (
            "שחרית של יום כיפור 🌅"
        )

    msg += (
        "\n\n"
        + format_section(
            shacharit_header,
            shacharit,
        )
    )

    if end_shema:
        msg += f"\n\n{end_shema}"

    if has_musaf:
        msg += (
            "\n\n"
            + musaf_header_line(
                year,
                month,
                day,
                rosh_chodesh_state,
                is_shabbat,
            )
        )

        if musaf_extras:
            msg += (
                "\n"
                + "\n".join(musaf_extras)
            )

    if mincha_header:
        msg += f"\n\n{mincha_header}"
    else:
        msg += (
            "\n\n"
            + format_section(
                "מנחה 🌇",
                mincha,
            )
        )

    mincha_zmanim = []

    if fast_start_evening:
        mincha_zmanim.append(
            fast_start_evening
        )

    if sunset:
        mincha_zmanim.append(sunset)

    if nightfall:
        mincha_zmanim.append(nightfall)

    if (
        for_date.weekday() == 4
        and candles
    ):
        mincha_zmanim.append(
            f"כניסת שבת:{nbsp}{candles}"
        )

    if is_shabbat and havdalah:
        mincha_zmanim.append(
            f"צאת השבת:{nbsp}{havdalah}"
        )

    if mincha_zmanim:
        msg += (
            "\n\n"
            + "\n".join(mincha_zmanim)
        )

    if is_yom_kippur_day:
        msg += "\n\nנעילה של יום כיפור 🔒"

    kabbalat_shabbat_reason = (
        short_kabbalat_shabbat_reason(
            for_date
        )
    )

    if kabbalat_shabbat_reason:
        msg += (
            "\n\n"
            + format_with_reason(
                "קבלת שבת מקוצרת",
                kabbalat_shabbat_reason,
            )
        )

    if arvit_header:
        msg += f"\n\n{arvit_header}"

        if arvit:
            msg += "\n" + "\n".join(arvit)
    else:
        msg += (
            "\n\n"
            + format_section(
                "ערבית 🌙",
                arvit,
            )
        )

    if fast_end:
        msg += f"\n\n{fast_end}"

    selichot = ashkenaz_selichot_line(
        for_date
    )

    if selichot:
        msg += f"\n\n{selichot}"

    greeting = get_greeting(
        year,
        month,
        day,
        for_date,
    )

    if greeting:
        msg += f"\n\n{greeting}"

    if fast_reminder:
        reminder_text = fast_reminder.removeprefix(
            "⏰ תזכורת: "
        )

        fast_name, start_time = (
            reminder_text.split(
                " יתחיל בשעה ",
                1,
            )
        )

        msg += (
            f"\n\n⏰ תזכורת:\n"
            f"{fast_name}\n"
            f"יתחיל בשעה "
            f"\u2066{start_time}\u2069"
            f"\n\u00a0"
        )

    return msg


# ===== UPDATES =====
def poll_updates():
    response = requests.get(
        f"{BASE_URL}/getUpdates",
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()

    for update in data.get("result", []):
        if "message" not in update:
            continue

        chat_id = update["message"]["chat"]["id"]
        text = update["message"].get(
            "text",
            "",
        )

        if text == "/start" and add_user(chat_id):
            send(
                chat_id,
                "נרשמת בהצלחה 🙌",
            )


def build_daily_digest(today=None):
    today = resolve_gregorian(today)
    msg = build_message(today)

    for digest_date in multi_day_digest_dates(
        today
    ):
        msg += (
            "\n\n"
            + build_message(digest_date)
        )

    return msg


def advance_after_digest_bundle(start_day):
    start_day = resolve_gregorian(start_day)
    last_day = start_day

    for digest_date in multi_day_digest_dates(
        start_day
    ):
        if digest_date > last_day:
            last_day = digest_date

    return last_day + timedelta(days=1)


# ===== MAIN =====
def main():
    poll_updates()

    force_count = parse_force_send_count()
    (
        preview_date_provided,
        preview_date,
    ) = parse_preview_date()

    if preview_date_provided:
        if preview_date is None:
            print(
                "PREVIEW_DATE must use "
                "YYYY-MM-DD format"
            )
            return

        cursor = preview_date

        for _ in range(force_count or 1):
            send(
                MY_CHAT_ID,
                build_message(cursor),
            )
            cursor += timedelta(days=1)

        return

    if force_count > 0:
        cursor = today_jerusalem()

        for _ in range(force_count):
            send(
                MY_CHAT_ID,
                build_daily_digest(cursor),
            )
            cursor = advance_after_digest_bundle(
                cursor
            )

        return

    manual = is_manual_dispatch_run()

    if not manual and not should_send_now():
        return

    if is_shabbat() or is_yomtov_today():
        return

    if manual:
        today_str = today_jerusalem().isoformat()
        _, sha = get_last_run()
        save_last_run(today_str, sha)

    broadcast(build_daily_digest())


if __name__ == "__main__":
    main()