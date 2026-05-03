import requests
import os
from datetime import datetime, date
from convertdate import hebrew

TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

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

        if u:
            return f"{t}״{u}"
        else:
            return f"{t}׳"

    return str(n)


# ===== שנה עברית =====
def hebrew_year(y):
    y = y % 1000

    mapping = [
        (400, "ת"), (300, "ש"), (200, "ר"), (100, "ק"),
        (90, "צ"), (80, "פ"), (70, "ע"), (60, "ס"), (50, "נ"),
        (40, "מ"), (30, "ל"), (20, "כ"), (10, "י"),
        (9, "ט"), (8, "ח"), (7, "ז"), (6, "ו"), (5, "ה"),
        (4, "ד"), (3, "ג"), (2, "ב"), (1, "א")
    ]

    result = ""
    for val, letter in mapping:
        while y >= val:
            result += letter
            y -= val

    if len(result) > 1:
        return result[:-1] + "״" + result[-1]
    else:
        return result + "׳"


# ===== תאריך עברי =====
def get_hebrew_date():
    today = date.today()
    h_year, h_month, h_day = hebrew.from_gregorian(today.year, today.month, today.day)

    months = [
        "", "ניסן", "אייר", "סיון", "תמוז", "אב",
        "אלול", "תשרי", "חשוון", "כסלו", "טבת", "שבט", "אדר"
    ]

    weekday_names = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]
    weekday = weekday_names[datetime.now().weekday()]

    day_str = hebrew_number(h_day)
    year_str = hebrew_year(h_year)

    return f"יום {weekday}, {day_str} ב{months[h_month]} {year_str}"


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

        res = requests.get(url, params=params, timeout=5)
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

    # ===== עומר (לערבית = יום הבא) =====
    omer_day = calculate_omer()
    if omer_day:
        arvit.append(f"ספירת העומר: היום {omer_day + 1} לעומר")

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
