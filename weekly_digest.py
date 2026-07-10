"""Weekly trade digest — a grid collage of every trade closed in the last 7
days, regenerated from journal.json (which performance_tracker.py now stores
enough data in — symbol/entry/sl/tp/entry_time — to rebuild each chart).
Posted to SIGNALS_CHANNEL on Sundays, after the backtest report.
"""
import os
from dotenv import load_dotenv
load_dotenv("/root/tradingbot/.env")

import json
import time
import requests
import pytz
from datetime import datetime

try:
    import chart
except Exception as _chart_import_err:
    chart = None
    print(f"chart module unavailable: {_chart_import_err}")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN_SIGNAL")
SIGNALS_CHANNEL = os.getenv("SIGNALS_CHANNEL")
if not TELEGRAM_TOKEN or not SIGNALS_CHANNEL:
    raise RuntimeError("TELEGRAM_TOKEN_SIGNAL and SIGNALS_CHANNEL must be set in .env")

JOURNAL_FILE = "/root/tradingbot/journal.json"
SEND_HOUR = 21  # Athens Sunday, after the 20:00 backtest report


def send_channel_photo(photo_path, caption=""):
    if not photo_path or not os.path.exists(photo_path):
        return
    try:
        with open(photo_path, "rb") as pf:
            r = requests.post(
                "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendPhoto",
                files={"photo": ("digest.png", pf, "image/png")},
                data={"chat_id": SIGNALS_CHANNEL, "caption": caption[:1024]}, timeout=30,
            )
        r.raise_for_status()
        print("Weekly digest sent!")
    except Exception as e:
        print(f"send_channel_photo error: {e}")
    finally:
        try:
            os.remove(photo_path)
        except OSError:
            pass


def run_once():
    if chart is None:
        print("weekly_digest: chart module unavailable, skipping")
        return
    try:
        with open(JOURNAL_FILE) as f:
            entries = json.load(f)
    except (json.JSONDecodeError, ValueError, OSError, FileNotFoundError) as e:
        print(f"journal load error: {e}")
        return

    cutoff = time.time() - 7 * 86400
    week_entries = [e for e in entries if e.get("close_time", 0) >= cutoff]
    if not week_entries:
        print("No trades closed this week — skipping digest")
        return

    path = chart.make_weekly_collage(week_entries)
    send_channel_photo(path, caption="\U0001f4d3 WEEKLY TRADE DIGEST — every trade closed this week")


def main():
    print("Weekly digest bot started...")
    sent_this_week = ""
    while True:
        try:
            tz = pytz.timezone("Europe/Athens")
            now = datetime.now(tz)
            week = now.strftime("%Y-%W")
            if now.weekday() == 6 and now.hour == SEND_HOUR and now.minute < 10 and sent_this_week != week:
                sent_this_week = week
                print("Running weekly digest...")
                run_once()
        except Exception as e:
            print(f"Main error: {e}")
        time.sleep(300)


if __name__ == "__main__":
    main()
