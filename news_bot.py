import os
from dotenv import load_dotenv
load_dotenv("/root/tradingbot/.env")

import html as _html
import json
import re
import requests
import time
import random
import feedparser
import anthropic
from datetime import datetime, timedelta
import pytz

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN_SIGNAL")
CHANNEL_ID = os.getenv("TELEGRAM_NEWS_CHANNEL")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
IMAGES_DIR = "/root/tradingbot/images"
CURSORS_FILE = "/root/tradingbot/cursors_news.json"
NEWS_IMAGES = ["news.jpg", "news_2.jpg", "news_3.jpg", "news_4.jpg"]
_photo_ids = {}
_img_cursors = {}

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

def send_photo_channel(photo_name, caption="", parse_mode=None):
    """photo_name is either a filename in IMAGES_DIR (generic rotating stock photo)
    or a full http(s) URL — Telegram's sendPhoto accepts a remote URL directly, so
    an actual article image needs no download/upload. Falls back to the generic
    pool if Telegram can't fetch the URL (e.g. the source blocks hotlinking)."""
    cap = caption[:1024]
    if isinstance(photo_name, str) and photo_name.startswith("http"):
        try:
            payload = {"chat_id": CHANNEL_ID, "photo": photo_name, "caption": cap, "disable_web_page_preview": True}
            if parse_mode:
                payload["parse_mode"] = parse_mode
            r = requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendPhoto",
                json=payload, timeout=15)
            if r.ok:
                return
            print(f"send_photo_channel: article image URL rejected ({r.status_code}), falling back")
        except Exception as e:
            print(f"send_photo_channel article image error: {e}")
        photo_name = _next_photo("news", NEWS_IMAGES)

    path = os.path.join(IMAGES_DIR, photo_name)
    try:
        fid = _photo_ids.get(photo_name)
        if fid:
            payload = {"chat_id": CHANNEL_ID, "photo": fid, "caption": cap, "disable_web_page_preview": True}
            if parse_mode:
                payload["parse_mode"] = parse_mode
            r = requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendPhoto",
                json=payload, timeout=15)
            if not r.ok:
                # Stale file_id — evict cache and fall through to re-upload
                _photo_ids.pop(photo_name, None)
                fid = None
        if not fid and os.path.exists(path):
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
        elif not fid:
            # Fallback: text only (no fid and no image file on disk)
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

# Minimum acceptable quality for a photo sent to the channel: HD (1280x720).
# RSS feeds usually advertise several renditions of the same picture plus small
# thumbnails, so we pick the largest and, where the URL carries a size token,
# bump it up so the delivered image is at least HD.
MIN_HD_WIDTH = 1280
MIN_HD_HEIGHT = 720

def _media_dims(m):
    """Return (width, height) advertised for a media item, 0 when unknown."""
    def _to_int(v):
        try:
            return int(str(v).strip())
        except (TypeError, ValueError):
            return 0
    return _to_int(m.get("width")), _to_int(m.get("height"))

def _upgrade_image_url(url):
    """Rewrite common thumbnail URL patterns to a full-resolution variant so the
    delivered picture is at least HD even when the feed only links a small one.
    Rewrites are conservative; if a rewritten URL fails, send_photo_channel falls
    back to the generic pool, so a bad guess degrades gracefully."""
    if not url:
        return url
    # Explicit width in a query param (?width=240, ?w=320, &imwidth=200 ...):
    # never shrink an already-large image, only raise small ones to HD width.
    def _raise_width(match):
        try:
            current = int(match.group(2))
        except ValueError:
            return match.group(0)
        return match.group(0) if current >= MIN_HD_WIDTH else f"{match.group(1)}{MIN_HD_WIDTH}"
    url = re.sub(r"([?&](?:width|w|imwidth)=)(\d+)", _raise_width, url, flags=re.IGNORECASE)
    # BBC ichef path size segment: /news/240/... -> /news/1920/...
    url = re.sub(r"(/news/)(\d{2,3})(/)", r"\g<1>1920\g<3>", url)
    return url

def _entry_image(entry):
    """Pull the actual article image out of the RSS entry, if the source
    provides one (media:content / media:thumbnail) — so the photo sent with a
    story is a real picture of that story, not a generic stock photo. Prefer the
    highest-resolution rendition (at least HD when the feed lets us)."""
    candidates = []  # (area, has_dims, url)
    for key in ("media_content", "media_thumbnail"):
        media = entry.get(key)
        if not (media and isinstance(media, list)):
            continue
        for m in media:
            if not isinstance(m, dict):
                continue
            url = m.get("url")
            if not url:
                continue
            w, h = _media_dims(m)
            candidates.append((w * h, bool(w and h), url))
    if not candidates:
        return None
    # Largest advertised picture first; entries with real dimensions win ties.
    best_area, best_has_dims, best_url = max(candidates, key=lambda c: (c[0], c[1]))
    upgraded = _upgrade_image_url(best_url)
    # If we know the best rendition is smaller than HD and no size token let us
    # bump it, skip it so we fall back to the (HD) generic stock pool instead of
    # sending a low-resolution picture.
    if best_has_dims and best_area < MIN_HD_WIDTH * MIN_HD_HEIGHT and upgraded == best_url:
        return None
    return upgraded

def collect_news():
    headlines = []    # list of (title, url, image)
    high_impact = []  # list of (title, url, image)
    for feed_url in FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:20]:
                title = entry.get("title","")
                url = entry.get("link","")
                image = _entry_image(entry)
                title_lower = title.lower()
                if any(k in title_lower for k in HIGH_IMPACT):
                    high_impact.append((title, url, image))
                elif any(k in title_lower for k in KEYWORDS):
                    headlines.append((title, url, image))
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
    titles = [t for t, u, img in items]
    top_links = [(t, u) for t, u, img in items[:6] if u][:4]
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
    _load_cursors()
    sent_today = {}

    while True:
        try:
            tz = pytz.timezone("Europe/Athens")
            now = datetime.now(tz)
            hour = now.hour
            minute = now.minute
            today = now.strftime("%Y-%m-%d")

            # Silence 00:00 - 06:59; sleep until 06:55 to avoid missing the 07:00 window
            if hour < 7:
                print("Silence hours - sleeping...")
                _now = datetime.now(tz)
                _wake = _now.replace(hour=6, minute=55, second=0, microsecond=0)
                if _wake <= _now:
                    # Already past 06:55 but still hour < 7 (06:55-06:59); add 1 day
                    _wake += timedelta(days=1)
                _secs = (_wake - _now).total_seconds()
                time.sleep(min(_secs, 1800))
                continue

            # Prune stale keys from previous days to prevent indefinite growth
            sent_today = {k: v for k, v in sent_today.items() if k.startswith(today)}

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
                        if top_links:
                            base = _html.escape(header)+"\n🕔 "+_html.escape(now_str)+"\n\n"+_html.escape(report)
                            links_section = "\n\n📎 Read more:\n"
                            for title, url in top_links:
                                short = title[:55]+"…" if len(title) > 55 else title
                                safe_url = url.replace("&", "&amp;")
                                links_section += f'• <a href="{safe_url}">{_html.escape(short)}</a>\n'
                            links_str = links_section.rstrip()
                            # Clamp base so base+links never exceeds 1024 chars
                            max_base = max(0, 1024 - len(links_str))
                            msg = base[:max_base] + links_str
                            parse_mode = "HTML"
                        else:
                            msg = header+"\n🕔 "+now_str+"\n\n"+report
                            parse_mode = None
                        # Prefer a real image from one of the actual stories (already
                        # priority-ordered: high-impact first) over the generic pool.
                        article_image = next((img for _, _, img in items if img), None)
                        photo = article_image or _next_photo("news", NEWS_IMAGES)
                        send_photo_channel(photo, caption=msg, parse_mode=parse_mode)
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
