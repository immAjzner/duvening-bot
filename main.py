import requests
import os
from datetime import datetime

TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

# ===== תאריך עברי (עם הגנה) =====
def get_hebrew_date():
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        url = f"https://www.hebcal.com/converter?g2h=1&date={today}&json=1"
        res = requests.get(url, timeout=10)

        if res.status_code != 200:
            raise Exception("Bad response")

        data = res.json()

        hebrew = f"{data['hd']} {data['hm']} {data['hy']}"
        weekday_names = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]
        weekday = weekday_names[datetime.now().weekday()]

        return f"יום {weekday}, {hebrew}"

    except Exception:
        weekday_names = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]
        weekday = weekday_names[datetime.now().weekday()]
        return f"יום {weekday}"

# ===== שליפת אירועים (עם הגנה) =====
def get_events():
    try:
        url = "https://www.hebcal.com/hebcal"
        params = {
            "v": "1",
            "cfg": "json",
            "maj": "on",
            "min": "on",
            "mod": "on",
            "nx": "on",
            "year": "now",
            "month": "x",
            "ss": "off",
            "mf": "off",
            "c": "on",
            "geo": "geoname",
            "geonameid": "2925533"
        }

        res = requests.get(url, params=params, timeout=10)

        if res.status_code != 200:
            return []

        data = res.json()
        today = datetime.now().strftime("%Y-%m-%d")
        return [e for e in data["items"] if e["date"].startswith(today)]

    except Exception:
        return []

def has(events, word):
    return any(word in e["title"] for e in events)

def get_omer(events):
    for e in events:
        if "Omer" in e["title"]:
            return e["title"]
    return None

def weekday():
    return datetime.now().weekday()  # 0=Mon

# ===== לוגיקה הלכתית =====
def analyze():
    events = get_events()
    wd = weekday()

    shacharit = []
    mincha = []
    arvit = []

    # זיהוי ימים
    rc = has(events, "Rosh Chodesh")
    chanukah = has(events, "Chanukah")
    pesach = has(events, "Pesach")
    chol = has(events, "Chol haMoed")
    shavuot = has(events, "Shavuot")
    sukkot = has(events, "Sukkot")
    atzmaut = has(events, "Yom HaAtzmaut")
    yerushalayim = has(events, "Yom Yerushalayim")
    isru = has(events, "Isru Chag")
    erev = has(events, "Erev")

    yomtov = any([pesach, shavuot, sukkot])

    # ===== תחנון =====
    no_tachanun = any([
        rc, chanukah, pesach, shavuot, sukkot, chol, atzmaut, isru
    ])

    if no_tachanun:
        shacharit.append("תחנון: לא אומרים")
        mincha.append("תחנון: לא אומרים")
    else:
        if wd in [0, 3]:  # שני / חמישי
            shacharit.append("תחנון: ארוך")
        else:
            shacharit.append("תחנון: רגיל")

    if erev:
        mincha.append("תחנון: לא אומרים")

    # ===== הלל =====
    if chanukah or shavuot or sukkot or atzmaut:
        shacharit.append("הלל: שלם")
    elif rc or pesach or chol:
        shacharit.append("הלל: בדילוג")

    if yerushalayim:
        shacharit.append("הלל: שלם")

    # ===== למנצח =====
    if no_tachanun:
        shacharit.append("למנצח: לא אומרים")

    # ===== מזמור לתודה =====
    if pesach or yomtov:
        shacharit.append("מזמור לתודה: לא אומרים")

    # ===== ספירת העומר =====
    omer = get_omer(events)
    if omer:
        arvit.append(omer)

    # ניקוי כפילויות
    shacharit = list(dict.fromkeys(shacharit))
    mincha = list(dict.fromkeys(mincha))
    arvit = list(dict.fromkeys(arvit))

    # ===== בניית הודעה (אופציה 2) =====
    header = get_hebrew_date()

    def format_section(title, items):
        if items:
            return f"{title}:\n" + "\n".join(items)
        else:
            return f"{title}:\nאין שינויים"

    # אם אין שום שינוי בכלל
    if not shacharit and not mincha and not arvit:
        return f"📅 {header}\n\nהיום הכל כרגיל בתפילות"

    sections = [
        format_section("🌅 שחרית", shacharit),
        format_section("🌇 מנחה", mincha),
        format_section("🌙 ערבית", arvit),
    ]

    return f"📅 {header}\n\nשינויים להיום:\n\n" + "\n\n".join(sections)

# ===== שליחה לטלגרם =====
def send(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, data={
        "chat_id": CHAT_ID,
        "text": msg
    })

def main():
    send(analyze())

if __name__ == "__main__":
    main()
