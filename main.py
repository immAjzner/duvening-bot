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

# זמני היום וכניסת/צאת שבת מאתר ישיבה (calaj) — מזהה מקום (173 = נתניה)
YESHIVA_PLACE_ID = os.environ.get("YESHIVA_PLACE_ID", "173")
YESHIVA_CALAJ_CACHE_VERSION = os.environ.get("YESHIVA_CALAJ_CACHE_VERSION", "21")

# כותרות כמו בדפדפן — בלי זה calaj לעיתים מחזיר HTML/403 וה־JSON לא נטען
YESHIVA_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*;q=0.01",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.yeshiva.org.il/calendar/timesday",
}

# שמות כפי שמופיעים ב־JSON ובגרסת ה־HTML (קיצורים שונים)
YI_NAMES_SOF_ZMAN_SHMA_GRA = (
    'סוף זמן קריאת שמע לגר"א',
    'סוף זמן ק"ש לגר"א',
)
YI_NAMES_SHKIA = ("שקיעה",)
YI_NAMES_TZEIT = ("צאת הכוכבים",)
YI_NAMES_KNISAT_SHABBAT = ("כניסת שבת",)
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
FOUR_PARSHIYOS = frozenset({"Shekalim", "Zachor", "Parah", "Hachodesh"})
RC_FULL_DAYS = frozenset({"day1", "day2"})
EXTRA_DIGEST_MAX_OFFSET = 4  # היום + עד 4 ימים קדימה בהודעה אחת
SUKKOT_MUSAF_U_BAYOM_DAYS = ("השני", "השלישי", "הרביעי", "החמישי", "השישי")

GITHUB_AUTH_HEADER = {"Authorization": f"Bearer {GITHUB_TOKEN}"}


def resolve_gregorian(for_date=None):
    return for_date if for_date is not None else date.today()


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

    if not (5 <= now.hour <= 8):
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
        "text": msg
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

    sh, _ = calculate_tachanun(for_date)

    return sh != "לא"

def is_shabbat_mevarchim(for_date=None):
    for_date = resolve_gregorian(for_date)

    if not is_shabbat():
        return False

    for i in range(1, 7):
        future = for_date + timedelta(days=i)
        _, _, d = hebrew_triple(future)

        if d == 1:
            return True

    return False

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


def is_shavuot(m, d):
    return m == 3 and d == 6


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


def is_yom_haatzmaut(m, d):
    return m == 2 and d == 5


def is_yom_yerushalayim(m, d):
    return m == 2 and d == 28


def is_modern_israel_festivals(m, d):
    return is_yom_haatzmaut(m, d) or is_yom_yerushalayim(m, d)


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
    return is_yomtov(*hebrew_triple(date.today()))


def day_is_shabbat_or_yomtov(gd):
    return is_shabbat_date(gd) or is_yomtov(*hebrew_triple(gd))


def need_multi_day_digest(today):
    wd = datetime.now(TZ).weekday()
    if wd == 4:
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


def heading_for_multi_day_section(today, d):
    n = (d - today).days
    if n == 1:
        return "📅 גם מחר"
    if n == 2:
        return "📅 גם בעוד יומיים"
    if n == 3:
        return "📅 גם בעוד שלושה ימים"
    if n == 4:
        return "📅 גם בעוד ארבעה ימים"
    return f"📅 בעוד {n} ימים"


def say_av_harachamim(for_date=None):
    for_date = resolve_gregorian(for_date)

    if not is_shabbat_date(for_date):
        return False

    y, m, d = hebrew_triple(for_date)

    # ========= חריגים — כן אומרים =========

    # שבת שלפני שבועות
    if is_sivan_shabbat_before_shavuot(m, d):
        return True

    # שבת שלפני תשעה באב
    if m == 5 and d in [7, 8]:
        return True

    # ========= כלל בסיס =========
    # אם אין תחנון ביום חול — לא אומרים אב הרחמים

    sh, _ = calculate_tachanun(for_date)
    if sh == "לא":
        return False

    # שבת מברכים
    if is_shabbat_mevarchim(for_date):
        # חריגים — כן אומרים
        if m in [2, 3]:  # אייר, סיון
            return True
        return False

    # ארבע פרשיות
    if is_four_parshiyot(for_date):
        return False

    # ========= ימים מיוחדים =========

    if is_chanukah(m, d):
        return False

    if is_purim_day(y, m, d):
        return False

    # ט"ו בשבט
    if m == 11 and d == 15:
        return False

    # ל"ג בעומר
    if m == 2 and d == 18:
        return False

    # ערב חג (פסח/שבועות/ר"ה)
    tomorrow = for_date + timedelta(days=1)
    if is_yomtov(*hebrew_triple(tomorrow)):
        return False

    # ========= ברירת מחדל =========
    return True

def is_four_parshiyot(for_date=None):
    for_date = resolve_gregorian(for_date)

    hdate = dates.GregorianDate(for_date.year, for_date.month, for_date.day).to_heb()

    if not is_shabbat_date(for_date):
        return False

    parsha = parshios.getparsha(hdate)

    return parsha in FOUR_PARSHIYOS

# ===== למנצח =====
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

    if is_modern_israel_festivals(m, d):
        return False

    if m == 5 and d == 9:
        return False

    if m == 5 and d == 15:
        return False

    if m == 11 and d == 15:
        return False

    return True

# ===== TACHANUN =====
def calculate_tachanun(for_date=None):
    for_date = resolve_gregorian(for_date)

    wd = datetime.now(TZ).weekday()
    _, m, d = hebrew_triple(for_date)

    if d == 1 or d == 30:
        return "לא", "לא"

    tomorrow = for_date + timedelta(days=1)
    _, m2, d2 = hebrew_triple(tomorrow)

    if m == 1 or m == 3:
        return "לא", "לא"

    if m == 2 and d == 18:
        return "לא", "לא"

    if (m2 == 2 and d2 == 18):
        return ("ארוך" if wd in [0,3] else "רגיל"), "לא"

    if wd in [0,3]:
        return "ארוך", "רגיל"

    return "רגיל", "רגיל"

def say_vihi_noam(for_date=None):
    for_date = resolve_gregorian(for_date)

    if for_date.weekday() != 6:
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

def get_day_name(y, m, d):
    if m == 2 and d == 18:
        return "ל״ג בעומר"

    if is_purim_day(y, m, d):
        return "פורים"

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

    return None

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

    if wd == 4:  # יום שישי
        return "שבת שלום!"

    if is_rosh_hashana(m, d):
        return "שנה טובה!"

    if is_yom_kippur(m, d):
        return "גמר חתימה טובה!"

    if m == 5 and d == 9:
        return "צום קל"

    if get_day_name(y, m, d):
        return "חג שמח!"

    return ""

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
    _, m, d = hebrew_triple(for_date)
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

    if is_modern_israel_festivals(m, d):
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
    yaale_idx = [i for i, x in enumerate(shacharit) if x == "יעלה ויבוא"]
    if yaale_idx:
        shacharit.insert(yaale_idx[-1] + 1, hl)
        return
    for token in ("אין למנצח", "אין אב הרחמים"):
        if token in shacharit:
            shacharit.insert(shacharit.index(token), hl)
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


def _yeshiva_calaj_x(place_id, year, month, day, lang="heb", op_tail="d"):
    pls = str(place_id)
    return (
        "r"
        + op_tail
        + str(month % 10)
        + "h"
        + str(year % 10)
        + "d"
        + pls[-1]
        + str(day % 10)
        + "k"
        + lang[-1]
    )


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


def _yeshiva_html_to_payload(page_html):
    low = page_html.lower()
    idx = low.find("class=shabat")
    if idx == -1:
        idx = low.find("class='shabat'")
    if idx == -1:
        idx = low.find('class="shabat"')
    main = page_html if idx < 0 else page_html[:idx]
    shabat_html = "" if idx < 0 else page_html[idx:]
    place_name = ""
    pm = re.search(
        r"<div\s+class\s*=\s*DayPlace\s*>([^<]*)</div>",
        page_html,
        re.I,
    )
    if pm:
        place_name = _norm_zman_title(pm.group(1))
    return {
        "times": _yeshiva_extract_time_pairs(main),
        "shabat": {"times": _yeshiva_extract_time_pairs(shabat_html)},
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
    y, m, d = for_date.year, for_date.month, for_date.day
    x = _yeshiva_calaj_x(pl, y, m, d)
    url = (
        "https://www.yeshiva.org.il/calendar/calaj.aspx"
        f"?cache_version={YESHIVA_CALAJ_CACHE_VERSION}&v=1&op=d&pl={pl}"
        f"&yr={y}&mn={m}&dy={d}&sv=false&lng=heb&x={x}"
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
    # NBSP (\u00A0) בין הנקודתיים לשעה — מונע מטלגרם למתוח את הרווח
    # ביישור־לרוחב כששורה אחרת בפסקה ארוכה יותר (למשל ספירת העומר)
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
    return (
        _yeshiva_shabat_time_by_names(p, YI_NAMES_KNISAT_SHABBAT),
        _yeshiva_shabat_time_by_names(p, YI_NAMES_TSET_SHABBAT),
    )


def format_section(name, items):
    name = name.strip()
    return f"{name}:\n" + "\n".join(items)

# ===== MESSAGE =====
def build_message(for_date=None):
    for_date = resolve_gregorian(for_date)

    header = get_hebrew_date(for_date)

    y, m, d = hebrew_triple(for_date)

    day_name = get_day_name(y, m, d)
    if day_name:
        header += f" - {day_name}"

    sh_tach, min_tach = calculate_tachanun(for_date)
    omer = calculate_omer(for_date)

    shacharit = []

    rc_state = get_rosh_chodesh_state(for_date)

    is_special_day = is_shabbat_date(for_date) or is_yomtov(m, d)

    if rc_state in RC_FULL_DAYS:
        shacharit.append("אין תחנון")
        shacharit.append("יעלה ויבוא")
        shacharit.append("ברכי נפשי")

    elif needs_yaale_veyavo(for_date):
        shacharit.append("אין תחנון")
        shacharit.append("יעלה ויבוא")

    elif not is_special_day:
        if sh_tach == "לא":
            shacharit.append("אין תחנון")

        elif sh_tach == "ארוך":
            shacharit.append("אין שינויים (והוא רחום)")

        else:
            shacharit.append("אין שינויים")

    insert_hallel_shacharit(shacharit, for_date)

    if not is_special_day:
        if not has_lamenatzeach(y, m, d):
            shacharit.append("אין למנצח")

    if is_shabbat_date(for_date):
        if not say_av_harachamim(for_date):
            shacharit.append("אין אב הרחמים")

    if needs_al_hanissim(y, m, d):
        shacharit.append("על הנסים")

    if rc_state in RC_FULL_DAYS or needs_yaale_veyavo(for_date):
        mincha = ["אין תחנון", "יעלה ויבוא"]

    elif not is_special_day:
        mincha = ["אין תחנון"] if min_tach == "לא" else ["אין שינויים"]

    else:
        mincha = ["אין שינויים"]

    if is_shabbat_date(for_date):
        if not say_tzidkatcha(for_date):
            mincha.append("אין צדקתך")

    if needs_al_hanissim(y, m, d):
        mincha.append("על הנסים")

    arvit = []

    if for_date.weekday() == 6:
        if not say_vihi_noam(for_date):
            arvit.append("אין ויהי נעם")

    if rc_state == "erev":
        arvit.append("יעלה ויבוא")

    elif needs_yaale_veyavo(for_date):
        arvit.append("יעלה ויבוא")

    if omer:
        arvit.append(f"ספירת העומר: היום {omer+1} לעומר")

    if needs_al_hanissim(y, m, d):
        arvit.append("על הנסים")

    arvit.extend(arvit_hallel_leil_pesach_lines(for_date))

    if not arvit:
        arvit = ["אין שינויים"]

    musaf_extras = []
    has_musaf = (
        rc_state in RC_FULL_DAYS
        or is_shabbat_date(for_date)
        or is_yomtov(m, d)
        or is_chol_hamoed(m, d)
        or is_hoshana_raba(m, d)
    )

    if rc_state in RC_FULL_DAYS and is_shabbat_date(for_date):
        musaf_extras.append("אתה יצרת")

    u_bayom = chol_sukkot_musaf_u_bayom(m, d)
    if u_bayom:
        musaf_extras.append(u_bayom)

    if is_hoshana_raba(m, d):
        musaf_extras.append("הושענא רבה")

    if has_musaf and is_chanukah(m, d):
        musaf_extras.append("על הנסים")

    z_sof, z_shkiah, z_tzeit = yeshiva_zmanim_lines(for_date)
    candles_hhmm, havdalah_hhmm = yeshiva_shabbat_candles_havdalah_hhmm(for_date)

    knisat_shabbat_block = ""
    if for_date.weekday() == 4 and candles_hhmm:
        knisat_shabbat_block = "\n\n" + format_section("כניסת שבת", [candles_hhmm])

    motzei_shabbat_block = ""
    if is_shabbat_date(for_date) and havdalah_hhmm:
        motzei_shabbat_block = "\n\n" + format_section("צאת השבת", [havdalah_hhmm])

    msg = f"{header} 📅\n\n{format_section('שחרית 🌅', shacharit)}"
    if z_sof:
        msg += f"\n{z_sof}"

    if has_musaf:
        msg += "\n\n" + format_section("מוסף 🕍", musaf_extras)

    msg += f"{knisat_shabbat_block}\n\n{format_section('מנחה 🌇', mincha)}"
    if z_shkiah:
        msg += f"\n{z_shkiah}"

    msg += f"\n\n{format_section('ערבית 🌙', arvit)}"
    if z_tzeit:
        msg += f"\n\n{z_tzeit}"
    msg += motzei_shabbat_block

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

# ===== MAIN =====
def main():
    poll_updates()

    force_send = os.environ.get("FORCE_SEND") == "1"

    if force_send:
        send(MY_CHAT_ID, build_message())
        return

    if not should_send_now():
        return

    if is_shabbat() or is_yomtov_today():
        return

    msg = build_message()
    today = date.today()
    for d in multi_day_digest_dates(today):
        heading = heading_for_multi_day_section(today, d)
        msg += f"\n\n{heading}:\n\n"
        msg += build_message(d)

    broadcast(msg)

if __name__ == "__main__":
    main()
