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

import chart

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN_SIGNAL")
if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN_SIGNAL is not set in environment")
SIGNALS_CHANNEL = os.getenv("SIGNALS_CHANNEL")
if not SIGNALS_CHANNEL:
    raise RuntimeError("SIGNALS_CHANNEL is not set in environment")
USERS_FILE = "/root/tradingbot/users.json"
TRADES_FILE = "/root/tradingbot/open_trades.json"
STATS_FILE = "/root/tradingbot/trade_stats.json"

SYMBOLS = {
    "USD/CAD": "USDCAD=X",
    "Oil/USD": "CL=F",
}

PAIR_EMOJIS = {
    "USD/CAD": "\U0001f1e8\U0001f1e6",
    "Oil/USD": "\U0001f6e2",
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
    with open(lock_path, "a") as _lf:
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
            payload.pop("reply_to_message_id")
            r = requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendMessage",
                json=payload, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"send_channel_reply error: {e}")

def send_result_photo(photo_path, caption, reply_to_message_id=None):
    """Send a generated result chart to the signals channel, optionally as a reply.
    Deletes the chart file after sending (each one is unique, nothing to cache)."""
    if not SIGNALS_CHANNEL or not TELEGRAM_TOKEN:
        return
    cap = caption[:1024]
    try:
        if not photo_path or not os.path.exists(photo_path):
            send_channel_reply(cap, reply_to_message_id)
            return
        data = {"chat_id": SIGNALS_CHANNEL, "caption": cap}
        if reply_to_message_id:
            data["reply_to_message_id"] = str(reply_to_message_id)
        with open(photo_path, "rb") as pf:
            r = requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendPhoto",
                files={"photo": ("chart.png", pf, "image/png")},
                data=data, timeout=20)
        if not r.ok and reply_to_message_id:
            # Retry without reply if the original was deleted
            data.pop("reply_to_message_id", None)
            with open(photo_path, "rb") as pf:
                r = requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendPhoto",
                    files={"photo": ("chart.png", pf, "image/png")},
                    data=data, timeout=20)
        r.raise_for_status()
    except Exception as e:
        print(f"send_result_photo error: {e}")
        send_channel_reply(cap, reply_to_message_id)
    finally:
        if photo_path and os.path.exists(photo_path):
            try:
                os.remove(photo_path)
            except OSError:
                pass

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
    # Pre-fetch prices BEFORE acquiring the lock so yfinance latency doesn't
    # block signal_strategy.py (which acquires the same lock to write new trades).
    snapshot = load_trades()
    price_cache = {}
    for trade in snapshot:
        symbol = SYMBOLS.get(trade.get("name", ""))
        if symbol and symbol not in price_cache:
            price_cache[symbol] = get_price(symbol)

    lock_path = TRADES_FILE + '.lock'
    with open(lock_path, 'a') as _lf:
        fcntl.flock(_lf, fcntl.LOCK_EX)
        try:
            _check_trades_inner(price_cache)
        finally:
            fcntl.flock(_lf, fcntl.LOCK_UN)

def _check_trades_inner(price_cache):
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

        price = price_cache.get(symbol)
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
        if not tp_hit and not sl_hit:
            half_move = abs(tp - entry) * 0.5
            sig_msg_id = trade.get("signal_message_id")
            # Use 1e-6 epsilon: round(entry,5) < entry by float precision, causing infinite loop
            if signal == "BUY" and price >= entry + half_move and sl < entry - 1e-6:
                trade["sl"] = round(entry, 5)
                open_mins = int((time.time() - trade.get("time", time.time())) / 60)
                dur = f"{open_mins//60}h {open_mins%60}min" if open_mins >= 60 else f"{open_mins}min"
                print(f"Breakeven set for {name} BUY @ {entry}")
                be_msg = (
                    f"\U0001f6e1 BREAKEVEN SET\n\n{emoji} {name}\n"
                    f"⏱ Open for: {dur}\n"
                    f"Entry: {round(entry,5)}  ➡️  Current: {round(price,5)}\n"
                    f"SL moved to entry — risk = 0 ✅"
                )
                photo_path = chart.make_result_chart(name, symbol, signal, entry, trade["sl"], tp, trade.get("time", time.time()), "BE")
                send_result_photo(photo_path, be_msg, sig_msg_id)
            elif signal == "SELL" and price <= entry - half_move and sl > entry + 1e-6:
                trade["sl"] = round(entry, 5)
                open_mins = int((time.time() - trade.get("time", time.time())) / 60)
                dur = f"{open_mins//60}h {open_mins%60}min" if open_mins >= 60 else f"{open_mins}min"
                print(f"Breakeven set for {name} SELL @ {entry}")
                be_msg = (
                    f"\U0001f6e1 BREAKEVEN SET\n\n{emoji} {name}\n"
                    f"⏱ Open for: {dur}\n"
                    f"Entry: {round(entry,5)}  ➡️  Current: {round(price,5)}\n"
                    f"SL moved to entry — risk = 0 ✅"
                )
                photo_path = chart.make_result_chart(name, symbol, signal, entry, trade["sl"], tp, trade.get("time", time.time()), "BE")
                send_result_photo(photo_path, be_msg, sig_msg_id)

        if tp_hit:
            closed.append((trade, "WIN", abs(tp - entry), now))
        elif sl_hit:
            pips_lost = abs(sl - entry)
            # Breakeven: SL was moved to entry and hit — not a loss.
            # Use 1e-5 tolerance to absorb float rounding from round(entry, 5).
            result_label = "BE" if pips_lost < 1e-5 else "LOSS"
            closed.append((trade, result_label, pips_lost, now))
        else:
            remaining.append(trade)

    # Remove closed trades from persistent storage FIRST so a crash here
    # can't cause double-counting on the next check cycle.
    save_trades(remaining)

    # Ensure by_pair key exists before iterating over closed trades
    if "by_pair" not in stats:
        stats["by_pair"] = {}

    # Now update stats, send notifications, and write journal for each closed trade
    for trade, result, pips, now in closed:
        name = trade["name"]
        symbol = SYMBOLS.get(name)
        signal = trade["signal"]
        entry = trade["entry"]
        sl = trade["sl"]
        tp = trade["tp"]
        emoji = PAIR_EMOJIS.get(name, "")
        sig_msg_id = trade.get("signal_message_id")
        entry_time = trade.get("time", time.time())

        pair_s = stats["by_pair"].setdefault(name, {"wins": 0, "losses": 0})

        open_mins = int((time.time() - trade.get("time", time.time())) / 60)
        dur = f"{open_mins//60}h {open_mins%60}min" if open_mins >= 60 else f"{open_mins}min"

        if result == "WIN":
            stats["wins"] += 1
            stats["total_pips"] += pips
            pair_s["wins"] += 1
            total = stats["wins"] + stats["losses"]
            winrate = round((stats["wins"] / total) * 100, 1) if total > 0 else 0
            _is_raw = any(k in name for k in ("XAU", "BTC", "SOL", "Silver", "Oil", "Copper"))
            pips_display = round(pips * (100 if "JPY" in name else 10000), 1) if not _is_raw else round(pips, 4)
            pips_unit = "pips" if not _is_raw else ""
            msg = (
                "\U0001f3af TAKE PROFIT HIT! \U0001f4b0\n\n"
                + emoji + " " + name + " | " + now + "\n"
                "⏱ Duration: " + dur + "\n\n"
                + signal + ": " + str(round(entry, 5)) + " ➡️ " + str(round(tp, 5)) + "\n"
                "Profit: +" + str(pips_display) + " " + pips_unit + " \U0001f7e2\n\n"
                "\U0001f4ca " + str(stats["wins"]) + "W / " + str(stats["losses"]) + "L | WR: " + str(winrate) + "%"
            )
            photo_path = chart.make_result_chart(name, symbol, signal, entry, sl, tp, entry_time, "WIN")
            send_result_photo(photo_path, msg, sig_msg_id)
            print("TP hit: " + name)
            _append_journal({"pair":name,"side":signal,"result":"WIN","pips":"+"+str(round(pips,4)),"note":"Auto - TP Hit","date":now})

        elif result == "BE":
            msg = (
                "\U0001f6e1 BREAKEVEN CLOSED \U0001f7e1\n\n"
                + emoji + " " + name + " | " + now + "\n"
                "⏱ Duration: " + dur + "\n\n"
                + signal + ": Entry " + str(round(entry, 5)) + "\n"
                "SL hit at entry — capital protected"
            )
            photo_path = chart.make_result_chart(name, symbol, signal, entry, sl, tp, entry_time, "BE")
            send_result_photo(photo_path, msg, sig_msg_id)
            print("BE closed: " + name)
            _append_journal({"pair":name,"side":signal,"result":"BE","pips":"0","note":"Auto - Breakeven","date":now})

        else:  # LOSS
            stats["losses"] += 1
            stats["total_pips"] -= pips
            pair_s["losses"] += 1
            total = stats["wins"] + stats["losses"]
            winrate = round((stats["wins"] / total) * 100, 1) if total > 0 else 0
            _is_raw = any(k in name for k in ("XAU", "BTC", "SOL", "Silver", "Oil", "Copper"))
            pips_display = round(pips * (100 if "JPY" in name else 10000), 1) if not _is_raw else round(pips, 4)
            pips_unit = "pips" if not _is_raw else ""
            msg = (
                "\U0000274c STOP LOSS HIT\n\n"
                + emoji + " " + name + " | " + now + "\n"
                "⏱ Duration: " + dur + "\n\n"
                + signal + ": " + str(round(entry, 5)) + " ➡️ " + str(round(sl, 5)) + "\n"
                "Loss: -" + str(pips_display) + " " + pips_unit + " \U0001f534\n\n"
                "\U0001f4ca " + str(stats["wins"]) + "W / " + str(stats["losses"]) + "L | WR: " + str(winrate) + "%"
            )
            photo_path = chart.make_result_chart(name, symbol, signal, entry, sl, tp, entry_time, "LOSS")
            send_result_photo(photo_path, msg, sig_msg_id)
            print("SL hit: " + name)
            _append_journal({"pair":name,"side":signal,"result":"LOSS","pips":"-"+str(round(pips,4)),"note":"Auto - SL Hit","date":now})

    if closed:
        save_stats(stats)  # only write when stats actually changed

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
    send_channel_reply(msg)
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
