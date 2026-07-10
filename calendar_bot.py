import os
from dotenv import load_dotenv
load_dotenv("/root/tradingbot/.env")

import requests
import time
import anthropic
from datetime import datetime
from bs4 import BeautifulSoup
import pytz

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN_SIGNAL")
if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN_SIGNAL is not set in environment")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    print("Warning: ANTHROPIC_API_KEY not set — AI calendar summaries will be unavailable")
CHANNEL_ID = os.getenv("TELEGRAM_NEWS_CHANNEL")
if not CHANNEL_ID:
    raise RuntimeError("TELEGRAM_NEWS_CHANNEL is not set in environment")

def send_channel(msg):
    try:
        r = requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendMessage",
            json={"chat_id": CHANNEL_ID, "text": msg[:4000]}, timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"send_channel error: {e}")
        return False


def get_calendar():
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://www.investing.com/economic-calendar/"
        }
        tz_athens = pytz.timezone("Europe/Athens")
        today = datetime.now(tz_athens).strftime("%Y-%m-%d")
        payload = {"dateFrom": today, "dateTo": today, "importance[]": ["2", "3"]}
        r = requests.post("https://www.investing.com/economic-calendar/Service/getCalendarFilteredData", headers=headers, data=payload, timeout=15)
        r.raise_for_status()
        data = r.json()
        html = data.get("data","")
        soup = BeautifulSoup(html, "html.parser")
        events = []
        for row in soup.find_all("tr", id=lambda x: x and x.startswith("eventRowId_")):
            try:
                time_td = row.find("td", class_="first")
                currency_td = row.find("td", class_="flagCur")
                impact_td = row.find("td", class_="sentiment")
                event_td = row.find("td", class_="event")
                forecast_td = row.find("td", class_="forecast")
                previous_td = row.find("td", class_="previous")

                if not all([time_td, currency_td, event_td]):
                    continue

                impact_bulls = len(impact_td.find_all("i", class_="grayFullBullishIcon")) if impact_td else 0
                if impact_bulls < 2:
                    continue

                event_time = time_td.text.strip()
                currency = currency_td.text.strip()
                event_name = event_td.text.strip()
                forecast = forecast_td.text.strip() if forecast_td else ""
                previous = previous_td.text.strip() if previous_td else ""

                if currency not in ["USD","EUR","GBP","JPY","CHF","AUD","CAD","NZD"]:
                    continue

                impact_emoji = "\U0001f534" if impact_bulls >= 3 else "\U0001f7e1"
                events.append({
                    "time": event_time,
                    "currency": currency,
                    "title": event_name,
                    "forecast": forecast,
                    "previous": previous,
                    "impact": impact_emoji,
                    "bulls": impact_bulls
                })
            except Exception as e:
                print(f"Calendar row parse error: {e}")
                continue
        return events
    except Exception as e:
        print("Calendar error: "+str(e))
        return []

def get_analysis(events):
    if not events:
        return ""
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        events_text = "\n".join([e["time"]+" "+e["currency"]+" "+e["title"]+" Forecast:"+e["forecast"]+" Previous:"+e["previous"] for e in events])
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            system="You are a forex analyst. Write in simple English only. No markdown.",
            messages=[{"role":"user","content":"Look at these economic events for today and write 3-4 simple sentences about what traders should watch. Which pairs will move most?\n\nEvents:\n"+events_text}]
        )
        return message.content[0].text if message.content else ""
    except Exception as e:
        print(f"get_analysis error: {e}")
        return ""

def format_message(events, analysis):
    tz = pytz.timezone("Europe/Athens")
    today = datetime.now(tz).strftime("%d/%m/%Y")
    lines = ["\U0001f4c5 ECONOMIC CALENDAR\n\U0001f554 " + today + "\n"]

    if not events:
        lines.append("No high impact events today.")
    else:
        for e in events:
            lines.append(e["impact"] + " " + e["time"] + " | " + e["currency"] + " | " + e["title"])
            if e["forecast"] or e["previous"]:
                lines.append("   \U0001f4ca Forecast: " + e["forecast"] + " | Previous: " + e["previous"])

        if analysis:
            lines.append("\n\U0001f4a1 ANALYST NOTE:\n" + analysis)

    return "\n".join(lines)

def main():
    print("Economic Calendar bot started...")
    sent_today = ""
    while True:
        try:
            tz = pytz.timezone("Europe/Athens")
            now = datetime.now(tz)
            today = now.strftime("%Y-%m-%d")
            hour = now.hour
            minute = now.minute

            if hour == 8 and minute < 10 and sent_today != today:
                print("Sending calendar...")
                events = get_calendar()
                analysis = get_analysis(events)
                msg = format_message(events, analysis)
                if send_channel(msg):
                    sent_today = today
                    print("Calendar sent! "+str(len(events))+" events")
                    time.sleep(600)
                else:
                    # send failed — sleep to avoid spinning hot in the 8:00-8:09 window
                    time.sleep(60)
            else:
                time.sleep(300)

        except Exception as e:
            print("Error: "+str(e))
            time.sleep(60)

if __name__ == "__main__":
    main()
