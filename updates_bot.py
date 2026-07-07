import os
from dotenv import load_dotenv
load_dotenv("/root/tradingbot/.env")

import requests
import anthropic
import schedule
import time
import pytz
from datetime import datetime

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN_SIGNAL")
CHANNEL_ID = os.getenv("TELEGRAM_UPDATES_CHANNEL")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")
IMAGES_DIR = "/root/tradingbot/images"
_photo_ids = {}

def send(msg, photo_name=None):
    cap = msg[:1024]
    path = os.path.join(IMAGES_DIR, photo_name) if photo_name else None
    try:
        if path and os.path.exists(path):
            fid = _photo_ids.get(photo_name)
            if fid:
                r = requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendPhoto",
                    json={"chat_id": CHANNEL_ID, "photo": fid, "caption": cap}, timeout=15)
                if not r.ok:
                    # Stale file_id — evict cache and fall through to re-upload
                    _photo_ids.pop(photo_name, None)
                    fid = None
            if not fid:
                with open(path, "rb") as pf:
                    r = requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendPhoto",
                        files={"photo": ("image.jpg", pf, "image/jpeg")},
                        data={"chat_id": CHANNEL_ID, "caption": cap}, timeout=15)
                photos = r.json().get("result", {}).get("photo", [])
                if photos:
                    _photo_ids[photo_name] = photos[-1]["file_id"]
        else:
            r = requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendMessage",
                json={"chat_id": CHANNEL_ID, "text": msg[:4000]}, timeout=10)
        r.raise_for_status()
        print("Sent!")
    except Exception as e:
        print("Error: "+str(e))

def ai(prompt):
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        r = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role":"user","content":prompt}]
        )
        return r.content[0].text
    except Exception as e:
        print("AI error: "+str(e))
        return ""

def daily_tip():
    import random
    topics = [
        ("risk management and position sizing", "the #1 rule most traders ignore about protecting their capital"),
        ("reading market structure and trends", "how to identify where the market is really going before it gets there"),
        ("entry timing and patience", "why waiting for the right moment makes or breaks a trade"),
        ("stop loss placement and trade management", "where to place your stop so the market can't stop you out prematurely"),
        ("trading psychology and emotional control", "the mental side of trading that nobody talks about enough"),
        ("technical analysis and key indicators", "how to use indicators as tools, not signals"),
        ("avoiding common beginner mistakes in forex", "what separates traders who blow accounts from those who don't"),
        ("trading during high impact news events", "how to protect your account when the market is unpredictable"),
        ("multi-timeframe analysis", "why looking at just one timeframe is like driving with one eye closed"),
        ("the importance of a trading journal", "why the best traders track everything and what they look for"),
        ("Smart Money Concepts and institutional levels", "how to trade with institutions instead of against them"),
        ("leverage and margin management", "how leverage is a tool that cuts both ways"),
        ("support and resistance levels", "why price respects certain levels over and over again"),
        ("the difference between reactive and proactive trading", "how to plan trades before the market moves, not after"),
    ]
    formats = [
        "Write a sharp, practical trading tip about {topic}. Context: {context}. 2-3 sentences, direct and confident. Use emojis. Plain text.",
        "Share a trading insight about {topic}. Context: {context}. Write like you're talking to a fellow trader, not a student. 3 sentences max. Emojis.",
        "Give one key lesson about {topic}. Context: {context}. Be specific — no generic advice. 2-3 punchy sentences. Use emojis.",
        "Write a trading truth about {topic}. Context: {context}. Challenge conventional thinking if needed. 3 sentences. Emojis. Plain text.",
    ]
    headers = ["💡 DAILY TIP", "📌 TRADER'S NOTE", "⚡ QUICK INSIGHT", "🎯 TODAY'S LESSON", "💬 TRADING WISDOM"]
    topic, context = random.choice(topics)
    prompt = random.choice(formats).format(topic=topic, context=context)
    text = ai(prompt)
    if text:
        send(random.choice(headers)+"\n\n"+text+"\n\n📊 @novasignalschannel1\n\n⚠️ Educational purposes only. Not financial advice.", photo_name="tips.jpg")

def psychology_post():
    import random
    prompts = [
        "Write a trading psychology post for forex/crypto traders. Include a quote from a famous trader or investor (real quote). Then give 2-3 sentences of your own take on discipline, FOMO, or patience. Write naturally, like a mentor talking to a student. Use emojis. Plain text.",
        "Write about a common psychological trap traders fall into — revenge trading, overtrading, or fear of missing out. Be honest and direct. Include a real trading quote. 3-5 sentences. Emojis. Plain text.",
        "Write a motivational but realistic post for traders about consistency over perfection. Include a quote from a famous trader. Don't be generic — give one specific, actionable mindset shift. 3-4 sentences. Emojis.",
        "Write about the relationship between emotions and trading decisions. Quote a famous trader or market wizard. Then give practical advice on how to stay neutral. 4-5 sentences. Emojis. Plain text.",
    ]
    headers = ["🧠 TRADING PSYCHOLOGY", "💭 MINDSET MATTERS", "🎯 TRADER MINDSET", "🧘 MENTAL EDGE"]
    text = ai(random.choice(prompts))
    if text:
        send(random.choice(headers)+"\n\n"+text+"\n\n📊 @novasignalschannel1", photo_name="psychology.jpg")

def weekly_preview():
    import random
    tz = pytz.timezone("Europe/Athens")
    week = datetime.now(tz).strftime("%d/%m/%Y")
    prompts = [
        "Write a weekly market preview for forex and crypto traders. What are the key events, data releases, and themes to watch this week? Be specific about which pairs or markets could move. 4-5 sentences. Use emojis. Plain text.",
        "Write a 'week ahead' briefing for traders. Focus on: what drove markets last week, what's coming this week (central banks, data, geopolitics), and which markets to watch closely. 4-6 sentences. Emojis. Conversational tone.",
        "Write a Monday market outlook for active traders. Highlight 2-3 key themes or events for the week. Which currencies, commodities or crypto could see big moves? Be direct. 4-5 sentences. Emojis.",
    ]
    headers = ["📅 WEEK AHEAD", "🗓 WEEKLY PREVIEW", "📊 THIS WEEK IN MARKETS", "🔭 WEEK AHEAD OUTLOOK"]
    text = ai(random.choice(prompts))
    if text:
        send(random.choice(headers)+" | "+week+"\n\n"+text+"\n\n📊 @novasignalschannel1", photo_name="weekly.jpg")

def weekly_summary():
    import random
    prompts = [
        "Write an end-of-week trading summary. What were the main market themes this week? What moved and why? End with a forward-looking sentence for next week. 4-5 sentences. Emojis. Plain text.",
        "Write a Friday wrap-up for forex and crypto traders. Cover the week's biggest moves, what surprised markets, and what traders should carry into next week. Keep it honest and specific. 4-5 sentences. Emojis.",
        "Write a weekly performance debrief for traders. Highlight 2-3 major market developments from this week, the lessons they teach, and a motivational close. 5 sentences max. Emojis. Plain text.",
    ]
    headers = ["📈 WEEKLY WRAP-UP", "📋 WEEK IN REVIEW", "🏁 FRIDAY WRAP", "📊 THIS WEEK SUMMARY"]
    text = ai(random.choice(prompts))
    if text:
        send(random.choice(headers)+"\n\n"+text+"\n\n📊 @novasignalschannel1", photo_name="weekly.jpg")

def main():
    try:
        schedule.every().day.at("06:00", "Europe/Athens").do(daily_tip)
        schedule.every().monday.at("05:00", "Europe/Athens").do(weekly_preview)
        schedule.every().friday.at("17:00", "Europe/Athens").do(weekly_summary)
        schedule.every().sunday.at("15:00", "Europe/Athens").do(psychology_post)
    except TypeError:
        # schedule >= 1.2.0 is required for timezone support; fall back to bare times
        print("WARNING: schedule>=1.2.0 required for timezone support; jobs will run in server local time")
        schedule.every().day.at("06:00").do(daily_tip)
        schedule.every().monday.at("05:00").do(weekly_preview)
        schedule.every().friday.at("17:00").do(weekly_summary)
        schedule.every().sunday.at("15:00").do(psychology_post)

    print("Updates Bot started!")
    while True:
        try:
            schedule.run_pending()
        except Exception as e:
            print("schedule error: "+str(e))
        time.sleep(60)

if __name__ == "__main__":
    main()
