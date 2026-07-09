"""Broader-pair "developing setup" scanner — a heads-up, not a trade call. Scans
a wider basket than the 2 pairs signal_strategy.py actually trades, using looser
criteria (price approaching EMA20 in the HTF trend direction, no confirmation
candle required yet) so users get early awareness of pairs worth watching
manually. Deliberately has no entry/SL/TP and no chart, so it can never be
mistaken for an actual trade signal.
"""
import os
from dotenv import load_dotenv
load_dotenv("/root/tradingbot/.env")

import json
import time
import requests
import pandas as pd
import yfinance as yf
import pytz
from datetime import datetime

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN_SIGNAL")
SIGNALS_CHANNEL = os.getenv("SIGNALS_CHANNEL")
if not TELEGRAM_TOKEN or not SIGNALS_CHANNEL:
    raise RuntimeError("TELEGRAM_TOKEN_SIGNAL and SIGNALS_CHANNEL must be set in .env")

STATE_FILE = "/root/tradingbot/watchlist_state.json"
OPEN_TRADES_FILE = "/root/tradingbot/open_trades.json"
SCAN_INTERVAL = 3600  # hourly — matches the 1H candle resolution being scanned

PAIRS = {
    "XAU/USD": "GC=F", "Silver/USD": "SI=F", "Oil/USD": "CL=F", "SOL/USD": "SOL-USD",
    "EUR/USD": "EURUSD=X", "GBP/USD": "GBPUSD=X", "USD/CHF": "USDCHF=X",
    "AUD/USD": "AUDUSD=X", "USD/CAD": "USDCAD=X", "NZD/USD": "NZDUSD=X", "USD/JPY": "USDJPY=X",
}

PAIR_EMOJIS = {
    "XAU/USD": "\U0001fa99", "Silver/USD": "\U0001f948", "Oil/USD": "⛽", "SOL/USD": "\U0001f535",
    "EUR/USD": "\U0001f1ea\U0001f1fa", "GBP/USD": "\U0001f1ec\U0001f1e7", "USD/CHF": "\U0001f1fa\U0001f1f8",
    "AUD/USD": "\U0001f1e6\U0001f1fa", "USD/CAD": "\U0001f1e8\U0001f1e6", "NZD/USD": "\U0001f1f3\U0001f1ff",
    "USD/JPY": "\U0001f1ef\U0001f1f5",
}


def _load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError, OSError) as e:
            print(f"load {path} error: {e}")
    return default


def _save_json(path, data):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except Exception as e:
        print(f"save {path} error: {e}")


def get_data(symbol):
    try:
        df = yf.Ticker(symbol).history(period="30d", interval="1h")
        if len(df) < 210:
            df = yf.Ticker(symbol).history(period="60d", interval="1h")
        if len(df) < 210:
            return None
        return df
    except Exception as e:
        print(f"get_data error {symbol}: {e}")
        return None


def find_developing_setup(df):
    """Looser than signal_strategy.find_setup: HTF trend + price currently
    within the EMA20 pullback zone — no rejection confirmation candle required
    yet, so this fires earlier (and less reliably) than an actual signal."""
    if df is None or len(df) < 210:
        return None
    close = df["Close"]; high = df["High"]; low = df["Low"]
    ema20 = close.ewm(span=20).mean()
    ema50 = close.ewm(span=50).mean()
    ema200 = close.ewm(span=200).mean()
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()

    price = close.iloc[-1]
    a = atr.iloc[-1]
    if pd.isna(a) or a == 0:
        return None
    tol = a * 0.6

    bull_trend = ema50.iloc[-1] > ema200.iloc[-1]
    bear_trend = ema50.iloc[-1] < ema200.iloc[-1]
    near_ema20 = abs(price - ema20.iloc[-1]) <= tol

    if bull_trend and near_ema20:
        return {"bias": "BULLISH", "price": price}
    if bear_trend and near_ema20:
        return {"bias": "BEARISH", "price": price}
    return None


def send_watchlist_alert(name, setup):
    emoji = PAIR_EMOJIS.get(name, "")
    action = "support" if setup["bias"] == "BULLISH" else "resistance"
    bias_emoji = "\U0001f7e2" if setup["bias"] == "BULLISH" else "\U0001f534"
    tz = pytz.timezone("Europe/Athens")
    now = datetime.now(tz).strftime("%d/%m %H:%M")
    msg = (
        "\U0001f440 WATCHLIST\n\n"
        + emoji + " " + name + "  |  " + now + "\n"
        + bias_emoji + " Approaching EMA20 " + action + " in the higher-timeframe trend\n"
        "Price: " + str(round(setup["price"], 5)) + "\n\n"
        "Not a signal — worth watching for a confirmed setup."
    )
    try:
        r = requests.post(
            "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage",
            json={"chat_id": SIGNALS_CHANNEL, "text": msg}, timeout=10,
        )
        r.raise_for_status()
        print(f"Watchlist alert sent: {name} {setup['bias']}")
    except Exception as e:
        print(f"send_watchlist_alert error {name}: {e}")


def main():
    print("Watchlist scanner started...")
    state = _load_json(STATE_FILE, {})
    while True:
        try:
            open_trades = _load_json(OPEN_TRADES_FILE, [])
            open_pairs = set(t["name"] for t in open_trades)

            for name, symbol in PAIRS.items():
                try:
                    if name in open_pairs:
                        continue
                    df = get_data(symbol)
                    setup = find_developing_setup(df)
                    was_near = state.get(name, {}).get("near", False)
                    if setup and not was_near:
                        send_watchlist_alert(name, setup)
                        state[name] = {"near": True}
                    elif not setup and was_near:
                        # Moved out of the zone — allow a fresh alert on the next approach
                        state[name] = {"near": False}
                except Exception as e:
                    print(f"Error {name}: {e}")
            _save_json(STATE_FILE, state)
        except Exception as e:
            print(f"Main error: {e}")

        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    main()
