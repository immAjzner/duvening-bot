import requests
import os
import json
from datetime import datetime, date
from convertdate import hebrew

TOKEN = os.environ["BOT_TOKEN"]
BASE_URL = f"https://api.telegram.org/bot{TOKEN}"

USERS_FILE = "users.json"

# ===== ניהול משתמשים =====
def load_users():
    try:
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    except:
        return []

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f)

def add_user(chat_id):
    users = load_users()
    if chat_id not in users:
        users.append(chat_id)
        save_users(users)

# ===== שליחה =====
def send(chat_id, msg):
    requests.post(f"{BASE_URL}/sendMessage", data={
        "chat_id": chat_id,
        "text": msg
    })

def broadcast(msg):
    users = load_users()
    for user in users:
        send(user, msg)

# ===== מספר עברי =====
def hebrew_number(n):
    units = ["", "א","ב","ג","ד","ה","ו","ז","ח","ט"]
    tens = ["", "י","כ","ל","מ","נ","ס","ע","פ","צ"]

    if n == 15:
        return "ט״ו"
    if n == 16:
        return "ט״ז"

    if n < 10:
        return units[n] + "׳"

    if n < 100:
        t = tens[n // 10]
        u = units[n % 10]
        return f"{t}״{u}" if u else f"{t}׳"

    return str(n)

def hebrew_year(y):
    y = y % 1000
    mapping = [
        (400,"ת"),(300,"ש"),(200,"ר"),(100,"ק"),
        (90,"צ"),(80,"פ"),(70,"ע"),(60,"ס"),(50,"נ"),
        (40,"מ"),(30,"ל"),(20,"כ"),(10,"י"),
        (9,"ט"),(8,"ח"),(7,"ז"),(6,"ו"),(5,"ה"),
        (4,"ד"),(3,"ג"),(2,"ב"),(1,"א")
    ]

    result = ""
    for val, letter in mapping:
        while y >= val:
            result += letter
            y -= val

    return result[:-1] + "״" + result[-1]

# ===== תאריך =====
def get_hebrew_date():
    today = date.today()
    h_year, h_month, h_day = hebrew.from_gregorian(today.year, today.month, today.day)

    months = ["","ניסן","אייר","סיון","תמוז","אב","אלול","תשרי","חשוון","כסלו","טבת","שבט","אדר"]
    weekday_names = ["שני","שלישי","רביעי","חמישי","שישי","שבת","ראשון"]

    return f"יום {weekday_names[datetime.now().weekday()]}, {hebrew_number(h_day)} ב{months[h_month]} {hebrew_year(h_year)}"

# ===== עומר =====
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

# ===== הודעה =====
def build_message():
    header = get_hebrew_date()

    arvit = []
    omer = calculate_omer()
    if omer:
        arvit.append(f"ספירת העומר: היום {omer + 1} לעומר")

    def section(name, items):
        return f"{name}:\n" + ("\n".join(items) if items else "אין שינויים")

    return f"""📅 {header}

שינויים להיום:

{section("🌅 שחרית", ["תחנון: רגיל"])}
{section("🌇 מנחה", [])}
{section("🌙 ערבית", arvit)}
"""

# ===== קבלת משתמשים חדשים =====
def poll_updates():
    url = f"{BASE_URL}/getUpdates"
    res = requests.get(url).json()

    for update in res.get("result", []):
        if "message" in update:
            chat_id = update["message"]["chat"]["id"]
            text = update["message"].get("text", "")

            if text == "/start":
                add_user(chat_id)
                send(chat_id, "נרשמת בהצלחה 🙌 תקבל עדכון יומי")

# ===== main =====
def main():
    # קבלת משתמשים חדשים
    poll_updates()

    # שליחה יומית
    msg = build_message()
    broadcast(msg)

if __name__ == "__main__":
    main()
