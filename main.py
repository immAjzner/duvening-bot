import requests
from datetime import datetime

import os
TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

def get_hebrew_calendar():
    today = datetime.now().strftime("%Y-%m-%d")
    url = f"https://www.hebcal.com/converter?g2h=1&date={today}&json=1"
    return requests.get(url).json()

def get_events():
    today = datetime.now().strftime("%Y-%m-%d")
    url = f"https://www.hebcal.com/hebcal?v=1&cfg=json&maj=on&min=on&mod=on&nx=on&year=now&month=x&ss=off&mf=off&c=on&geo=geoname&geonameid=2925533"
    data = requests.get(url).json()
    return [item["title"] for item in data["items"] if item["date"].startswith(today)]

def analyze_day(events):
    changes = []

    # חגים מרכזיים
    if any("Rosh Chodesh" in e for e in events):
        changes.append("הלל: אומרים הלל בדילוג")
        changes.append("תחנון: לא אומרים")
    
    if any("Chanukah" in e for e in events):
        changes.append("הלל: אומרים הלל שלם")
        changes.append("תחנון: לא אומרים")

    if any("Pesach" in e for e in events):
        changes.append("הלל: תלוי ביום (בד״כ בדילוג בחול המועד)")
        changes.append("תחנון: לא אומרים")

    if any("Shavuot" in e for e in events):
        changes.append("הלל: אומרים הלל שלם")
        changes.append("תחנון: לא אומרים")

    if any("Sukkot" in e for e in events):
        changes.append("הלל: אומרים הלל שלם (בחג), בדילוג בחול המועד")
        changes.append("תחנון: לא אומרים")

    # יום העצמאות (ציוני)
    if any("Yom HaAtzmaut" in e for e in events):
        changes.append("הלל: אומרים הלל שלם")
        changes.append("תחנון: לא אומרים")

    # יום ירושלים
    if any("Yom Yerushalayim" in e for e in events):
        changes.append("הלל: אומרים הלל שלם")

    # ברירת מחדל
    if not changes:
        return "📅 היום הכל כרגיל בתפילה"

    return "📅 שינויים בתפילה היום:\n\n" + "\n".join(changes)

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
