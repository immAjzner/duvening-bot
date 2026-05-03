import requests
import os
from datetime import datetime

TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

# ===== תאריך עברי =====
def get_hebrew_date():
    today = datetime.now().strftime("%Y-%m-%d")
    url = f"https://www.hebcal.com/converter?g2h=1&date={today}&json=1"
    data = requests.get(url).json()

    hebrew = f"{data['hd']} {data['hm']} {data['hy']}"
    weekday_names = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]
    weekday = weekday_names[datetime.now().weekday()]

    return f"יום {weekday}, {hebrew}"

# ===== שליפת אירועים =====
def get_events():
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

    data = requests.get(url, params=params).json()
    today = datetime.now().strftime("%Y-%m-%d")
    return [e for e in data["items"] if e["date"].startswith(today)]

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

    # בניית הודעה
    sections = []

    if shacharit:
        sections.append("🌅 שחרית:\n" + "\n".join(shacharit))
    if mincha:
        sections.append("🌇 מנחה:\n" + "\n".join(mincha))
    if arvit:
        sections.append("🌙 ערבית:\n" + "\n".join(arvit))

    header = get_hebrew_date()

    if not sections:
        return f"📅 {header}\n\nהיום הכל כרגיל בתפילות"

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
