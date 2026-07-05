import os
from dotenv import load_dotenv
load_dotenv("/root/tradingbot/.env")

import html as _html
import requests
import time
import random
import feedparser
import anthropic
from datetime import datetime
import pytz

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN_SIGNAL")
CHANNEL_ID = os.getenv("TELEGRAM_NEWS_CHANNEL")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
IMAGES_DIR = "/root/tradingbot/images"
_photo_ids = {}

def send_photo_channel(photo_name, caption="", parse_mode=None):
    path = os.path.join(IMAGES_DIR, photo_name)
    cap = caption[:1024]
    try:
        fid = _photo_ids.get(photo_name)
        if fid and os.path.exists(path):
            payload = {"chat_id": CHANNEL_ID, "photo": fid, "caption": cap, "disable_web_page_preview": True}
            if parse_mode:
                payload["parse_mode"] = parse_mode
            r = requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendPhoto",
                json=payload, timeout=15)
        elif os.path.exists(path):
            data = {"chat_id": CHANNEL_ID, "caption": cap, "disable_web_page_preview": "true"}
            if parse_mode:
                data["parse_mode"] = parse_mode
            with open(path, "rb") as pf:
                r = requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendPhoto",
                    files={"photo": ("image.jpg", pf, "image/jpeg")},
                    data=data, timeout=15)
            photos = r.json().get("result", {}).get("photo", [])
            if photos:
                _photo_ids[photo_name] = photos[-1]["file_id"]
        else:
            # Fallback: text only
            r = requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendMessage",
                json={"chat_id": CHANNEL_ID, "text": cap, "disable_web_page_preview": True,
                      **({"parse_mode": parse_mode} if parse_mode else {})}, timeout=15)
        r.raise_for_status()
    except Exception as e:
        print(f"send_photo error: {e}")

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
    7:  ["🌍 MARKETS OPEN BRIEF", "📰 EARLY MORNING UPDATE", "🌅 PRE-MARKET SNAPSHOT"],
    8:  ["🌅 GOOD MORNING BRIEF", "☕ MORNING MARKET WRAP", "📊 START OF DAY BRIEFING"],
    12: ["📊 MIDDAY UPDATE", "🌍 NOON MARKETS BRIEF", "⚡ MIDDAY SNAPSHOT"],
    16: ["📈 AFTERNOON UPDATE", "🔔 MARKET MID-SESSION", "🌍 AFTERNOON BRIEF"],
    20: ["🌆 EVENING WRAP", "📉 END OF SESSION UPDATE", "🌍 EVENING MARKETS BRIEF"],
    23: ["🌙 DAY SUMMARY", "🌃 LATE NIGHT BRIEF", "📋 CLOSING WRAP"],
}

def get_greece_time():
    tz = pytz.timezone("Europe/Athens")
    return datetime.now(tz).strftime("%d/%m/%Y %H:%M")

def collect_news():
    headlines = []    # list of (title, url)
    high_impact = []  # list of (title, url)
    for feed_url in FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:20]:
                title = entry.get("title","")
                url = entry.get("link","")
                title_lower = title.lower()
                if any(k in title_lower for k in HIGH_IMPACT):
                    high_impact.append((title, url))
                elif any(k in title_lower for k in KEYWORDS):
                    headlines.append((title, url))
        except Exception as e:
            print(f"collect_news feed error {feed_url}: {e}")
    # high-impact first, deduplicate by title
    combined = []
    seen = set()
    for item in high_impact + headlines:
        if item[0] not in seen:
            seen.add(item[0])
            combined.append(item)
    return combined[:40]

REPORT_STYLES = [
    {
        "system": "You are a sharp forex news editor. Write 5 punchy bullet points for traders. Each under 15 words. Start each with a relevant emoji. No headers.",
        "user": "What are the 5 most market-moving stories right now? Be direct.\n\nHeadlines:\n{headlines}"
    },
    {
        "system": "You are a senior market analyst briefing a trading desk. Write naturally, 3-4 short paragraphs. Use emojis. Focus on what matters for EUR, USD, Gold, Oil positions.",
        "user": "Brief the desk on today's key developments and their trading implications.\n\nHeadlines:\n{headlines}"
    },
    {
        "system": "You are a concise financial journalist. Pick the 3 most important stories, explain each in 2 sentences: what happened + why it matters for forex/crypto traders. Use emojis.",
        "user": "What should traders know right now?\n\nHeadlines:\n{headlines}"
    },
    {
        "system": "You are a forex trader sharing key news with your community. Write conversationally, 4-6 lines. Use emojis. Highlight risk events and opportunities.",
        "user": "Share the most relevant news for traders right now in a natural, engaging way.\n\nHeadlines:\n{headlines}"
    },
    {
        "system": "You are a market intelligence analyst. Group the news into themes (geopolitical / macro / commodities) and give 1-2 sentences per theme. Use emojis. Plain text only.",
        "user": "Analyze today's headlines by theme and explain the trading impact.\n\nHeadlines:\n{headlines}"
    },
]

def create_report(items):
    if not items:
        return None, []
    titles = [t for t, u in items]
    top_links = [(t, u) for t, u in items[:6] if u][:4]
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        style = random.choice(REPORT_STYLES)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=380,
            system=style["system"],
            messages=[{"role":"user","content":style["user"].format(headlines="\n".join(titles[:10]))}]
        )
        return message.content[0].text, top_links
    except Exception as e:
        print("AI error: "+str(e))
        return None, []

def send_channel(msg, parse_mode=None):
    try:
        payload = {"chat_id": CHANNEL_ID, "text": msg[:4096], "disable_web_page_preview": True}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        r = requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendMessage",
            json=payload, timeout=10)
        r.raise_for_status()
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
                items = collect_news()
                if items:
                    report, top_links = create_report(items)
                    if report:
                        header = random.choice(SCHEDULE[hour])
                        base = _html.escape(header)+"\n🕔 "+_html.escape(now_str)+"\n\n"+_html.escape(report)
                        if top_links:
                            links_section = "\n\n📎 Read more:\n"
                            for title, url in top_links:
                                short = title[:55]+"…" if len(title) > 55 else title
                                safe_url = url.replace("&", "&amp;")
                                links_section += f'• <a href="{safe_url}">{_html.escape(short)}</a>\n'
                            links_str = links_section.rstrip()
                            max_base = 1024 - len(links_str)
                            msg = base[:max_base] + links_str
                            parse_mode = "HTML"
                        else:
                            msg = base
                            parse_mode = None
                        send_photo_channel("news.jpg", caption=msg, parse_mode=parse_mode)
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
