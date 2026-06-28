import os
from dotenv import load_dotenv
load_dotenv("/root/tradingbot/.env")

import yfinance as yf
import requests
import pandas as pd
import numpy as np
import json
import os
import time
from datetime import datetime
import pytz

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN_SIGNAL")
SIGNALS_CHANNEL = os.getenv("SIGNALS_CHANNEL")
LAST_SIGNAL_FILE = "/root/tradingbot/last_signals_smc.json"

ALL_PAIRS = {
    "XAU/USD": "GC=F",
    "BTC/USD": "BTC-USD",
    "SOL/USD": "SOL-USD",
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
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
    except:
        pass
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
    except:
        pass
    return None

def load_last_signals():
    if os.path.exists(LAST_SIGNAL_FILE):
        with open(LAST_SIGNAL_FILE) as f:
            return json.load(f)
    return {}

def save_last_signals(data):
    with open(LAST_SIGNAL_FILE, "w") as f:
        json.dump(data, f)

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
    except:
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

    # FVG
    fvg_bull_zone = None
    fvg_bear_zone = None
    for i in range(2, min(10, len(df))):
        if df["Low"].iloc[-i] > df["High"].iloc[-i-2]:
            fvg_bull_zone = (round(df["High"].iloc[-i-2], 5), round(df["Low"].iloc[-i], 5))
            break
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
    if 40 < rsi < 65:
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
    if 35 < rsi < 60:
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
        "Strategy: SMC + EMA + MACD | 1H"
    )

def add_trade(name, poi):
    trades_file = "/root/tradingbot/open_trades.json"
    trades = []
    if os.path.exists(trades_file):
        with open(trades_file) as f:
            trades = json.load(f)
    signal = "BUY" if poi["bias"] == "BULLISH" else "SELL"
    trades.append({"name": name, "signal": signal, "entry": poi["price"], "sl": poi["sl"], "tp": poi["tp"], "time": time.time()})
    with open(trades_file, "w") as f:
        json.dump(trades, f)

def main():
    print("POI Strategy started (1H timeframe)...")
    last_signals = load_last_signals()

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

            # Load open trades to prevent conflicts
            open_trades_file = "/root/tradingbot/open_trades.json"
            open_trades = []
            if os.path.exists(open_trades_file):
                with open(open_trades_file) as f:
                    open_trades = json.load(f)
            open_pairs = set(t["name"] for t in open_trades)

            for name, symbol in ALL_PAIRS.items():
                try:
                    # Skip if already have open trade for this pair
                    if name in open_pairs:
                        continue

                    last_sig = last_signals.get(name, {})
                    last_sig_time = last_sig.get("time", 0)
                    if (now_time - last_sig_time) < 21600:
                        continue
                    last_dir = last_sig.get("signal", "")

                    # HTF 4H confirmation
                    trend_4h = get_trend_4h(symbol)

                    df = get_data(symbol)
                    poi = find_poi(df, name)

                    if poi:
                        signal = "BUY" if poi["bias"] == "BULLISH" else "SELL"
                        if last_dir and signal == last_dir:
                            continue
                        # HTF filter: skip if 4H trend disagrees
                        if trend_4h and signal == "BUY" and trend_4h != "BULL":
                            continue
                        if trend_4h and signal == "SELL" and trend_4h != "BEAR":
                            continue
                        # LTF 15m confirmation: skip if 15m contradicts entry direction
                        trend_15m = get_trend_15m(symbol)
                        if trend_15m and signal == "BUY" and trend_15m == "BEAR":
                            continue
                        if trend_15m and signal == "SELL" and trend_15m == "BULL":
                            continue
                        if poi["score"] > best_score:
                            best_score = poi["score"]
                            best_poi = poi
                            best_name = name
                except Exception as e:
                    print("Error "+name+": "+str(e))

            if best_poi:
                msg = format_poi(best_name, best_poi)
                send_signal(msg)
                signal = "BUY" if best_poi["bias"] == "BULLISH" else "SELL"
                last_signals[best_name] = {"time": now_time, "signal": signal}
                save_last_signals(last_signals)
                add_trade(best_name, best_poi)
                print("POI sent: "+best_name+" "+best_poi["bias"]+" score:"+str(best_score))
            else:
                print("Scan complete - no POI found")

        except Exception as e:
            print("Main error: "+str(e))

        time.sleep(3600)

if __name__ == "__main__":
    main()
