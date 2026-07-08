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

# Same two pairs as signal_strategy.py — kept in sync deliberately, this weekly report
# is an ongoing out-of-sample check on the exact strategy that's live, not a separate one.
PAIRS = {
    "USD/CAD": "USDCAD=X",
    "Oil/USD": "CL=F",
}

RR = 1.5  # matches signal_strategy.RR


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


def backtest_pair(name, symbol):
    """HTF trend (EMA50/200) + pullback-to-EMA20 + rejection confirmation — identical
    logic to signal_strategy.find_setup(), so this weekly report tracks the strategy
    that's actually live, not a stand-in. Entry at the open of the bar AFTER the
    confirmation candle closes — no look-ahead bias."""
    try:
        df = yf.Ticker(symbol).history(period="90d", interval="1h")
        if len(df) < 300:
            df = yf.Ticker(symbol).history(period="60d", interval="1h")
    except Exception as e:
        print(f"backtest_pair data error {name}: {e}")
        return None
    if len(df) < 261:
        return None

    close = df["Close"]; high = df["High"]; low = df["Low"]; open_ = df["Open"]
    ema20 = close.ewm(span=20).mean()
    ema50 = close.ewm(span=50).mean()
    ema200 = close.ewm(span=200).mean()
    tr = pd.concat([high-low, (high-close.shift()).abs(), (low-close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()

    wins = losses = timeouts = ambiguous = 0
    total_R = 0.0
    n = len(df)

    for i in range(200, n - 60):
        a = atr.iloc[i]
        if pd.isna(a) or a == 0:
            continue

        bull_trend = ema50.iloc[i] > ema200.iloc[i]
        bear_trend = ema50.iloc[i] < ema200.iloc[i]
        pull_low = low.iloc[i-1]; pull_high = high.iloc[i-1]
        tol = a * 0.5

        if bull_trend:
            touched = pull_low <= ema20.iloc[i-1] + tol
            body = close.iloc[i] - open_.iloc[i]
            rng = high.iloc[i] - low.iloc[i]
            body_ratio = body / rng if rng > 0 else 0
            if touched and body > 0 and body_ratio > 0.5 and close.iloc[i] > ema20.iloc[i] and i+1 < n:
                entry = open_.iloc[i+1]
                sl = pull_low - a * 0.3
                risk = entry - sl
                if risk <= 0:
                    continue
                tp = entry + risk * RR
                resolved = False
                for j in range(i+1, min(i+61, n)):
                    sl_hit = low.iloc[j] <= sl
                    tp_hit = high.iloc[j] >= tp
                    if sl_hit and tp_hit:
                        ambiguous += 1; resolved = True; break
                    if sl_hit:
                        losses += 1; total_R -= 1; resolved = True; break
                    if tp_hit:
                        wins += 1; total_R += RR; resolved = True; break
                if not resolved:
                    timeouts += 1
                continue

        if bear_trend:
            touched = pull_high >= ema20.iloc[i-1] - tol
            body = open_.iloc[i] - close.iloc[i]
            rng = high.iloc[i] - low.iloc[i]
            body_ratio = body / rng if rng > 0 else 0
            if touched and body > 0 and body_ratio > 0.5 and close.iloc[i] < ema20.iloc[i] and i+1 < n:
                entry = open_.iloc[i+1]
                sl = pull_high + a * 0.3
                risk = sl - entry
                if risk <= 0:
                    continue
                tp = entry - risk * RR
                resolved = False
                for j in range(i+1, min(i+61, n)):
                    sl_hit = high.iloc[j] >= sl
                    tp_hit = low.iloc[j] <= tp
                    if sl_hit and tp_hit:
                        ambiguous += 1; resolved = True; break
                    if sl_hit:
                        losses += 1; total_R -= 1; resolved = True; break
                    if tp_hit:
                        wins += 1; total_R += RR; resolved = True; break
                if not resolved:
                    timeouts += 1

    total = wins + losses + timeouts + ambiguous
    decided = wins + losses
    winrate = round(wins/decided*100, 1) if decided > 0 else 0
    return {
        "name": name, "wins": wins, "losses": losses, "timeouts": timeouts,
        "ambiguous": ambiguous, "winrate": winrate, "total_R": round(total_R, 2),
        "signals": total,
    }


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
    overall_R = sum(r["total_R"] for r in results)

    lines = ["📊 WEEKLY BACKTEST REPORT\n🕔 " + now + " | Last 90 days\n"]
    r_sign = "+" if overall_R >= 0 else ""
    lines.append("📈 Overall Win Rate: " + str(overall_wr) + "%")
    lines.append("✅ " + str(total_w) + "W  ❌ " + str(total_l) + "L  ⏳ " + str(total_t) + "T  ❓ " + str(total_a) + "A")
    lines.append("💰 Net R: " + r_sign + str(round(overall_R, 2)) + "R\n")

    for r in results:
        emoji = "🟢" if r["winrate"] >= 45 else "🟡" if r["winrate"] >= 35 else "🔴"
        r_str = "+" if r["total_R"] > 0 else ""
        timeout_str = ("/" + str(r.get("timeouts", 0)) + "T") if r.get("timeouts", 0) else ""
        ambiguous_str = ("/" + str(r.get("ambiguous", 0)) + "A") if r.get("ambiguous", 0) else ""
        lines.append(emoji + " " + r["name"] + ": " + str(r["winrate"]) + "% (" + str(r["wins"]) + "W/" + str(r["losses"]) + "L" + timeout_str + ambiguous_str + ") | " + r_str + str(r["total_R"]) + "R")

    best = results[0]
    lines.append("\n🏆 Best pair: " + best["name"] + " (" + str(best["winrate"]) + "% | " + str(best["signals"]) + " signals)")
    lines.append("Strategy: Pullback to EMA20 + confirmation | 1H | R:R 1:" + str(RR))

    send_all("\n".join(lines))
    print("Backtest report sent!")


def main():
    print("Backtest bot started (pullback strategy, USD/CAD + Oil/USD)...")
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
