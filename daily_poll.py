"""Daily engagement poll — posts a simple Bullish/Bearish poll on a rotating
pair to the news channel once a day. Separate from sentiment_bot.py's AI Fear &
Greed read; this is community engagement, not a data-driven signal.
"""
import os
from dotenv import load_dotenv
load_dotenv("/root/tradingbot/.env")

import json
import time
import requests
import pytz
from datetime import datetime

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN_SIGNAL")
CHANNEL_ID = os.getenv("TELEGRAM_NEWS_CHANNEL")
if not TELEGRAM_TOKEN or not CHANNEL_ID:
    raise RuntimeError("TELEGRAM_TOKEN_SIGNAL and TELEGRAM_NEWS_CHANNEL must be set in .env")

CURSOR_FILE = "/root/tradingbot/cursors_poll.json"
SEND_HOUR = 10  # Athens time

PAIRS = ["EUR/USD", "GBP/USD", "XAU/USD", "BTC/USD", "Oil/USD", "USD/JPY", "AUD/USD", "USD/CAD"]


def _load_cursor():
    if os.path.exists(CURSOR_FILE):
        try:
            with open(CURSOR_FILE) as f:
                return json.load(f).get("idx", 0)
        except (json.JSONDecodeError, ValueError, OSError) as e:
            print(f"load cursor error: {e}")
    return 0


def _save_cursor(idx):
    tmp = CURSOR_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump({"idx": idx}, f)
        os.replace(tmp, CURSOR_FILE)
    except Exception as e:
        print(f"save cursor error: {e}")


def send_poll(pair):
    try:
        r = requests.post(
            "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendPoll",
            json={
                "chat_id": CHANNEL_ID,
                "question": "\U0001f4ca " + pair + " — Bullish or Bearish today?",
                "options": ["\U0001f7e2 Bullish", "\U0001f534 Bearish"],
                "is_anonymous": True,
                "type": "regular",
            },
            timeout=10,
        )
        r.raise_for_status()
        print(f"Poll sent: {pair}")
        return True
    except Exception as e:
        print(f"send_poll error: {e}")
        return False


def run_once():
    idx = _load_cursor()
    pair = PAIRS[idx % len(PAIRS)]
    # Only advance cursor if the poll was actually sent so a failed poll is retried next run
    if send_poll(pair):
        _save_cursor((idx + 1) % len(PAIRS))


def main():
    print("Daily poll bot started...")
    sent_today = ""
    while True:
        try:
            tz = pytz.timezone("Europe/Athens")
            now = datetime.now(tz)
            today = now.strftime("%Y-%m-%d")
            if now.hour == SEND_HOUR and now.minute < 10 and sent_today != today:
                print("Sending daily poll...")
                run_once()
                # Mark sent AFTER run_once so a failure lets the next tick retry
                sent_today = today
        except Exception as e:
            print(f"Main error: {e}")
        time.sleep(300)


if __name__ == "__main__":
    main()
