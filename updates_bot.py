import os
from dotenv import load_dotenv
load_dotenv("/root/tradingbot/.env")

import json
import random
import requests
import anthropic
import schedule
import time
import pytz
from datetime import datetime

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN_SIGNAL")
if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN_SIGNAL is not set in environment")
CHANNEL_ID = os.getenv("TELEGRAM_UPDATES_CHANNEL")
if not CHANNEL_ID:
    raise RuntimeError("TELEGRAM_UPDATES_CHANNEL is not set in environment")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_KEY:
    print("Warning: ANTHROPIC_API_KEY not set — AI update generation will be unavailable")
_anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_KEY) if ANTHROPIC_KEY else None
IMAGES_DIR = "/root/tradingbot/images"
CURSORS_FILE = "/root/tradingbot/cursors_updates.json"
_photo_ids = {}
_img_cursors = {}

TIPS_IMAGES = ["tips.jpg", "tips_2.jpg", "tips_3.jpg", "tips_4.jpg"]
PSYCHOLOGY_IMAGES = ["psychology.jpg", "psychology_2.jpg", "psychology_3.jpg"]
WEEKLY_IMAGES = ["weekly.jpg", "weekly_2.jpg", "weekly_3.jpg"]

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

def _next_item(category, pool):
    idx = _img_cursors.get(category, 0)
    _img_cursors[category] = (idx + 1) % len(pool)
    _save_cursors()
    return pool[idx]

# kept as an alias — same rotation logic, used for photo pools specifically
_next_photo = _next_item

POLLS = [
    {"q": "🌍 Favorite session to trade?", "options": ["🇯🇵 Tokyo", "🇬🇧 London", "🇺🇸 New York", "London/NY overlap"]},
    {"q": "😅 Biggest trading mistake you're guilty of?", "options": ["Overtrading", "No stop loss", "Revenge trading", "FOMO entries"]},
    {"q": "⏱ Which timeframe do you trade most?", "options": ["Scalping (1m-15m)", "Swing (1h-4h)", "Position (Daily+)"]},
    {"q": "📊 How do you feel about the markets today?", "options": ["🟢 Bullish", "🔴 Bearish", "🟡 Neutral", "🤷 Not sure"]},
    {"q": "🎯 What's your risk per trade?", "options": ["Under 1%", "1-2%", "2-5%", "Over 5%"]},
    {"q": "💹 Favorite asset class?", "options": ["Forex", "Crypto", "Commodities", "Indices"]},
    {"q": "📰 Do you trade around big news events?", "options": ["Always", "Sometimes", "Never", "Only NFP/CPI"]},
    {"q": "🕰 How long have you been trading?", "options": ["Under 1 year", "1-3 years", "3-5 years", "5+ years"]},
    {"q": "🧠 What breaks your discipline most?", "options": ["FOMO", "Boredom", "Revenge trading", "Overconfidence"]},
    {"q": "📈 Which tool do you trust most?", "options": ["EMA/Moving Averages", "RSI", "Support/Resistance", "Pure price action"]},
    {"q": "💰 Demo or live account?", "options": ["Still on demo", "Live, small size", "Live, full size"]},
    {"q": "🎯 What's your main trading goal?", "options": ["Extra income", "Full-time career", "Learning/hobby", "Building long-term wealth"]},
    {"q": "📓 How do you journal your trades?", "options": ["Every single trade", "Only losses", "Rarely", "I don't"]},
    {"q": "📅 Best day of the week for you to trade?", "options": ["Monday", "Tue-Thu", "Friday", "Doesn't matter"]},
    {"q": "🤔 What's harder for you?", "options": ["Entries", "Exits", "Both equally", "Staying disciplined after"]},
    {"q": "💛 Which pair moves you emotionally the most?", "options": ["XAU/USD (Gold)", "BTC/USD", "USD/JPY", "EUR/USD"]},
    {"q": "📉 How do you handle a losing streak?", "options": ["Stop and reassess", "Reduce size", "Push through it", "Take a full break"]},
    {"q": "🕯 Preferred chart type?", "options": ["Candlesticks", "Line chart", "Heikin Ashi", "Something else"]},
    {"q": "🧩 What's your real edge?", "options": ["Technical analysis", "Fundamentals", "Smart Money Concepts", "Experience + gut feel"]},
    {"q": "👀 How many pairs do you actually watch daily?", "options": ["Just 1-2", "3-5", "6-10", "More than 10"]},
]

def community_poll():
    poll = _next_item("poll", POLLS)
    try:
        r = requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendPoll",
            json={"chat_id": CHANNEL_ID, "question": poll["q"], "options": poll["options"],
                  "is_anonymous": True, "type": "regular"}, timeout=10)
        r.raise_for_status()
        print("Poll sent!")
    except Exception as e:
        print("Poll error: "+str(e))

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
        r = _anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role":"user","content":prompt}]
        )
        return r.content[0].text if r.content else ""
    except Exception as e:
        print("AI error: "+str(e))
        return ""

def daily_tip():
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
        send(random.choice(headers)+"\n\n"+text+"\n\n📊 @novasignalschannel1\n\n⚠️ Educational purposes only. Not financial advice.", photo_name=_next_photo("tips", TIPS_IMAGES))
    else:
        print("daily_tip: AI returned empty — post skipped")

def psychology_post():
    prompts = [
        "Write a trading psychology post for forex/crypto traders. Include a quote from a famous trader or investor (real quote). Then give 2-3 sentences of your own take on discipline, FOMO, or patience. Write naturally, like a mentor talking to a student. Use emojis. Plain text.",
        "Write about a common psychological trap traders fall into — revenge trading, overtrading, or fear of missing out. Be honest and direct. Include a real trading quote. 3-5 sentences. Emojis. Plain text.",
        "Write a motivational but realistic post for traders about consistency over perfection. Include a quote from a famous trader. Don't be generic — give one specific, actionable mindset shift. 3-4 sentences. Emojis.",
        "Write about the relationship between emotions and trading decisions. Quote a famous trader or market wizard. Then give practical advice on how to stay neutral. 4-5 sentences. Emojis. Plain text.",
    ]
    headers = ["🧠 TRADING PSYCHOLOGY", "💭 MINDSET MATTERS", "🎯 TRADER MINDSET", "🧘 MENTAL EDGE"]
    text = ai(random.choice(prompts))
    if text:
        send(random.choice(headers)+"\n\n"+text+"\n\n📊 @novasignalschannel1", photo_name=_next_photo("psychology", PSYCHOLOGY_IMAGES))
    else:
        print("psychology_post: AI returned empty — post skipped")

def weekly_preview():
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
        send(random.choice(headers)+" | "+week+"\n\n"+text+"\n\n📊 @novasignalschannel1", photo_name=_next_photo("weekly", WEEKLY_IMAGES))
    else:
        print("weekly_preview: AI returned empty — post skipped")

def weekly_summary():
    prompts = [
        "Write an end-of-week trading summary. What were the main market themes this week? What moved and why? End with a forward-looking sentence for next week. 4-5 sentences. Emojis. Plain text.",
        "Write a Friday wrap-up for forex and crypto traders. Cover the week's biggest moves, what surprised markets, and what traders should carry into next week. Keep it honest and specific. 4-5 sentences. Emojis.",
        "Write a weekly performance debrief for traders. Highlight 2-3 major market developments from this week, the lessons they teach, and a motivational close. 5 sentences max. Emojis. Plain text.",
    ]
    headers = ["📈 WEEKLY WRAP-UP", "📋 WEEK IN REVIEW", "🏁 FRIDAY WRAP", "📊 THIS WEEK SUMMARY"]
    text = ai(random.choice(prompts))
    if text:
        send(random.choice(headers)+"\n\n"+text+"\n\n📊 @novasignalschannel1", photo_name=_next_photo("weekly", WEEKLY_IMAGES))
    else:
        print("weekly_summary: AI returned empty — post skipped")

def main():
    _load_cursors()
    try:
        schedule.every().day.at("06:00", "Europe/Athens").do(daily_tip)
        schedule.every().monday.at("05:00", "Europe/Athens").do(weekly_preview)
        schedule.every().friday.at("17:00", "Europe/Athens").do(weekly_summary)
        schedule.every().sunday.at("15:00", "Europe/Athens").do(psychology_post)
        schedule.every().day.at("20:00", "Europe/Athens").do(community_poll)
    except TypeError:
        # schedule >= 1.2.0 is required for timezone support; fall back to bare times
        print("WARNING: schedule>=1.2.0 required for timezone support; jobs will run in server local time")
        schedule.clear()
        schedule.every().day.at("06:00").do(daily_tip)
        schedule.every().monday.at("05:00").do(weekly_preview)
        schedule.every().friday.at("17:00").do(weekly_summary)
        schedule.every().sunday.at("15:00").do(psychology_post)
        schedule.every().day.at("20:00").do(community_poll)

    print("Updates Bot started!")
    while True:
        try:
            schedule.run_pending()
        except Exception as e:
            print("schedule error: "+str(e))
        time.sleep(60)

if __name__ == "__main__":
    main()
