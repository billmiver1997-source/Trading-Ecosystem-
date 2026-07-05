import os
from dotenv import load_dotenv
load_dotenv("/root/tradingbot/.env")

import requests
import time
import feedparser
import anthropic
from datetime import datetime
import pytz

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN_SIGNAL")
CHANNEL_ID = os.getenv("TELEGRAM_NEWS_CHANNEL")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

FEEDS = [
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://rss.reuters.com/reuters/worldNews",
    "https://www.forexlive.com/feed/news",
    "https://feeds.skynews.com/feeds/rss/world.xml",
    "https://www.aljazeera.com/xml/rss/all.xml"
]

KEYWORDS = [
    "war","attack","missile","nuclear","sanction","invasion","conflict","crisis",
    "fed","rate","inflation","recession","gdp","central bank","ecb","boe",
    "trump","election","president","government","nato",
    "oil","gold","silver","copper","commodit",
    "dollar","euro","pound","yen","forex","currency",
    "crash","rally","market","stock","bond",
    "russia","ukraine","zelensky","kyiv","ceasefire",
    "iran","israel","middle east","china","putin",
    "tariff","trade","default","debt","imf"
]

HIGH_IMPACT = [
    "war","attack","missile","nuclear","invasion","ceasefire","coup",
    "fed rate","rate decision","rate hike","rate cut","inflation data",
    "trump tariff","sanctions","earthquake","tsunami"
]

# Schedule: 07:00 night summary, 08:00 morning, 12:00, 16:00, 20:00 updates, 23:00 day summary
SCHEDULE = {
    7:  "🌍 WORLD & 📈 MARKETS UPDATE",
    8:  "🌅 GOOD MORNING BRIEF",
    12: "🌍 WORLD & 📈 MARKETS UPDATE",
    16: "🌍 WORLD & 📈 MARKETS UPDATE",
    20: "🌍 WORLD & 📈 MARKETS UPDATE",
    23: "🌙 DAY SUMMARY",
}

def get_greece_time():
    tz = pytz.timezone("Europe/Athens")
    return datetime.now(tz).strftime("%d/%m/%Y %H:%M")

def collect_news():
    headlines = []
    high_impact = []
    for feed_url in FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:20]:
                title = entry.get("title","")
                title_lower = title.lower()
                if any(k in title_lower for k in HIGH_IMPACT):
                    high_impact.append(title)
                elif any(k in title_lower for k in KEYWORDS):
                    headlines.append(title)
        except Exception as e:
            print(f"collect_news feed error {feed_url}: {e}")
    # high-impact headlines first, then general; deduplicate while preserving order
    combined = []
    seen = set()
    for h in high_impact + headlines:
        if h not in seen:
            seen.add(h)
            combined.append(h)
    return combined[:40]

def create_report(headlines):
    if not headlines:
        return None
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=250,
            system="You are a concise forex news editor. Respond with MAXIMUM 5 short bullet points. Each bullet MUST be under 15 words. Start each bullet with a relevant emoji. NO headers, NO sections, NO long paragraphs.",
            messages=[{"role":"user","content":"Summarize the most important market-moving news for forex traders right now in 5 bullet points.\n\nHeadlines:\n"+"\n".join(headlines[:8])}]
        )
        return message.content[0].text
    except Exception as e:
        print("AI error: "+str(e))
        return None

def send_channel(msg):
    try:
        for i in range(0, len(msg), 4000):
            r = requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendMessage",
                json={"chat_id": CHANNEL_ID, "text": msg[i:i+4000]}, timeout=10)
            r.raise_for_status()
            time.sleep(0.5)
    except Exception as e:
        print("Send error: "+str(e))

def main():
    print("News bot started...")
    sent_today = {}

    while True:
        try:
            tz = pytz.timezone("Europe/Athens")
            now = datetime.now(tz)
            hour = now.hour
            minute = now.minute
            today = now.strftime("%Y-%m-%d")

            # Silence 01:00 - 06:59; sleep until 06:55 to avoid missing the 07:00 window
            if 1 <= hour < 7:
                print("Silence hours - sleeping...")
                _now = datetime.now(tz)
                _wake = _now.replace(hour=6, minute=55, second=0, microsecond=0)
                _secs = max(60, (_wake - _now).total_seconds())
                time.sleep(min(_secs, 1800))
                continue

            # Check schedule
            send_key = today+"_"+str(hour)
            if hour in SCHEDULE and minute < 10 and send_key not in sent_today:
                now_str = get_greece_time()
                print(f"Sending {hour}:00 update...")
                headlines = collect_news()
                if headlines:
                    report = create_report(headlines)
                    if report:
                        header = SCHEDULE[hour]
                        send_channel(header+"\n🕔 "+now_str+"\n\n"+report)
                        print(f"Sent {hour}:00 update!")
                sent_today[send_key] = True  # mark attempted regardless to prevent duplicate sends
                time.sleep(600)
                continue

            time.sleep(300)

        except Exception as e:
            print("Error: "+str(e))
            time.sleep(60)

if __name__ == "__main__":
    main()
