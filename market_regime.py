"""Daily market regime classifier — trending / ranging / squeeze per pair, using
Wilder's ADX (trend strength) and Bollinger Band width percentile (volatility
compression). Posted to the news channel: context for which style of setup
(breakout vs mean-reversion vs pullback-continuation) suits current conditions.
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
CHANNEL_ID = os.getenv("TELEGRAM_NEWS_CHANNEL")
if not TELEGRAM_TOKEN or not CHANNEL_ID:
    raise RuntimeError("TELEGRAM_TOKEN_SIGNAL and TELEGRAM_NEWS_CHANNEL must be set in .env")

SENT_STATE_FILE = "/root/tradingbot/sent_state_regime.json"

def _load_sent_day():
    """Persisted (not just in-memory) so a restart inside the send window — e.g.
    monitor.sh catching a crash — can't cause a duplicate send."""
    if os.path.exists(SENT_STATE_FILE):
        try:
            with open(SENT_STATE_FILE) as f:
                return json.load(f).get("day", "")
        except (json.JSONDecodeError, ValueError, OSError) as e:
            print(f"load sent state error: {e}")
    return ""

def _save_sent_day(day):
    tmp = SENT_STATE_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump({"day": day}, f)
        os.replace(tmp, SENT_STATE_FILE)
    except Exception as e:
        print(f"save sent state error: {e}")

SEND_HOUR = 9  # Athens time, distinct from correlation_bot's 09:00 slot — see main()

PAIRS = {
    "EUR/USD": "EURUSD=X", "GBP/USD": "GBPUSD=X", "USD/JPY": "USDJPY=X",
    "XAU/USD": "GC=F", "Oil/USD": "CL=F", "BTC/USD": "BTC-USD",
}

ADX_TREND = 25
ADX_WEAK = 20
SQUEEZE_PERCENTILE = 0.20


def _wilder_smooth(series, period):
    """Wilder's smoothing == an EWM with alpha=1/period, not the more common
    span-based EWM — using span here would understate ADX by smoothing too
    fast relative to the standard definition traders actually reference."""
    return series.ewm(alpha=1 / period, adjust=False).mean()


def compute_adx(df, period=14):
    high, low, close = df["High"], df["Low"], df["Close"]
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = ((up_move > down_move) & (up_move > 0)) * up_move
    minus_dm = ((down_move > up_move) & (down_move > 0)) * down_move

    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr = _wilder_smooth(tr, period)

    plus_di = 100 * _wilder_smooth(plus_dm, period) / atr
    minus_di = 100 * _wilder_smooth(minus_dm, period) / atr
    denom = (plus_di + minus_di).replace(0, float('nan'))
    dx = (100 * (plus_di - minus_di).abs() / denom).fillna(0)  # 0 DI sum = no trend, ADX=0
    adx = _wilder_smooth(dx, period)
    return adx, plus_di, minus_di


def classify_regime(df):
    if df is None or len(df) < 60:
        return None
    close = df["Close"]
    adx, plus_di, minus_di = compute_adx(df)
    if pd.isna(adx.iloc[-1]):
        return None

    bb_mean = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    bb_width = (4 * bb_std) / bb_mean  # (upper-lower)/mean
    width_now = bb_width.iloc[-1]
    if pd.isna(width_now):
        return None
    width_percentile = (bb_width.iloc[-100:] < width_now).mean() if len(bb_width) >= 100 else 0.5

    adx_now = adx.iloc[-1]
    bullish = plus_di.iloc[-1] > minus_di.iloc[-1]

    if adx_now >= ADX_TREND:
        regime = "TRENDING_UP" if bullish else "TRENDING_DOWN"
    elif adx_now < ADX_WEAK and width_percentile <= SQUEEZE_PERCENTILE:
        regime = "SQUEEZE"
    elif adx_now < ADX_WEAK:
        regime = "RANGING"
    else:
        regime = "TRANSITIONING"

    return {"regime": regime, "adx": round(float(adx_now), 1), "width_pct": round(float(width_percentile) * 100)}


REGIME_LABEL = {
    "TRENDING_UP": ("\U0001f7e2 TRENDING UP", "pullback-continuation setups"),
    "TRENDING_DOWN": ("\U0001f534 TRENDING DOWN", "pullback-continuation setups"),
    "SQUEEZE": ("\U0001f7e1 SQUEEZE", "breakout watch — volatility compressed"),
    "RANGING": ("\U000026aa RANGING", "mean-reversion / range trades"),
    "TRANSITIONING": ("\U0001f7e0 TRANSITIONING", "no clear edge — wait for confirmation"),
}


def build_report():
    lines = ["\U0001f9ed MARKET REGIME\n"]
    tz = pytz.timezone("Europe/Athens")
    lines[0] += datetime.now(tz).strftime("%d/%m/%Y")
    any_data = False
    for name, symbol in PAIRS.items():
        try:
            df = yf.Ticker(symbol).history(period="6mo", interval="1d")
        except Exception as e:
            print(f"market_regime fetch error {name}: {e}")
            continue
        result = classify_regime(df)
        if not result:
            continue
        any_data = True
        label, note = REGIME_LABEL[result["regime"]]
        lines.append(f"\n{label}  {name}")
        lines.append(f"ADX {result['adx']} | BB width percentile {result['width_pct']}% | {note}")
    if not any_data:
        return None
    lines.append("\n⚠️ Context only — not a signal. ADX>25 = trending, <20 = ranging; a tight Bollinger squeeze often precedes a breakout in either direction.")
    return "\n".join(lines)


def send_channel(msg):
    try:
        r = requests.post(
            "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage",
            json={"chat_id": CHANNEL_ID, "text": msg[:4096]}, timeout=10,
        )
        r.raise_for_status()
        print("Market regime report sent!")
        return True
    except Exception as e:
        print(f"send_channel error: {e}")
        return False


def main():
    print("Market regime bot started...")
    sent_today = _load_sent_day()
    while True:
        try:
            tz = pytz.timezone("Europe/Athens")
            now = datetime.now(tz)
            today = now.strftime("%Y-%m-%d")
            if now.hour == SEND_HOUR and now.minute >= 30 and now.minute < 40 and sent_today != today:
                print("Building market regime report...")
                report = build_report()
                if report and send_channel(report):
                    # Only mark sent (in memory + on disk) on confirmed delivery, so a
                    # missing report or a failed send is retried on the next 5-min tick
                    # instead of being silently skipped for the rest of the day.
                    sent_today = today
                    _save_sent_day(today)
        except Exception as e:
            print(f"Main error: {e}")
        time.sleep(300)


if __name__ == "__main__":
    main()
