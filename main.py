import requests
import os
import json
import base64
from datetime import datetime, date, timedelta

from convertdate import hebrew
from pyluach import dates, hebrewcal

TOKEN = os.environ["BOT_TOKEN"]
BASE_URL = f"https://api.telegram.org/bot{TOKEN}"

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
REPO = os.environ["GITHUB_REPOSITORY"]
FILE_PATH = "users.json"

# ===== USERS =====
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

def get_hebrew_date():
    today = date.today()
    y, m, d = hebrew.from_gregorian(today.year, today.month, today.day)

    months = ["","ניסן","אייר","סיון","תמוז","אב","אלול","תשרי","חשוון","כסלו","טבת","שבט","אדר"]
    weekdays = ["שני","שלישי","רביעי","חמישי","שישי","שבת","ראשון"]

    wd = datetime.now().weekday()
    return f"יום {weekdays[wd]}, {hebrew_number(d)} ב{months[m]} {hebrew_year(y)}"

# ===== OMER =====
def calculate_omer():
    today = date.today()
    y, m, d = hebrew.from_gregorian(today.year, today.month, today.day)

    if m == 1 and d >= 16: return d - 15
    if m == 2: return 15 + d
    if m == 3 and d <= 5: return 44 + d

    return None

# ===== HYBRID HALACHIC ENGINE =====
def hybrid_tachanun():
    today = date.today()
    wd = datetime.now().weekday()

    y, m, d = hebrew.from_gregorian(today.year, today.month, today.day)

    # ===== בסיס (מנוע הלכתי) =====
    no_tachanun = False

    # ניסן
    if m == 1:
        no_tachanun = True

    # סיון
    if m == 3:
        no_tachanun = True

    # ל"ג בעומר
    if m == 2 and d == 18:
        no_tachanun = True

    # חנוכה
    if (m == 9 and d >= 25) or (m == 10 and d <= 2):
        no_tachanun = True

    # פורים
    if (m == 12 and d == 14) or (m == 12 and d == 15):
        no_tachanun = True

    # ===== override ציוני =====
    if m == 2 and d in [4,5,28]:
        no_tachanun = True

    # ערב יום שאין תחנון
    tomorrow = today + timedelta(days=1)
    y2,m2,d2 = hebrew.from_gregorian(tomorrow.year, tomorrow.month, tomorrow.day)

    if (m2 == 2 and d2 == 18):
        return "רגיל" if wd not in [0,3] else "ארוך", "לא"

    if no_tachanun:
        return "לא", "לא"

    if wd in [0,3]:
        return "ארוך", "רגיל"

    return "רגיל", "רגיל"

# ===== ADDITIONS =====
def hybrid_additions():
    today = date.today()
    y, m, d = hebrew.from_gregorian(today.year, today.month, today.day)

    additions = []

    # הלל
    if (m == 9 and d >= 25) or (m == 10 and d <= 2):
        additions.append("הלל שלם")
    elif m == 1 and d >= 15:
        additions.append("הלל בדילוג" if d > 16 else "הלל שלם")
    elif d == 1 or d == 30:
        additions.append("הלל בדילוג")

    # override ציוני
    if m == 2 and d in [4,5,28]:
        additions.append("הלל שלם")

    # למנצח
    sh,_ = hybrid_tachanun()
    if sh == "לא":
        additions.append("אין למנצח")

    # מזמור לתודה
    if m == 1:
        additions.append("אין מזמור לתודה")

    return additions

# ===== MESSAGE =====
def build_message():
    header = get_hebrew_date()

    sh_tach, min_tach = hybrid_tachanun()
    additions = hybrid_additions()
    omer = calculate_omer()

    shacharit = []

    if sh_tach == "לא":
        shacharit.append("אין תחנון")
    elif sh_tach == "ארוך":
        shacharit.append("תחנון ארוך (והוא רחום)")
    else:
        shacharit.append("אין שינויים (והוא רחום)")

    shacharit += additions

    mincha = ["אין תחנון"] if min_tach == "לא" else ["אין שינויים"]

    arvit = [f"ספירת העומר: היום {omer+1} לעומר"] if omer else ["אין שינויים"]

    def section(name, items):
        return f"{name}:\n" + "\n".join(items)

    return f"""📅 {header}

{section("🌅 שחרית", shacharit)}

{section("🌇 מנחה", mincha)}

{section("🌙 ערבית", arvit)}
"""

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

# ===== MAIN =====
def main():
    poll_updates()
    broadcast(build_message())

if __name__ == "__main__":
    main()
