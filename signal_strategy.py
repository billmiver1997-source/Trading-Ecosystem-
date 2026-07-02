import os
from dotenv import load_dotenv
load_dotenv("/root/tradingbot/.env")

import fcntl
import yfinance as yf
import requests
import pandas as pd
import numpy as np
import json
import time
from datetime import datetime
import pytz

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN_SIGNAL")
SIGNALS_CHANNEL = os.getenv("SIGNALS_CHANNEL")
LAST_SIGNAL_FILE = "/root/tradingbot/last_signals_smc.json"

ALL_PAIRS = {
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

CRYPTO_PAIRS = ["BTC/USD", "SOL/USD"]

PAIR_EMOJIS = {
    "USD/CHF": "\U0001f1fa\U0001f1f8", "AUD/USD": "\U0001f1e6\U0001f1fa",
    "EUR/USD": "\U0001f1ea\U0001f1fa", "EUR/CHF": "\U0001f1ea\U0001f1fa",
    "GBP/USD": "\U0001f1ec\U0001f1e7", "USD/CAD": "\U0001f1e8\U0001f1e6",
    "NZD/USD": "\U0001f1f3\U0001f1ff", "XAU/USD": "\U0001fa99",
    "Silver/USD": "\U0001f948", "Copper/USD": "\U0001f7e0",
    "Oil/USD": "\u26fd", "BTC/USD": "\U0001f7e1",
    "SOL/USD": "\U0001f535", "DXY": "\U0001f4b5",
    "USD/JPY": "\U0001f1ef\U0001f1f5",
}


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

def get_trend_15m(symbol):
    try:
        df = yf.Ticker(symbol).history(period="5d", interval="15m")
        if len(df) < 20:
            return None
        close = df["Close"]
        ema20 = close.ewm(span=20).mean().iloc[-1]
        ema50 = close.ewm(span=50).mean().iloc[-1]
        if ema20 > ema50:
            return "BULL"
        if ema20 < ema50:
            return "BEAR"
    except Exception as e:
        print(f"get_trend_15m error {symbol}: {e}")
    return None

def load_last_signals():
    if os.path.exists(LAST_SIGNAL_FILE):
        try:
            with open(LAST_SIGNAL_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"load_last_signals JSON error: {e}")
    return {}

def save_last_signals(data):
    tmp = LAST_SIGNAL_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f)
    os.replace(tmp, LAST_SIGNAL_FILE)

def send_signal(msg):
    try:
        requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendMessage",
            json={"chat_id": SIGNALS_CHANNEL, "text": msg[:4000]})
    except Exception as e:
        print("Send error: "+str(e))

def is_trading_session():
    tz = pytz.timezone("Europe/Athens")
    now = datetime.now(tz)
    hour = now.hour
    weekday = now.weekday()
    if weekday >= 5:
        return False
    return 10 <= hour < 23

def get_data(symbol):
    try:
        df = yf.Ticker(symbol).history(period="30d", interval="1h")
        if len(df) < 50:
            df = yf.Ticker(symbol).history(period="60d", interval="1h")
        return df
    except Exception as e:
        print(f"get_data error {symbol}: {e}")
        return None

def find_poi(df, name):
    if df is None or len(df) < 50:
        return None

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    price = close.iloc[-1]

    # ATR
    tr = pd.concat([high-low, (high-close.shift()).abs(), (low-close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().iloc[-1]
    atr_pct = atr / price
    is_crypto = name in CRYPTO_PAIRS
    min_atr = 0.003 if is_crypto else 0.0003
    if atr_pct < min_atr:
        return None

    # Candle body strength (last closed candle)
    candle_range = high.iloc[-1] - low.iloc[-1]
    candle_body = abs(close.iloc[-1] - df["Open"].iloc[-1])
    body_ratio = candle_body / candle_range if candle_range > 0 else 0
    is_bull_body = close.iloc[-1] > df["Open"].iloc[-1] and body_ratio > 0.5
    is_bear_body = close.iloc[-1] < df["Open"].iloc[-1] and body_ratio > 0.5

    # EMAs
    ema20 = close.ewm(span=20).mean()
    ema50 = close.ewm(span=50).mean()
    ema200 = close.ewm(span=200).mean()

    # RSI
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = -delta.clip(upper=0).rolling(14).mean()
    rsi = (100 - (100 / (1 + gain / loss))).iloc[-1]

    # MACD
    macd = close.ewm(span=12).mean() - close.ewm(span=26).mean()
    signal_line = macd.ewm(span=9).mean()
    hist = macd - signal_line

    curr_ema20 = ema20.iloc[-1]
    curr_ema50 = ema50.iloc[-1]
    curr_ema200 = ema200.iloc[-1]

    # Swing levels
    swing_high = high.iloc[-20:-1].max()
    swing_low = low.iloc[-20:-1].min()
    prev_swing_high = high.iloc[-40:-20].max()
    prev_swing_low = low.iloc[-40:-20].min()

    # BOS
    bos_bull = price > swing_high
    bos_bear = price < swing_low

    # CHoCH
    choch_bull = swing_high > prev_swing_high and swing_low > prev_swing_low
    choch_bear = swing_low < prev_swing_low and swing_high < prev_swing_high

    # Order Block
    ob_bull_zone = None
    ob_bear_zone = None
    for i in range(3, min(15, len(df))):
        if df["Close"].iloc[-i] > df["Open"].iloc[-i] and df["Close"].iloc[-i-1] < df["Open"].iloc[-i-1]:
            ob_bull_zone = (round(df["Low"].iloc[-i-1], 5), round(df["High"].iloc[-i-1], 5))
            break
    for i in range(3, min(15, len(df))):
        if df["Close"].iloc[-i] < df["Open"].iloc[-i] and df["Close"].iloc[-i-1] > df["Open"].iloc[-i-1]:
            ob_bear_zone = (round(df["Low"].iloc[-i-1], 5), round(df["High"].iloc[-i-1], 5))
            break

    # FVG - separate loops so both zones can be found independently
    fvg_bull_zone = None
    fvg_bear_zone = None
    for i in range(2, min(10, len(df))):
        if df["Low"].iloc[-i] > df["High"].iloc[-i-2]:
            fvg_bull_zone = (round(df["High"].iloc[-i-2], 5), round(df["Low"].iloc[-i], 5))
            break
    for i in range(2, min(10, len(df))):
        if df["High"].iloc[-i] < df["Low"].iloc[-i-2]:
            fvg_bear_zone = (round(df["High"].iloc[-i], 5), round(df["Low"].iloc[-i-2], 5))
            break

    # BULL POI
    bull_score = 0
    bull_reasons = []
    if curr_ema20 > curr_ema50 and price > curr_ema200:
        bull_score += 1
        bull_reasons.append("EMA bullish alignment")
    if macd.iloc[-1] > signal_line.iloc[-1] and hist.iloc[-1] > hist.iloc[-2]:
        bull_score += 1
        bull_reasons.append("MACD bullish momentum")
    if bos_bull or choch_bull:
        bull_score += 1
        bull_reasons.append("BOS/CHoCH bullish structure")
    if ob_bull_zone and ob_bull_zone[0] <= price <= ob_bull_zone[1] * 1.001:
        bull_score += 1
        bull_reasons.append("Price at Order Block")
    if fvg_bull_zone and fvg_bull_zone[0] <= price <= fvg_bull_zone[1]:
        bull_score += 1
        bull_reasons.append("Price in FVG zone")
    if 50 < rsi < 70:
        bull_score += 1
        bull_reasons.append("RSI in bullish zone")
    if is_bull_body:
        bull_score += 1
        bull_reasons.append("Strong bullish candle")

    # BEAR POI
    bear_score = 0
    bear_reasons = []
    if curr_ema20 < curr_ema50 and price < curr_ema200:
        bear_score += 1
        bear_reasons.append("EMA bearish alignment")
    if macd.iloc[-1] < signal_line.iloc[-1] and hist.iloc[-1] < hist.iloc[-2]:
        bear_score += 1
        bear_reasons.append("MACD bearish momentum")
    if bos_bear or choch_bear:
        bear_score += 1
        bear_reasons.append("BOS/CHoCH bearish structure")
    if ob_bear_zone and ob_bear_zone[0] * 0.999 <= price <= ob_bear_zone[1]:
        bear_score += 1
        bear_reasons.append("Price at Order Block")
    if fvg_bear_zone and fvg_bear_zone[0] <= price <= fvg_bear_zone[1]:
        bear_score += 1
        bear_reasons.append("Price in FVG zone")
    if 30 < rsi < 50:
        bear_score += 1
        bear_reasons.append("RSI in bearish zone")
    if is_bear_body:
        bear_score += 1
        bear_reasons.append("Strong bearish candle")

    if bull_score >= 5:
        sl = round(price - (atr * 1.5), 5)
        tp = round(price + (atr * 3), 5)
        zone_low = round(price - atr * 0.3, 5)
        zone_high = round(price + atr * 0.3, 5)
        return {
            "bias": "BULLISH",
            "price": price,
            "zone_low": zone_low,
            "zone_high": zone_high,
            "sl": sl,
            "tp": tp,
            "rsi": rsi,
            "atr": atr,
            "score": bull_score,
            "reasons": bull_reasons[:3]
        }

    if bear_score >= 5:
        sl = round(price + (atr * 1.5), 5)
        tp = round(price - (atr * 3), 5)
        zone_low = round(price - atr * 0.3, 5)
        zone_high = round(price + atr * 0.3, 5)
        return {
            "bias": "BEARISH",
            "price": price,
            "zone_low": zone_low,
            "zone_high": zone_high,
            "sl": sl,
            "tp": tp,
            "rsi": rsi,
            "atr": atr,
            "score": bear_score,
            "reasons": bear_reasons[:3]
        }

    return None

def format_poi(name, poi):
    emoji = PAIR_EMOJIS.get(name, "")
    bias_emoji = "\U0001f7e2" if poi["bias"] == "BULLISH" else "\U0001f534"
    watch_emoji = "\U0001f4c8" if poi["bias"] == "BULLISH" else "\U0001f4c9"
    tz = pytz.timezone("Europe/Athens")
    now = datetime.now(tz).strftime("%d/%m/%Y %H:%M")
    reasons = " | ".join(poi["reasons"])
    rr = "1:2"
    return (
        "\U0001f3af POINT OF INTEREST\n\n"
        +emoji+" "+name+" | "+now+"\n\n"
        "\U0001f4cd Zone: "+str(poi["zone_low"])+" - "+str(poi["zone_high"])+"\n"
        "\U0001f4ca Bias: "+poi["bias"]+" "+bias_emoji+"\n\n"
        "\u26a1 Why: "+reasons+"\n\n"
        +watch_emoji+" Watch for "+("BUY" if poi["bias"] == "BULLISH" else "SELL")+" reaction from this zone\n"
        "SL: "+str(poi["sl"])+"\n"
        "TP: "+str(poi["tp"])+"\n"
        "R:R = "+rr+"\n\n"
        "Score: "+str(poi["score"])+"/7 | ATR: "+str(round(poi["atr"],5))+"\n"
        "Strategy: SMC + EMA + MACD | 1H\n\n"
        "⚠️ For educational purposes only. Not financial advice. Trading involves significant risk of loss."
    )

def add_trade(name, poi):
    trades_file = "/root/tradingbot/open_trades.json"
    lock_path = trades_file + '.lock'
    signal = "BUY" if poi["bias"] == "BULLISH" else "SELL"
    new_trade = {"name": name, "signal": signal, "entry": poi["price"], "sl": poi["sl"], "tp": poi["tp"], "atr": poi["atr"], "time": time.time()}
    # Exclusive lock prevents race with performance_tracker.py
    with open(lock_path, 'w') as _lf:
        fcntl.flock(_lf, fcntl.LOCK_EX)
        try:
            trades = []
            if os.path.exists(trades_file):
                try:
                    with open(trades_file) as f:
                        trades = json.load(f)
                except (json.JSONDecodeError, ValueError) as e:
                    print(f"add_trade JSON error: {e}")
            trades.append(new_trade)
            tmp = trades_file + '.tmp'
            with open(tmp, 'w') as f:
                json.dump(trades, f)
            os.replace(tmp, trades_file)
        finally:
            fcntl.flock(_lf, fcntl.LOCK_UN)

PAIR_CURRENCIES = {
    "XAU/USD": ["USD"], "Silver/USD": ["USD"], "Oil/USD": ["USD"],
    "BTC/USD": ["USD"], "SOL/USD": ["USD"],
    "EUR/USD": ["EUR", "USD"], "GBP/USD": ["GBP", "USD"],
    "USD/CHF": ["USD", "CHF"], "AUD/USD": ["AUD", "USD"],
    "USD/CAD": ["USD", "CAD"], "NZD/USD": ["NZD", "USD"],
    "USD/JPY": ["USD", "JPY"],
}

def get_news_blocked_currencies():
    """Returns set of currency codes with high-impact events within ±30 minutes."""
    try:
        from bs4 import BeautifulSoup
        tz = pytz.timezone("Europe/Athens")
        now = datetime.now(tz)
        today = now.strftime("%Y-%m-%d")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://www.investing.com/economic-calendar/"
        }
        payload = {"dateFrom": today, "dateTo": today, "importance[]": ["3"]}
        r = requests.post(
            "https://www.investing.com/economic-calendar/Service/getCalendarFilteredData",
            headers=headers, data=payload, timeout=10
        )
        soup = BeautifulSoup(r.json().get("data", ""), "html.parser")
        blocked = set()
        for row in soup.find_all("tr", id=lambda x: x and x.startswith("eventRowId_")):
            try:
                time_td = row.find("td", class_="first")
                currency_td = row.find("td", class_="flagCur")
                if not time_td or not currency_td:
                    continue
                event_time_str = time_td.text.strip()
                currency = currency_td.text.strip()
                event_dt = tz.localize(datetime.strptime(today + " " + event_time_str, "%Y-%m-%d %H:%M"))
                delta_min = (event_dt - now).total_seconds() / 60
                if -15 <= delta_min <= 30:
                    blocked.add(currency)
            except Exception:
                continue
        if blocked:
            print(f"News filter blocking currencies: {blocked}")
        return blocked
    except Exception as e:
        print(f"News filter error: {e}")
        return set()

def get_min_score(name):
    """Returns required score threshold based on recent win rate for this pair."""
    journal_file = "/root/tradingbot/journal.json"
    journal_lock = journal_file + ".lock"
    try:
        if not os.path.exists(journal_file):
            return 5
        # Shared read lock prevents reading a torn file during a concurrent write
        with open(journal_lock, "w") as _lf:
            fcntl.flock(_lf, fcntl.LOCK_SH)
            try:
                with open(journal_file) as f:
                    entries = json.load(f)
            finally:
                fcntl.flock(_lf, fcntl.LOCK_UN)
        pair_entries = [e for e in entries if e.get("pair") == name][-20:]
        if len(pair_entries) < 10:
            return 5
        wins = sum(1 for e in pair_entries if e.get("result") == "WIN")
        win_rate = wins / len(pair_entries)
        if win_rate < 0.40:
            print(f"Low win rate {round(win_rate*100)}% for {name} — raising threshold to 6")
            return 6
        return 5
    except Exception as e:
        print(f"Score threshold error: {e}")
        return 5

def main():
    print("POI Strategy started (1H timeframe)...")
    last_signals = load_last_signals()
    news_cache = {"time": 0, "blocked": set()}

    while True:
        try:
            if not is_trading_session():
                print("Outside trading session - sleeping...")
                time.sleep(1800)
                continue

            now_time = time.time()
            best_poi = None
            best_score = 0
            best_name = ""

            # Refresh news filter once per hour
            if now_time - news_cache["time"] > 3600:
                news_cache["blocked"] = get_news_blocked_currencies()
                news_cache["time"] = now_time

            # Load open trades to prevent conflicts
            open_trades_file = "/root/tradingbot/open_trades.json"
            open_trades = []
            if os.path.exists(open_trades_file):
                try:
                    with open(open_trades_file) as f:
                        open_trades = json.load(f)
                except (json.JSONDecodeError, ValueError) as e:
                    print(f"load open_trades JSON error: {e}")
            open_pairs = set(t["name"] for t in open_trades)

            for name, symbol in ALL_PAIRS.items():
                try:
                    if name in open_pairs:
                        continue

                    # News filter: skip if any currency in this pair has upcoming high-impact event
                    pair_ccys = PAIR_CURRENCIES.get(name, [])
                    if news_cache["blocked"] & set(pair_ccys):
                        print(f"Skipping {name} — news filter active")
                        continue

                    last_sig = last_signals.get(name, {})
                    last_sig_time = last_sig.get("time", 0)
                    if (now_time - last_sig_time) < 21600:
                        continue
                    last_dir = last_sig.get("signal", "")

                    trend_4h = get_trend_4h(symbol)
                    df = get_data(symbol)
                    poi = find_poi(df, name)

                    if poi:
                        signal = "BUY" if poi["bias"] == "BULLISH" else "SELL"
                        if last_dir and signal == last_dir:
                            continue
                        if trend_4h and signal == "BUY" and trend_4h != "BULL":
                            continue
                        if trend_4h and signal == "SELL" and trend_4h != "BEAR":
                            continue
                        trend_15m = get_trend_15m(symbol)
                        if trend_15m and signal == "BUY" and trend_15m == "BEAR":
                            continue
                        if trend_15m and signal == "SELL" and trend_15m == "BULL":
                            continue

                        # Performance-adjusted score threshold
                        min_score = get_min_score(name)
                        if poi["score"] < min_score:
                            continue

                        if poi["score"] > best_score:
                            best_score = poi["score"]
                            best_poi = poi
                            best_name = name
                except Exception as e:
                    print(f"Error {name}: {e}")

            if best_poi:
                msg = format_poi(best_name, best_poi)
                send_signal(msg)
                signal = "BUY" if best_poi["bias"] == "BULLISH" else "SELL"
                last_signals[best_name] = {"time": now_time, "signal": signal}
                save_last_signals(last_signals)
                add_trade(best_name, best_poi)
                print(f"POI sent: {best_name} {best_poi['bias']} score:{best_score}")
            else:
                print("Scan complete - no POI found")

        except Exception as e:
            print(f"Main error: {e}")

        time.sleep(3600)

if __name__ == "__main__":
    main()
