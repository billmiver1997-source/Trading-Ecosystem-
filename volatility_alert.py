"""Proactive volatility spike alert — posts to SIGNALS_CHANNEL the moment a pair's
current ATR crosses meaningfully above its own 5-day average (same >150% threshold
and True-Range ATR calc as listener.py's on-demand "Volatility Alert" button), instead
of waiting for a user to ask for the on-demand report.
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
from concurrent.futures import ThreadPoolExecutor

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN_SIGNAL")
SIGNALS_CHANNEL = os.getenv("SIGNALS_CHANNEL")
if not TELEGRAM_TOKEN or not SIGNALS_CHANNEL:
    raise RuntimeError("TELEGRAM_TOKEN_SIGNAL and SIGNALS_CHANNEL must be set in .env")

STATE_FILE = "/root/tradingbot/volatility_state.json"
HIGH_THRESHOLD = 150  # % of 5-day average ATR
SCAN_INTERVAL = 900   # 15 minutes

PAIRS = {
    "EUR/USD": "EURUSD=X", "GBP/USD": "GBPUSD=X", "XAU/USD": "GC=F",
    "BTC/USD": "BTC-USD", "Oil/USD": "CL=F", "USD/JPY": "USDJPY=X",
    "USD/CHF": "USDCHF=X", "SOL/USD": "SOL-USD", "AUD/USD": "AUDUSD=X",
}

PAIR_EMOJIS = {
    "EUR/USD": "\U0001f1ea\U0001f1fa", "GBP/USD": "\U0001f1ec\U0001f1e7",
    "XAU/USD": "\U0001fa99", "BTC/USD": "\U0001f7e1", "Oil/USD": "⛽",
    "USD/JPY": "\U0001f1ef\U0001f1f5", "USD/CHF": "\U0001f1fa\U0001f1f8",
    "SOL/USD": "\U0001f535", "AUD/USD": "\U0001f1e6\U0001f1fa",
}


def _load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError, OSError) as e:
            print(f"load state error: {e}")
    return {}


def _save_state(state):
    tmp = STATE_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(state, f)
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        print(f"save state error: {e}")


def fetch_volatility(args):
    name, symbol = args
    try:
        df = yf.Ticker(symbol).history(period="5d", interval="1h")
        if len(df) < 20:
            return name, None
        prev_close = df["Close"].shift(1)
        tr = pd.concat(
            [df["High"] - df["Low"], (df["High"] - prev_close).abs(), (df["Low"] - prev_close).abs()],
            axis=1,
        ).max(axis=1)
        atr_series = tr.rolling(14).mean()
        atr = atr_series.iloc[-1]
        # Exclude the current bar from the baseline so a spike doesn't inflate its own average
        avg_atr = atr_series.iloc[:-1].mean()
        if pd.isna(atr) or pd.isna(avg_atr) or avg_atr == 0:
            return name, None
        pct = round((atr / avg_atr) * 100)
        price = df["Close"].iloc[-1]
        return name, {"atr": round(float(atr), 5), "pct": int(pct), "price": float(price)}
    except Exception as e:
        print(f"Volatility fetch error {name}: {e}")
        return name, None


def send_alert(name, data):
    emoji = PAIR_EMOJIS.get(name, "")
    tz = pytz.timezone("Europe/Athens")
    now = datetime.now(tz).strftime("%d/%m %H:%M")
    msg = (
        "\U0001f4a5 VOLATILITY SPIKE\n\n"
        + emoji + " " + name + "  |  " + now + "\n"
        "ATR: " + str(data["atr"]) + " (" + str(data["pct"]) + "% of 5-day avg)\n"
        "Price: " + str(round(data["price"], 5)) + "\n\n"
        "Unusual price movement detected — expect wider spreads and faster moves."
    )
    try:
        r = requests.post(
            "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage",
            json={"chat_id": SIGNALS_CHANNEL, "text": msg}, timeout=10,
        )
        r.raise_for_status()
        print(f"Volatility alert sent: {name} ({data['pct']}%)")
        return True
    except Exception as e:
        print(f"send_alert error {name}: {e}")
        return False


def main():
    print("Volatility alert service started...")
    state = _load_state()
    while True:
        try:
            with ThreadPoolExecutor(max_workers=8) as ex:
                results = dict(ex.map(fetch_volatility, PAIRS.items()))

            state_changed = False
            for name, data in results.items():
                if not data:
                    continue
                was_alerting = state.get(name, {}).get("alerting", False)
                is_high = data["pct"] > HIGH_THRESHOLD
                if is_high and not was_alerting:
                    if send_alert(name, data):
                        state[name] = {"alerting": True}
                        state_changed = True
                elif not is_high and was_alerting:
                    # Dropped back under threshold — allow a fresh alert if it spikes again
                    state[name] = {"alerting": False}
                    state_changed = True
            if state_changed:
                _save_state(state)
        except Exception as e:
            print(f"Main error: {e}")

        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    main()
