import requests
import os
from datetime import datetime

TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

def get_data():
    today = datetime.now().strftime("%Y-%m-%d")
    url = f"https://www.hebcal.com/hebcal?v=1&cfg=json&maj=on&min=on&mod=on&nx=on&year=now&month=x&ss=off&mf=off&c=on&geo=geoname&geonameid=2925533"
    data = requests.get(url).json()
    events = [item for item in data["items"] if item["date"].startswith(today)]
    return events

def get_weekday():
    return datetime.now().weekday()  # 0=Mon ... 6=Sun

def has_event(events, keyword):
    return any(keyword in e["title"] for e in events)

def get_omer(events):
    for e in events:
        if "Omer" in e["title"]:
            return e["title"]
    return None

def analyze():
    events = get_data()
    weekday = get_weekday()

    shacharit = []
    mincha = []
    arvit = []

    # ===== זיהוי ימים =====
    is_rosh_chodesh = has_event(events, "Rosh Chodesh")
    is_chanukah = has_event(events, "Chanukah")
    is_pesach = has_event(events, "Pesach")
    is_chol_hamoed = has_event(events, "Chol haMoed")
    is_shavuot = has_event(events, "Shavuot")
    is_sukkot = has_event(events, "Sukkot")
    is_yom_haatzmaut = has_event(events, "Yom HaAtzmaut")
    is_yom_yerushalayim = has_event(events, "Yom Yerushalayim")

    is_yomtov = any([
        is_pesach, is_shavuot, is_sukkot
    ])

    # ===== הלל =====
    if is_chanukah or is_shavuot or is_sukkot or is_yom_haatzmaut:
        shacharit.append("הלל: שלם")
    elif is_rosh_chodesh or is_pesach or is_chol_hamoed:
        shacharit.append("הלל: בדילוג")

    if is_yom_yerushalayim:
        shacharit.append("הלל: שלם")

    # ===== תחנון =====
    no_tachanun = any([
        is_rosh_chodesh, is_chanukah, is_pesach,
        is_shavuot, is_sukkot, is_yom_haatzmaut
    ])

    if no_tachanun:
        shacharit.append("תחנון: אין")
        mincha.append("תחנון: אין")
    else:
        if weekday in [0, 3]:  # שני, חמישי
            shacharit.append("תחנון: ארוך")
        else:
            shacharit.append("תחנון: רגיל")

    # ===== למנצח =====
    if no_tachanun:
        shacharit.append("למנצח: אין")

    # ===== מזמור לתודה =====
    if is_pesach:
        shacharit.append("מזמור לתודה: אין")

    # ===== ספירת העומר =====
    omer = get_omer(events)
    if omer:
        arvit.append(f"{omer}")

    # ===== סיכום =====
    sections = []

    if shacharit:
        sections.append("🌅 שחרית:\n" + "\n".join(shacharit))
    if mincha:
        sections.append("🌇 מנחה:\n" + "\n".join(mincha))
    if arvit:
        sections.append("🌙 ערבית:\n" + "\n".join(arvit))

    if not sections:
        return "📅 היום הכל כרגיל בתפילות"

    return "📅 שינויים להיום:\n\n" + "\n\n".join(sections)

def send(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, data={
        "chat_id": CHAT_ID,
        "text": msg
    })

def main():
    msg = analyze()
    send(msg)

if __name__ == "__main__":
    main()
