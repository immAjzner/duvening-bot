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

# ===== HEBREW FORMAT =====
def hebrew_number(n):
    units = ["", "א","ב","ג","ד","ה","ו","ז","ח","ט"]
    tens = ["", "י","כ","ל","מ","נ","ס","ע","פ","צ"]

    if n == 15:
        return "ט״ו"
    if n == 16:
        return "ט״ז"

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
def get_hebrew_date():
    today = date.today()
    h_year, h_month, h_day = hebrew.from_gregorian(today.year, today.month, today.day)

    months = ["","ניסן","אייר","סיון","תמוז","אב","אלול","תשרי","חשוון","כסלו","טבת","שבט","אדר"]
    weekdays = ["שני","שלישי","רביעי","חמישי","שישי","שבת","ראשון"]

    return f"יום {weekdays[datetime.now().weekday()]}, {hebrew_number(h_day)} ב{months[h_month]} {hebrew_year(h_year)}"

# ===== OMER =====
def calculate_omer():
    today = date.today()
    h_year, h_month, h_day = hebrew.from_gregorian(today.year, today.month, today.day)

    if h_month == 1 and h_day >= 16:
        return h_day - 15
    if h_month == 2:
        return 15 + h_day
    if h_month == 3 and h_day <= 5:
        return 44 + h_day

    return None

# ===== HOLIDAYS =====
def is_yomtov(h_month, h_day):
    return (
        (h_month == 1 and h_day in [15,16,21,22]) or
        (h_month == 3 and h_day in [6,7]) or
        (h_month == 7 and h_day in [1,2,10,15,16,22,23])
    )

def is_erev_yomtov():
    tomorrow = date.today() + timedelta(days=1)
    y, m, d = hebrew.from_gregorian(tomorrow.year, tomorrow.month, tomorrow.day)
    return is_yomtov(m, d)

def is_isru_chag(h_month, h_day):
    return (
        (h_month == 1 and h_day == 23) or
        (h_month == 3 and h_day == 7) or
        (h_month == 7 and h_day == 23)
    )

# ===== TACHANUN =====
def calculate_tachanun():
    today = date.today()
    wd = datetime.now().weekday()
    y, m, d = hebrew.from_gregorian(today.year, today.month, today.day)

    # אין תחנון
    if m == 1:  # ניסן
        return "לא אומרים", "לא אומרים"

    if m == 3:  # סיון
        return "לא אומרים", "לא אומרים"

    if m == 2 and d == 18:  # ל״ג בעומר
        return "לא אומרים", "לא אומרים"

    if is_yomtov(m, d) or is_isru_chag(m, d):
        return "לא אומרים", "לא אומרים"

    # ערב חג
    if is_erev_yomtov():
        shacharit = "רגיל" if wd not in [0,3] else "ארוך"
        return shacharit, "לא אומרים"

    # רגיל
    if wd in [0,3]:
        return "ארוך", "רגיל"

    return "רגיל", "רגיל"

# ===== MESSAGE =====
def build_message():
    header = get_hebrew_date()

    sh_tach, min_tach = calculate_tachanun()
    omer = calculate_omer()

        # ===== שחרית =====
    if sh_tach == "לא אומרים":
        shacharit = ["אין תחנון"]
    elif sh_tach == "ארוך":
        shacharit = ["תחנון ארוך (והוא רחום)"]
    else:
        shacharit = ["אין שינויים"]

    # ===== מנחה =====
    if min_tach == "לא אומרים":
        mincha = ["אין תחנון"]
    else:
        mincha = ["אין שינויים"]

    # ===== ערבית =====
    arvit = []
    if omer:
        arvit.append(f"ספירת העומר: היום {omer + 1} לעומר")

    if not arvit:
        arvit = ["אין שינויים"]

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

    if res.get("result"):
        last = res["result"][-1]["update_id"]
        requests.get(f"{BASE_URL}/getUpdates?offset={last+1}")

# ===== MAIN =====
def main():
    poll_updates()
    broadcast(build_message())

if __name__ == "__main__":
    main()
