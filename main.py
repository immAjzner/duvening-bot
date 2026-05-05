import requests
import os
import json
import base64
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from convertdate import hebrew

# ===== CONFIG =====
TOKEN = os.environ["BOT_TOKEN"]
BASE_URL = f"https://api.telegram.org/bot{TOKEN}"

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
REPO = os.environ["GITHUB_REPOSITORY"]

USERS_FILE = "users.json"
LAST_RUN_FILE = "last_run.json"
MY_CHAT_ID = "5474184664"

TZ = ZoneInfo("Asia/Jerusalem")

# ===== GITHUB =====
def get_file(path):
    url = f"https://api.github.com/repos/{REPO}/contents/{path}"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}
    res = requests.get(url, headers=headers)

    if res.status_code != 200:
        return None, None

    data = res.json()
    content = base64.b64decode(data["content"]).decode("utf-8")
    return json.loads(content), data["sha"]

def save_file(path, content_obj, sha, message):
    url = f"https://api.github.com/repos/{REPO}/contents/{path}"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}

    content = json.dumps(content_obj, ensure_ascii=False, indent=2)
    encoded = base64.b64encode(content.encode()).decode()

    data = {
        "message": message,
        "content": encoded,
        "sha": sha
    }

    requests.put(url, headers=headers, json=data)

# ===== USERS =====
def get_users():
    data, sha = get_file(USERS_FILE)
    return (data or []), sha

def add_user(chat_id):
    users, sha = get_users()
    if chat_id not in users:
        users.append(chat_id)
        save_file(USERS_FILE, users, sha, "add user")

# ===== LAST RUN =====
def get_last_run():
    return get_file(LAST_RUN_FILE)

def save_last_run(today_str, sha):
    save_file(LAST_RUN_FILE, {"date": today_str}, sha, "update last run")

# ===== SCHEDULING =====
def should_send_now():
    now = datetime.now(TZ)

    if not (6 <= now.hour <= 8):
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
    if not for_date:
        for_date = date.today()

    y, m, d = hebrew.from_gregorian(for_date.year, for_date.month, for_date.day)

    months = ["","ניסן","אייר","סיון","תמוז","אב","אלול","תשרי","חשוון","כסלו","טבת","שבט","אדר"]
    weekdays = ["שני","שלישי","רביעי","חמישי","שישי","שבת","ראשון"]

    wd = datetime.now(TZ).weekday()
    return f"יום {weekdays[wd]}, {hebrew_number(d)} ב{months[m]} {hebrew_year(y)}"

# ===== OMER =====
def calculate_omer(for_date=None):
    if not for_date:
        for_date = date.today()

    y, m, d = hebrew.from_gregorian(for_date.year, for_date.month, for_date.day)

    if m == 1 and d >= 16: return d - 15
    if m == 2: return 15 + d
    if m == 3 and d <= 5: return 44 + d

    return None

# ===== HOLIDAYS =====
def is_yomtov(m, d):
    return (
        (m == 1 and d in [15,16,21,22]) or
        (m == 3 and d in [6,7]) or
        (m == 7 and d in [1,2,10,15,16,22,23])
    )

def is_shabbat():
    return datetime.now(TZ).weekday() == 5

def is_yomtov_today():
    today = date.today()
    y,m,d = hebrew.from_gregorian(today.year, today.month, today.day)
    return is_yomtov(m,d)

def is_erev_special():
    tomorrow = date.today() + timedelta(days=1)
    wd = datetime.now(TZ).weekday()
    y,m,d = hebrew.from_gregorian(tomorrow.year, tomorrow.month, tomorrow.day)

    return wd == 4 or is_yomtov(m,d)

# ===== למנצח =====
def has_lamenatzeach(m, d):
    if d == 1 or d == 30:
        return False

    if m == 7 and d == 9:
        return False

    if m == 1 and d == 14:
        return False
    if m == 3 and d == 5:
        return False
    if m == 7 and d == 14:
        return False
    if m == 7 and d == 21:
        return False

    if (m == 9 and d >= 25) or (m == 10 and d <= 2):
        return False

    if m == 12 and d == 14:
        return False

    if m == 13 and d == 14:
        return False

    if m == 1 and 16 <= d <= 20:
        return False
    if m == 7 and 16 <= d <= 20:
        return False

    if (m == 1 and d == 22) or (m == 3 and d == 7) or (m == 7 and d == 23):
        return False

    if m == 2 and d == 5:
        return False

    if m == 2 and d == 28:
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
    if not for_date:
        for_date = date.today()

    wd = datetime.now(TZ).weekday()
    y,m,d = hebrew.from_gregorian(for_date.year, for_date.month, for_date.day)

    if d == 1 or d == 30:
        return "לא", "לא"

    tomorrow = for_date + timedelta(days=1)
    y2,m2,d2 = hebrew.from_gregorian(tomorrow.year, tomorrow.month, tomorrow.day)

    if m == 1 or m == 3:
        return "לא", "לא"

    if m == 2 and d == 18:
        return "לא", "לא"

    if (m2 == 2 and d2 == 18):
        return ("ארוך" if wd in [0,3] else "רגיל"), "לא"

    if wd in [0,3]:
        return "ארוך", "רגיל"

    return "רגיל", "רגיל"

def get_day_name(m, d):
    if m == 2 and d == 18:
        return "ל״ג בעומר"

    if m == 12 and d == 14:
        return "פורים"

    if (m == 9 and d >= 25) or (m == 10 and d <= 2):
        return "חנוכה"

    if m == 7 and d in [1,2]:
        return "ראש השנה"

    if m == 7 and d == 10:
        return "יום כיפור"

    if m == 1 and d >= 15:
        return "פסח"

    if m == 3 and d == 6:
        return "שבועות"

    if m == 7 and d >= 15:
        return "סוכות"

    return None

def get_greeting(m, d):
    wd = datetime.now(TZ).weekday()

    if wd == 4:  # יום שישי
        return "שבת שלום!"

    if m == 7 and d in [1,2]:
        return "שנה טובה!"

    if m == 7 and d == 10:
        return "גמר חתימה טובה!"

    if m == 5 and d == 9:
        return "צום קל"

    if get_day_name(m, d):
        return "חג שמח!"

    return ""

def get_rosh_chodesh_state(for_date=None):
    if not for_date:
        for_date = date.today()

    today = for_date
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)

    y, m, d = hebrew.from_gregorian(today.year, today.month, today.day)
    y0, m0, d0 = hebrew.from_gregorian(yesterday.year, yesterday.month, yesterday.day)
    y2, m2, d2 = hebrew.from_gregorian(tomorrow.year, tomorrow.month, tomorrow.day)

    # יום ראשון של ראש חודש (א׳)
    if d == 1:
        return "day1"

    # יום שני של ראש חודש (ל׳)
    if d == 30:
        return "day2"

    # ערב ראש חודש (ערבית בלבד)
    if d2 == 1 or d2 == 30:
        return "erev"

    # היום שאחרי יום 30 (יום 1 כבר טופל)
    if d0 == 30:
        return "day1"

    return None

def needs_yaale_veyavo(for_date=None):
    if not for_date:
        for_date = date.today()

    y, m, d = hebrew.from_gregorian(for_date.year, for_date.month, for_date.day)

    # ראש חודש
    if d == 1 or d == 30:
        return True

    # פסח (כולל חול המועד)
    if m == 1 and d >= 15:
        return True

    # שבועות
    if m == 3 and d == 6:
        return True

    # סוכות (כולל חול המועד)
    if m == 7 and d >= 15:
        return True

    return False

# ===== MESSAGE =====
def build_message(for_date=None):
    if not for_date:
        for_date = date.today()

    header = get_hebrew_date(for_date)

    y, m, d = hebrew.from_gregorian(for_date.year, for_date.month, for_date.day)
    
    day_name = get_day_name(m, d)
    if day_name:
        header += f" - {day_name}"

    sh_tach, min_tach = calculate_tachanun(for_date)
    omer = calculate_omer(for_date)

    y,m,d = hebrew.from_gregorian(for_date.year, for_date.month, for_date.day)
    shacharit = []

    rc_state = get_rosh_chodesh_state(for_date)
    
    if rc_state in ["day1", "day2"]:
        shacharit.append("אין תחנון")
        shacharit.append("יעלה ויבוא")
        shacharit.append("הלל בדילוג")
        shacharit.append("ברכי נפשי")

    elif needs_yaale_veyavo(for_date):
        shacharit.append("אין תחנון")
        shacharit.append("יעלה ויבוא")
    
    elif sh_tach == "לא":
        shacharit.append("אין תחנון")
    
    elif sh_tach == "ארוך":
        shacharit.append("אין שינויים (והוא רחום)")
    
    else:
        shacharit.append("אין שינויים")
    
    if not has_lamenatzeach(m,d):
        shacharit.append("אין למנצח")

    if rc_state in ["day1", "day2"] or needs_yaale_veyavo(for_date):
        mincha = ["אין תחנון", "יעלה ויבוא"]
    
    else:
        mincha = ["אין תחנון"] if min_tach == "לא" else ["אין שינויים"]

    arvit = []

    if rc_state == "erev":
    arvit.append("יעלה ויבוא")

    elif needs_yaale_veyavo(for_date):
        # ערבית של יום טוב / חול המועד
        arvit.append("יעלה ויבוא")    
    
    if omer:
        arvit.append(f"ספירת העומר: היום {omer+1} לעומר")
    
    if not arvit:
        arvit = ["אין שינויים"]

    musaf = []

    if rc_state in ["day1", "day2"]:
        musaf.append("מוסף")
    
        if is_shabbat():
            musaf.append("אתה יצרת")

    def section(name, items):
        return f"{name}:\n" + "\n".join(items)

    msg = f"""📅 {header}

    {section("🌅 שחרית", shacharit)}
    """

    if musaf:
        if len(musaf) == 1:
            msg += f"\n\n🕍 {musaf[0]}"
        else:
            msg += f"\n\n🕍 מוסף:\n" + "\n".join(musaf)

    msg += f"""
    
    {section("🌇 מנחה", mincha)}
    
    {section("🌙 ערבית", arvit)}
    """

    greeting = get_greeting(m, d)
    if greeting:
        msg += f"\n\n{greeting}"
    
    return msg    

# ===== UPDATES =====
def poll_updates():
    res = requests.get(f"{BASE_URL}/getUpdates").json()
    users, sha = get_users()

    for u in res.get("result", []):
        if "message" not in u:
            continue

        chat_id = u["message"]["chat"]["id"]
        text = u["message"].get("text", "")

        if text == "/start":
            if chat_id not in users:
                users.append(chat_id)
                save_file(USERS_FILE, users, sha, "add user")
                send(chat_id, "נרשמת בהצלחה 🙌")

# ===== MAIN =====
def main():
    poll_updates()

    force_send = os.environ.get("FORCE_SEND") == "1"

    if force_send:
        # שליחה רק אליך
        send(MY_CHAT_ID, build_message())
        return

    if not should_send_now():
        return

    if is_shabbat() or is_yomtov_today():
        return

    msg = build_message()

    if is_erev_special():
        msg += "\n\n📅 גם למחר:\n\n"
        msg += build_message(date.today() + timedelta(days=1))

    broadcast(msg)

if __name__ == "__main__":
    main()
