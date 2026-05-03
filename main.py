import requests
import os
import json
from datetime import datetime, date
from convertdate import hebrew

TOKEN = os.environ["BOT_TOKEN"]
BASE_URL = f"https://api.telegram.org/bot{TOKEN}"

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
REPO = os.environ["GITHUB_REPOSITORY"]  # owner/repo
FILE_PATH = "users.json"

# ===== GitHub helpers =====
import base64

def get_users_from_github():
    url = f"https://api.github.com/repos/{REPO}/contents/{FILE_PATH}"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}

    res = requests.get(url, headers=headers)

    if res.status_code != 200:
        print("Failed to fetch users:", res.text)
        return [], None

    data = res.json()

    try:
        content = base64.b64decode(data["content"]).decode("utf-8")
        users = json.loads(content)
    except Exception as e:
        print("Decode error:", e)
        users = []

    return users, data["sha"]


def save_users_to_github(users, sha):
    import base64

    url = f"https://api.github.com/repos/{REPO}/contents/{FILE_PATH}"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}

    content = json.dumps(users, ensure_ascii=False, indent=2)
    encoded = base64.b64encode(content.encode()).decode()

    data = {
        "message": "update users",
        "content": encoded,
        "sha": sha
    }

    res = requests.put(url, headers=headers, json=data)

    if res.status_code not in [200, 201]:
        print("Failed to save users:", res.text)


def add_user(chat_id):
    users, sha = get_users_from_github()

    if chat_id not in users:
        users.append(chat_id)
        save_users_to_github(users, sha)


# ===== שליחה =====
def send(chat_id, msg):
    requests.post(f"{BASE_URL}/sendMessage", data={
        "chat_id": chat_id,
        "text": msg
    })


def broadcast(msg):
    users, _ = get_users_from_github()
    for user in users:
        send(user, msg)


# ===== תאריך =====
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

{section("🌅 שחרית", ["תחנון: רגיל"])}

{section("🌇 מנחה", [])}

{section("🌙 ערבית", arvit)}
"""


# ===== קבלת משתמשים =====
def poll_updates():
    try:
        users, sha = get_users_from_github()

        res = requests.get(f"{BASE_URL}/getUpdates").json()

        for update in res.get("result", []):
            if "message" not in update:
                continue

            chat_id = update["message"]["chat"]["id"]
            text = update["message"].get("text", "")

            if text == "/start":
                if chat_id not in users:
                    users.append(chat_id)
                    save_users_to_github(users, sha)
                    send(chat_id, "נרשמת בהצלחה 🙌 תקבל עדכון יומי")

        # ⚠️ חשוב: לנקות updates כדי שלא יחזרו שוב
        if res.get("result"):
            last_update_id = res["result"][-1]["update_id"]
            requests.get(f"{BASE_URL}/getUpdates?offset={last_update_id + 1}")

    except Exception as e:
        print("poll error:", e)


# ===== main =====
def main():
    poll_updates()
    broadcast(build_message())


if __name__ == "__main__":
    main()
