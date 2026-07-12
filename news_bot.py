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
from datetime import datetime
import pytz

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN_SIGNAL")
if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN_SIGNAL is not set in environment")
CHANNEL_ID = os.getenv("TELEGRAM_NEWS_CHANNEL")
if not CHANNEL_ID:
    raise RuntimeError("TELEGRAM_NEWS_CHANNEL is not set in environment")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    print("Warning: ANTHROPIC_API_KEY not set — AI news summaries will be unavailable")
_anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None
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

MIN_IMAGE_WIDTH = 1280  # skip anything smaller than this — not "full HD"

def _upgrade_to_hd(url):
    """Some CDNs embed the requested width in the URL path and will happily
    serve a much larger version on request. BBC's ichef always ships a 240px
    thumbnail in the feed even though the same path supports 1920px — verified
    by fetching both and comparing actual decoded pixel size."""
    m = re.search(r"(ichef\.bbci\.co\.uk/ace/standard/)\d+(/)", url)
    if m:
        return re.sub(r"(ichef\.bbci\.co\.uk/ace/standard/)\d+(/)", r"\g<1>1920\g<2>", url)
    return url

def _entry_image(entry):
    """Pull a full-HD article image out of the RSS entry, if the source provides
    one (media:content / media:thumbnail) — so the photo sent with a story is a
    real, current picture of that story, not a generic stock photo. Thumbnails
    below MIN_IMAGE_WIDTH are skipped unless they come from a CDN we know we
    can force to a larger size."""
    for key in ("media_content", "media_thumbnail"):
        media = entry.get(key)
        if not media or not isinstance(media, list) or not media[0].get("url"):
            continue
        url = media[0]["url"]
        upgraded = _upgrade_to_hd(url)
        if upgraded != url:
            return upgraded
        width = media[0].get("width")
        try:
            if width is not None and int(width) < MIN_IMAGE_WIDTH:
                continue  # too small to pass as a full-HD headline image
        except (TypeError, ValueError):
            pass
        return url
    return None

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

SEEN_FILE = "/root/tradingbot/news_seen.json"
SEEN_TTL_HOURS = 20  # just under a full day, so a still-developing story can
                      # resurface once daily instead of never, but not every
                      # 3-4h slot — the RSS feeds don't refresh that often, so
                      # without this the same top headline (and its photo)
                      # was repeating across consecutive scheduled updates.

def _load_seen():
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError, OSError) as e:
            print(f"load seen error: {e}")
    return {}

def _save_seen(seen):
    tmp = SEEN_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(seen, f)
        os.replace(tmp, SEEN_FILE)
    except Exception as e:
        print(f"save seen error: {e}")

def _split_fresh(items, seen):
    cutoff = time.time() - SEEN_TTL_HOURS * 3600
    fresh = [it for it in items if seen.get(it[0], 0) < cutoff]
    return fresh

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
    if not _anthropic_client:
        print("create_report: ANTHROPIC_API_KEY not set, skipping AI summary")
        return None, top_links
    try:
        style = random.choice(REPORT_STYLES)
        message = _anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=380,
            system=style["system"],
            messages=[{"role":"user","content":style["user"].format(headlines="\n".join(titles[:10]))}]
        )
        return (message.content[0].text if message.content else None), top_links
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
                    # Already past 06:55 but still before 07:00 — sleep briefly, don't skip a day
                    time.sleep(30)
                    continue
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
                all_items = collect_news()
                seen = _load_seen()
                fresh_items = _split_fresh(all_items, seen)
                if fresh_items:
                    items = fresh_items
                else:
                    print("No fresh headlines since last update — reusing existing coverage")
                    items = all_items
                if items:
                    report, top_links = create_report(items)
                    if report:
                        header = random.choice(SCHEDULE[hour])
                        if top_links:
                            base = _html.escape(header)+"\n🕔 "+_html.escape(now_str)+"\n\n"+_html.escape(report)
                            links_section = "\n\n📎 Read more:\n"
                            for title, url in top_links:
                                short = title[:55]+"…" if len(title) > 55 else title
                                safe_url = _html.escape(url, quote=True)
                                links_section += f'• <a href="{safe_url}">{_html.escape(short)}</a>\n'
                            links_str = links_section.rstrip()
                            # Ensure links_str alone never exceeds 700 chars so base always
                            # gets at least 324 chars and Telegram's 1024-cap never truncates
                            # mid HTML-tag (which would cause Telegram to reject the message).
                            if len(links_str) > 700:
                                links_section = "\n\n📎 Read more:\n"
                                for _t, _u in top_links:
                                    _short = _t[:55]+"…" if len(_t) > 55 else _t
                                    _line = f'• <a href="{_html.escape(_u, quote=True)}">{_html.escape(_short)}</a>\n'
                                    if len(links_section) + len(_line) > 700:
                                        break
                                    links_section += _line
                                links_str = links_section.rstrip()
                            max_base = max(0, 1024 - len(links_str))
                            if len(base) > max_base:
                                truncated = base[:max_base]
                                amp_idx = truncated.rfind('&')
                                if amp_idx != -1 and ';' not in truncated[amp_idx:]:
                                    truncated = truncated[:amp_idx]
                                msg = truncated + links_str
                            else:
                                msg = base + links_str
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
                        now_t = time.time()
                        for it in items:
                            seen[it[0]] = now_t
                        # Prune anything older than 2x the TTL so the file doesn't grow forever
                        seen = {k: v for k, v in seen.items() if now_t - v < SEEN_TTL_HOURS * 3600 * 2}
                        _save_seen(seen)
                        sent_today[send_key] = True  # only mark sent when content was actually delivered
                time.sleep(600)
                continue

            time.sleep(300)

        except Exception as e:
            print("Error: "+str(e))
            time.sleep(60)

if __name__ == "__main__":
    main()
