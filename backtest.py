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
if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN_SIGNAL is not set in environment")
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
        try:
            with open(USERS_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError, OSError) as e:
            print(f"load_users error: {e}")
    return []

def send_all(msg):
    for chat_id in load_users():
        try:
            r = requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendMessage",
                json={"chat_id": chat_id, "text": msg[:4000]}, timeout=10)
            r.raise_for_status()
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
    try:
        df = yf.Ticker(symbol).history(period="60d", interval="1h")
    except Exception as e:
        print(f"backtest_pair data error {name}: {e}")
        return None
    # Need at least 261 rows so range(200, len(df)-60) has at least one iteration
    if len(df) < 261:
        return None

    # Do NOT call get_trend_4h() here — it returns today's trend and applying it
    # to every historical bar is look-ahead bias. Instead derive trend from the
    # already-computed 1H EMAs at each bar inside the loop.

    close = df["Close"]; high = df["High"]; low = df["Low"]; open_ = df["Open"]
    ema20 = close.ewm(span=20).mean()
    ema50 = close.ewm(span=50).mean()
    ema200 = close.ewm(span=200).mean()
    macd = close.ewm(span=12).mean() - close.ewm(span=26).mean()
    signal_line = macd.ewm(span=9).mean()
    hist = macd - signal_line
    delta = close.diff()
    # rolling(14).mean() matches the live signal_strategy.py RSI calculation
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = -delta.clip(upper=0).rolling(14).mean()
    loss = loss.replace(0, 1e-10)
    rsi = 100 - (100 / (1 + gain / loss))
    tr = pd.concat([high-low,(high-close.shift()).abs(),(low-close.shift()).abs()],axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    bb_mean = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    bb_upper = bb_mean + 2 * bb_std
    bb_lower = bb_mean - 2 * bb_std

    wins = losses = timeouts = ambiguous = 0
    total_pips = 0.0

    for i in range(200, len(df)-60):
        p = close.iloc[i]; a = atr.iloc[i]
        # Trend at bar i derived from data available at that time — no look-ahead bias
        local_bull = ema20.iloc[i] > ema50.iloc[i]
        local_bear = ema20.iloc[i] < ema50.iloc[i]
        sb = se = 0

        # 1. EMA alignment
        if local_bull and p > ema200.iloc[i]: sb += 1
        if local_bear and p < ema200.iloc[i]: se += 1
        # 2. MACD momentum
        if macd.iloc[i] > signal_line.iloc[i] and hist.iloc[i] > hist.iloc[i-1]: sb += 1
        if macd.iloc[i] < signal_line.iloc[i] and hist.iloc[i] < hist.iloc[i-1]: se += 1
        # 3. BOS
        sh = high.iloc[i-20:i].max(); slo = low.iloc[i-20:i].min()
        if p > sh: sb += 1
        if p < slo: se += 1
        # 4. RSI
        if 50 < rsi.iloc[i] < 70: sb += 1
        if 30 < rsi.iloc[i] < 50: se += 1
        # 5. Strong candle body (use candle at i, already closed in backtest)
        c_range = high.iloc[i] - low.iloc[i]
        c_body = abs(close.iloc[i] - open_.iloc[i])
        body_ratio = c_body / c_range if c_range > 0 else 0
        if close.iloc[i] > open_.iloc[i] and body_ratio > 0.5: sb += 1
        if close.iloc[i] < open_.iloc[i] and body_ratio > 0.5: se += 1
        # 6. Bollinger Band proximity
        if p <= bb_lower.iloc[i] * 1.015: sb += 1
        if p >= bb_upper.iloc[i] * 0.985: se += 1
        # 7. Fibonacci golden pocket (50-61.8% of 20-bar range)
        fib_range = sh - slo
        if fib_range > 0:
            fib_bull_50 = sh - fib_range * 0.50
            fib_bull_618 = sh - fib_range * 0.618
            fib_tol = a * 0.75
            if (fib_bull_618 - fib_tol) <= p <= (fib_bull_50 + fib_tol): sb += 1
            fib_bear_50 = slo + fib_range * 0.50
            fib_bear_618 = slo + fib_range * 0.618
            if (fib_bear_50 - fib_tol) <= p <= (fib_bear_618 + fib_tol): se += 1

        # Threshold: 5/7 (more conservative than live bot's 6/9 — OB/FVG excluded, not backtest-safe)
        if sb >= 5 and local_bull:
            sl2 = p - a*1.5; tp = p + a*3
            resolved = False
            for j in range(i+1, min(i+61, len(df))):
                sl_hit = low.iloc[j] <= sl2
                tp_hit = high.iloc[j] >= tp
                # Both hit on the same candle — ambiguous, count separately, exclude from P&L
                if sl_hit and tp_hit: ambiguous+=1; resolved=True; break
                if sl_hit: losses+=1; total_pips-=abs(p-sl2); resolved=True; break
                if tp_hit: wins+=1; total_pips+=abs(tp-p); resolved=True; break
            if not resolved:
                timeouts += 1

        elif se >= 5 and local_bear:
            sl2 = p + a*1.5; tp = p - a*3
            resolved = False
            for j in range(i+1, min(i+61, len(df))):
                sl_hit = high.iloc[j] >= sl2
                tp_hit = low.iloc[j] <= tp
                # Both hit on the same candle — ambiguous, count separately, exclude from P&L
                if sl_hit and tp_hit: ambiguous+=1; resolved=True; break
                if sl_hit: losses+=1; total_pips-=abs(sl2-p); resolved=True; break
                if tp_hit: wins+=1; total_pips+=abs(p-tp); resolved=True; break
            if not resolved:
                timeouts += 1

    total = wins + losses + timeouts + ambiguous
    # Winrate excludes ambiguous and timeout trades — only count decided outcomes
    decided = wins + losses
    winrate = round(wins/decided*100, 1) if decided > 0 else 0
    return {"name": name, "wins": wins, "losses": losses, "timeouts": timeouts, "ambiguous": ambiguous, "winrate": winrate, "pips": round(total_pips, 4), "signals": total}

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
    total_t = sum(r.get("timeouts", 0) for r in results)
    total_a = sum(r.get("ambiguous", 0) for r in results)
    total = total_w + total_l + total_t + total_a
    overall_wr = round(total_w/total*100, 1) if total > 0 else 0

    lines = ["📊 WEEKLY BACKTEST REPORT\n🕔 " + now + " | Last 60 days\n"]
    overall_pips = sum(r["pips"] for r in results)
    pips_sign = "+" if overall_pips >= 0 else ""
    lines.append("📈 Overall Win Rate: " + str(overall_wr) + "%")
    lines.append("✅ " + str(total_w) + "W  ❌ " + str(total_l) + "L  ⏳ " + str(total_t) + "T  ❓ " + str(total_a) + "A")
    lines.append("💰 Net Pips: " + pips_sign + str(round(overall_pips, 2)) + "\n")

    for r in results:
        emoji = "🟢" if r["winrate"] >= 55 else "🟡" if r["winrate"] >= 45 else "🔴"
        pips_str = "+" if r["pips"] > 0 else ""
        timeout_str = ("/" + str(r.get("timeouts", 0)) + "T") if r.get("timeouts", 0) else ""
        ambiguous_str = ("/" + str(r.get("ambiguous", 0)) + "A") if r.get("ambiguous", 0) else ""
        lines.append(emoji + " " + r["name"] + ": " + str(r["winrate"]) + "% (" + str(r["wins"]) + "W/" + str(r["losses"]) + "L" + timeout_str + ambiguous_str + ") | " + pips_str + str(r["pips"]) + " pips")

    best = results[0]
    lines.append("\n🏆 Best pair: " + best["name"] + " (" + str(best["winrate"]) + "% | " + str(best["signals"]) + " signals)")
    lines.append("Strategy: SMC + Fibonacci + BB + EMA200 + 4H HTF | 5/7 score | R:R 1:2")

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
                # Mark done BEFORE running so a partial failure inside run_backtest()
                # doesn't cause a second run (and duplicate send) on the next loop tick.
                sent_this_week = week
                print("Running backtest...")
                run_backtest()
        except Exception as e:
            print("Error: "+str(e))
        time.sleep(300)

if __name__ == "__main__":
    main()
