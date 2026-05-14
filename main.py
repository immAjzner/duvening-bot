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


def is_manual_dispatch_run():
    """True when GitHub Actions workflow_dispatch sets MANUAL_RUN=1 (see daily.yml).

    Scheduled (cron) runs do not set it; they keep the morning window and last_run behavior.
    """
    v = (os.environ.get("MANUAL_RUN") or "").strip().lower()
    if v in ("1", "true", "yes"):
        return True
    # Convenience: honor GITHUB_EVENT_NAME when set manually (e.g. local testing).
    return (os.environ.get("GITHUB_EVENT_NAME") or "").strip() == "workflow_dispatch"


# Day zmanim and Shabbat times from yeshiva.org — place id (173 = Netanya).
YESHIVA_PLACE_ID = os.environ.get("YESHIVA_PLACE_ID", "173")

# Browser-like headers — without these, calaj sometimes returns HTML/403 and JSON will not parse.
YESHIVA_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*;q=0.01",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.yeshiva.org.il/calendar/timesday",
}

# Labels as they appear in JSON and HTML (different abbreviations).
YI_NAMES_SOF_ZMAN_SHMA_GRA = (
    'סוף זמן קריאת שמע לגר"א',
    'סוף זמן ק"ש לגר"א',
)
YI_NAMES_SHKIA = ("שקיעה",)
YI_NAMES_TZEIT = ("צאת הכוכבים",)
YI_NAMES_TSET_SHABBAT = ("צאת שבת", "יציאת שבת")

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
EXTRA_DIGEST_MAX_OFFSET = 4  # today + up to 4 days ahead in one message
SUKKOT_MUSAF_U_BAYOM_DAYS = ("השני", "השלישי", "הרביעי", "החמישי", "השישי")

GITHUB_AUTH_HEADER = {"Authorization": f"Bearer {GITHUB_TOKEN}"}


def resolve_gregorian(for_date=None):
    return for_date if for_date is not None else today_jerusalem()


def hebrew_triple(for_date=None):
    g = resolve_gregorian(for_date)
    return hebrew.from_gregorian(g.year, g.month, g.day)


def is_hebrew_leap_year(y):
    leap_fn = getattr(hebrew, "leap", None)
    if leap_fn is not None:
        return bool(leap_fn(y))
    return ((7 * y + 1) % 19) < 7


def is_purim_day(y, m, d):
    if d != 14:
        return False
    if is_hebrew_leap_year(y):
        return m == 13
    return m == 12


# ===== GITHUB =====
def get_file(path):
    url = f"https://api.github.com/repos/{REPO}/contents/{path}"
    res = requests.get(url, headers=GITHUB_AUTH_HEADER)

    if res.status_code != 200:
        return None, None

    data = res.json()
    content = base64.b64decode(data["content"]).decode("utf-8")
    return json.loads(content), data["sha"]

def save_file(path, content_obj, sha, message):
    url = f"https://api.github.com/repos/{REPO}/contents/{path}"

    content = json.dumps(content_obj, ensure_ascii=False, indent=2)
    encoded = base64.b64encode(content.encode()).decode()

    data = {
        "message": message,
        "content": encoded,
        "sha": sha
    }

    requests.put(url, headers=GITHUB_AUTH_HEADER, json=data)

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
    save_file(LAST_RUN_FILE, {"date": today_str}, sha, "update last run")

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
    requests.post(f"{BASE_URL}/sendMessage", data={
        "chat_id": chat_id,
        "text": msg,
        "parse_mode": "HTML"
    })

def broadcast(msg):
    users, _ = get_users()
    for u in users:
        send(u, msg)

# ===== FORMAT =====
def hebrew_number(n):
    units = ["", "א","ב","ג","ד","ה","ו","ז","ח","ט"]
    tens = ["", "י","כ","ל","מ","נ","ס","ע","פ","צ"]

    if n == 15: return "ט״ו"
    if n == 16: return "ט״ז"

    if n < 10:
        return units[n] + "׳"

    t = tens[n // 10]
    u = units[n % 10]
    return f"{t}״{u}" if u else f"{t}׳"

def hebrew_year(y):
    y %= 1000
    mapping = [
        (400,"ת"),(300,"ש"),(200,"ר"),(100,"ק"),
        (90,"צ"),(80,"פ"),(70,"ע"),(60,"ס"),(50,"נ"),
        (40,"מ"),(30,"ל"),(20,"כ"),(10,"י"),
        (9,"ט"),(8,"ח"),(7,"ז"),(6,"ו"),(5,"ה"),
        (4,"ד"),(3,"ג"),(2,"ב"),(1,"א")
    ]
    result = ""
    for v, l in mapping:
        while y >= v:
            result += l
            y -= v
    return result[:-1] + "״" + result[-1]

# ===== DATE =====
def get_hebrew_date(for_date=None):
    for_date = resolve_gregorian(for_date)
    y, m, d = hebrew_triple(for_date)
    wd = for_date.weekday()
    return (
        f"יום {HEBREW_WEEKDAY_NAMES[wd]}, {hebrew_number(d)} "
        f"ב{HEBREW_MONTH_NAMES[m]} ה{hebrew_year(y)}"
    )

# ===== OMER =====
def calculate_omer(for_date=None):
    _, m, d = hebrew_triple(for_date)

    if m == 1 and d >= 16: return d - 15
    if m == 2: return 15 + d
    if m == 3 and d <= 5: return 44 + d

    return None

def say_tzidkatcha(for_date=None):
    for_date = resolve_gregorian(for_date)
    if not is_shabbat_date(for_date):
        return True

    sh, _, _, _ = calculate_tachanun(for_date)

    return sh != "לא"


def tzidkatcha_omit_reason(for_date=None):
    for_date = resolve_gregorian(for_date)
    if not is_shabbat_date(for_date):
        return None
    sh_tach, _, sh_skip_note, _ = calculate_tachanun(for_date)
    if sh_tach == "לא":
        return sh_skip_note or "אין תחנון"
    return None


def hebrew_month_name(y, m):
    if m == 12 and is_hebrew_leap_year(y):
        return "אדר א׳"
    return HEBREW_MONTH_NAMES[m]


def is_shabbat_mevarchim(for_date=None):
    for_date = resolve_gregorian(for_date)

    if not is_shabbat_date(for_date):
        return False

    y, m, _ = hebrew_triple(for_date)
    if m == 6:
        return False

    for i in range(1, 8):
        future = for_date + timedelta(days=i)
        _, _, d = hebrew_triple(future)

        if d == 1:
            return True

    return False


def upcoming_rosh_chodesh_dates_after_shabbat(shabbat_date):
    rc_dates = []
    for i in range(1, 8):
        dte = shabbat_date + timedelta(days=i)
        _, _, hd = hebrew_triple(dte)
        if hd in (1, 30):
            rc_dates.append(dte)
    return rc_dates


def shabbat_mevarchim_line(for_date=None):
    for_date = resolve_gregorian(for_date)
    if not is_shabbat_date(for_date):
        return None

    if not is_shabbat_mevarchim(for_date):
        return None

    rc_dates = upcoming_rosh_chodesh_dates_after_shabbat(for_date)
    if not rc_dates:
        return None

    month_date = next(
        (dte for dte in rc_dates if hebrew_triple(dte)[2] == 1),
        rc_dates[-1],
    )
    rc_year, rc_month, _ = hebrew_triple(month_date)
    month_name = hebrew_month_name(rc_year, rc_month)

    weekdays = [HEBREW_WEEKDAY_NAMES[dte.weekday()] for dte in rc_dates]
    if len(weekdays) == 1:
        days_text = f"ביום {weekdays[0]}"
    else:
        days_text = "בימים " + "-".join(weekdays)

    return f"שבת מברכים - ר״ח {month_name} יהיה {days_text}"

# ===== HOLIDAYS =====
def is_rosh_hashana(m, d):
    return m == 7 and d in (1, 2)


def is_yom_kippur(m, d):
    return m == 7 and d == 10


def is_erev_yom_kippur(m, d):
    return m == 7 and d == 9


def is_pesach_first_day(m, d):
    return m == 1 and d == 15


def is_pesach_seventh_day(m, d):
    return m == 1 and d == 21


def is_pesach_yom_tov(m, d):
    return is_pesach_first_day(m, d) or is_pesach_seventh_day(m, d)


def is_pesach_from_first_day(m, d):
    return m == 1 and d >= 15


def is_pesach_hallel_dilug_range(m, d):
    return m == 1 and 16 <= d <= 20


def is_erev_pesach_seder(m, d):
    return m == 1 and d == 14


def is_pesach_sheni(m, d):
    return m == 2 and d == 14


def is_tu_bav(m, d):
    return m == 5 and d == 15


def is_tu_bishvat(m, d):
    return m == 11 and d == 15


def is_shavuot(m, d):
    return m == 3 and d == 6


def is_isru_chag(m, d):
    return (m, d) in ((1, 22), (3, 7), (7, 23))


def is_sivan_shabbat_before_shavuot(m, d):
    return m == 3 and d in (4, 5)


def is_erev_shavuot(m, d):
    return m == 3 and d == 5


def is_sukkot_yom_tov(m, d):
    return m == 7 and d in (15, 16, 22)


def is_sukkot_from_first_day(m, d):
    return m == 7 and d >= 15


def is_erev_sukkot(m, d):
    return m == 7 and d == 14


def is_sukkot_days_16_to_20(m, d):
    return m == 7 and 16 <= d <= 20


def is_sukkot_hallel_through_shemini(m, d):
    return m == 7 and 15 <= d <= 22


def gregorian_from_hebrew(y, m, d):
    return date(*hebrew.to_gregorian(y, m, d))


def is_yom_haatzmaut(y, m, d):
    actual = gregorian_from_hebrew(y, 2, 5)
    if actual.weekday() == 4:  # 5 Iyar on Friday -> observed Thursday
        observed = actual - timedelta(days=1)
    elif actual.weekday() == 5:  # 5 Iyar on Shabbat -> observed Thursday
        observed = actual - timedelta(days=2)
    elif actual.weekday() == 0:  # 5 Iyar on Monday -> deferred to Tuesday
        observed = actual + timedelta(days=1)
    else:
        observed = actual
    return hebrew_triple(observed) == (y, m, d)


def is_yom_yerushalayim(m, d):
    return m == 2 and d == 28


def is_modern_israel_festivals(y, m, d):
    return is_yom_haatzmaut(y, m, d) or is_yom_yerushalayim(m, d)


def is_tzom_gedaliah_observed(for_date=None):
    for_date = resolve_gregorian(for_date)
    y, m, d = hebrew_triple(for_date)
    if m != 7:
        return False
    fast = gregorian_from_hebrew(y, 7, 3)
    if fast.weekday() == 5:
        fast += timedelta(days=1)
    return for_date == fast


def is_asara_btevet_observed(for_date=None):
    for_date = resolve_gregorian(for_date)
    y, _, _ = hebrew_triple(for_date)
    return for_date == gregorian_from_hebrew(y, 10, 10)


def is_shiva_asar_btammuz_observed(for_date=None):
    for_date = resolve_gregorian(for_date)
    y, _, _ = hebrew_triple(for_date)
    fast = gregorian_from_hebrew(y, 4, 17)
    if fast.weekday() == 5:
        fast += timedelta(days=1)
    return for_date == fast


def is_tisha_bav_observed(for_date=None):
    for_date = resolve_gregorian(for_date)
    y, _, _ = hebrew_triple(for_date)
    fast = gregorian_from_hebrew(y, 5, 9)
    if fast.weekday() == 5:
        fast += timedelta(days=1)
    return for_date == fast


def is_taanit_esther_observed(for_date=None):
    for_date = resolve_gregorian(for_date)
    y, _, _ = hebrew_triple(for_date)
    adar = 13 if is_hebrew_leap_year(y) else 12
    fast = gregorian_from_hebrew(y, adar, 13)
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


def is_aseret_yemei_teshuva(m, d):
    return m == 7 and 1 <= d <= 10


SELICHOT_WEEKDAY_LABELS = {
    6: "א׳",
    0: "ב׳",
    1: "ג׳",
    2: "ד׳",
    3: "ה׳",
    4: "ו׳",
}


def ashkenaz_selichot_start_date(rh_year):
    rh = gregorian_from_hebrew(rh_year, 7, 1)
    days_since_sunday = (rh.weekday() - 6) % 7
    start = rh - timedelta(days=days_since_sunday)
    if (rh - start).days < 4:
        start -= timedelta(days=7)
    return start


def ashkenaz_selichot_line(for_date=None):
    evening_date = resolve_gregorian(for_date) + timedelta(days=1)
    y, m, d = hebrew_triple(evening_date)
    rh_year = y + 1 if m <= 6 else y
    start = ashkenaz_selichot_start_date(rh_year)
    erev_yk = gregorian_from_hebrew(rh_year, 7, 9)

    if not (start <= evening_date <= erev_yk):
        return None
    if evening_date.weekday() == 5:
        return None
    if m == 7 and d in (1, 2):
        return None
    if m == 6 and d == 29:
        return "סליחות ערב ראש השנה"
    if m == 7 and d == 9:
        return "סליחות ערב יו״כ"

    weekday_label = SELICHOT_WEEKDAY_LABELS.get(evening_date.weekday())
    if not weekday_label:
        return None
    return f"סליחות יום {weekday_label}"


def is_moed_window_vihi_pesach_or_sukkot(m, d):
    return is_pesach_hallel_dilug_range(m, d) or is_sukkot_days_16_to_20(m, d)


def is_yomtov(m, d):
    return (
        is_rosh_hashana(m, d)
        or is_yom_kippur(m, d)
        or is_pesach_yom_tov(m, d)
        or is_shavuot(m, d)
        or is_sukkot_yom_tov(m, d)
    )

def is_shabbat():
    return datetime.now(TZ).weekday() == 5

def is_shabbat_date(for_date):
    return for_date.weekday() == 5

def is_yomtov_today():
    _, m, d = hebrew_triple(today_jerusalem())
    return is_yomtov(m, d)


def day_is_shabbat_or_yomtov(gd):
    _, m, d = hebrew_triple(gd)
    return is_shabbat_date(gd) or is_yomtov(m, d)


def need_multi_day_digest(today):
    if datetime.now(TZ).weekday() == 4:
        return True
    return day_is_shabbat_or_yomtov(today + timedelta(days=1))


def multi_day_digest_dates(today):
    if not need_multi_day_digest(today):
        return []
    out = []
    for k in range(1, EXTRA_DIGEST_MAX_OFFSET + 1):
        d = today + timedelta(days=k)
        if day_is_shabbat_or_yomtov(d):
            out.append(d)
    return out


def say_av_harachamim(for_date=None):
    for_date = resolve_gregorian(for_date)

    if not is_shabbat_date(for_date):
        return False

    y, m, d = hebrew_triple(for_date)

    # ========= Exceptions — still say =========

    # Shabbat before Shavuot
    if is_sivan_shabbat_before_shavuot(m, d):
        return True

    # Shabbat before Tisha B'Av
    if m == 5 and d in [7, 8]:
        return True

    # ========= Base rule =========
    # If no tachanun on a weekday — do not say Av Harachamim

    sh, _, _, _ = calculate_tachanun(for_date)
    if sh == "לא":
        return False

    # Shabbat Mevarchim
    if is_shabbat_mevarchim(for_date):
        # Exceptions — still say
        if m in [2, 3]:  # Iyar, Sivan
            return True
        return False

    # Four parshiyot
    if is_four_parshiyot(for_date):
        return False

    # ========= Special days =========

    if is_chanukah(m, d):
        return False

    if is_purim_day(y, m, d):
        return False

    # Tu BiShvat
    if m == 11 and d == 15:
        return False

    # Lag BaOmer
    if m == 2 and d == 18:
        return False

    # Erev chag (Pesach/Shavuos/R"H)
    tomorrow = for_date + timedelta(days=1)
    _, tomorrow_m, tomorrow_d = hebrew_triple(tomorrow)
    if is_yomtov(tomorrow_m, tomorrow_d):
        return False

    # ========= Default =========
    return True


def av_harachamim_omit_reason(for_date=None):
    """Shown only when Av Harachamim is omitted on Shabbat — check order matches say_av_harachamim."""
    for_date = resolve_gregorian(for_date)
    y, m, d = hebrew_triple(for_date)
    sh_tach, _, sh_skip_note, _ = calculate_tachanun(for_date)
    if sh_tach == "לא":
        return sh_skip_note or "אין תחנון"
    if is_shabbat_mevarchim(for_date) and m not in [2, 3]:
        return "שבת מברכים"
    if is_four_parshiyot(for_date):
        return "ארבע פרשיות"
    if is_chanukah(m, d):
        return "חנוכה"
    if is_purim_day(y, m, d):
        return "פורים"
    if m == 11 and d == 15:
        return "ט״ו בשבט"
    if m == 2 and d == 18:
        return "ל״ג בעומר"
    tomorrow = for_date + timedelta(days=1)
    _, tm, td = hebrew_triple(tomorrow)
    if is_yomtov(tm, td):
        return "ערב יו״ט"
    return "כללים"


def is_four_parshiyot(for_date=None):
    for_date = resolve_gregorian(for_date)

    if not is_shabbat_date(for_date):
        return False

    hdate = dates.GregorianDate(for_date.year, for_date.month, for_date.day).to_heb()
    hy = hdate.year

    # In a leap year the four parshiyot are read in Adar II (month 13);
    # in a regular year, in Adar (month 12).
    is_leap = ((7 * hy + 1) % 19) < 7
    adar_month = 13 if is_leap else 12

    # pyluach weekday: 1 = Sunday ... 7 = Shabbat
    def shabbat_on_or_before(d):
        wd = d.weekday()
        return d if wd == 7 else d - wd

    rc_adar = dates.HebrewDate(hy, adar_month, 1)
    purim = dates.HebrewDate(hy, adar_month, 14)
    rc_nisan = dates.HebrewDate(hy, 1, 1)

    shekalim = shabbat_on_or_before(rc_adar)
    # Zachor: Shabbat preceding Purim (or Purim itself if it falls on Shabbat)
    zachor = purim if purim.weekday() == 7 else purim - purim.weekday()
    hachodesh = shabbat_on_or_before(rc_nisan)
    parah = hachodesh - 7

    return hdate in (shekalim, zachor, parah, hachodesh)

# ===== Lamenatzeach (intro psalm) =====
def has_lamenatzeach(y, m, d):
    if d == 1 or d == 30:
        return False

    if is_erev_yom_kippur(m, d):
        return False

    if is_erev_pesach_seder(m, d):
        return False
    if is_erev_shavuot(m, d):
        return False
    if is_erev_sukkot(m, d):
        return False
    if is_hoshana_raba(m, d):
        return False

    if is_chanukah(m, d):
        return False

    if is_purim_day(y, m, d):
        return False

    if is_pesach_hallel_dilug_range(m, d):
        return False
    if is_sukkot_days_16_to_20(m, d):
        return False

    if is_pesach_seventh_day(m, d) or is_shavuot(m, d):
        return False

    if is_modern_israel_festivals(y, m, d):
        return False

    if m == 5 and d == 9:
        return False

    if m == 5 and d == 15:
        return False

    if m == 11 and d == 15:
        return False

    return True


def lamenatzeach_omit_reason(y, m, d):
    """Short reason when "Lamenatzeach" is omitted — order matches has_lamenatzeach."""
    if d == 1 or d == 30:
        return "ר״ח"
    if is_erev_yom_kippur(m, d):
        return "ערב יום כיפור"
    if is_erev_pesach_seder(m, d):
        return "ערב פסח"
    if is_erev_shavuot(m, d):
        return "ערב שבועות"
    if is_erev_sukkot(m, d):
        return "ערב סוכות"
    if is_hoshana_raba(m, d):
        return "הושענא רבה"
    if is_chanukah(m, d):
        return "חנוכה"
    if is_purim_day(y, m, d):
        return "פורים"
    if is_pesach_hallel_dilug_range(m, d):
        return "חוה״מ פסח"
    if is_sukkot_days_16_to_20(m, d):
        return "חוה״מ סוכות"
    if is_pesach_seventh_day(m, d):
        return "שביעי של פסח"
    if is_shavuot(m, d):
        return "שבועות"
    if is_modern_israel_festivals(y, m, d):
        return "יום העצמאות" if is_yom_haatzmaut(y, m, d) else "יום ירושלים"
    if m == 5 and d == 9:
        return "תשעה באב"
    if m == 5 and d == 15:
        return "ט״ו באב"
    if m == 11 and d == 15:
        return "ט״ו בשבט"
    return "כללים"


def say_ledavid_hashem(y, m, d):
    return m == 6 or (m == 7 and d <= 21)


def say_ledavid_hashem_arvit(for_date=None):
    evening_date = resolve_gregorian(for_date) + timedelta(days=1)
    _, m, d = hebrew_triple(evening_date)
    return m == 6 or (m == 7 and d <= 20)

# ===== TACHANUN =====
def mincha_eve_omission_reason(for_date, y2, m2, d2):
    """Mincha footnote when the next civil day is erev Yom Tov / Lag BaOmer / erev Shabbat, etc."""
    for_date = resolve_gregorian(for_date)
    if m2 == 2 and d2 == 18:
        return "ערב ל״ג בעומר"
    if is_yom_yerushalayim(m2, d2):
        return "ערב יום ירושלים"
    if is_purim_day(y2, m2, d2):
        return "ערב פורים"
    if is_rosh_hashana(m2, d2):
        return "ערב ראש השנה"
    if is_yom_kippur(m2, d2):
        return "ערב יום כיפור"
    if m2 == 7 and d2 == 15:
        return "ערב סוכות"
    if m2 == 7 and d2 == 16:
        return "ערב יו״ט סוכות"
    if m2 == 7 and d2 == 22:
        return "ערב שמיני עצרת"
    if is_pesach_first_day(m2, d2):
        return "ערב פסח"
    if is_shavuot(m2, d2):
        return "ערב שבועות"
    if is_yom_haatzmaut(y2, m2, d2):
        return "ערב יום העצמאות"
    tomorrow = for_date + timedelta(days=1)
    if is_shabbat_date(tomorrow):
        return "ערב שבת"
    return None


def calculate_tachanun(for_date=None):
    """Returns (shacharit, mincha, shacharit 'no tachanun' reason, mincha reason) — for bot parentheses only.

    When tachanun is omitted only at mincha (erev), shacharit reason is None.
    """
    for_date = resolve_gregorian(for_date)

    wd = for_date.weekday()
    _, m, d = hebrew_triple(for_date)

    if d == 1 or d == 30:
        note = "ר״ח"
        return "לא", "לא", note, note

    tomorrow = for_date + timedelta(days=1)
    y2, m2, d2 = hebrew_triple(tomorrow)

    if m == 1 or m == 3:
        note = "חודש ניסן" if m == 1 else "חודש סיון"
        return "לא", "לא", note, note

    if m == 2 and d == 18:
        note = "ל״ג בעומר"
        return "לא", "לא", note, note

    if get_rosh_chodesh_state(for_date) == "erev":
        sh = "ארוך" if wd in [0, 3] else "רגיל"
        return sh, "לא", None, "ערב ר״ח"

    eve_r = mincha_eve_omission_reason(for_date, y2, m2, d2)
    if eve_r:
        sh = "ארוך" if wd in [0, 3] else "רגיל"
        return sh, "לא", None, eve_r

    if wd in [0, 3]:
        return "ארוך", "רגיל", None, None

    return "רגיל", "רגיל", None, None

def say_vihi_noam(for_date=None):
    for_date = resolve_gregorian(for_date)
    if not is_shabbat_date(for_date):
        return True

    _, m, d = hebrew_triple(for_date)
    if is_yomtov(m, d):
        return False

    for i in range(1, 7):
        future = for_date + timedelta(days=i)
        _, m2, d2 = hebrew_triple(future)

        if is_yomtov(m2, d2):
            return False

        if is_intermediate_moed_window_vihi(m2, d2):
            return False

    return True


def rosh_chodesh_header_name(y, m, d):
    """Rosh Chodesh day title, e.g. 'Rosh Chodesh Cheshvan' — not on Rosh Hashanah (stays 'Rosh Hashanah')."""
    if is_rosh_hashana(m, d):
        return None
    if d == 1:
        return f"ראש חודש {hebrew_month_name(y, m)}"
    if d == 30:
        tomorrow_g = gregorian_from_hebrew(y, m, d) + timedelta(days=1)
        y2, m2, d2 = hebrew_triple(tomorrow_g)
        if d2 != 1:
            return None
        if is_rosh_hashana(m2, d2):
            return None
        return f"ראש חודש {hebrew_month_name(y2, m2)}"
    return None


def rosh_chodesh_yaale_month_suffix(y, m, d, for_date=None):
    """e.g. 'R"Ch Sivan' for the Yaaleh VeYavo line at mincha/arvit on Rosh Chodesh."""
    for_date = resolve_gregorian(for_date)
    if d == 1:
        return f"ר״ח {hebrew_month_name(y, m)}"
    if d == 30:
        t = for_date + timedelta(days=1)
        y2, m2, d2 = hebrew_triple(t)
        if d2 == 1:
            return f"ר״ח {hebrew_month_name(y2, m2)}"
    return "ר״ח"


def yaale_erev_rc_suffix(for_date=None):
    """Evening after Rosh Chodesh (day 2 or 30) for arvit — e.g. 'R"Ch Sivan', not 'erev R"Ch'."""
    for_date = resolve_gregorian(for_date)
    t = for_date + timedelta(days=1)
    y2, m2, d2 = hebrew_triple(t)
    if d2 == 1:
        return f"ר״ח {hebrew_month_name(y2, m2)}"
    if d2 == 30:
        t3 = t + timedelta(days=1)
        y3, m3, d3 = hebrew_triple(t3)
        if d3 == 1:
            return f"ר״ח {hebrew_month_name(y3, m3)}"
    return "ר״ח"


def get_day_name(y, m, d):
    if is_pesach_sheni(m, d):
        return "פסח שני"

    if is_isru_chag(m, d):
        return "איסרו חג"

    if is_tu_bav(m, d):
        return "ט״ו באב"

    if is_tu_bishvat(m, d):
        return "ט״ו בשבט"

    if m == 2 and d == 18:
        return "ל״ג בעומר"

    if is_purim_day(y, m, d):
        return "פורים"

    rc_hdr = rosh_chodesh_header_name(y, m, d)
    if rc_hdr:
        return rc_hdr

    if is_chanukah(m, d):
        return "חנוכה"

    if is_rosh_hashana(m, d):
        return "ראש השנה"

    if is_yom_kippur(m, d):
        return "יום כיפור"

    if is_pesach_from_first_day(m, d):
        return "פסח"

    if is_shavuot(m, d):
        return "שבועות"

    if is_sukkot_from_first_day(m, d):
        return "סוכות"

    if is_yom_haatzmaut(y, m, d):
        return "יום העצמאות"

    if is_yom_yerushalayim(m, d):
        return "יום ירושלים"

    return None


def vihi_noam_omit_reason(for_date=None):
    """Shown only when Vihi Noam is omitted on Motzaei Shabbat — only in the Shabbat-day digest (Motzaei Shabbat arvit)."""
    for_date = resolve_gregorian(for_date)
    if not is_shabbat_date(for_date):
        return None
    y, m, d = hebrew_triple(for_date)
    if is_yomtov(m, d):
        return get_day_name(y, m, d) or "יו״ט"
    for i in range(1, 7):
        future = for_date + timedelta(days=i)
        y2, m2, d2 = hebrew_triple(future)
        if is_yomtov(m2, d2):
            return get_day_name(y2, m2, d2) or "יו״ט"
        if is_intermediate_moed_window_vihi(m2, d2):
            return "חוה״מ פסח/סוכות"
    return "כללים"


def is_chanukah(m, d):
    return (m == 9 and d >= 25) or (m == 10 and d <= 2)


def needs_al_hanissim(y, m, d):
    return is_chanukah(m, d) or is_purim_day(y, m, d)


def is_chol_hamoed_pesach(m, d):
    return m == 1 and 17 <= d <= 20


def is_chol_hamoed_sukkot(m, d):
    return m == 7 and 17 <= d <= 20


def is_chol_hamoed(m, d):
    return is_chol_hamoed_pesach(m, d) or is_chol_hamoed_sukkot(m, d)


def chol_sukkot_musaf_u_bayom(m, d):
    if not is_sukkot_days_16_to_20(m, d):
        return None
    day = SUKKOT_MUSAF_U_BAYOM_DAYS[d - 16]
    return f"וביום {day}"

def is_hoshana_raba(m, d):
    return m == 7 and d == 21

def is_intermediate_moed_window_vihi(m, d):
    return is_moed_window_vihi_pesach_or_sukkot(m, d)

def get_greeting(y, m, d, for_date=None):
    for_date = resolve_gregorian(for_date)
    wd = for_date.weekday()

    if is_rosh_hashana(m, d):
        greeting = "שנה טובה!"
    elif is_yom_kippur(m, d):
        greeting = "גמר חתימה טובה!"
    elif get_fast_name(for_date):
        greeting = "צום קל"
    elif (d == 1 or d == 30) and not is_rosh_hashana(m, d):
        greeting = "חודש טוב!"
    elif get_day_name(y, m, d):
        greeting = "חג שמח!"
    else:
        greeting = ""

    if wd == 5:  # Shabbat only
        return f"שבת שלום ו{greeting}" if greeting else "שבת שלום!"

    return greeting

def get_rosh_chodesh_state(for_date=None):
    today = resolve_gregorian(for_date)
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)

    _, _, d = hebrew_triple(today)
    _, _, d0 = hebrew_triple(yesterday)
    _, _, d2 = hebrew_triple(tomorrow)

    if d == 1:
        return "day1"

    if d == 30:
        return "day2"

    if d2 == 1 or d2 == 30:
        return "erev"

    if d0 == 30:
        return "day1"

    return None

def needs_yaale_veyavo(for_date=None):
    _, m, d = hebrew_triple(for_date)

    if d == 1 or d == 30:
        return True

    if is_pesach_from_first_day(m, d):
        return True

    if is_shavuot(m, d):
        return True

    if is_sukkot_from_first_day(m, d):
        return True

    return False


def hallel_shacharit_line(for_date=None):
    for_date = resolve_gregorian(for_date)
    y, m, d = hebrew_triple(for_date)
    rc = get_rosh_chodesh_state(for_date)
    ch = is_chanukah(m, d)

    if ch and rc in RC_FULL_DAYS and not is_rosh_hashana(m, d):
        return "הלל בדילוג"

    if is_rosh_hashana(m, d):
        return "הלל שלם"

    if is_pesach_yom_tov(m, d):
        return "הלל שלם"
    if is_pesach_hallel_dilug_range(m, d):
        return "הלל בדילוג"

    if is_shavuot(m, d):
        return "הלל שלם"

    if is_sukkot_hallel_through_shemini(m, d):
        return "הלל שלם"

    if ch:
        return "הלל שלם"

    if is_modern_israel_festivals(y, m, d):
        return "הלל שלם"

    if rc in RC_FULL_DAYS:
        return "הלל בדילוג"

    return None


def insert_hallel_shacharit(shacharit, for_date):
    hl = hallel_shacharit_line(for_date)
    if not hl or hl in shacharit:
        return
    if "ברכי נפשי" in shacharit:
        shacharit.insert(shacharit.index("ברכי נפשי"), hl)
        return
    yaale_idx = [
        i
        for i, x in enumerate(shacharit)
        if x == "יעלה ויבוא" or x.startswith("יעלה ויבוא (")
    ]
    if yaale_idx:
        shacharit.insert(yaale_idx[-1] + 1, hl)
        return
    for prefix in ("אין למנצח", "אין אב הרחמים"):
        for i, line in enumerate(shacharit):
            if line == prefix or line.startswith(prefix + " ("):
                shacharit.insert(i, hl)
                return
    shacharit.append(hl)


def arvit_hallel_leil_pesach_lines(for_date=None):
    for_date = resolve_gregorian(for_date)
    _, m, d = hebrew_triple(for_date)
    if m != 1:
        return []
    if is_erev_pesach_seder(m, d):
        return ["הלל שלם (ליל פסח)"]
    return []


# ===== ZMANIM (yeshiva.org.il calaj) =====
_YI_PAIR_RE = re.compile(
    r"<span[^>]*\bclass\s*=\s*['\"]?(timesName)['\"]?[^>]*>(.*?)</span>\s*"
    r"<span[^>]*\bclass\s*=\s*['\"]?(timesVal)['\"]?[^>]*>(.*?)</span>",
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
        h, m = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    return f"{h:02d}:{m:02d}"


def _shift_hhmm(hhmm, minutes_delta):
    hhmm = _normalize_hhmm(hhmm)
    if not hhmm:
        return None
    h, m = (int(part) for part in hhmm.split(":"))
    total = (h * 60 + m + minutes_delta) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def _yeshiva_hebrew_month(hy, hm):
    # convertdate uses Nisan=1..Adar(II)=12/13; yeshiva.org.il uses Tishrei=1..Elul=12/13.
    if hm >= 7:
        return hm - 6
    return hm + (7 if hebrew.leap(hy) else 6)


def _yeshiva_strip_html_fragment(frag):
    if not frag:
        return ""
    t = re.sub(r"<[^>]+>", " ", frag)
    return html.unescape(t)


def _norm_zman_title(s):
    s = _yeshiva_strip_html_fragment(s)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.replace("״", '"').replace("\u201c", '"').replace("\u201d", '"')
    return s


def _yeshiva_extract_time_pairs(html_fragment):
    rows = []
    for m in _YI_PAIR_RE.finditer(html_fragment or ""):
        name = _norm_zman_title(m.group(2))
        val = _norm_zman_title(m.group(4))
        if name and val:
            rows.append({"name": name, "value": val})
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
    norm = _norm_zman_title(name)
    return any(norm.startswith(p) for p in _SHABAT_TIME_NAME_PREFIXES)


def _yeshiva_html_to_payload(page_html):
    daily, shabat = [], []
    for row in _yeshiva_extract_time_pairs(page_html):
        (shabat if _is_shabat_time_name(row["name"]) else daily).append(row)
    place_name = ""
    pm = re.search(
        r"<div\s+class\s*=\s*['\"]?DayPlace['\"]?\s*>([^<]*)</div>",
        page_html,
        re.I,
    )
    if pm:
        place_name = _norm_zman_title(pm.group(1))
    return {
        "times": daily,
        "shabat": {"times": shabat},
        "place": {"name": place_name} if place_name else {},
    }


def _yeshiva_parse_calaj_body(raw_text):
    t = raw_text.lstrip("\ufeff").strip()
    if t.startswith("{") or t.startswith("["):
        try:
            data = json.loads(t)
            if isinstance(data, dict) and isinstance(data.get("day"), dict):
                inner = data["day"]
                if "times" in inner or "shabat" in inner:
                    return inner
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            pass
    return _yeshiva_html_to_payload(t)


def _yeshiva_payload_has_times(payload):
    if not payload:
        return False
    if payload.get("times"):
        return True
    st = (payload.get("shabat") or {}).get("times")
    return bool(st)


_yeshiva_day_cache = {}


def yeshiva_day_payload(for_date=None):
    for_date = resolve_gregorian(for_date)
    key = for_date.isoformat()
    if key in _yeshiva_day_cache:
        return _yeshiva_day_cache[key]
    pl = YESHIVA_PLACE_ID
    hy, hm, hd = hebrew.from_gregorian(for_date.year, for_date.month, for_date.day)
    yorg_month = _yeshiva_hebrew_month(hy, hm)
    # timesDayPrint exposes a full set of daily zmanim for the requested place;
    # the older calaj.aspx?op=d only returns Shabbat times for many dates.
    url = (
        "https://www.yeshiva.org.il/calendar/timesDayPrint.aspx"
        f"?hy={hy}&hm={yorg_month}&hd={hd}&place={pl}"
    )
    result = {}
    try:
        r = requests.get(url, timeout=20, headers=YESHIVA_HTTP_HEADERS)
        r.raise_for_status()
        if r.text.strip():
            data = _yeshiva_parse_calaj_body(r.text)
            result = data if isinstance(data, dict) else {}
    except (requests.RequestException, ValueError, TypeError):
        pass
    if _yeshiva_payload_has_times(result):
        _yeshiva_day_cache[key] = result
    return result


def _yeshiva_time_by_names(payload, accepted_names):
    want = {_norm_zman_title(n) for n in accepted_names}
    for row in payload.get("times") or []:
        if _norm_zman_title(row.get("name", "")) in want:
            t = _normalize_hhmm(row.get("value"))
            if t:
                return t
    return None


def _yeshiva_shabat_time_by_names(payload, accepted_names):
    want = {_norm_zman_title(n) for n in accepted_names}
    sh = payload.get("shabat") or {}
    for row in sh.get("times") or []:
        if _norm_zman_title(row.get("name", "")) in want:
            t = _normalize_hhmm(row.get("value"))
            if t:
                return t
    return None


def yeshiva_zmanim_lines(for_date=None):
    p = yeshiva_day_payload(for_date)
    # NBSP (\u00A0) between the colon and time — keeps Telegram from stretching the space
    # when a line in the paragraph has longer text (e.g. Omer count).
    nbsp = "\u00a0"

    def line(label, names):
        t = _yeshiva_time_by_names(p, names)
        return f"{label}:{nbsp}{t}" if t else ""

    return (
        line("סוף זמן ק״ש", YI_NAMES_SOF_ZMAN_SHMA_GRA),
        line("שקיעה", YI_NAMES_SHKIA),
        line("צאת הכוכבים", YI_NAMES_TZEIT),
    )


def yeshiva_shabbat_candles_havdalah_hhmm(for_date=None):
    p = yeshiva_day_payload(for_date)
    shkiah_hhmm = _yeshiva_time_by_names(p, YI_NAMES_SHKIA)
    return (
        _shift_hhmm(shkiah_hhmm, -18),
        _yeshiva_shabat_time_by_names(p, YI_NAMES_TSET_SHABBAT),
    )


def get_shabbat_parsha_line(for_date):
    if not is_shabbat_date(for_date):
        return None

    _, m, d = hebrew_triple(for_date)
    if is_chol_hamoed_pesach(m, d):
        return "שבת חוה״מ <b>פסח</b>"
    if is_chol_hamoed_sukkot(m, d):
        return "שבת חוה״מ <b>סוכות</b>"

    hdate = dates.GregorianDate(for_date.year, for_date.month, for_date.day).to_heb()
    parsha = parshios.getparsha_string(hdate, hebrew=True, israel=True)
    if not parsha:
        return None

    parts = [p.strip() for p in parsha.split(",") if p.strip()]
    if len(parts) >= 2:
        return f"פרשות השבוע: <b>{'-'.join(parts)}</b>"
    return f"פרשת השבוע: <b>{parts[0]}</b>"


def format_section(name, items):
    name = name.strip()
    return f"{name}:\n" + "\n".join(items)


def append_once(items, value):
    if value not in items:
        items.append(value)


def format_ain_tachanun(note=None):
    if note:
        return f"אין תחנון ({note})"
    return "אין תחנון"


def format_with_reason(phrase, note=None):
    if note:
        return f"{phrase} ({note})"
    return phrase


def yaale_vehavo_chag_reason(y, m, d):
    """Short text for parentheses when Yaaleh VeYavo is for chag/moed (not Rosh Chodesh)."""
    if is_pesach_from_first_day(m, d):
        if is_pesach_yom_tov(m, d):
            return "פסח"
        if is_chol_hamoed_pesach(m, d):
            return "חוה״מ פסח"
        return "חול הפסח"
    if is_shavuot(m, d):
        return "שבועות"
    if is_hoshana_raba(m, d):
        return "הושענא רבה"
    if is_sukkot_from_first_day(m, d):
        if is_sukkot_yom_tov(m, d):
            return "סוכות"
        if is_chol_hamoed_sukkot(m, d):
            return "חוה״מ סוכות"
        return "סוכות"
    return "חג"


# ===== MESSAGE =====
def build_message(for_date=None):
    for_date = resolve_gregorian(for_date)

    header = get_hebrew_date(for_date)

    y, m, d = hebrew_triple(for_date)

    day_name = get_day_name(y, m, d) or get_fast_name(for_date)
    if day_name:
        header += f" - <b>{day_name}</b>"

    sh_tach, min_tach, sh_skip_note, min_skip_note = calculate_tachanun(for_date)
    omer = calculate_omer(for_date)

    shacharit = []

    rc_state = get_rosh_chodesh_state(for_date)
    is_shabbat = is_shabbat_date(for_date)

    is_special_day = is_shabbat or is_yomtov(m, d)

    if rc_state in RC_FULL_DAYS:
        shacharit.append(
            format_ain_tachanun(rosh_chodesh_yaale_month_suffix(y, m, d, for_date))
        )
        shacharit.append("יעלה ויבוא")
        shacharit.append("ברכי נפשי")

    elif needs_yaale_veyavo(for_date):
        shacharit.append(
            format_ain_tachanun(yaale_vehavo_chag_reason(y, m, d))
        )
        shacharit.append("יעלה ויבוא")

    elif not is_special_day:
        if sh_tach == "לא":
            shacharit.append(format_ain_tachanun(sh_skip_note))

        elif sh_tach == "ארוך":
            shacharit.append("אין שינויים (והוא רחום)")

        else:
            if not hallel_shacharit_line(for_date):
                shacharit.append("אין שינויים")

    insert_hallel_shacharit(shacharit, for_date)

    if not is_special_day:
        if not has_lamenatzeach(y, m, d):
            shacharit.append("אין למנצח")

    if is_shabbat:
        if not say_av_harachamim(for_date):
            shacharit.append(
                format_with_reason("אין אב הרחמים", av_harachamim_omit_reason(for_date))
            )

    if needs_al_hanissim(y, m, d):
        shacharit.append("על הנסים")

    if is_aseret_yemei_teshuva(m, d):
        append_once(shacharit, "שיר המעלות ממעמקים")
        if not is_shabbat:
            append_once(shacharit, "אבינו מלכנו")

    if is_public_fast_observed(for_date) and not is_shabbat:
        append_once(shacharit, "אבינו מלכנו")

    if say_ledavid_hashem(y, m, d):
        shacharit.append("לדוד ה׳")

    if rc_state in RC_FULL_DAYS or needs_yaale_veyavo(for_date):
        if rc_state in RC_FULL_DAYS:
            yaale_note = rosh_chodesh_yaale_month_suffix(y, m, d, for_date)
            m_no_tach_note = yaale_note
        else:
            m_no_tach_note = yaale_vehavo_chag_reason(y, m, d)
            yaale_note = m_no_tach_note
        mincha = [
            format_ain_tachanun(m_no_tach_note),
            format_with_reason("יעלה ויבוא", yaale_note),
        ]

    elif not is_special_day:
        mincha = (
            [format_ain_tachanun(min_skip_note)]
            if min_tach == "לא"
            else ["אין שינויים"]
        )

    else:
        mincha = ["אין שינויים"]

    if is_shabbat:
        if not say_tzidkatcha(for_date):
            mincha.append(
                format_with_reason("אין צדקתך", tzidkatcha_omit_reason(for_date))
            )

    if needs_al_hanissim(y, m, d):
        mincha.append("על הנסים")

    if is_public_fast_observed(for_date):
        mincha.append("עננו ה׳ עננו")

    if is_tisha_bav_observed(for_date):
        mincha.append("נחמו")

    arvit = []

    if is_shabbat:
        if not say_vihi_noam(for_date):
            arvit.append(
                format_with_reason("אין ויהי נעם", vihi_noam_omit_reason(for_date))
            )

    if rc_state == "erev":
        arvit.append(
            format_with_reason("יעלה ויבוא", yaale_erev_rc_suffix(for_date))
        )

    elif needs_yaale_veyavo(for_date):
        if rc_state in RC_FULL_DAYS:
            yv_note = rosh_chodesh_yaale_month_suffix(y, m, d, for_date)
        else:
            yv_note = yaale_vehavo_chag_reason(y, m, d)
        arvit.append(format_with_reason("יעלה ויבוא", yv_note))

    if omer:
        arvit.append(f"ספירת העומר: היום {omer+1} לעומר")

    if needs_al_hanissim(y, m, d):
        arvit.append("על הנסים")

    arvit.extend(arvit_hallel_leil_pesach_lines(for_date))

    if say_ledavid_hashem_arvit(for_date):
        arvit.append("לדוד ה׳")

    if not arvit:
        arvit = ["אין שינויים"]

    musaf_extras = []
    has_musaf = (
        rc_state in RC_FULL_DAYS
        or is_shabbat
        or is_yomtov(m, d)
        or is_chol_hamoed(m, d)
        or is_hoshana_raba(m, d)
    )

    if rc_state in RC_FULL_DAYS and is_shabbat:
        musaf_extras.append("אתה יצרת")

    u_bayom = chol_sukkot_musaf_u_bayom(m, d)
    if u_bayom:
        musaf_extras.append(u_bayom)

    if is_hoshana_raba(m, d):
        musaf_extras.append("הושענא רבה")

    if has_musaf and is_chanukah(m, d):
        musaf_extras.append("על הנסים")

    if not shacharit:
        shacharit = ["אין שינויים"]

    if has_musaf and not musaf_extras:
        musaf_extras = ["אין שינויים"]

    z_sof, z_shkiah, z_tzeit = yeshiva_zmanim_lines(for_date)
    candles_hhmm, havdalah_hhmm = yeshiva_shabbat_candles_havdalah_hhmm(for_date)
    nbsp = "\u00a0"

    msg = f"{header} 📅"
    parsha_line = get_shabbat_parsha_line(for_date)
    if parsha_line:
        msg += f"\n\n{parsha_line}"

    mevarchim = shabbat_mevarchim_line(for_date)
    if mevarchim:
        msg += f"\n\n{mevarchim}"

    if is_aseret_yemei_teshuva(m, d):
        msg += "\n\n<b>עשרת ימי תשובה</b>"
    msg += f"\n\n{format_section('שחרית 🌅', shacharit)}"
    if z_sof:
        msg += f"\n\n{z_sof}"

    if has_musaf:
        msg += "\n\n" + format_section("מוסף 🕍", musaf_extras)

    msg += f"\n\n{format_section('מנחה 🌇', mincha)}"
    mincha_zmanim = []
    if z_shkiah:
        mincha_zmanim.append(z_shkiah)
    if z_tzeit:
        mincha_zmanim.append(z_tzeit)
    if for_date.weekday() == 4 and candles_hhmm:
        mincha_zmanim.append(f"כניסת שבת:{nbsp}{candles_hhmm}")
    if is_shabbat and havdalah_hhmm:
        mincha_zmanim.append(f"צאת השבת:{nbsp}{havdalah_hhmm}")
    if mincha_zmanim:
        msg += "\n\n" + "\n".join(mincha_zmanim)

    msg += f"\n\n{format_section('ערבית 🌙', arvit)}"

    selichot = ashkenaz_selichot_line(for_date)
    if selichot:
        msg += f"\n\n{selichot}"

    greeting = get_greeting(y, m, d, for_date)
    if greeting:
        msg += f"\n\n{greeting}"

    return msg

# ===== UPDATES =====
def poll_updates():
    res = requests.get(f"{BASE_URL}/getUpdates").json()

    for u in res.get("result", []):
        if "message" not in u:
            continue

        chat_id = u["message"]["chat"]["id"]
        text = u["message"].get("text", "")

        if text == "/start" and add_user(chat_id):
            send(chat_id, "נרשמת בהצלחה 🙌")

def build_daily_digest(today=None):
    today = resolve_gregorian(today)
    msg = build_message(today)
    for d in multi_day_digest_dates(today):
        msg += "\n\n" + build_message(d)
    return msg


def advance_after_digest_bundle(start_day):
    """Next calendar day to use for preview after sending build_daily_digest(start_day)."""
    d0 = resolve_gregorian(start_day)
    last = d0
    for d in multi_day_digest_dates(d0):
        if d > last:
            last = d
    return last + timedelta(days=1)


# ===== MAIN =====
def main():
    poll_updates()

    force_n = parse_force_send_count()
    if force_n > 0:
        cursor = today_jerusalem()
        for _ in range(force_n):
            send(MY_CHAT_ID, build_daily_digest(cursor))
            cursor = advance_after_digest_bundle(cursor)
        return

    manual = is_manual_dispatch_run()
    # Scheduled run: morning window + do not send twice same day (last_run).

    if not manual and not should_send_now():
        return

    if is_shabbat() or is_yomtov_today():
        return

    # Manual workflow_dispatch with FORCE_SEND=0: broadcast to all without editing last_run.json by hand.
    if manual:
        today_str = today_jerusalem().isoformat()
        _, sha = get_last_run()
        save_last_run(today_str, sha)

    broadcast(build_daily_digest())

if __name__ == "__main__":
    main()
