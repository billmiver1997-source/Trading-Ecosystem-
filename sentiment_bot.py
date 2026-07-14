import os
from dotenv import load_dotenv
load_dotenv("/root/tradingbot/.env")

import json
import random
import requests
import time
import anthropic
import yfinance as yf
from datetime import datetime
import pytz

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN_SIGNAL")
if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN_SIGNAL is not set in environment")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    print("Warning: ANTHROPIC_API_KEY not set — AI sentiment commentary will be unavailable")
_anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None
CHANNEL_ID = os.getenv("TELEGRAM_NEWS_CHANNEL")
if not CHANNEL_ID:
    raise RuntimeError("TELEGRAM_NEWS_CHANNEL is not set in environment")

SENT_STATE_FILE = "/root/tradingbot/sent_state_sentiment.json"

def _load_sent_day():
    """Persisted (not just in-memory) so a restart inside the send window — e.g.
    monitor.sh catching a crash — can't cause a duplicate send."""
    if os.path.exists(SENT_STATE_FILE):
        try:
            with open(SENT_STATE_FILE) as f:
                return json.load(f).get("day", "")
        except (json.JSONDecodeError, ValueError, OSError) as e:
            print(f"load sent state error: {e}")
    return ""

def _save_sent_day(day):
    tmp = SENT_STATE_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump({"day": day}, f)
        os.replace(tmp, SENT_STATE_FILE)
    except Exception as e:
        print(f"save sent state error: {e}")
IMAGES_DIR = "/root/tradingbot/images"
_photo_ids = {}

def send_channel(msg):
    path = os.path.join(IMAGES_DIR, "sentiment.jpg")
    cap = msg[:1024]
    try:
        fid = _photo_ids.get("sentiment.jpg")
        if fid:
            r = requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendPhoto",
                json={"chat_id": CHANNEL_ID, "photo": fid, "caption": cap}, timeout=15)
            if not r.ok:
                # Stale file_id — evict cache and fall through to re-upload
                _photo_ids.pop("sentiment.jpg", None)
                fid = None
        if not fid and os.path.exists(path):
            with open(path, "rb") as pf:
                r = requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendPhoto",
                    files={"photo": ("image.jpg", pf, "image/jpeg")},
                    data={"chat_id": CHANNEL_ID, "caption": cap}, timeout=15)
            photos = r.json().get("result", {}).get("photo", [])
            if photos:
                _photo_ids["sentiment.jpg"] = photos[-1]["file_id"]
        elif not fid:
            r = requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendMessage",
                json={"chat_id": CHANNEL_ID, "text": msg[:4000]}, timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"send_channel error: {e}")
        return False


def get_fear_greed():
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        r.raise_for_status()
        data = r.json()["data"][0]
        value = int(data["value"])
        classification = data["value_classification"]
        if value >= 75: emoji = "\U0001f7e2"
        elif value >= 55: emoji = "\U0001f7e1"
        elif value >= 45: emoji = "\U0001f7e0"
        elif value >= 25: emoji = "\U0001f534"
        else: emoji = "\U0001f4a5"
        return {"value": value, "classification": classification, "emoji": emoji}
    except Exception as e:
        print(f"get_fear_greed error: {e}")
        return None

def get_dxy_sentiment():
    try:
        df = yf.Ticker("DX-Y.NYB").history(period="5d", interval="1h")
        if len(df) < 25:
            return None
        change = ((df["Close"].iloc[-1] - df["Close"].iloc[-25]) / df["Close"].iloc[-25]) * 100
        if change > 0.3: sentiment = "Bullish \U0001f7e2"
        elif change < -0.3: sentiment = "Bearish \U0001f534"
        else: sentiment = "Neutral \U0001f7e1"
        return {"value": round(df["Close"].iloc[-1], 2), "change": round(change, 2), "sentiment": sentiment}
    except Exception as e:
        print(f"get_dxy_sentiment error: {e}")
        return None

def get_gold_sentiment():
    try:
        df = yf.Ticker("GC=F").history(period="5d", interval="1h")
        if len(df) < 25:
            return None
        change = ((df["Close"].iloc[-1] - df["Close"].iloc[-25]) / df["Close"].iloc[-25]) * 100
        if change > 0.5: sentiment = "Bullish \U0001f7e2"
        elif change < -0.5: sentiment = "Bearish \U0001f534"
        else: sentiment = "Neutral \U0001f7e1"
        return {"value": round(df["Close"].iloc[-1], 2), "change": round(change, 2), "sentiment": sentiment}
    except Exception as e:
        print(f"get_gold_sentiment error: {e}")
        return None

def get_vix():
    try:
        df = yf.Ticker("^VIX").history(period="2d", interval="1h")
        if len(df) < 1:
            return None
        vix = round(df["Close"].iloc[-1], 2)
        if vix > 30: level = "High Fear \U0001f4a5"
        elif vix > 20: level = "Elevated \U0001f7e0"
        else: level = "Low/Normal \U0001f7e2"
        return {"value": vix, "level": level}
    except Exception as e:
        print(f"get_vix error: {e}")
        return None

SENTIMENT_STYLES = [
    "Write a morning sentiment briefing for forex and crypto traders. Use the data below. Start with the most important signal, then connect the dots between Fear & Greed, DXY, Gold and VIX. What does it all mean together? Write 3-4 sentences, naturally, with emojis. No headers or bullet points.",
    "You're a senior trader writing your daily sentiment note. Use the data below. Be direct and opinionated — what is the market telling us today? What should traders be cautious about or excited about? 3-4 sentences, emojis, plain text.",
    "Write a market mood report using the data below. Structure: 1 sentence on risk appetite, 1 on dollar strength, 1 on Gold, 1 overall conclusion. Use emojis. Conversational tone.",
    "Analyze the market sentiment data below and write a concise briefing. Highlight any contradictions or confirmations between the indicators. What's the dominant theme today? 3-5 sentences, emojis, plain text.",
    "Using the sentiment data below, write a quick market pulse for traders. Lead with what stands out most, then give context. End with one actionable insight. 3-4 sentences, emojis.",
]

SENTIMENT_HEADERS = [
    "🧠 MARKET SENTIMENT",
    "📊 DAILY SENTIMENT REPORT",
    "🎯 MARKET PULSE",
    "🧠 SENTIMENT BRIEFING",
    "📈 MARKET MOOD",
]

def format_message(fg, dxy, gold, vix):
    tz = pytz.timezone("Europe/Athens")
    now = datetime.now(tz).strftime("%d/%m/%Y %H:%M")

    data = ""
    if fg:
        bar = "█" * (fg["value"] // 10) + "░" * (10 - fg["value"] // 10)
        data += f"Crypto Fear & Greed: {fg['value']}/100 - {fg['classification']} [{bar}]\n"
    if dxy:
        data += f"DXY (US Dollar): {dxy['value']} | {dxy['change']}% 24h | {dxy['sentiment']}\n"
    if gold:
        data += f"Gold: ${gold['value']} | {gold['change']}% 24h | {gold['sentiment']}\n"
    if vix:
        data += f"VIX (Market Fear): {vix['value']} | {vix['level']}\n"

    if not data:
        print("Sentiment: all data sources unavailable, skipping AI call")
        return None

    if not _anthropic_client:
        print("Sentiment: ANTHROPIC_API_KEY not set, using raw data")
        header = random.choice(SENTIMENT_HEADERS)
        return header + "\n🕔 " + now + "\n\n" + data

    try:
        style = random.choice(SENTIMENT_STYLES)
        message = _anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=350,
            system=style,
            messages=[{"role":"user","content":"Sentiment data:\n"+data}]
        )
        ai_text = message.content[0].text if message.content else data
    except Exception as e:
        print(f"sentiment AI error: {e}")
        ai_text = data

    header = random.choice(SENTIMENT_HEADERS)
    return header+"\n🕔 "+now+"\n\n"+ai_text

def main():
    print("Sentiment bot started...")
    sent_today = _load_sent_day()
    while True:
        try:
            tz = pytz.timezone("Europe/Athens")
            now = datetime.now(tz)
            today = now.strftime("%Y-%m-%d")
            hour = now.hour
            minute = now.minute

            # 08:40, not 08:00 — staggered so this doesn't land in the same burst as
            # news_bot's 08:00 morning brief and calendar_bot's 08:20 calendar.
            if hour == 8 and 40 <= minute < 50 and sent_today != today:
                print("Sending sentiment report...")
                fg = get_fear_greed()
                dxy = get_dxy_sentiment()
                gold = get_gold_sentiment()
                vix = get_vix()
                msg = format_message(fg, dxy, gold, vix)
                if msg and send_channel(msg):
                    sent_today = today
                    _save_sent_day(today)
                    print("Sentiment sent!")
                elif not msg:
                    print("Sentiment skipped — no data available")

        except Exception as e:
            print("Error: "+str(e))

        time.sleep(300)

if __name__ == "__main__":
    main()
