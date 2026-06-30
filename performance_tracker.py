import os
from dotenv import load_dotenv
load_dotenv("/root/tradingbot/.env")

import yfinance as yf
import requests
import json
import time
from datetime import datetime
import pytz

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN_SIGNAL")
USERS_FILE = "/root/tradingbot/users.json"
TRADES_FILE = "/root/tradingbot/open_trades.json"
STATS_FILE = "/root/tradingbot/trade_stats.json"

SYMBOLS = {
    "USD/CHF": "USDCHF=X",
    "AUD/USD": "AUDUSD=X",
    "EUR/USD": "EURUSD=X",
    "EUR/CHF": "EURCHF=X",
    "GBP/USD": "GBPUSD=X",
    "USD/CAD": "USDCAD=X",
    "NZD/USD": "NZDUSD=X",
    "XAU/USD": "GC=F",
    "Silver/USD": "SI=F",
    "Copper/USD": "HG=F",
    "Oil/USD": "CL=F",
    "BTC/USD": "BTC-USD",
    "SOL/USD": "SOL-USD",
    "DXY": "DX-Y.NYB",
}

PAIR_EMOJIS = {
    "USD/CHF": "\U0001f1fa\U0001f1f8",
    "AUD/USD": "\U0001f1e6\U0001f1fa",
    "EUR/USD": "\U0001f1ea\U0001f1fa",
    "EUR/CHF": "\U0001f1ea\U0001f1fa",
    "GBP/USD": "\U0001f1ec\U0001f1e7",
    "USD/CAD": "\U0001f1e8\U0001f1e6",
    "NZD/USD": "\U0001f1f3\U0001f1ff",
    "XAU/USD": "\U0001fa99",
    "Silver/USD": "\U0001f948",
    "Copper/USD": "\U0001f7e0",
    "Oil/USD": "\U0001f6e2",
    "BTC/USD": "\U0001f7e1",
    "SOL/USD": "\U0001f535",
    "DXY": "\U0001f4b5",
}

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE) as f:
            return json.load(f)
    return []

def load_trades():
    if os.path.exists(TRADES_FILE):
        with open(TRADES_FILE) as f:
            return json.load(f)
    return []

def save_trades(trades):
    with open(TRADES_FILE, "w") as f:
        json.dump(trades, f)

def load_stats():
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE) as f:
            return json.load(f)
    return {"wins": 0, "losses": 0, "total_pips": 0.0, "by_pair": {}}

def save_stats(stats):
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f)

def send_all(msg):
    for chat_id in load_users():
        try:
            requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendMessage",
                json={"chat_id": chat_id, "text": msg[:4000]})
            time.sleep(0.1)
        except Exception as e:
            print(f"send_all error: {e}")

def get_price(symbol):
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="1d", interval="1m")
        if len(df) > 0:
            return float(df["Close"].iloc[-1])
    except Exception as e:
        print(f"get_price error {symbol}: {e}")
    return None

def add_trade(name, signal, entry, sl, tp):
    trades = load_trades()
    trades.append({
        "name": name,
        "signal": signal,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "time": time.time()
    })
    save_trades(trades)

def check_trades():
    trades = load_trades()
    if not trades:
        return

    remaining = []
    stats = load_stats()
    tz = pytz.timezone("Europe/Athens")

    for trade in trades:
        name = trade["name"]
        symbol = SYMBOLS.get(name)
        if not symbol:
            continue

        price = get_price(symbol)
        if price is None:
            remaining.append(trade)
            continue

        entry = trade["entry"]
        sl = trade["sl"]
        tp = trade["tp"]
        signal = trade["signal"]
        emoji = PAIR_EMOJIS.get(name, "")
        now = datetime.now(tz).strftime("%d/%m/%Y %H:%M")

        tp_hit = (signal == "BUY" and price >= tp) or (signal == "SELL" and price <= tp)
        sl_hit = (signal == "BUY" and price <= sl) or (signal == "SELL" and price >= sl)

        # Trailing SL: move to breakeven when price covers 50% to TP
        atr = trade.get("atr", 0)
        if atr and not tp_hit and not sl_hit:
            half_move = abs(tp - entry) * 0.5
            if signal == "BUY" and price >= entry + half_move and sl < entry:
                trade["sl"] = round(entry, 5)
                print(f"Breakeven set for {name} BUY @ {entry}")
                send_all(
                    f"\U0001f6e1 BREAKEVEN SET\n\n{emoji} {name}\n"
                    f"Trade moved to breakeven @ {round(entry,5)}\n"
                    f"Current price: {round(price,5)}"
                )
            elif signal == "SELL" and price <= entry - half_move and sl > entry:
                trade["sl"] = round(entry, 5)
                print(f"Breakeven set for {name} SELL @ {entry}")
                send_all(
                    f"\U0001f6e1 BREAKEVEN SET\n\n{emoji} {name}\n"
                    f"Trade moved to breakeven @ {round(entry,5)}\n"
                    f"Current price: {round(price,5)}"
                )

        if tp_hit:
            pips = abs(tp - entry)
            stats["wins"] += 1
            stats["total_pips"] += pips
            if "by_pair" not in stats:
                stats["by_pair"] = {}
            pair_s = stats["by_pair"].setdefault(name, {"wins": 0, "losses": 0})
            pair_s["wins"] += 1
            save_stats(stats)
            total = stats["wins"] + stats["losses"]
            winrate = round((stats["wins"] / total) * 100, 1) if total > 0 else 0
            msg = (
                "\U0001f3af TAKE PROFIT HIT!\n\n"
                + emoji + " " + name + " | " + now + "\n\n"
                "Signal: " + signal + "\n"
                "Entry: " + str(round(entry, 5)) + "\n"
                "TP: " + str(round(tp, 5)) + "\n"
                "Result: +"+str(round(pips, 5))+" \U0001f4b0\n\n"
                "\U0001f4ca Stats: " + str(stats["wins"]) + "W / " + str(stats["losses"]) + "L | Win Rate: " + str(winrate) + "%"
            )
            send_all(msg)
            print("TP hit: " + name)
            # Auto journal
            import json as j2
            jf = "/root/tradingbot/journal.json"
            entries = j2.load(open(jf)) if os.path.exists(jf) else []
            entries.append({"pair":name,"side":signal,"result":"WIN","pips":"+"+str(round(pips,4)),"note":"Auto - TP Hit","date":now})
            entries = entries[-200:]
            with open(jf,"w") as f2: j2.dump(entries,f2)

        elif sl_hit:
            pips = abs(sl - entry)
            stats["losses"] += 1
            stats["total_pips"] -= pips
            if "by_pair" not in stats:
                stats["by_pair"] = {}
            pair_s = stats["by_pair"].setdefault(name, {"wins": 0, "losses": 0})
            pair_s["losses"] += 1
            save_stats(stats)
            total = stats["wins"] + stats["losses"]
            winrate = round((stats["wins"] / total) * 100, 1) if total > 0 else 0
            msg = (
                "\U0000274c STOP LOSS HIT\n\n"
                + emoji + " " + name + " | " + now + "\n\n"
                "Signal: " + signal + "\n"
                "Entry: " + str(round(entry, 5)) + "\n"
                "SL: " + str(round(sl, 5)) + "\n"
                "Result: -"+str(round(pips, 5))+" \U0001f4c9\n\n"
                "\U0001f4ca Stats: " + str(stats["wins"]) + "W / " + str(stats["losses"]) + "L | Win Rate: " + str(winrate) + "%"
            )
            send_all(msg)
            print("SL hit: " + name)
            # Auto journal
            import json as j2
            jf = "/root/tradingbot/journal.json"
            entries = j2.load(open(jf)) if os.path.exists(jf) else []
            entries.append({"pair":name,"side":signal,"result":"LOSS","pips":"-"+str(round(pips,4)),"note":"Auto - SL Hit","date":now})
            entries = entries[-200:]
            with open(jf,"w") as f2: j2.dump(entries,f2)

        else:
            remaining.append(trade)

    save_trades(remaining)

def send_daily_stats():
    stats = load_stats()
    total = stats["wins"] + stats["losses"]
    if total == 0:
        return
    winrate = round((stats["wins"] / total) * 100, 1)
    tz = pytz.timezone("Europe/Athens")
    now = datetime.now(tz).strftime("%d/%m/%Y")
    msg = (
        "\U0001f4ca PERFORMANCE REPORT\n\U0001f554 " + now + "\n\n"
        "\U0001f7e2 Wins: " + str(stats["wins"]) + "\n"
        "\U0001f534 Losses: " + str(stats["losses"]) + "\n"
        "\U0001f3af Win Rate: " + str(winrate) + "%\n"
        "\U0001f4b0 Total P&L: " + str(round(stats["total_pips"], 4)) + " pips"
    )
    send_all(msg)
    print("Daily stats sent!")

def main():
    print("Performance tracker started...")
    last_stats_day = ""
    while True:
        try:
            check_trades()
            tz = pytz.timezone("Europe/Athens")
            now = datetime.now(tz)
            today = now.strftime("%Y-%m-%d")
            if now.hour == 23 and now.minute >= 50 and last_stats_day != today:
                send_daily_stats()
                last_stats_day = today
        except Exception as e:
            print("Error: "+str(e))
        time.sleep(60)

if __name__ == "__main__":
    main()
