import requests
import os
import json
import base64
from datetime import datetime, date, timedelta
from convertdate import hebrew

TOKEN = os.environ["BOT_TOKEN"]
BASE_URL = f"https://api.telegram.org/bot{TOKEN}"

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
REPO = os.environ["GITHUB_REPOSITORY"]
FILE_PATH = "users.json"

def get_last_run():
    url = f"https://api.github.com/repos/{REPO}/contents/last_run.json"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}

    res = requests.get(url, headers=headers)

    if res.status_code != 200:
        return None, None

    data = res.json()
    content = base64.b64decode(data["content"]).decode("utf-8")
    return json.loads(content), data["sha"]


def save_last_run(today_str, sha):
    url = f"https://api.github.com/repos/{REPO}/contents/last_run.json"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}

    content = json.dumps({"date": today_str})
    encoded = base64.b64encode(content.encode()).decode()

    data = {
        "message": "update last run",
        "content": encoded,
        "sha": sha
    }

    requests.put(url, headers=headers, json=data)

def should_send_now():
    now = datetime.utcnow()

    if now.hour != 3:
        return False

    today_str = date.today().isoformat()

    last_run, sha = get_last_run()

    if last_run and last_run.get("date") == today_str:
        return False  # כבר שלחנו היום

    save_last_run(today_str, sha)

    return True

# ===== GitHub USERS =====
def get_users_from_github():
    url = f"https://api.github.com/repos/{REPO}/contents/{FILE_PATH}"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}
    res = requests.get(url, headers=headers)

    if res.status_code != 200:
        return [], None

    data = res.json()
    content = base64.b64decode(data["content"]).decode("utf-8")
    return json.loads(content), data["sha"]


def save_users_to_github(users, sha):
    url = f"https://api.github.com/repos/{REPO}/contents/{FILE_PATH}"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}

    content = json.dumps(users, ensure_ascii=False, indent=2)
    encoded = base64.b64encode(content.encode()).decode()

    data = {
        "message": "update users",
        "content": encoded,
        "sha": sha
    }

    requests.put(url, headers=headers, json=data)


def add_user(chat_id):
    users, sha = get_users_from_github()
    if chat_id not in users:
        users.append(chat_id)
        save_users_to_github(users, sha)

# ===== TELEGRAM =====
def send(chat_id, msg):
    requests.post(f"{BASE_URL}/sendMessage", data={
        "chat_id": chat_id,
        "text": msg
    })

def broadcast(msg):
    users, _ = get_users_from_github()
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

# ===== GET HEBREW DATE ===== 
def get_hebrew_date(for_date=None):
    if not for_date:
        for_date = date.today()

    y, m, d = hebrew.from_gregorian(for_date.year, for_date.month, for_date.day)

    months = ["","ניסן","אייר","סיון","תמוז","אב","אלול","תשרי","חשוון","כסלו","טבת","שבט","אדר"]
    weekdays = ["שני","שלישי","רביעי","חמישי","שישי","שבת","ראשון"]

    wd = datetime.now().weekday()
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
    return datetime.now().weekday() == 5

def is_yomtov_today():
    y,m,d = hebrew.from_gregorian(date.today().year, date.today().month, date.today().day)
    return is_yomtov(m,d)

def is_erev_special():
    tomorrow = date.today() + timedelta(days=1)
    wd = datetime.now().weekday()
    y,m,d = hebrew.from_gregorian(tomorrow.year, tomorrow.month, tomorrow.day)

    if wd == 4: return True
    if is_yomtov(m,d): return True
    return False

def is_isru_chag(m, d):
    return (
        (m == 1 and d == 23) or
        (m == 3 and d == 7) or
        (m == 7 and d == 23)
    )

# ===== TACHANUN =====
def calculate_tachanun(for_date=None):
    if not for_date:
        for_date = date.today()

    wd = datetime.now().weekday()
    y,m,d = hebrew.from_gregorian(for_date.year, for_date.month, for_date.day)

    if m == 1 or m == 3:
        return "לא אומרים", "לא אומרים"

    if m == 2 and d == 18:
        return "לא אומרים", "לא אומרים"

    if is_yomtov(m,d) or is_isru_chag(m,d):
        return "לא אומרים", "לא אומרים"

    if is_erev_special():
        sh = "ארוך" if wd in [0,3] else "רגיל"
        return sh, "לא אומרים"

    if wd in [0,3]:
        return "ארוך", "רגיל"

    return "רגיל", "רגיל"

# ===== ADDITIONS =====
def calculate_additions(for_date=None):
    if not for_date:
        for_date = date.today()

    y,m,d = hebrew.from_gregorian(for_date.year, for_date.month, for_date.day)

    additions = []

    # הלל
    if (m == 9 and d >= 25) or (m == 10 and d <= 2):
        additions.append("הלל שלם")

    elif m == 7 and d in [15,16,17,18,19,20,21]:
        additions.append("הלל שלם")

    elif m == 3 and d in [6,7]:
        additions.append("הלל שלם")

    elif m == 1 and d >= 15:
        additions.append("הלל בדילוג" if d > 16 else "הלל שלם")

    elif d == 1 or d == 30:
        additions.append("הלל בדילוג")

    # יום העצמאות / ירושלים (בלי לציין)
    if m == 2 and d in [4,5,28]:
        additions.append("הלל שלם")

    # למנצח
    sh,_ = calculate_tachanun(for_date)
    if sh == "לא אומרים":
        additions.append("אין למנצח")

    # מזמור לתודה
    if m == 1 or is_yomtov(m,d):
        additions.append("אין מזמור לתודה")

    return additions

# ===== MESSAGE =====
def build_message(for_date=None):
    if not for_date:
        for_date = date.today()

    header = get_hebrew_date(for_date)

    sh_tach, min_tach = calculate_tachanun(for_date)
    additions = calculate_additions(for_date)
    omer = calculate_omer(for_date)

    shacharit = []
    if sh_tach == "לא אומרים":
        shacharit.append("אין תחנון")
    elif sh_tach == "ארוך":
        shacharit.append("תחנון ארוך (והוא רחום)")
    shacharit += additions
    if not shacharit:
        shacharit = ["אין שינויים"]

    mincha = ["אין תחנון"] if min_tach == "לא אומרים" else ["אין שינויים"]

    arvit = [f"ספירת העומר: היום {omer+1} לעומר"] if omer else ["אין שינויים"]

    musaf = []
    y,m,d = hebrew.from_gregorian(for_date.year, for_date.month, for_date.day)
    if is_shabbat() or is_yomtov(m,d):
        musaf = ["יש מוסף"]

    def section(name, items):
        return f"{name}:\n" + "\n".join(items)

    msg = f"""📅 {header}

{section("🌅 שחרית", shacharit)}

{section("🌇 מנחה", mincha)}

{section("🌙 ערבית", arvit)}
"""

    if musaf:
        msg += f"\n{section('🕍 מוסף', musaf)}"

    return msg

# ===== UPDATES =====
def poll_updates():
    res = requests.get(f"{BASE_URL}/getUpdates").json()
    users, sha = get_users_from_github()

    for u in res.get("result", []):
        if "message" not in u:
            continue

        chat_id = u["message"]["chat"]["id"]
        text = u["message"].get("text", "")

        if text == "/start":
            if chat_id not in users:
                users.append(chat_id)
                save_users_to_github(users, sha)
                send(chat_id, "נרשמת בהצלחה 🙌")

    if res.get("result"):
        last = res["result"][-1]["update_id"]
        requests.get(f"{BASE_URL}/getUpdates?offset={last+1}")

# ===== MAIN =====
def main():
    poll_updates()

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
