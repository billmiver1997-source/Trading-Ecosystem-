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
try:
    from bs4 import BeautifulSoup as _BeautifulSoup
except ImportError:
    _BeautifulSoup = None

try:
    import chart
except Exception as _chart_import_err:
    chart = None  # chart.py missing or broken — signals send as text only
    print(f"chart module unavailable: {_chart_import_err}")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN_SIGNAL")
SIGNALS_CHANNEL = os.getenv("SIGNALS_CHANNEL")
if not TELEGRAM_TOKEN or not SIGNALS_CHANNEL:
    raise RuntimeError("TELEGRAM_TOKEN_SIGNAL and SIGNALS_CHANNEL must be set in .env")
LAST_SIGNAL_FILE = "/root/tradingbot/last_signals_smc.json"
LAST_SIGNAL_LOCK_PATH = LAST_SIGNAL_FILE + ".lock"

# Strategy: HTF trend (EMA50/EMA200) + pullback to EMA20 + rejection confirmation candle.
# Backtested on 90d of 1H data across all 11 previously-traded pairs (no lookahead —
# entries fire at the open of the bar AFTER the confirmation candle closes). Only USD/CAD
# and Oil/USD showed a real, out-of-sample-consistent positive edge in that first pass;
# the other 9 (incl. XAU/USD, EUR/USD, GBP/USD which were the biggest live losers) were
# flat or negative in a first-half/second-half split test and were dropped rather than
# "fixed". A second round (2026-07) tested 6 majors + EUR/CHF + 3 metals + BTC/SOL with
# category-specific tweaks (ADX filter, DXY correlation, volume filter, tuned RR/buffers)
# — only NZD/USD (majors, +ADX>20 filter) and BTC/USD + SOL/USD (crypto, +volume filter)
# cleared the same bar. EUR/USD, GBP/USD, USD/CHF, USD/JPY, AUD/USD, EUR/CHF, XAU/USD,
# Silver/USD and Copper/USD were all negative or half-inconsistent even after tuning and
# were NOT added. See PAIR_PARAMS below for the per-pair validated parameters.
ALL_PAIRS = {
    "USD/CAD": "USDCAD=X",
    "Oil/USD": "CL=F",
    "NZD/USD": "NZDUSD=X",
    "BTC/USD": "BTC-USD",
    "SOL/USD": "SOL-USD",
}

# Pairs that trade 24/7 — skip the liquid-FX-hours session gate for these only.
CRYPTO_PAIRS = {"BTC/USD", "SOL/USD"}

PAIR_CURRENCIES = {
    "USD/CAD": ["USD", "CAD"],
    "Oil/USD": ["USD"],
    "NZD/USD": ["NZD", "USD"],
    "BTC/USD": ["USD"],
    "SOL/USD": ["USD"],
}

RR = 1.5  # default/fallback only — each pair's real RR lives in PAIR_PARAMS below.

# VALIDATED per-pair parameters (90d 1H backtest, split-half consistency required — see
# ALL_PAIRS comment above for what was tried and rejected). Do NOT change any pair's
# values without re-running the comparison backtest first:
#   USD/CAD / Oil/USD: RR=1.5, tol=0.5x ATR, SL buffer=0.3x ATR — the original validated pair.
#   NZD/USD: RR=1.2 (2.0/1.8 decayed hard in the 2nd half — 1.2 split +16.2R/+11.6R, most
#     even). Requires ADX(14) > 20 on the pullback bar — without it, net R is similar but
#     front-loaded (+23.2R/+5.0R), i.e. weaker out-of-sample confidence, not a bigger edge.
#   BTC/USD: RR=1.75, wider tol=1.25x ATR + SL buffer=0.6x ATR (crypto's larger natural
#     swings need more room). Requires volume >= 70% of its own 20-bar average on the
#     pullback bar — without it, net R looks bigger (+35R) but is badly front-loaded
#     (+27.5R/+7.75R); with the filter it's +9.75R/+8.25R, a much more even, trustworthy split.
#   SOL/USD: RR=1.75, tol=1.25x ATR, SL buffer=0.5x ATR. The volume filter isn't optional
#     here — without it the first half is net NEGATIVE (-24.75R) and the pair fails outright.
PAIR_PARAMS = {
    "USD/CAD": {"tol_mult": 0.5, "sl_mult": 0.3, "rr": 1.5},
    "Oil/USD": {"tol_mult": 0.5, "sl_mult": 0.3, "rr": 1.5},
    "NZD/USD": {"tol_mult": 0.5, "sl_mult": 0.3, "rr": 1.2, "adx_min": 20},
    "BTC/USD": {"tol_mult": 1.25, "sl_mult": 0.6, "rr": 1.75, "vol_min_ratio": 0.7},
    "SOL/USD": {"tol_mult": 1.25, "sl_mult": 0.5, "rr": 1.75, "vol_min_ratio": 0.7},
}

PAIR_EMOJIS = {
    "USD/CAD": "\U0001f1e8\U0001f1e6",
    "Oil/USD": "⛽",
    "NZD/USD": "\U0001f1f3\U0001f1ff",
    "BTC/USD": "\U0001f7e1",
    "SOL/USD": "\U0001f535",
}

# Cumulative wins/losses per pair (since this strategy's stats were reset) below this
# win rate pauses new signals for that pair — a safety net so a second broken strategy
# can't run unnoticed for 10 days again like the old one did.
CIRCUIT_BREAKER_MIN_TRADES = 8
CIRCUIT_BREAKER_MIN_WINRATE = 0.30


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
            os.fsync(f.fileno())  # ensure bytes reach disk before atomic rename
        os.replace(tmp, path)
        return True
    except Exception as e:
        print(f"save {path} error: {e}")
        try:
            os.unlink(tmp)
        except OSError as e:
            print(f"_save_json: failed to delete temp {tmp}: {e}")
        return False


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


def is_trading_session():
    """Liquid FX/commodity hours — Athens weekdays 10:00-23:00. Execution-quality
    filter, not part of the backtested edge (the backtest didn't restrict by hour).
    Does NOT apply to CRYPTO_PAIRS — those trade 24/7, see main()."""
    tz = pytz.timezone("Europe/Athens")
    now = datetime.now(tz)
    if now.weekday() >= 5:
        return False
    return 10 <= now.hour < 23


def _wilder_smooth(series, period):
    """Wilder's smoothing == an EWM with alpha=1/period — matches market_regime.py's
    ADX exactly so the NZD/USD filter uses the same definition traders reference."""
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
    dx = (100 * (plus_di - minus_di).abs() / denom).fillna(0)  # 0 DI sum = no trend, ADX=0
    return _wilder_smooth(dx, period)


def send_signal_photo(msg, photo_path):
    """Send the generated chart to the channel with the signal caption. Returns message_id."""
    cap = msg[:1024]
    message_id = None
    try:
        if photo_path and os.path.exists(photo_path):
            with open(photo_path, "rb") as pf:
                r = requests.post(
                    "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendPhoto",
                    files={"photo": ("chart.png", pf, "image/png")},
                    data={"chat_id": SIGNALS_CHANNEL, "caption": cap}, timeout=20,
                )
        else:
            r = requests.post(
                "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage",
                json={"chat_id": SIGNALS_CHANNEL, "text": msg[:4000]}, timeout=10,
            )
        r.raise_for_status()
        message_id = r.json().get("result", {}).get("message_id")
    except Exception as e:
        print("Send error: " + str(e))
    finally:
        if photo_path and os.path.exists(photo_path):
            try:
                os.remove(photo_path)
            except OSError as e:
                print(f"Failed to delete temp chart file {photo_path}: {e}")
    return message_id


def send_channel_text(msg):
    try:
        r = requests.post(
            "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage",
            json={"chat_id": SIGNALS_CHANNEL, "text": msg[:4000]}, timeout=10,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        print("Send channel text error: " + str(e))
        return False


def get_data(symbol):
    try:
        ticker = yf.Ticker(symbol)
        # Fetch 60d directly — avoids a wasted 30d call on pairs that routinely need it
        df = ticker.history(period="60d", interval="1h")
        if len(df) < 210:
            return None
        return df
    except Exception as e:
        print(f"get_data error {symbol}: {e}")
        return None


def find_setup(df, name):
    """HTF trend + pullback-to-EMA20 + rejection confirmation. Mirrors backtest_v2.py
    exactly so live behavior matches what was validated: the confirmation candle is the
    last CLOSED candle (iloc[-2]); entry is the current live price (iloc[-1], the bar
    that opened right after confirmation closed) — no lookahead. Per-pair tolerance/SL/RR
    and optional ADX or volume filters come from PAIR_PARAMS — see its comment for why
    each pair's values are what they are."""
    if df is None or len(df) < 210:
        return None

    params = PAIR_PARAMS.get(name, {"tol_mult": 0.5, "sl_mult": 0.3, "rr": RR})
    tol_mult = params["tol_mult"]; sl_mult = params["sl_mult"]; rr = params["rr"]
    adx_min = params.get("adx_min")
    vol_min_ratio = params.get("vol_min_ratio")

    close = df["Close"]; high = df["High"]; low = df["Low"]; open_ = df["Open"]
    ema20 = close.ewm(span=20).mean()
    ema50 = close.ewm(span=50).mean()
    ema200 = close.ewm(span=200).mean()
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()

    i = len(df) - 2  # last closed candle = confirmation candle
    a = atr.iloc[i]
    if pd.isna(a) or a == 0:
        return None

    if adx_min is not None:
        adx_val = compute_adx(df).iloc[i - 1]
        if pd.isna(adx_val) or adx_val <= adx_min:
            return None

    if vol_min_ratio is not None:
        vol = df["Volume"] if "Volume" in df.columns else None
        if vol is None:
            return None  # can't validate the filter — skip rather than trade unfiltered
        # Exclude the pullback bar (i-1) from its own baseline to avoid self-referential inflation
        vol_avg = vol.iloc[max(0, i - 21):i - 1].mean()
        if vol_avg == 0 or pd.isna(vol_avg) or pd.isna(vol.iloc[i - 1]):
            return None
        if vol.iloc[i - 1] < vol_avg * vol_min_ratio:
            return None

    price = open_.iloc[-1]
    confirm_bar_time = df.index[i].isoformat()

    bull_trend = ema50.iloc[i] > ema200.iloc[i]
    bear_trend = ema50.iloc[i] < ema200.iloc[i]

    pull_low = low.iloc[i - 1]; pull_high = high.iloc[i - 1]
    if pd.isna(atr.iloc[i - 1]):
        return None
    tol = atr.iloc[i - 1] * tol_mult  # use pullback bar's own ATR for proximity tolerance

    if bull_trend:
        touched = pull_low <= ema20.iloc[i - 1] + tol
        body = close.iloc[i] - open_.iloc[i]
        rng = high.iloc[i] - low.iloc[i]
        body_ratio = body / rng if rng > 0 else 0
        if touched and body > 0 and body_ratio > 0.5 and close.iloc[i] > ema20.iloc[i]:
            sl = round(pull_low - a * sl_mult, 5)
            risk = price - sl
            if risk <= 0:
                return None
            tp = round(price + risk * rr, 5)
            return {
                "bias": "BULLISH", "price": price, "sl": sl, "tp": tp,
                "confirm_bar_time": confirm_bar_time,
                "reason": "Pullback to EMA20 + bullish rejection candle, HTF trend up",
            }

    if bear_trend:
        touched = pull_high >= ema20.iloc[i - 1] - tol
        body = open_.iloc[i] - close.iloc[i]
        rng = high.iloc[i] - low.iloc[i]
        body_ratio = body / rng if rng > 0 else 0
        if touched and body > 0 and body_ratio > 0.5 and close.iloc[i] < ema20.iloc[i]:
            sl = round(pull_high + a * sl_mult, 5)
            risk = sl - price
            if risk <= 0:
                return None
            tp = round(price - risk * rr, 5)
            return {
                "bias": "BEARISH", "price": price, "sl": sl, "tp": tp,
                "confirm_bar_time": confirm_bar_time,
                "reason": "Pullback to EMA20 + bearish rejection candle, HTF trend down",
            }

    return None


def format_setup(name, setup):
    emoji = PAIR_EMOJIS.get(name, "")
    bias_emoji = "\U0001f7e2" if setup["bias"] == "BULLISH" else "\U0001f534"
    tz = pytz.timezone("Europe/Athens")
    now = datetime.now(tz).strftime("%d/%m %H:%M")
    action = "BUY" if setup["bias"] == "BULLISH" else "SELL"
    session = get_session_label()
    sl_dist = abs(setup["sl"] - setup["price"])
    rr_dist = abs(setup["tp"] - setup["price"])
    rr_ratio = round(rr_dist / sl_dist, 1) if sl_dist > 0 else RR
    return (
        "\U0001f3af TRADING SETUP — " + name + "\n\n"
        + emoji + "  " + now + "  |  " + session + "\n"
        + bias_emoji + " " + setup["bias"] + "  |  " + action + " now\n\n"
        "\U0001f4cd Entry: " + str(round(setup["price"], 5)) + "\n"
        "\U0001f6d1 SL: " + str(setup["sl"]) + "   ✅ TP: " + str(setup["tp"]) + "\n"
        "\U0001f4d0 R:R = 1:" + str(rr_ratio) + "\n\n"
        "⚡ " + setup["reason"] + "\n\n"
        "Pullback + confirmation | 1H\n"
        "⚠️ Educational only. Not financial advice."
    )


def add_trade(name, setup, signal_message_id=None):
    trades_file = "/root/tradingbot/open_trades.json"
    lock_path = trades_file + ".lock"
    signal = "BUY" if setup["bias"] == "BULLISH" else "SELL"
    new_trade = {
        "name": name, "signal": signal, "entry": setup["price"], "sl": setup["sl"],
        "tp": setup["tp"], "time": time.time(), "signal_message_id": signal_message_id,
    }
    with open(lock_path, "a") as _lf:
        fcntl.flock(_lf, fcntl.LOCK_EX)
        try:
            trades = _load_json(trades_file, [])
            trades.append(new_trade)
            _save_json(trades_file, trades)
        finally:
            fcntl.flock(_lf, fcntl.LOCK_UN)


def circuit_breaker_tripped(name):
    stats = _load_json("/root/tradingbot/trade_stats.json", {})
    pair_s = stats.get("by_pair", {}).get(name, {})
    total = pair_s.get("wins", 0) + pair_s.get("losses", 0)
    if total < CIRCUIT_BREAKER_MIN_TRADES:
        return False
    wr = pair_s.get("wins", 0) / total
    return wr < CIRCUIT_BREAKER_MIN_WINRATE


def get_news_blocked_currencies():
    """Returns set of currency codes with high-impact events within -15/+30 minutes."""
    if _BeautifulSoup is None:
        return set()
    try:
        BeautifulSoup = _BeautifulSoup
        tz = pytz.timezone("Europe/Athens")
        now = datetime.now(tz)
        today = now.strftime("%Y-%m-%d")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://www.investing.com/economic-calendar/",
        }
        payload = {"dateFrom": today, "dateTo": today, "importance[]": ["3"]}
        r = requests.post(
            "https://www.investing.com/economic-calendar/Service/getCalendarFilteredData",
            headers=headers, data=payload, timeout=10,
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
        print(f"News filter DISABLED (fetch failed: {e}) — all pairs unblocked this cycle")
        return set()


def main():
    print("Pullback strategy started (1H timeframe, USD/CAD + Oil/USD + NZD/USD + BTC/USD + SOL/USD)...")
    tripped_alerted = set()
    news_blocked: set = set()

    while True:
        try:
            # FX/commodity pairs only trade during liquid hours; CRYPTO_PAIRS trade 24/7,
            # so unlike before this can no longer globally skip the whole cycle — the
            # per-pair check below decides individually.
            session_open = is_trading_session()

            news_blocked = get_news_blocked_currencies()

            open_trades = _load_json("/root/tradingbot/open_trades.json", [])
            open_pairs = set(t["name"] for t in open_trades)

            for name, symbol in ALL_PAIRS.items():
                try:
                    if name not in CRYPTO_PAIRS and not session_open:
                        continue

                    if name in open_pairs:
                        continue

                    if circuit_breaker_tripped(name):
                        if name not in tripped_alerted:
                            # Only mark as alerted if Telegram delivery succeeds
                            if send_channel_text(
                                "⚠️ " + name + " signals paused — win rate fell below "
                                + str(int(CIRCUIT_BREAKER_MIN_WINRATE * 100))
                                + "% over the last " + str(CIRCUIT_BREAKER_MIN_TRADES) + "+ trades. "
                                "Needs manual review before resuming."
                            ):
                                tripped_alerted.add(name)
                        continue
                    else:
                        # Pair has recovered — allow a fresh alert if it trips again later
                        tripped_alerted.discard(name)

                    pair_ccys = PAIR_CURRENCIES.get(name, [])
                    if news_blocked & set(pair_ccys):
                        print(f"Skipping {name} — news filter active")
                        continue

                    df = get_data(symbol)
                    setup = find_setup(df, name)
                    if not setup:
                        continue

                    signal = "BUY" if setup["bias"] == "BULLISH" else "SELL"
                    dedup_key = f"{name}_{signal}"

                    # Fresh disk read under shared lock to catch signals from a concurrent process
                    with open(LAST_SIGNAL_LOCK_PATH, "a") as _lf:
                        fcntl.flock(_lf, fcntl.LOCK_SH)
                        current_signals = _load_json(LAST_SIGNAL_FILE, {})
                        fcntl.flock(_lf, fcntl.LOCK_UN)
                    if current_signals.get(dedup_key, {}).get("confirm_bar_time") == setup["confirm_bar_time"]:
                        continue  # already signaled this exact confirmation candle

                    msg = format_setup(name, setup)
                    try:
                        photo_path = chart.make_signal_chart(
                            name, symbol, setup["bias"], setup["price"], setup["sl"], setup["tp"]
                        ) if chart is not None else None
                    except Exception as chart_err:
                        print(f"Chart generation failed for {name}: {chart_err}")
                        photo_path = None
                    msg_id = send_signal_photo(msg, photo_path)
                    if msg_id is None:
                        # Telegram delivery failed — don't record dedup or open trade
                        print(f"Signal send failed for {name} — will retry next cycle.")
                        continue
                    # Register trade and dedup only after confirmed delivery; exclusive lock
                    # to prevent a race with a simultaneously restarted second instance.
                    # add_trade() is called INSIDE the lock so a concurrent process that
                    # wins the race on dedup cannot also race on writing the trade entry.
                    with open(LAST_SIGNAL_LOCK_PATH, "a") as _lf:
                        fcntl.flock(_lf, fcntl.LOCK_EX)
                        try:
                            last_signals = _load_json(LAST_SIGNAL_FILE, {})
                            # Re-check under exclusive lock: a concurrent process may have
                            # already written this dedup entry between our initial check and now.
                            if last_signals.get(dedup_key, {}).get("confirm_bar_time") == setup["confirm_bar_time"]:
                                continue
                            last_signals[dedup_key] = {"time": time.time(), "confirm_bar_time": setup["confirm_bar_time"]}
                            # Only add the trade if dedup write succeeds; a failed write
                            # would leave no dedup entry, causing a repeated signal next cycle.
                            if _save_json(LAST_SIGNAL_FILE, last_signals):
                                add_trade(name, setup, signal_message_id=msg_id)
                            else:
                                print(f"Dedup write failed for {name} — trade not recorded to prevent repeat signal")
                        finally:
                            fcntl.flock(_lf, fcntl.LOCK_UN)
                    print(f"Signal sent: {name} {setup['bias']} entry:{setup['price']} sl:{setup['sl']} tp:{setup['tp']} msg_id:{msg_id}")
                except Exception as e:
                    print(f"Error {name}: {e}")
                    continue

        except Exception as e:
            print(f"Main error: {e}")
            time.sleep(300)  # short recovery sleep on exception; avoid missing next crypto candle
            continue

        time.sleep(3600)


if __name__ == "__main__":
    main()
