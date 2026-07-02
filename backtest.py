import os
from dotenv import load_dotenv
load_dotenv("/root/tradingbot/.env")

import yfinance as yf
import requests
import pandas as pd
import json
import time
from datetime import datetime
import pytz

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN_SIGNAL")
USERS_FILE = "/root/tradingbot/users.json"

PAIRS = {
    "XAU/USD": "GC=F",
    "Silver/USD": "SI=F",
    "Oil/USD": "CL=F",
    "BTC/USD": "BTC-USD",
    "SOL/USD": "SOL-USD",
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "USD/CHF": "USDCHF=X",
    "AUD/USD": "AUDUSD=X",
    "USD/CAD": "USDCAD=X",
    "NZD/USD": "NZDUSD=X",
    "USD/JPY": "USDJPY=X",
}

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE) as f:
            return json.load(f)
    return []

def send_all(msg):
    for chat_id in load_users():
        try:
            requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendMessage",
                json={"chat_id": chat_id, "text": msg[:4000]})
            time.sleep(0.1)
        except Exception as e:
            print(f"send_all error {chat_id}: {e}")

def get_trend_4h(symbol):
    try:
        df = yf.Ticker(symbol).history(period="60d", interval="4h")
        if len(df) < 50:
            return None
        close = df["Close"]
        ema20 = close.ewm(span=20).mean().iloc[-1]
        ema50 = close.ewm(span=50).mean().iloc[-1]
        if ema20 > ema50:
            return "BULL"
        if ema20 < ema50:
            return "BEAR"
    except Exception as e:
        print(f"get_trend_4h error {symbol}: {e}")
    return None

def backtest_pair(name, symbol):
    df = yf.Ticker(symbol).history(period="60d", interval="1h")
    if len(df) < 200:
        return None

    trend_4h = get_trend_4h(symbol)

    close = df["Close"]; high = df["High"]; low = df["Low"]
    ema20 = close.ewm(span=20).mean()
    ema50 = close.ewm(span=50).mean()
    ema200 = close.ewm(span=200).mean()
    macd = close.ewm(span=12).mean() - close.ewm(span=26).mean()
    sl = macd.ewm(span=9).mean()
    hist = macd - sl
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = -delta.clip(upper=0).rolling(14).mean()
    rsi = 100 - (100 / (1 + gain / loss))
    tr = pd.concat([high-low,(high-close.shift()).abs(),(low-close.shift()).abs()],axis=1).max(axis=1)
    atr = tr.rolling(14).mean()

    wins = losses = 0
    total_pips = 0.0

    for i in range(200, len(df)-60):
        p = close.iloc[i]; a = atr.iloc[i]
        sb = se = 0

        if ema20.iloc[i] > ema50.iloc[i] and p > ema200.iloc[i]: sb += 1
        if ema20.iloc[i] < ema50.iloc[i] and p < ema200.iloc[i]: se += 1
        if macd.iloc[i] > sl.iloc[i] and hist.iloc[i] > hist.iloc[i-1]: sb += 1
        if macd.iloc[i] < sl.iloc[i] and hist.iloc[i] < hist.iloc[i-1]: se += 1
        sh = high.iloc[i-20:i].max(); slo = low.iloc[i-20:i].min()
        if p > sh: sb += 1
        if p < slo: se += 1
        if 50 < rsi.iloc[i] < 70: sb += 1
        if 30 < rsi.iloc[i] < 50: se += 1

        if sb >= 5 and trend_4h == "BULL":
            tp = p + a*3; sl2 = p - a*1.5
            for j in range(i+1, min(i+60, len(df))):
                pr = close.iloc[j]
                if pr >= tp: wins+=1; total_pips+=abs(tp-p); break
                if pr <= sl2: losses+=1; total_pips-=abs(p-sl2); break

        elif se >= 5 and trend_4h == "BEAR":
            tp = p - a*3; sl2 = p + a*1.5
            for j in range(i+1, min(i+60, len(df))):
                pr = close.iloc[j]
                if pr <= tp: wins+=1; total_pips+=abs(p-tp); break
                if pr >= sl2: losses+=1; total_pips-=abs(sl2-p); break

    total = wins + losses
    winrate = round(wins/total*100, 1) if total > 0 else 0
    return {"name": name, "wins": wins, "losses": losses, "winrate": winrate, "pips": round(total_pips, 4), "signals": total}

def run_backtest():
    tz = pytz.timezone("Europe/Athens")
    now = datetime.now(tz).strftime("%d/%m/%Y %H:%M")
    results = []

    for name, symbol in PAIRS.items():
        try:
            r = backtest_pair(name, symbol)
            if r and r["signals"] > 0:
                results.append(r)
                print("Done: "+name)
        except Exception as e:
            print("Error "+name+": "+str(e))

    if not results:
        send_all("⚠️ Backtest: No results")
        return

    results.sort(key=lambda x: x["winrate"], reverse=True)
    total_w = sum(r["wins"] for r in results)
    total_l = sum(r["losses"] for r in results)
    total = total_w + total_l
    overall_wr = round(total_w/total*100, 1) if total > 0 else 0

    lines = ["📊 BACKTEST REPORT (60d — SMC+EMA+HTF)\n🕔 "+now+"\n"]
    lines.append("Overall Win Rate: "+str(overall_wr)+"%")
    lines.append("Total: "+str(total_w)+"W / "+str(total_l)+"L\n")

    for r in results:
        emoji = "🟢" if r["winrate"] >= 55 else "🟡" if r["winrate"] >= 45 else "🔴"
        pips_str = ("+") if r["pips"] > 0 else ""
        lines.append(emoji+" "+r["name"]+": "+str(r["winrate"])+"% ("+str(r["wins"])+"W/"+str(r["losses"])+"L) | "+pips_str+str(r["pips"])+" pips")

    best = results[0]
    lines.append("\n🎯 Best: "+best["name"]+" ("+str(best["winrate"])+"% | "+str(best["signals"])+" signals)")
    lines.append("Strategy: SMC + EMA200 + MACD + HTF 4H | Score>=4 | R:R 1:3")

    send_all("\n".join(lines))
    print("Backtest report sent!")

def main():
    print("Backtest bot started (SMC strategy)...")
    sent_this_week = ""
    while True:
        try:
            tz = pytz.timezone("Europe/Athens")
            now = datetime.now(tz)
            week = now.strftime("%Y-%W")
            if now.weekday() == 6 and now.hour == 20 and now.minute < 10 and sent_this_week != week:
                print("Running backtest...")
                run_backtest()
                sent_this_week = week
        except Exception as e:
            print("Error: "+str(e))
        time.sleep(300)

if __name__ == "__main__":
    main()
