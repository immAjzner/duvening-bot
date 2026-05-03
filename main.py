import requests
import os
from datetime import datetime

TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

def get_events():
    today = datetime.now().strftime("%Y-%m-%d")
    url = f"https://www.hebcal.com/hebcal?v=1&cfg=json&maj=on&min=on&mod=on&nx=on&year=now&month=x&ss=off&mf=off&c=on&geo=geoname&geonameid=2925533"
    data = requests.get(url).json()
    return [item["title"] for item in data["items"] if item["date"].startswith(today)]

def is_omer_period(events):
    return any("Omer" in e for e in events)

def get_omer_day(events):
    for e in events:
        if "Omer" in e:
            return e
    return None

def analyze_day(events):
    changes = []

    # ===== חגים =====
    is_rosh_chodesh = any("Rosh Chodesh" in e for e in events)
    is_chanukah = any("Chanukah" in e for e in events)
    is_pesach = any("Pesach" in e for e in events)
    is_shavuot = any("Shavuot" in e for e in events)
    is_sukkot = any("Sukkot" in e for e in events)
    is_yom_haatzmaut = any("Yom HaAtzmaut" in e for e in events)
    is_yom_yerushalayim = any("Yom Yerushalayim" in e for e in events)

    # ===== הלל =====
    if is_chanukah or is_shavuot or is_sukkot or is_yom_haatzmaut:
        changes.append("הלל: אומרים הלל שלם")
    elif is_rosh_chodesh or is_pesach:
        changes.append("הלל: אומרים הלל בדילוג")

    # ===== תחנון =====
    if any(x in str(events) for x in [
        "Rosh Chodesh", "Chanukah", "Pesach",
        "Shavuot", "Sukkot", "Yom HaAtzmaut"
    ]):
        changes.append("תחנון: לא אומרים")

    # ===== למנצח =====
    if any(x in str(events) for x in [
        "Rosh Chodesh", "Chanukah", "Pesach",
        "Shavuot", "Sukkot"
    ]):
        changes.append("למנצח: לא אומרים")

    # ===== מזמור לתודה =====
    if any(x in str(events) for x in ["Pesach"]):
        changes.append("מזמור לתודה: לא אומרים")

    # ===== יום ירושלים =====
    if is_yom_yerushalayim:
        changes.append("הלל: אומרים הלל שלם")

    # ===== ספירת העומר =====
    omer = get_omer_day(events)
    if omer:
        changes.append(f"ספירת העומר: {omer}")

    # ===== יום רגיל =====
    if not changes:
        return "📅 היום הכל כרגיל בתפילה"

    return "📅 שינויים בתפילה היום:\n\n" + "\n".join(sorted(set(changes)))

def send_message(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, data={
        "chat_id": CHAT_ID,
        "text": text
    })

def main():
    events = get_events()
    message = analyze_day(events)
    send_message(message)

if __name__ == "__main__":
    main()
