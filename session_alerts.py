import os
from dotenv import load_dotenv
load_dotenv("/root/tradingbot/.env")

import requests
import time
import pytz
from datetime import datetime, timedelta

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN_SIGNAL")
NEWS_CHANNEL = os.getenv("TELEGRAM_NEWS_CHANNEL")

SESSIONS = [
    {"name": "Tokyo", "emoji": "\U0001f30f", "open": (2,0), "close": (11,0), "color": "🔵"},
    {"name": "London", "emoji": "\U0001f1ec\U0001f1e7", "open": (10,0), "close": (19,0), "color": "🟢"},
    {"name": "New York", "emoji": "\U0001f1fa\U0001f1f8", "open": (16,0), "close": (23,0), "color": "🔴"},
]

def send_all(msg):
    try:
        r = requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendMessage",
            json={"chat_id": NEWS_CHANNEL, "text": msg[:4000]}, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"send_all error: {e}")
        raise

def get_session_status(now_hour, now_min):
    active = []
    for s in SESSIONS:
        oh, om = s["open"]
        ch, cm = s["close"]
        open_mins = oh*60 + om
        close_mins = ch*60 + cm
        curr_mins = now_hour*60 + now_min
        if open_mins <= curr_mins < close_mins:
            active.append(s["name"])
    return active

def main():
    print("Session alerts started...")
    tz = pytz.timezone("Europe/Athens")
    sent = {}

    while True:
        try:
            now = datetime.now(tz)
            weekday = now.weekday()

            if weekday == 5 or weekday == 6:
                # Sleep until Monday 00:01 instead of looping every hour for 48h
                # weekday is 5 or 6 here, so (7 - weekday) % 7 is always 1 or 2
                days_until_monday = (7 - weekday) % 7
                monday = (now + timedelta(days=days_until_monday)).replace(
                    hour=0, minute=1, second=0, microsecond=0
                )
                sleep_secs = max(60, (monday - now).total_seconds())
                time.sleep(min(sleep_secs, 86400))  # cap at 24h in case of clock issues
                continue

            hour = now.hour
            minute = now.minute

            for s in SESSIONS:
                oh, om = s["open"]
                ch, cm = s["close"]

                # Alert 30 min before open
                alert_hour = oh
                alert_min = om - 30
                if alert_min < 0:
                    alert_hour -= 1
                    alert_min += 60

                alert_key_open = s["name"]+"_open_"+now.strftime("%Y-%m-%d")
                alert_key_close = s["name"]+"_close_"+now.strftime("%Y-%m-%d")

                if hour == alert_hour and alert_min <= minute < alert_min+5 and alert_key_open not in sent:
                    active = get_session_status(hour, minute)
                    active_str = " | ".join(active) if active else "None"
                    msg = (
                        "\U000023f0 SESSION OPENING SOON\n\n"
                        +s["emoji"]+" "+s["name"]+" opens in 30 minutes!\n\n"
                        "Currently active: "+active_str+"\n\n"
                        "\U0001f4a1 "+s["name"]+" session = higher volatility on:\n"
                    )
                    if s["name"] == "Tokyo":
                        msg += "JPY pairs, AUD/NZD pairs, Gold"
                    elif s["name"] == "London":
                        msg += "EUR, GBP pairs, Gold, Oil"
                    elif s["name"] == "New York":
                        msg += "USD pairs, Gold, Oil, S&P500"

                    if s["name"] == "New York":
                        # London (10:00–19:00) overlaps with NY (16:00–23:00); alert fires 30 min early
                        msg += "\n\n\U0001f525 OVERLAP: London + NY overlap starts in 30 minutes! Highest volatility period!"

                    send_all(msg)
                    sent[alert_key_open] = True
                    print("Sent: "+s["name"]+" opening alert")

                if hour == ch and cm <= minute < cm+5 and alert_key_close not in sent:
                    msg = (
                        "\U0001f534 SESSION CLOSING\n\n"
                        +s["emoji"]+" "+s["name"]+" session closing now.\n\n"
                        "Volatility may decrease on "+s["name"]+" pairs."
                    )
                    send_all(msg)
                    sent[alert_key_close] = True
                    print("Sent: "+s["name"]+" closing alert")

        except Exception as e:
            print("Error: "+str(e))

        time.sleep(60)

if __name__ == "__main__":
    main()
