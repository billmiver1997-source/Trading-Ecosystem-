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

def send(msg):
    try:
        requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendMessage",
            json={"chat_id": CHANNEL_ID, "text": msg[:4000]})
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
        "Write a trading tip about risk management and position sizing. Max 3 sentences. No markdown. Use emojis.",
        "Write a trading tip about reading market structure and trends. Max 3 sentences. No markdown. Use emojis.",
        "Write a trading tip about entry timing and patience. Max 3 sentences. No markdown. Use emojis.",
        "Write a trading tip about stop loss placement and trade management. Max 3 sentences. No markdown. Use emojis.",
        "Write a trading tip about trading psychology and emotional control. Max 3 sentences. No markdown. Use emojis.",
        "Write a trading tip about technical analysis and key indicators. Max 3 sentences. No markdown. Use emojis.",
        "Write a trading tip about avoiding common beginner mistakes in forex. Max 3 sentences. No markdown. Use emojis.",
        "Write a trading tip about trading during high impact news events. Max 3 sentences. No markdown. Use emojis.",
        "Write a trading tip about multi-timeframe analysis. Max 3 sentences. No markdown. Use emojis.",
        "Write a trading tip about the importance of a trading journal. Max 3 sentences. No markdown. Use emojis.",
        "Write a trading tip about Smart Money Concepts and institutional levels. Max 3 sentences. No markdown. Use emojis.",
        "Write a trading tip about crypto trading vs forex trading differences. Max 3 sentences. No markdown. Use emojis.",
        "Write a trading tip about leverage and margin management. Max 3 sentences. No markdown. Use emojis.",
        "Write a trading tip about support and resistance levels. Max 3 sentences. No markdown. Use emojis.",
    ]
    prompt = random.choice(topics)
    text = ai(prompt)
    if text:
        send("\U0001f4a1 DAILY TIP\n\n"+text+"\n\n\U0001f4ca @novasignalschannel1")

def psychology_post():
    text = ai("Write a trading psychology post for forex/crypto traders. Include a quote from a famous trader. Then 2-3 sentences about discipline, FOMO, or patience. Max 5 sentences. No markdown. Use emojis.")
    if text:
        send("\U0001f9e0 TRADING PSYCHOLOGY\n\n"+text+"\n\n\U0001f4ca @novasignalschannel1")

def weekly_preview():
    tz = pytz.timezone("Europe/Athens")
    week = datetime.now(tz).strftime("%d/%m/%Y")
    text = ai("Write a brief forex/crypto market weekly preview. Key events to watch this week. 4-5 sentences. No markdown. Use emojis.")
    if text:
        send("\U0001f4c5 WEEK AHEAD | "+week+"\n\n"+text+"\n\n\U0001f4ca @novasignalschannel1")

def weekly_summary():
    text = ai("Write a brief end-of-week trading summary. Market themes this week. End with motivation for next week. Max 5 sentences. No markdown. Use emojis.")
    if text:
        send("\U0001f4c8 WEEKLY WRAP-UP\n\n"+text+"\n\n\U0001f4ca @novasignalschannel1")

schedule.every().day.at("06:00").do(daily_tip)
schedule.every().monday.at("05:00").do(weekly_preview)
schedule.every().friday.at("17:00").do(weekly_summary)
schedule.every().sunday.at("15:00").do(psychology_post)

print("Updates Bot started!")
while True:
    schedule.run_pending()
    time.sleep(60)
