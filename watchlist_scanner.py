"""Broader-pair "developing setup" scanner — a heads-up, not a trade call. Covers
the full 15-instrument universe (vs. the 5 pairs signal_strategy.py actually
trades), using looser criteria (price approaching EMA20 in the HTF trend
direction, no confirmation candle required yet) so users get early awareness of
pairs worth watching manually. Deliberately has no entry/SL/TP and no chart, so
it can never be mistaken for an actual trade signal.

Each category applies the same filter logic that was backtested for live trading
(2026-07 category review — see signal_strategy.py's ALL_PAIRS comment for the
full results) even though most of these categories backtested NEGATIVE for real
entries: an ADX(14)>20 trend-strength filter for FX majors, a tighter EMA20
tolerance for EUR/CHF, a DXY inverse-correlation filter for metals, and a volume
filter for crypto. Applying the tuned filters to a no-risk "worth watching" flag
is safe even for pairs that don't have a validated live edge — it's just early
awareness, never a trade call.
"""
import os
from dotenv import load_dotenv
load_dotenv("/root/tradingbot/.env")

import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor
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
    "XAU/USD": "GC=F", "Silver/USD": "SI=F", "Copper/USD": "HG=F", "Oil/USD": "CL=F",
    "BTC/USD": "BTC-USD", "SOL/USD": "SOL-USD",
    "EUR/USD": "EURUSD=X", "GBP/USD": "GBPUSD=X", "USD/CHF": "USDCHF=X",
    "AUD/USD": "AUDUSD=X", "USD/CAD": "USDCAD=X", "NZD/USD": "NZDUSD=X", "USD/JPY": "USDJPY=X",
    "EUR/CHF": "EURCHF=X", "DXY": "DX-Y.NYB",
}

PAIR_EMOJIS = {
    "XAU/USD": "\U0001fa99", "Silver/USD": "\U0001f948", "Copper/USD": "\U0001f7e4", "Oil/USD": "⛽",
    "BTC/USD": "\U0001f7e1", "SOL/USD": "\U0001f535",
    "EUR/USD": "\U0001f1ea\U0001f1fa", "GBP/USD": "\U0001f1ec\U0001f1e7", "USD/CHF": "\U0001f1fa\U0001f1f8",
    "AUD/USD": "\U0001f1e6\U0001f1fa", "USD/CAD": "\U0001f1e8\U0001f1e6", "NZD/USD": "\U0001f1f3\U0001f1ff",
    "USD/JPY": "\U0001f1ef\U0001f1f5", "EUR/CHF": "\U0001f1ea\U0001f1fa\U0001f1e8\U0001f1ed", "DXY": "\U0001f4b5",
}

# Category-specific filters for the watchlist heads-up (see module docstring). Pairs
# not listed fall back to the original generic tol=0.6x ATR with no extra filter
# (USD/CAD, Oil/USD, DXY itself).
PAIR_PARAMS = {
    "EUR/USD": {"tol_mult": 0.5, "adx_min": 20},
    "GBP/USD": {"tol_mult": 0.5, "adx_min": 20},
    "USD/CHF": {"tol_mult": 0.5, "adx_min": 20},
    "USD/JPY": {"tol_mult": 0.5, "adx_min": 20},
    "AUD/USD": {"tol_mult": 0.5, "adx_min": 20},
    "NZD/USD": {"tol_mult": 0.5, "adx_min": 20},
    "EUR/CHF": {"tol_mult": 0.3},
    "XAU/USD": {"tol_mult": 0.65, "dxy_filter": True},
    "Silver/USD": {"tol_mult": 0.65, "dxy_filter": True},
    "Copper/USD": {"tol_mult": 0.65, "dxy_filter": True},
    "BTC/USD": {"tol_mult": 1.0, "vol_min_ratio": 0.7},
    "SOL/USD": {"tol_mult": 1.0, "vol_min_ratio": 0.7},
}

_YF_EXECUTOR = ThreadPoolExecutor(max_workers=4)


def _wilder_smooth(series, period):
    return series.ewm(alpha=1 / period, adjust=False).mean()


def compute_adx(df, period=14):
    high, low, close = df["High"], df["Low"], df["Close"]
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = ((up_move > down_move) & (up_move > 0)) * up_move
    minus_dm = ((down_move > up_move) & (down_move > 0)) * down_move
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr_w = _wilder_smooth(tr, period)
    plus_di = 100 * _wilder_smooth(plus_dm, period) / atr_w
    minus_di = 100 * _wilder_smooth(minus_dm, period) / atr_w
    denom = (plus_di + minus_di).replace(0, float('nan'))
    # replace inf before fillna: zero-range candles produce inf DX that bypass ADX thresholds
    dx = (100 * (plus_di - minus_di).abs() / denom).replace([float('inf'), float('-inf')], float('nan')).fillna(0)
    return _wilder_smooth(dx, period)


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
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception as e:
        print(f"save {path} error: {e}")


def get_data(symbol):
    try:
        df = _YF_EXECUTOR.submit(yf.Ticker(symbol).history, period="30d", interval="1h").result(timeout=20)
        if len(df) < 210:
            df = _YF_EXECUTOR.submit(yf.Ticker(symbol).history, period="60d", interval="1h").result(timeout=20)
        if len(df) < 210:
            return None
        return df
    except Exception as e:
        print(f"get_data error {symbol}: {e}")
        return None


def find_developing_setup(df, name, dxy_bull=None, dxy_bear=None):
    """Looser than signal_strategy.find_setup: HTF trend + price currently
    within the EMA20 pullback zone — no rejection confirmation candle required
    yet, so this fires earlier (and less reliably) than an actual signal.
    Category-specific tolerance/ADX/volume/DXY filters come from PAIR_PARAMS —
    see module docstring for why."""
    if df is None or len(df) < 210:
        return None

    params = PAIR_PARAMS.get(name, {"tol_mult": 0.6})
    tol_mult = params["tol_mult"]
    adx_min = params.get("adx_min")
    vol_min_ratio = params.get("vol_min_ratio")
    dxy_filter = params.get("dxy_filter", False)

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

    if adx_min is not None:
        adx_val = compute_adx(df).iloc[-1]
        if pd.isna(adx_val) or adx_val <= adx_min:
            return None

    if vol_min_ratio is not None:
        vol = df["Volume"] if "Volume" in df.columns else None
        if vol is None:
            return None
        vol_avg = vol.iloc[-21:-1].mean()
        if vol_avg == 0 or pd.isna(vol_avg) or pd.isna(vol.iloc[-1]):
            return None
        if vol.iloc[-1] < vol_avg * vol_min_ratio:
            return None

    tol = a * tol_mult
    bull_trend = ema50.iloc[-1] > ema200.iloc[-1]
    bear_trend = ema50.iloc[-1] < ema200.iloc[-1]
    near_ema20 = abs(price - ema20.iloc[-1]) <= tol

    if dxy_filter and dxy_bull is not None and dxy_bear is not None and not dxy_bull.empty and not dxy_bear.empty:
        # Metals inverse-correlation: only flag a bullish metal watch while DXY
        # itself is bearish, and vice versa — a gold BUY read that agrees with a
        # simultaneous dollar-bullish read is the exact conflict the filter exists for.
        if bull_trend and not dxy_bear.iloc[-1]:
            bull_trend = False
        if bear_trend and not dxy_bull.iloc[-1]:
            bear_trend = False

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
        return True
    except Exception as e:
        print(f"send_watchlist_alert error {name}: {e}")
        return False


def main():
    print("Watchlist scanner started...")
    state = _load_json(STATE_FILE, {})
    while True:
        try:
            open_trades = _load_json(OPEN_TRADES_FILE, [])
            open_pairs = set(t["name"] for t in open_trades if "name" in t)

            # Fetched once per cycle (not per pair) and only consumed by metals,
            # which have dxy_filter=True in PAIR_PARAMS.
            dxy_bull = dxy_bear = None
            try:
                dxy_df = get_data(PAIRS["DXY"])
                if dxy_df is not None and len(dxy_df) >= 210:
                    dxy_close = dxy_df["Close"]
                    dxy_ema50 = dxy_close.ewm(span=50).mean()
                    dxy_ema200 = dxy_close.ewm(span=200).mean()
                    dxy_bull = dxy_ema50 > dxy_ema200
                    dxy_bear = dxy_ema50 < dxy_ema200
                else:
                    # DXY filter bypassed — metals alerts may fire on USD-strength conditions
                    bars = len(dxy_df) if dxy_df is not None else 0
                    print(f"WARNING: DXY filter bypassed — insufficient data ({bars} bars), metals may alert regardless of USD direction")
            except Exception as e:
                print(f"DXY fetch error: {e}")

            state_changed = False
            for name, symbol in PAIRS.items():
                try:
                    if name == "DXY":  # DXY is a correlation reference, not a tradable pair
                        continue
                    if name in open_pairs:
                        continue
                    df = get_data(symbol)
                    setup = find_developing_setup(df, name, dxy_bull, dxy_bear)
                    was_near = state.get(name, {}).get("near", False)
                    if setup and not was_near:
                        if send_watchlist_alert(name, setup):
                            state[name] = {"near": True}
                            state_changed = True
                    elif not setup and was_near:
                        # Moved out of the zone — allow a fresh alert on the next approach
                        state[name] = {"near": False}
                        state_changed = True
                except Exception as e:
                    print(f"Error {name}: {e}")
            if state_changed:
                _save_json(STATE_FILE, state)
        except Exception as e:
            print(f"Main error: {e}")

        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    main()
