import os
from dotenv import load_dotenv
load_dotenv("/root/tradingbot/.env")

import requests
import json
import time
import anthropic
from datetime import datetime
import pytz
import csv
import io

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN_SIGNAL")
if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN_SIGNAL is not set in environment")
USERS_FILE = "/root/tradingbot/users.json"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    print("Warning: ANTHROPIC_API_KEY not set — AI earnings summaries will be unavailable")
_anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None
ALPHA_KEY = os.getenv("ALPHA_VANTAGE_KEY")

IMPORTANT_STOCKS = [
    "AAPL","MSFT","GOOGL","AMZN","META","NVDA","TSLA","JPM","BAC","GS",
    "MS","C","WFC","XOM","CVX","AMD","INTC","NFLX","DIS","V","MA","UBER",
    "COIN","PYPL","SNAP","SHOP","SQ","ROKU","ZM","PLTR","ARM","SMCI"
]

def load_users():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError, OSError) as e:
            print(f"load_users error: {e}")
    return []

def send_all(msg):
    sent = 0
    # users.json may contain list of strings (listener.py) or list of dicts (main_bot.py)
    for item in load_users():
        chat_id = item["id"] if isinstance(item, dict) else item
        try:
            r = requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendMessage",
                json={"chat_id": chat_id, "text": msg[:4000]}, timeout=10)
            r.raise_for_status()
            sent += 1
            time.sleep(0.1)
        except Exception as e:
            print(f"send_all error {chat_id}: {e}")
    return sent

def get_earnings():
    if not ALPHA_KEY:
        print("get_earnings: ALPHA_VANTAGE_KEY not set, skipping")
        return []
    try:
        tz = pytz.timezone("Europe/Athens")
        today = datetime.now(tz).strftime("%Y-%m-%d")
        r = requests.get(
            "https://www.alphavantage.co/query?function=EARNINGS_CALENDAR&horizon=3month&apikey="+ALPHA_KEY,
            timeout=15
        )
        # Alpha Vantage returns JSON error bodies (not CSV) when the key is invalid or rate-limited
        if r.status_code != 200 or not r.text.lstrip().startswith("symbol"):
            print(f"Earnings API unexpected response (status={r.status_code}): {r.text[:200]}")
            return []
        reader = csv.DictReader(io.StringIO(r.text))
        earnings = []
        for row in reader:
            if row.get("reportDate","") == today:
                ticker = row.get("symbol","")
                name = row.get("name","")
                estimate = row.get("estimate","")
                time_of_day = row.get("timeOfTheDay","")
                currency = row.get("currency","USD")
                if ticker in IMPORTANT_STOCKS:
                    earnings.append({
                        "ticker": ticker,
                        "company": name,
                        "time": time_of_day,
                        "eps_est": estimate,
                        "currency": currency
                    })
        return earnings
    except Exception as e:
        print("Earnings error: "+str(e))
        return []

def get_analysis(earnings):
    if not earnings:
        return ""
    try:
        earnings_text = "\n".join([e["ticker"]+" - "+e["company"]+" ("+e["time"]+") EPS est: "+e["eps_est"] for e in earnings])
        message = _anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system="You are a financial analyst briefing traders. Write in plain English only, no markdown.",
            messages=[{"role":"user","content":"These major companies report earnings today. Write 2-3 simple sentences about what traders should watch and how it might affect markets, USD and risk sentiment.\n\n"+earnings_text}]
        )
        return message.content[0].text if message.content else ""
    except Exception as e:
        print(f"get_analysis error: {e}")
        return ""

def format_message(earnings, analysis):
    tz = pytz.timezone("Europe/Athens")
    today = datetime.now(tz).strftime("%d/%m/%Y")
    lines = ["\U0001f4b0 EARNINGS CALENDAR\n\U0001f554 "+today+"\n"]

    if not earnings:
        lines.append("No major earnings reports today.")
    else:
        lines.append("Major companies reporting today:\n")
        for e in earnings:
            time_emoji = "\U0001f305" if "pre" in e["time"].lower() else "\U0001f307" if "post" in e["time"].lower() else "\U0001f554"
            lines.append(time_emoji+" "+e["ticker"]+" | "+e["company"])
            if e["eps_est"]:
                lines.append("   EPS Estimate: "+e["eps_est"]+" "+e["currency"])

        if analysis:
            lines.append("\n\U0001f4a1 MARKET IMPACT:\n"+analysis)

    return "\n".join(lines)

def main():
    print("Earnings bot started...")
    sent_today = ""
    while True:
        try:
            tz = pytz.timezone("Europe/Athens")
            now = datetime.now(tz)
            today = now.strftime("%Y-%m-%d")
            hour = now.hour
            minute = now.minute

            if hour == 7 and minute < 10 and sent_today != today:
                print("Sending earnings calendar...")
                earnings = get_earnings()
                analysis = get_analysis(earnings)
                msg = format_message(earnings, analysis)
                users = load_users()
                if send_all(msg) > 0 or not users:
                    sent_today = today
                    print("Earnings sent! "+str(len(earnings))+" companies")
                time.sleep(600)
            else:
                time.sleep(300)

        except Exception as e:
            print("Error: "+str(e))
            time.sleep(60)

if __name__ == "__main__":
    main()
