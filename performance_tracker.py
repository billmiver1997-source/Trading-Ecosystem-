import os
from dotenv import load_dotenv
load_dotenv("/root/tradingbot/.env")

import fcntl
import yfinance as yf
import requests
import json
import time
from datetime import datetime
import pytz

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN_SIGNAL")
if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN_SIGNAL is not set in environment")
SIGNALS_CHANNEL = os.getenv("SIGNALS_CHANNEL")
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
    "USD/JPY": "USDJPY=X",
}

PAIR_EMOJIS = {
    "USD/CHF": "\U0001f1fa\U0001f1f8",
    "AUD/USD": "\U0001f1e6\U0001f1fa",
    "EUR/USD": "\U0001f1ea\U0001f1fa",
    "EUR/CHF": "\U0001f1e8\U0001f1ed",
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
    "USD/JPY": "\U0001f1ef\U0001f1f5",
}

def load_users():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError, OSError) as e:
            print(f"load_users error: {e}")
    return []

def load_trades():
    if os.path.exists(TRADES_FILE):
        try:
            with open(TRADES_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError, OSError) as e:
            print(f"load_trades JSON error (file may be corrupted): {e}")
    return []

def save_trades(trades):
    # atomic write prevents partial-write corruption
    tmp = TRADES_FILE + '.tmp'
    try:
        with open(tmp, 'w') as f:
            json.dump(trades, f)
        os.replace(tmp, TRADES_FILE)
    except Exception as e:
        print(f"save_trades error: {e}")

def load_stats():
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError, OSError) as e:
            print(f"load_stats JSON error: {e}")
    return {"wins": 0, "losses": 0, "total_pips": 0.0, "by_pair": {}}

def save_stats(stats):
    tmp = STATS_FILE + '.tmp'
    try:
        with open(tmp, 'w') as f:
            json.dump(stats, f)
        os.replace(tmp, STATS_FILE)
    except Exception as e:
        print(f"save_stats error: {e}")

JOURNAL_FILE = "/root/tradingbot/journal.json"

def _append_journal(entry):
    """Atomically append one entry to journal.json, capped at 200 entries."""
    lock_path = JOURNAL_FILE + ".lock"
    with open(lock_path, "w") as _lf:
        fcntl.flock(_lf, fcntl.LOCK_EX)
        try:
            entries = []
            if os.path.exists(JOURNAL_FILE):
                try:
                    with open(JOURNAL_FILE) as f:
                        entries = json.load(f)
                except (json.JSONDecodeError, ValueError) as e:
                    print(f"journal load error: {e}")
            entries.append(entry)
            entries = entries[-200:]
            tmp = JOURNAL_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(entries, f)
            os.replace(tmp, JOURNAL_FILE)
        finally:
            fcntl.flock(_lf, fcntl.LOCK_UN)

def send_all(msg):
    for chat_id in load_users():
        try:
            r = requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendMessage",
                json={"chat_id": chat_id, "text": msg[:4000]}, timeout=10)
            r.raise_for_status()
            time.sleep(0.1)
        except Exception as e:
            print(f"send_all error {chat_id}: {e}")

def send_channel_reply(msg, reply_to_message_id=None):
    """Send result to signals channel, replying to the original signal message."""
    if not SIGNALS_CHANNEL or not TELEGRAM_TOKEN:
        return
    try:
        payload = {"chat_id": SIGNALS_CHANNEL, "text": msg[:4000]}
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id
        r = requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendMessage",
            json=payload, timeout=10)
        if not r.ok and reply_to_message_id:
            # Original message may have been deleted — retry without reply
            payload.pop("reply_to_message_id")
            r = requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendMessage",
                json=payload, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"send_channel_reply error: {e}")

def get_price(symbol):
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="1d", interval="1m")
        if len(df) > 0:
            return float(df["Close"].iloc[-1])
    except Exception as e:
        print(f"get_price error {symbol}: {e}")
    return None

def check_trades():
    # Exclusive lock prevents race with signal_strategy.py writing to the same file
    lock_path = TRADES_FILE + '.lock'
    with open(lock_path, 'w') as _lf:
        fcntl.flock(_lf, fcntl.LOCK_EX)
        try:
            _check_trades_inner()
        finally:
            fcntl.flock(_lf, fcntl.LOCK_UN)

def _check_trades_inner():
    trades = load_trades()
    if not trades:
        return

    stats = load_stats()
    tz = pytz.timezone("Europe/Athens")
    remaining = []
    closed = []  # list of (trade, "WIN"/"LOSS", pips, now_str)

    for trade in trades:
        name = trade["name"]
        symbol = SYMBOLS.get(name)
        if not symbol:
            remaining.append(trade)
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
            sig_msg_id = trade.get("signal_message_id")
            if signal == "BUY" and price >= entry + half_move and sl < entry:
                trade["sl"] = round(entry, 5)
                print(f"Breakeven set for {name} BUY @ {entry}")
                be_msg = (
                    f"\U0001f6e1 BREAKEVEN SET\n\n{emoji} {name}\n"
                    f"Trade moved to breakeven @ {round(entry,5)}\n"
                    f"Current price: {round(price,5)}"
                )
                send_channel_reply(be_msg, sig_msg_id)
                send_all(be_msg)
            elif signal == "SELL" and price <= entry - half_move and sl > entry:
                trade["sl"] = round(entry, 5)
                print(f"Breakeven set for {name} SELL @ {entry}")
                be_msg = (
                    f"\U0001f6e1 BREAKEVEN SET\n\n{emoji} {name}\n"
                    f"Trade moved to breakeven @ {round(entry,5)}\n"
                    f"Current price: {round(price,5)}"
                )
                send_channel_reply(be_msg, sig_msg_id)
                send_all(be_msg)

        if tp_hit:
            closed.append((trade, "WIN", abs(tp - entry), now))
        elif sl_hit:
            pips_lost = abs(sl - entry)
            # Breakeven: SL was moved to entry and hit — not a loss
            result_label = "BE" if pips_lost < 1e-9 else "LOSS"
            closed.append((trade, result_label, pips_lost, now))
        else:
            remaining.append(trade)

    # Remove closed trades from persistent storage FIRST so a crash here
    # can't cause double-counting on the next check cycle.
    save_trades(remaining)

    # Now update stats, send notifications, and write journal for each closed trade
    for trade, result, pips, now in closed:
        name = trade["name"]
        signal = trade["signal"]
        entry = trade["entry"]
        sl = trade["sl"]
        tp = trade["tp"]
        emoji = PAIR_EMOJIS.get(name, "")
        sig_msg_id = trade.get("signal_message_id")

        if "by_pair" not in stats:
            stats["by_pair"] = {}
        pair_s = stats["by_pair"].setdefault(name, {"wins": 0, "losses": 0})

        if result == "WIN":
            stats["wins"] += 1
            stats["total_pips"] += pips
            pair_s["wins"] += 1
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
            send_channel_reply(msg, sig_msg_id)
            send_all(msg)
            print("TP hit: " + name)
            _append_journal({"pair":name,"side":signal,"result":"WIN","pips":"+"+str(round(pips,4)),"note":"Auto - TP Hit","date":now})

        elif result == "BE":
            msg = (
                "\U0001f6e1 BREAKEVEN CLOSED\n\n"
                + emoji + " " + name + " | " + now + "\n\n"
                "Signal: " + signal + "\n"
                "Entry: " + str(round(entry, 5)) + "\n"
                "Result: Breakeven \U0001f7e1"
            )
            send_channel_reply(msg, sig_msg_id)
            send_all(msg)
            print("BE closed: " + name)
            _append_journal({"pair":name,"side":signal,"result":"BE","pips":"0","note":"Auto - Breakeven","date":now})

        else:  # LOSS
            stats["losses"] += 1
            stats["total_pips"] -= pips
            pair_s["losses"] += 1
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
            send_channel_reply(msg, sig_msg_id)
            send_all(msg)
            print("SL hit: " + name)
            _append_journal({"pair":name,"side":signal,"result":"LOSS","pips":"-"+str(round(pips,4)),"note":"Auto - SL Hit","date":now})

    save_stats(stats)  # single write after all closed trades are processed

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
