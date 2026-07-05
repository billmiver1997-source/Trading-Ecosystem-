import os
from dotenv import load_dotenv
load_dotenv("/root/tradingbot/.env")

import requests
import time
import anthropic
from datetime import datetime
import pytz

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN_SIGNAL")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

def send_channel(msg):
    CHANNEL_ID = os.getenv("TELEGRAM_NEWS_CHANNEL")
    try:
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
        import yfinance as yf
        df = yf.Ticker("DX-Y.NYB").history(period="5d", interval="1h")
        if len(df) < 25:
            return None
        change = ((df["Close"].iloc[-1] - df["Close"].iloc[-24]) / df["Close"].iloc[-24]) * 100
        if change > 0.3: sentiment = "Bullish \U0001f7e2"
        elif change < -0.3: sentiment = "Bearish \U0001f534"
        else: sentiment = "Neutral \U0001f7e1"
        return {"value": round(df["Close"].iloc[-1], 2), "change": round(change, 2), "sentiment": sentiment}
    except Exception as e:
        print(f"get_dxy_sentiment error: {e}")
        return None

def get_gold_sentiment():
    try:
        import yfinance as yf
        df = yf.Ticker("GC=F").history(period="5d", interval="1h")
        if len(df) < 25:
            return None
        change = ((df["Close"].iloc[-1] - df["Close"].iloc[-24]) / df["Close"].iloc[-24]) * 100
        if change > 0.5: sentiment = "Bullish \U0001f7e2"
        elif change < -0.5: sentiment = "Bearish \U0001f534"
        else: sentiment = "Neutral \U0001f7e1"
        return {"value": round(df["Close"].iloc[-1], 2), "change": round(change, 2), "sentiment": sentiment}
    except Exception as e:
        print(f"get_gold_sentiment error: {e}")
        return None

def get_vix():
    try:
        import yfinance as yf
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
    import random
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

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        style = random.choice(SENTIMENT_STYLES)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=350,
            messages=[{"role":"user","content":style+"\n\nData:\n"+data}]
        )
        ai_text = message.content[0].text
    except Exception as e:
        print(f"sentiment AI error: {e}")
        ai_text = data

    header = random.choice(SENTIMENT_HEADERS)
    return header+"\n🕔 "+now+"\n\n"+ai_text

def main():
    print("Sentiment bot started...")
    sent_today = ""
    while True:
        try:
            tz = pytz.timezone("Europe/Athens")
            now = datetime.now(tz)
            today = now.strftime("%Y-%m-%d")
            hour = now.hour
            minute = now.minute

            if hour == 8 and minute < 10 and sent_today != today:
                print("Sending sentiment report...")
                fg = get_fear_greed()
                dxy = get_dxy_sentiment()
                gold = get_gold_sentiment()
                vix = get_vix()
                msg = format_message(fg, dxy, gold, vix)
                if send_channel(msg):
                    sent_today = today
                print("Sentiment sent!")

        except Exception as e:
            print("Error: "+str(e))

        time.sleep(300)

if __name__ == "__main__":
    main()
