import os
from dotenv import load_dotenv
load_dotenv("/root/tradingbot/.env")

import json
import requests
import time
import pytz
from datetime import datetime, timedelta

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN_SIGNAL")
SIGNALS_CHANNEL = os.getenv("SIGNALS_CHANNEL")
IMAGES_DIR = "/root/tradingbot/images"
CURSORS_FILE = "/root/tradingbot/cursors_sessions.json"
_photo_ids = {}
_img_cursors = {}

SESSIONS = [
    {
        "name": "Tokyo",
        "emoji": "\U0001f30f",
        "open": (2, 0),
        "close": (11, 0),
        "pairs": "USD/JPY \U0001f1ef\U0001f1f5 AUD/USD \U0001f1e6\U0001f1fa NZD/USD \U0001f1f3\U0001f1ff XAU/USD \U0001fa99",
        "note": "Slower, range-bound market. Crypto most active 24/7.",
        "images_open":  ["tokyo.jpg", "tokyo_2.jpg", "tokyo_3.jpg", "tokyo_4.jpg"],
        "images_close": ["signals_3.jpg", "signals_5.jpg", "signals.jpg", "signals_2.jpg"],
    },
    {
        "name": "London",
        "emoji": "\U0001f1ec\U0001f1e7",
        "open": (10, 0),
        "close": (19, 0),
        "pairs": "EUR/USD \U0001f1ea\U0001f1fa GBP/USD \U0001f1ec\U0001f1e7 XAU/USD \U0001fa99 Oil ⛽",
        "note": "Trend direction often set here. High volume, sharp moves.",
        "images_open":  ["london.jpg", "london_2.jpg", "london_3.jpg", "london_4.jpg"],
        "images_close": ["signals_2.jpg", "signals_4.jpg", "signals_3.jpg", "signals_5.jpg"],
    },
    {
        "name": "New York",
        "emoji": "\U0001f5fd",
        "open": (16, 0),
        "close": (23, 0),
        "pairs": "EUR/USD \U0001f1ea\U0001f1fa GBP/USD \U0001f1ec\U0001f1e7 XAU/USD \U0001fa99 USD/CAD \U0001f1e8\U0001f1e6",
        "note": "Peak liquidity 16:00–19:00 (London/NY overlap). Strongest moves of the day.",
        "images_open":  ["ny.jpg", "ny_2.jpg", "ny_3.jpg", "ny_4.jpg"],
        "images_close": ["signals.jpg", "signals_3.jpg", "signals_4.jpg", "signals_5.jpg"],
    },
]


def _load_cursors():
    global _img_cursors
    try:
        if os.path.exists(CURSORS_FILE):
            with open(CURSORS_FILE) as f:
                _img_cursors = json.load(f)
    except Exception as e:
        print(f"load cursors error: {e}")

def _save_cursors():
    try:
        tmp = CURSORS_FILE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(_img_cursors, f)
        os.replace(tmp, CURSORS_FILE)
    except Exception as e:
        print(f"save cursors error: {e}")

def _next_photo(category, pool):
    idx = _img_cursors.get(category, 0)
    _img_cursors[category] = (idx + 1) % len(pool)
    _save_cursors()
    return pool[idx]


def send_photo(photo_name, caption):
    if not SIGNALS_CHANNEL or not TELEGRAM_TOKEN:
        return
    path = os.path.join(IMAGES_DIR, photo_name)
    cap = caption[:1024]
    try:
        fid = _photo_ids.get(photo_name)
        if fid:
            r = requests.post(
                "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendPhoto",
                json={"chat_id": SIGNALS_CHANNEL, "photo": fid, "caption": cap},
                timeout=15,
            )
            if not r.ok:
                _photo_ids.pop(photo_name, None)
                fid = None
        if not fid and os.path.exists(path):
            with open(path, "rb") as pf:
                r = requests.post(
                    "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendPhoto",
                    files={"photo": ("image.jpg", pf, "image/jpeg")},
                    data={"chat_id": SIGNALS_CHANNEL, "caption": cap},
                    timeout=15,
                )
            photos = r.json().get("result", {}).get("photo", [])
            if photos:
                _photo_ids[photo_name] = photos[-1]["file_id"]
        elif not fid:
            requests.post(
                "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage",
                json={"chat_id": SIGNALS_CHANNEL, "text": cap},
                timeout=10,
            )
            return
        r.raise_for_status()
    except Exception as e:
        print(f"send_photo error: {e}")


def get_active_sessions(now_hour, now_min):
    active = []
    for s in SESSIONS:
        oh, om = s["open"]
        ch, cm = s["close"]
        if oh * 60 + om <= now_hour * 60 + now_min < ch * 60 + cm:
            active.append(s["name"])
    return active


def main():
    print("Session alerts started...")
    _load_cursors()
    tz = pytz.timezone("Europe/Athens")
    sent = {}

    while True:
        try:
            now = datetime.now(tz)
            weekday = now.weekday()

            if weekday >= 5:
                days_until_monday = (7 - weekday) % 7
                monday = (now + timedelta(days=days_until_monday)).replace(
                    hour=0, minute=1, second=0, microsecond=0
                )
                sleep_secs = max(60, (monday - now).total_seconds())
                time.sleep(min(sleep_secs, 86400))
                continue

            hour = now.hour
            minute = now.minute
            today = now.strftime("%Y-%m-%d")
            time_str = now.strftime("%H:%M")

            for s in SESSIONS:
                oh, om = s["open"]
                ch, cm = s["close"]

                # ── OPEN alert (fires at session open time) ──────────────
                open_key = s["name"] + "_open_" + today
                if hour == oh and om <= minute < om + 5 and open_key not in sent:
                    active = get_active_sessions(hour, minute)
                    active_str = " | ".join(a for a in active if a != s["name"]) or "—"
                    overlap_note = ""
                    if s["name"] == "New York":
                        overlap_note = "\n\n\U0001f525 London/NY OVERLAP active until 19:00\nHighest liquidity of the day — strong moves expected"
                    msg = (
                        s["emoji"] + " " + s["name"].upper() + " SESSION OPEN\n\n"
                        "\U0001f552 " + time_str + " Athens\n\n"
                        "\U0001f4b1 Watch: " + s["pairs"] + "\n\n"
                        + s["note"]
                        + overlap_note
                    )
                    photo = _next_photo(s["name"] + "_open", s["images_open"])
                    send_photo(photo, msg)
                    sent[open_key] = True
                    print("Sent: " + s["name"] + " open alert")

                # ── CLOSE alert (fires at session close time) ─────────────
                close_key = s["name"] + "_close_" + today
                if hour == ch and cm <= minute < cm + 5 and close_key not in sent:
                    active = get_active_sessions(hour, minute)
                    still_active = [a for a in active if a != s["name"]]
                    next_str = " | ".join(still_active) if still_active else "Markets quiet until next session"
                    msg = (
                        "\U0001f534 " + s["name"].upper() + " SESSION CLOSED\n\n"
                        + s["emoji"] + " " + time_str + " Athens\n\n"
                        "Still active: " + next_str + "\n"
                        "Volatility on " + s["name"] + " pairs may decrease."
                    )
                    photo = _next_photo(s["name"] + "_close", s["images_close"])
                    send_photo(photo, msg)
                    sent[close_key] = True
                    print("Sent: " + s["name"] + " close alert")

        except Exception as e:
            print("Error: " + str(e))

        time.sleep(60)


if __name__ == "__main__":
    main()
