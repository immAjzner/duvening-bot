import requests
import os
from datetime import datetime

TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

# ===== תאריך עברי =====
def get_hebrew_data():
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        url = f"https://www.hebcal.com/converter?g2h=1&date={today}&json=1"
        res = requests.get(url, timeout=10)
        return res.json()
    except:
        return None

def get_hebrew_date():
    data = get_hebrew_data()
    weekday_names = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]
    weekday = weekday_names[datetime.now().weekday()]

    if not data:
        return f"יום {weekday}"

    return f"יום {weekday}, {data['hd']} {data['hm']} {data['hy']}"

# ===== עומר (פתרון סופי!) =====
def calculate_omer():
    try:
        today = datetime.now().strftime("%Y-%m-%d")

        # ט"ז ניסן 2024 כבסיס (אפשר גם שנה נוכחית, זה לא משנה כי אנחנו מחשבים לפי שנה)
        url = f"https://www.hebcal.com/converter?g2h=1&date={today}&json=1"
        res = requests.get(url, timeout=10)
        data = res.json()

        hd = int(data["hd"])
        hm = data["hm"]

        # נזהה לפי שם חלקי בלבד
        hm = hm.lower()

        if "nisan" in hm and hd >= 16:
            return hd - 15

        if "iyar" in hm:
            return 15 + hd

        if "sivan" in hm and hd <= 5:
            return 44 + hd

        return None

    except:
        return None

# ===== אירועים =====
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
            "geonameid": "293397"
        }

        res = requests.get(url, params=params, timeout=10)
        data = res.json()

        today = datetime.now().strftime("%Y-%m-%d")
        return [e for e in data["items"] if e["date"].startswith(today)]

    except:
        return []

def has(events, word):
    return any(word in e["title"] for e in events)

def weekday():
    return datetime.now().weekday()

# ===== לוגיקה =====
def analyze():
    events = get_events()
    wd = weekday()

    shacharit = []
    mincha = []
    arvit = []

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

    # תחנון
    no_tachanun = any([
        rc, chanukah, pesach, shavuot, sukkot, chol, atzmaut, isru
    ])

    if no_tachanun:
        shacharit.append("תחנון: לא אומרים")
        mincha.append("תחנון: לא אומרים")
    else:
        if wd in [0, 3]:
            shacharit.append("תחנון: ארוך")
        else:
            shacharit.append("תחנון: רגיל")

    if erev:
        mincha.append("תחנון: לא אומרים")

    # הלל
    if chanukah or shavuot or sukkot or atzmaut:
        shacharit.append("הלל: שלם")
    elif rc or pesach or chol:
        shacharit.append("הלל: בדילוג")

    if yerushalayim:
        shacharit.append("הלל: שלם")

    # למנצח
    if no_tachanun:
        shacharit.append("למנצח: לא אומרים")

    # מזמור לתודה
    if pesach or yomtov:
        shacharit.append("מזמור לתודה: לא אומרים")

    # ===== עומר =====
    omer_day = calculate_omer()
    if omer_day:
        arvit.append(f"ספירת העומר: היום {omer_day} לעומר")

    # ניקוי כפילויות
    shacharit = list(dict.fromkeys(shacharit))
    mincha = list(dict.fromkeys(mincha))
    arvit = list(dict.fromkeys(arvit))

    header = get_hebrew_date()

    def section(title, items):
        return f"{title}:\n" + ("\n".join(items) if items else "אין שינויים")

    if not shacharit and not mincha and not arvit:
        return f"📅 {header}\n\nהיום הכל כרגיל בתפילות"

    return f"""📅 {header}

שינויים להיום:

{section("🌅 שחרית", shacharit)}

{section("🌇 מנחה", mincha)}

{section("🌙 ערבית", arvit)}
"""

# ===== שליחה =====
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
