import os
from dotenv import load_dotenv
load_dotenv("/root/tradingbot/.env")

import requests
import json
import time
import anthropic
from datetime import datetime
import pytz

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN_SIGNAL")
USERS_FILE = "/root/tradingbot/users.json"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

def load_users():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"load_users error: {e}")
    return []

def send_channel(msg):
    CHANNEL_ID = os.getenv("TELEGRAM_NEWS_CHANNEL")
    try:
        r = requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendMessage",
            json={"chat_id": CHANNEL_ID, "text": msg[:4000]}, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"send_channel error: {e}")
        raise


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

def get_ai_summary(fg, dxy, gold, vix):
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        data = ""
        if fg: data += "Crypto Fear & Greed: "+str(fg["value"])+" ("+fg["classification"]+")\n"
        if dxy: data += "DXY: "+str(dxy["value"])+" | 24h change: "+str(dxy["change"])+"%\n"
        if gold: data += "Gold: "+str(gold["value"])+" | 24h change: "+str(gold["change"])+"%\n"
        if vix: data += "VIX: "+str(vix["value"])+" ("+vix["level"]+")\n"
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role":"user","content":"Based on this market sentiment data, write 2-3 simple sentences about overall market mood and what forex/crypto traders should expect. Simple English only.\n\n"+data}]
        )
        return message.content[0].text
    except Exception as e:
        print(f"get_ai_summary error: {e}")
        return ""

def format_message(fg, dxy, gold, vix, summary):
    tz = pytz.timezone("Europe/Athens")
    now = datetime.now(tz).strftime("%d/%m/%Y %H:%M")
    lines = ["\U0001f9e0 MARKET SENTIMENT\n\U0001f554 " + now + "\n"]

    if fg:
        bar = "█" * (fg["value"] // 10) + "░" * (10 - fg["value"] // 10)
        lines.append("\U0001f7e1 CRYPTO FEAR & GREED")
        lines.append(fg["emoji"] + " " + str(fg["value"]) + "/100 - " + fg["classification"])
        lines.append("[" + bar + "]")

    if dxy:
        lines.append("\n\U0001f4b5 US DOLLAR (DXY)")
        lines.append(dxy["sentiment"] + " | " + str(dxy["value"]) + " (" + str(dxy["change"]) + "% 24h)")

    if gold:
        lines.append("\n\U0001fa99 GOLD")
        lines.append(gold["sentiment"] + " | $" + str(gold["value"]) + " (" + str(gold["change"]) + "% 24h)")

    if vix:
        lines.append("\n\U0001f4ca VIX (Market Fear)")
        lines.append(vix["level"] + " | " + str(vix["value"]))

    if summary:
        lines.append("\n\U0001f4a1 ANALYST NOTE:\n" + summary)

    return "\n".join(lines)

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
                summary = get_ai_summary(fg, dxy, gold, vix)
                msg = format_message(fg, dxy, gold, vix, summary)
                send_channel(msg)
                sent_today = today
                print("Sentiment sent!")

        except Exception as e:
            print("Error: "+str(e))

        time.sleep(300)

if __name__ == "__main__":
    main()
