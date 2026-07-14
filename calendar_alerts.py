"""Proactive economic calendar alerts — pings the news channel ~30 minutes
before a high-impact event, instead of only surfacing it in the 08:00 daily
calendar digest (calendar_bot.py). Reuses the same investing.com scrape
signal_strategy.py already uses for its news filter.
"""
import os
from dotenv import load_dotenv
load_dotenv("/root/tradingbot/.env")

import json
import time
import requests
import pytz
from datetime import datetime
from bs4 import BeautifulSoup

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN_SIGNAL")
CHANNEL_ID = os.getenv("TELEGRAM_NEWS_CHANNEL")
if not TELEGRAM_TOKEN or not CHANNEL_ID:
    raise RuntimeError("TELEGRAM_TOKEN_SIGNAL and TELEGRAM_NEWS_CHANNEL must be set in .env")

STATE_FILE = "/root/tradingbot/calendar_alerts_state.json"
SCAN_INTERVAL = 300  # 5 minutes — fine enough to reliably land in the 25-35min pre-event window
LEAD_MIN_LOW = 20
LEAD_MIN_HIGH = 35


def _load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError, OSError) as e:
            print(f"load state error: {e}")
    return {}


def _save_state(state):
    tmp = STATE_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(state, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        print(f"save state error: {e}")


def get_high_impact_events():
    """Same investing.com endpoint signal_strategy.py's news filter uses,
    importance=3 (highest) only, but keeping the event name/time/currency
    instead of collapsing to a blocked-currency set."""
    try:
        tz = pytz.timezone("Europe/Athens")
        today = datetime.now(tz).strftime("%Y-%m-%d")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://www.investing.com/economic-calendar/",
        }
        payload = {"dateFrom": today, "dateTo": today, "importance[]": ["3"]}
        r = requests.post(
            "https://www.investing.com/economic-calendar/Service/getCalendarFilteredData",
            headers=headers, data=payload, timeout=15,
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.json().get("data", ""), "html.parser")
        events = []
        for row in soup.find_all("tr", id=lambda x: x and x.startswith("eventRowId_")):
            try:
                time_td = row.find("td", class_="first")
                currency_td = row.find("td", class_="flagCur")
                event_td = row.find("td", class_="event")
                forecast_td = row.find("td", class_="forecast")
                previous_td = row.find("td", class_="previous")
                if not all([time_td, currency_td, event_td]):
                    continue
                event_time_str = time_td.text.strip()
                if not event_time_str or "Day" in event_time_str or ":" not in event_time_str:
                    continue
                events.append({
                    "time": event_time_str,
                    "currency": currency_td.text.strip(),
                    "title": event_td.text.strip(),
                    "forecast": forecast_td.text.strip() if forecast_td else "",
                    "previous": previous_td.text.strip() if previous_td else "",
                })
            except Exception as e:
                print(f"calendar row parse error: {e}")
        return events
    except Exception as e:
        print(f"get_high_impact_events error: {e}")
        return []


def send_alert(event, minutes_until):
    msg = (
        "⏰ UPCOMING HIGH-IMPACT EVENT\n\n"
        + "\U0001f534 " + event["currency"] + " | " + event["title"] + "\n"
        "In ~" + str(minutes_until) + " minutes (" + event["time"] + ")\n"
    )
    if event["forecast"] or event["previous"]:
        msg += "\U0001f4ca Forecast: " + event["forecast"] + " | Previous: " + event["previous"] + "\n"
    msg += "\nExpect volatility on " + event["currency"] + "-related pairs."
    try:
        r = requests.post(
            "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage",
            json={"chat_id": CHANNEL_ID, "text": msg}, timeout=10,
        )
        r.raise_for_status()
        print(f"Calendar alert sent: {event['currency']} {event['title']}")
        return True
    except Exception as e:
        print(f"send_alert error: {e}")
        return False


def main():
    print("Calendar alerts bot started...")
    state = _load_state()
    # Initialise to today so a cold start doesn't reset persisted dedup state
    tz0 = pytz.timezone("Europe/Athens")
    last_date = datetime.now(tz0).strftime("%Y-%m-%d")
    while True:
        try:
            tz = pytz.timezone("Europe/Athens")
            now = datetime.now(tz)
            today = now.strftime("%Y-%m-%d")
            if today != last_date:
                state = {}  # fresh dedup state each day
                last_date = today

            events = get_high_impact_events()
            state_changed = False
            for event in events:
                try:
                    event_dt = tz.localize(datetime.strptime(today + " " + event["time"], "%Y-%m-%d %H:%M"))
                except Exception as e:
                    # ValueError for bad format; pytz AmbiguousTimeError/NonExistentTimeError at DST transitions
                    print(f"calendar_alerts: time parse error for '{event.get('time')}': {e}")
                    continue
                minutes_until = (event_dt - now).total_seconds() / 60
                key = event["currency"] + "_" + event["title"] + "_" + event["time"]
                if LEAD_MIN_LOW <= minutes_until <= LEAD_MIN_HIGH and key not in state:
                    if send_alert(event, round(minutes_until)):
                        state[key] = True  # only mark sent if Telegram delivery succeeded
                        state_changed = True
            # Only write to disk when state actually changed (saves unnecessary I/O every 5 min)
            if state_changed:
                _save_state(state)
        except Exception as e:
            print(f"Main error: {e}")

        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    main()
