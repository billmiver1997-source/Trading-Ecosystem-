import os
from dotenv import load_dotenv
load_dotenv("/root/tradingbot/.env")

import fcntl
import yfinance as yf
import requests
import pandas as pd
import json
import time
from datetime import datetime
import pytz

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN_SIGNAL")
SIGNALS_CHANNEL = os.getenv("SIGNALS_CHANNEL")
if not TELEGRAM_TOKEN or not SIGNALS_CHANNEL:
    raise RuntimeError("TELEGRAM_TOKEN_SIGNAL and SIGNALS_CHANNEL must be set in .env")
LAST_SIGNAL_FILE = "/root/tradingbot/last_signals_smc.json"
IMAGES_DIR = "/root/tradingbot/images"
CURSORS_FILE = "/root/tradingbot/cursors_signals.json"
_photo_ids = {}


ALL_PAIRS = {
    "XAU/USD": "GC=F",
    "Silver/USD": "SI=F",
    "Oil/USD": "CL=F",
    "SOL/USD": "SOL-USD",
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "USD/CHF": "USDCHF=X",
    "AUD/USD": "AUDUSD=X",
    "USD/CAD": "USDCAD=X",
    "NZD/USD": "NZDUSD=X",
    "USD/JPY": "USDJPY=X",
}

CRYPTO_PAIRS = ["SOL/USD"]
ASIAN_PAIRS = {"XAU/USD", "USD/JPY", "AUD/USD", "NZD/USD"}
SIGNAL_IMAGES = ["signals.jpg", "signals_2.jpg", "signals_3.jpg", "signals_4.jpg", "signals_5.jpg"]
_img_cursors = {}

def _load_cursors():
    global _img_cursors
    try:
        if os.path.exists(CURSORS_FILE):
            with open(CURSORS_FILE) as f:
                _img_cursors = json.load(f)
    except Exception as e:
        print(f"load cursors error: {e}")

def _save_cursors():
    try:
        tmp = CURSORS_FILE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(_img_cursors, f)
        os.replace(tmp, CURSORS_FILE)
    except Exception as e:
        print(f"save cursors error: {e}")

def _next_photo(category, pool):
    idx = _img_cursors.get(category, 0)
    _img_cursors[category] = (idx + 1) % len(pool)
    _save_cursors()
    return pool[idx]

def get_session_label():
    tz = pytz.timezone("Europe/Athens")
    hour = datetime.now(tz).hour
    if 3 <= hour < 10:
        return "\U0001f30f Asian"
    elif 10 <= hour < 13:
        return "\U0001f1ec\U0001f1e7 London"
    elif 13 <= hour < 16:
        return "\U0001f525 London/NY"
    elif 16 <= hour < 23:
        return "\U0001f5fd New York"
    else:
        return "\U0001f319 Off-hours"

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


def get_weekly_trend(symbol):
    """Price vs EMA20 on weekly chart — highest timeframe filter."""
    try:
        df = yf.Ticker(symbol).history(period="52wk", interval="1wk")
        if len(df) < 10:
            return None
        close = df["Close"]
        ema20 = close.ewm(span=20).mean().iloc[-1]
        price = close.iloc[-1]
        return "BULL" if price > ema20 else "BEAR"
    except Exception as e:
        print(f"get_weekly_trend error {symbol}: {e}")
    return None

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
        if len(df) < 50:  # EMA50 needs at least 50 candles to be meaningful
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
    try:
        with open(tmp, 'w') as f:
            json.dump(data, f)
        os.replace(tmp, LAST_SIGNAL_FILE)
    except Exception as e:
        print(f"save_last_signals error: {e}")

def send_signal(msg):
    """Send signal photo to channel. Round-robin through 5 signal images. Returns message_id."""
    photo_name = _next_photo("signal", SIGNAL_IMAGES)
    path = os.path.join(IMAGES_DIR, photo_name)
    cap = msg[:1024]
    message_id = None
    try:
        fid = _photo_ids.get(photo_name)
        if fid:
            r = requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendPhoto",
                json={"chat_id": SIGNALS_CHANNEL, "photo": fid, "caption": cap}, timeout=15)
            if not r.ok:
                _photo_ids.pop(photo_name, None)
                fid = None
        if not fid and os.path.exists(path):
            with open(path, "rb") as pf:
                r = requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendPhoto",
                    files={"photo": ("image.jpg", pf, "image/jpeg")},
                    data={"chat_id": SIGNALS_CHANNEL, "caption": cap}, timeout=15)
            photos = r.json().get("result", {}).get("photo", [])
            if photos:
                _photo_ids[photo_name] = photos[-1]["file_id"]
        elif not fid:
            r = requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendMessage",
                json={"chat_id": SIGNALS_CHANNEL, "text": msg[:4000]}, timeout=10)
        r.raise_for_status()
        message_id = r.json().get("result", {}).get("message_id")
    except Exception as e:
        print("Send error: "+str(e))
    return message_id

def is_trading_session():
    tz = pytz.timezone("Europe/Athens")
    now = datetime.now(tz)
    weekday = now.weekday()
    if weekday >= 5:
        return False
    return 10 <= now.hour < 23

def is_asian_session():
    """Asian session 03:00-09:59 Athens — Gold, JPY, AUD, NZD active."""
    tz = pytz.timezone("Europe/Athens")
    now = datetime.now(tz)
    if now.weekday() >= 5:
        return False
    return 3 <= now.hour < 10

def get_data(symbol):
    try:
        df = yf.Ticker(symbol).history(period="30d", interval="1h")
        if len(df) < 50:
            df = yf.Ticker(symbol).history(period="60d", interval="1h")
        if len(df) < 50:
            return None
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
    if pd.isna(atr) or atr == 0:
        return None
    atr_pct = atr / price
    is_crypto = name in CRYPTO_PAIRS
    min_atr = 0.003 if is_crypto else 0.0003
    if atr_pct < min_atr:
        return None

    # Candle body strength (last CLOSED candle — iloc[-1] is still forming)
    candle_range = high.iloc[-2] - low.iloc[-2]
    candle_body = abs(close.iloc[-2] - df["Open"].iloc[-2])
    body_ratio = candle_body / candle_range if candle_range > 0 else 0
    is_bull_body = close.iloc[-2] > df["Open"].iloc[-2] and body_ratio > 0.5
    is_bear_body = close.iloc[-2] < df["Open"].iloc[-2] and body_ratio > 0.5

    # EMAs
    ema20 = close.ewm(span=20).mean()
    ema50 = close.ewm(span=50).mean()
    ema200 = close.ewm(span=200).mean()

    # RSI
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = -delta.clip(upper=0).rolling(14).mean()
    loss = loss.replace(0, 1e-10)  # prevent NaN RSI on all-flat windows
    rsi = (100 - (100 / (1 + gain / loss))).iloc[-1]

    # MACD
    macd = close.ewm(span=12).mean() - close.ewm(span=26).mean()
    signal_line = macd.ewm(span=9).mean()
    hist = macd - signal_line

    curr_ema20 = ema20.iloc[-1]
    curr_ema50 = ema50.iloc[-1]
    curr_ema200 = ema200.iloc[-1]

    # Bollinger Bands (20-period, 2 std dev)
    bb_period = min(20, len(close))
    bb_mean = close.iloc[-bb_period:].mean()
    bb_std_val = close.iloc[-bb_period:].std()
    bb_upper = bb_mean + 2 * bb_std_val
    bb_lower = bb_mean - 2 * bb_std_val

    # Swing levels — use 20 closed candles (iloc[-21:-1] = positions -21 through -2 = 20 elements)
    swing_high = high.iloc[-21:-1].max()
    swing_low = low.iloc[-21:-1].min()
    prev_swing_high = high.iloc[-41:-21].max()
    prev_swing_low = low.iloc[-41:-21].min()

    # Fibonacci golden pocket (50–61.8% retracement of 20-bar range)
    fib_range = swing_high - swing_low
    fib_tol = atr * 0.75
    fib_bull_zone = False
    fib_bear_zone = False
    if fib_range > 0:
        # Bull: price pulled back 50–61.8% from the recent swing high
        fib_bull_50 = swing_high - fib_range * 0.50
        fib_bull_618 = swing_high - fib_range * 0.618
        fib_bull_zone = (fib_bull_618 - fib_tol) <= price <= (fib_bull_50 + fib_tol)
        # Bear: price bounced 50–61.8% from the recent swing low
        fib_bear_50 = swing_low + fib_range * 0.50
        fib_bear_618 = swing_low + fib_range * 0.618
        fib_bear_zone = (fib_bear_50 - fib_tol) <= price <= (fib_bear_618 + fib_tol)

    # BOS
    bos_bull = price > swing_high
    bos_bear = price < swing_low

    # CHoCH
    choch_bull = swing_high > prev_swing_high and swing_low > prev_swing_low
    choch_bear = swing_low < prev_swing_low and swing_high < prev_swing_high

    # Order Block — start at i=2 so the most recent closed candle (iloc[-2]) is considered
    ob_bull_zone = None
    ob_bear_zone = None
    for i in range(2, min(15, len(df))):
        if df["Close"].iloc[-i] > df["Open"].iloc[-i] and df["Close"].iloc[-i-1] < df["Open"].iloc[-i-1]:
            ob_bull_zone = (round(df["Low"].iloc[-i-1], 5), round(df["High"].iloc[-i-1], 5))
            break
    for i in range(2, min(15, len(df))):
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

    # BULL POI scoring — 9 criteria
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
    if price <= bb_lower * 1.015:
        bull_score += 1
        bull_reasons.append("Bollinger Band support")
    if fib_bull_zone:
        bull_score += 1
        bull_reasons.append("Fibonacci golden pocket")

    # BEAR POI scoring — 9 criteria
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
    if price >= bb_upper * 0.985:
        bear_score += 1
        bear_reasons.append("Bollinger Band resistance")
    if fib_bear_zone:
        bear_score += 1
        bear_reasons.append("Fibonacci golden pocket")

    # Live market context for the signal message
    change_24h = round((price - close.iloc[-25]) / close.iloc[-25] * 100, 2) if len(close) > 25 else None
    day_high = round(high.iloc[-24:].max(), 5)
    day_low = round(low.iloc[-24:].min(), 5)

    # Threshold: 6/9 minimum. Return the stronger side only; skip on a tie.
    if bull_score >= 6 and bull_score > bear_score:
        sl = round(price - atr * 1.5, 5)
        if ob_bull_zone and ob_bull_zone[0] > price - atr * 2 and ob_bull_zone[0] < price:
            sl = round(ob_bull_zone[0] - atr * 0.3, 5)
        elif fvg_bull_zone and fvg_bull_zone[0] > price - atr * 2 and fvg_bull_zone[0] < price:
            sl = round(fvg_bull_zone[0] - atr * 0.3, 5)
        tp = round(price + abs(price - sl) * 2, 5)
        zone_low = round(price - atr * 0.3, 5)
        zone_high = round(price + atr * 0.3, 5)
        return {
            "bias": "BULLISH",
            "price": price,
            "zone_low": zone_low,
            "zone_high": zone_high,
            "sl": sl,
            "tp": tp,
            "rsi": round(rsi, 1),
            "atr": atr,
            "score": bull_score,
            "reasons": bull_reasons[:3],
            "change_24h": change_24h,
            "day_high": day_high,
            "day_low": day_low,
        }

    if bear_score >= 6 and bear_score > bull_score:
        sl = round(price + atr * 1.5, 5)
        if ob_bear_zone and ob_bear_zone[1] < price + atr * 2 and ob_bear_zone[1] > price:
            sl = round(ob_bear_zone[1] + atr * 0.3, 5)
        elif fvg_bear_zone and fvg_bear_zone[1] < price + atr * 2 and fvg_bear_zone[1] > price:
            sl = round(fvg_bear_zone[1] + atr * 0.3, 5)
        tp = round(price - abs(sl - price) * 2, 5)
        zone_low = round(price - atr * 0.3, 5)
        zone_high = round(price + atr * 0.3, 5)
        return {
            "bias": "BEARISH",
            "price": price,
            "zone_low": zone_low,
            "zone_high": zone_high,
            "sl": sl,
            "tp": tp,
            "rsi": round(rsi, 1),
            "atr": atr,
            "score": bear_score,
            "reasons": bear_reasons[:3],
            "change_24h": change_24h,
            "day_high": day_high,
            "day_low": day_low,
        }

    return None

def format_poi(name, poi):
    emoji = PAIR_EMOJIS.get(name, "")
    bias_emoji = "\U0001f7e2" if poi["bias"] == "BULLISH" else "\U0001f534"
    watch_emoji = "\U0001f4c8" if poi["bias"] == "BULLISH" else "\U0001f4c9"
    tz = pytz.timezone("Europe/Athens")
    now = datetime.now(tz).strftime("%d/%m %H:%M")
    score = poi["score"]
    if score >= 7:
        quality = "\u2b50\u2b50\u2b50 PREMIUM"
    elif score >= 5:
        quality = "\u2b50\u2b50 STRONG"
    else:
        quality = "\u2b50 VALID"
    action = "BUY" if poi["bias"] == "BULLISH" else "SELL"
    sl_dist = abs(poi["sl"] - poi["price"])
    rr_dist = abs(poi["tp"] - poi["price"])
    rr_ratio = round(rr_dist / sl_dist, 1) if sl_dist > 0 else 2.0
    session = get_session_label()
    reasons = " \u2022 ".join(poi["reasons"])
    change = poi.get("change_24h")
    change_str = ("+" if change and change > 0 else "") + str(change) + "%" if change is not None else "N/A"
    day_high = poi.get("day_high", "")
    day_low = poi.get("day_low", "")
    rsi = poi.get("rsi", "")
    return (
        "\U0001f3af TRADING SETUP \u2014 " + name + "\n\n"
        + emoji + "  " + now + "  |  " + session + "\n"
        "RSI: " + str(rsi) + "  |  24h: " + change_str + "\n"
        "\U0001f4ca Range: " + str(day_low) + " \u2013 " + str(day_high) + "\n\n"
        "\U0001f4cd Zone: " + str(poi["zone_low"]) + " \u2013 " + str(poi["zone_high"]) + "\n"
        + bias_emoji + " " + poi["bias"] + "  |  " + quality + " (" + str(score) + "/9)\n\n"
        "\u26a1 " + reasons + "\n\n"
        + watch_emoji + " " + action + " on return to zone\n"
        "\U0001f6d1 SL: " + str(poi["sl"]) + "   \u2705 TP: " + str(poi["tp"]) + "\n"
        "\U0001f4d0 R:R = 1:" + str(rr_ratio) + "\n\n"
        "SMC + Fibonacci + BB | 1H\n"
        "\u26a0\ufe0f Educational only. Not financial advice."
    )

def add_trade(name, poi, signal_message_id=None):
    trades_file = "/root/tradingbot/open_trades.json"
    lock_path = trades_file + '.lock'
    signal = "BUY" if poi["bias"] == "BULLISH" else "SELL"
    new_trade = {"name": name, "signal": signal, "entry": poi["price"], "sl": poi["sl"], "tp": poi["tp"], "atr": poi["atr"], "time": time.time(), "signal_message_id": signal_message_id}
    # Exclusive lock prevents race with performance_tracker.py
    with open(lock_path, 'a') as _lf:
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
    """Returns set of currency codes with high-impact events within -15/+30 minutes."""
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
        r.raise_for_status()
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
                if not event_time_str or "Day" in event_time_str or ":" not in event_time_str:
                    continue
                event_dt = tz.localize(datetime.strptime(today + " " + event_time_str, "%Y-%m-%d %H:%M"))
                delta_min = (event_dt - now).total_seconds() / 60
                if -15 <= delta_min <= 30:
                    blocked.add(currency)
            except Exception as e:
                print(f"News calendar row parse error: {e}")
                continue
        if blocked:
            print(f"News filter blocking currencies: {blocked}")
        return blocked
    except Exception as e:
        print(f"News filter error: {e}")
        return set()

def get_min_score(name):
    """Returns required score threshold (out of 9). Default 6; raises to 7 when global WR < 35%."""
    stats_file = "/root/tradingbot/trade_stats.json"
    try:
        if os.path.exists(stats_file):
            with open(stats_file) as f:
                gs = json.load(f)
            total = gs.get("wins", 0) + gs.get("losses", 0)
            if total >= 10:
                wr = gs.get("wins", 0) / total
                if wr < 0.35:
                    print(f"Global WR {round(wr*100)}% < 35% — raising threshold to 7 for {name}")
                    return 7
    except Exception as e:
        print(f"Score threshold error: {e}")
    return 6

MAX_SIGNALS_PER_DAY = 2
_daily_signals = {}  # date -> count (in-memory, resets on restart)

def main():
    print("POI Strategy started (1H timeframe)...")
    _load_cursors()
    last_signals = load_last_signals()
    news_cache = {"time": 0, "blocked": set()}

    while True:
        try:
            tz_athens = pytz.timezone("Europe/Athens")
            today_str = datetime.now(tz_athens).strftime("%Y-%m-%d")
            if _daily_signals.get(today_str, 0) >= MAX_SIGNALS_PER_DAY:
                print(f"Daily signal limit ({MAX_SIGNALS_PER_DAY}) reached — sleeping 1h")
                time.sleep(3600)
                continue

            in_session = is_trading_session()
            in_asian = is_asian_session()
            if not in_session and not in_asian:
                print("Outside session - scanning crypto only...")
            elif in_asian and not in_session:
                print("Asian session - scanning Gold/JPY/AUD/NZD + crypto...")

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
                    if not in_session and not in_asian and name not in CRYPTO_PAIRS:
                        continue
                    if in_asian and not in_session and name not in CRYPTO_PAIRS and name not in ASIAN_PAIRS:
                        continue
                    if name in open_pairs:
                        continue

                    # News filter: skip if any currency in this pair has upcoming high-impact event
                    pair_ccys = PAIR_CURRENCIES.get(name, [])
                    if news_cache["blocked"] & set(pair_ccys):
                        print(f"Skipping {name} — news filter active")
                        continue

                    df = get_data(symbol)
                    poi = find_poi(df, name)

                    if poi:
                        trend_4h = get_trend_4h(symbol)
                        signal = "BUY" if poi["bias"] == "BULLISH" else "SELL"
                        # Cooldown is direction-aware: a valid reversal (BUY after SELL or
                        # vice versa) is not suppressed by a recent signal in the other direction.
                        last_sig_key = f"{name}_{signal}"
                        if (now_time - last_signals.get(last_sig_key, {}).get("time", 0)) < 21600:
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

                        # Weekly trend — highest timeframe must agree
                        trend_weekly = get_weekly_trend(symbol)
                        if trend_weekly and signal == "BUY" and trend_weekly != "BULL":
                            continue
                        if trend_weekly and signal == "SELL" and trend_weekly != "BEAR":
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
                msg_id = send_signal(msg)
                signal = "BUY" if best_poi["bias"] == "BULLISH" else "SELL"
                last_sig_key = f"{best_name}_{signal}"
                last_signals[last_sig_key] = {"time": now_time, "signal": signal}
                save_last_signals(last_signals)
                add_trade(best_name, best_poi, signal_message_id=msg_id)
                _daily_signals[today_str] = _daily_signals.get(today_str, 0) + 1
                print(f"POI sent: {best_name} {best_poi['bias']} score:{best_score} msg_id:{msg_id} (today:{_daily_signals[today_str]}/{MAX_SIGNALS_PER_DAY})")
            else:
                print("Scan complete - no POI found")

        except Exception as e:
            print(f"Main error: {e}")

        time.sleep(3600)

if __name__ == "__main__":
    main()
