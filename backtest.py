import os
from dotenv import load_dotenv
load_dotenv("/root/tradingbot/.env")

import yfinance as yf
import requests
import pandas as pd
import json
import time
from datetime import datetime
import pytz

try:
    import chart
except Exception as _chart_import_err:
    chart = None
    print(f"chart module unavailable: {_chart_import_err}")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN_SIGNAL")
if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN_SIGNAL is not set in environment")
SIGNALS_CHANNEL = os.getenv("SIGNALS_CHANNEL")
USERS_FILE = "/root/tradingbot/users.json"
JOURNAL_FILE = "/root/tradingbot/journal.json"

# Same pairs as signal_strategy.ALL_PAIRS — kept in sync deliberately, this weekly report
# is an ongoing out-of-sample check on the exact strategy that's live, not a separate one.
PAIRS = {
    "USD/CAD": "USDCAD=X",
    "Oil/USD": "CL=F",
    "NZD/USD": "NZDUSD=X",
    "BTC/USD": "BTC-USD",
    "SOL/USD": "SOL-USD",
}

# Mirrors signal_strategy.PAIR_PARAMS exactly — see that file's comment for why each
# pair's values are what they are. Do not change without re-running the comparison
# backtest in both places.
PAIR_PARAMS = {
    "USD/CAD": {"tol_mult": 0.5, "sl_mult": 0.3, "rr": 1.5},
    "Oil/USD": {"tol_mult": 0.5, "sl_mult": 0.3, "rr": 1.5},
    "NZD/USD": {"tol_mult": 0.5, "sl_mult": 0.3, "rr": 1.2, "adx_min": 20},
    "BTC/USD": {"tol_mult": 1.25, "sl_mult": 0.6, "rr": 1.75, "vol_min_ratio": 0.7},
    "SOL/USD": {"tol_mult": 1.25, "sl_mult": 0.5, "rr": 1.75, "vol_min_ratio": 0.7},
}

RR = 1.5  # default/fallback only — the per-pair report uses PAIR_PARAMS[name]["rr"].


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
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return _wilder_smooth(dx, period)


def load_users():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError, OSError) as e:
            print(f"load_users error: {e}")
    return []


def send_channel_photo(photo_path, caption=""):
    """Post the weekly equity curve to the signals channel once. Deletes the
    file after sending — regenerated fresh next week, nothing to cache."""
    if not SIGNALS_CHANNEL or not photo_path or not os.path.exists(photo_path):
        return
    try:
        with open(photo_path, "rb") as pf:
            r = requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendPhoto",
                files={"photo": ("equity.png", pf, "image/png")},
                data={"chat_id": SIGNALS_CHANNEL, "caption": caption[:1024]}, timeout=20)
        r.raise_for_status()
    except Exception as e:
        print(f"send_channel_photo error: {e}")
    finally:
        try:
            os.remove(photo_path)
        except OSError:
            pass


def send_all(msg):
    # users.json may contain list of strings (listener.py) or list of dicts (main_bot.py)
    for item in load_users():
        chat_id = item["id"] if isinstance(item, dict) else item
        try:
            r = requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendMessage",
                json={"chat_id": chat_id, "text": msg[:4096]}, timeout=10)
            r.raise_for_status()
            time.sleep(0.1)
        except Exception as e:
            print(f"send_all error {chat_id}: {e}")


def backtest_pair(name, symbol):
    """HTF trend (EMA50/200) + pullback-to-EMA20 + rejection confirmation — identical
    logic to signal_strategy.find_setup(), so this weekly report tracks the strategy
    that's actually live, not a stand-in. Entry at the open of the bar AFTER the
    confirmation candle closes — no look-ahead bias. Per-pair tolerance/SL/RR and
    optional ADX/volume filters come from PAIR_PARAMS, mirroring signal_strategy.py."""
    try:
        df = yf.Ticker(symbol).history(period="90d", interval="1h")
    except Exception as e:
        print(f"backtest_pair data error {name}: {e}")
        return None
    if len(df) < 300:
        try:
            df180 = yf.Ticker(symbol).history(period="180d", interval="1h")
            # Only upgrade to the wider window if it actually has more bars
            if len(df180) > len(df):
                df = df180
        except Exception as e:
            print(f"backtest_pair 180d fallback error {name}: {e}")
    if len(df) < 261:
        return None

    params = PAIR_PARAMS.get(name, {"tol_mult": 0.5, "sl_mult": 0.3, "rr": RR})
    tol_mult = params["tol_mult"]; sl_mult = params["sl_mult"]; rr = params["rr"]
    adx_min = params.get("adx_min")
    vol_min_ratio = params.get("vol_min_ratio")

    close = df["Close"]; high = df["High"]; low = df["Low"]; open_ = df["Open"]
    ema20 = close.ewm(span=20).mean()
    ema50 = close.ewm(span=50).mean()
    ema200 = close.ewm(span=200).mean()
    tr = pd.concat([high-low, (high-close.shift()).abs(), (low-close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    adx = compute_adx(df) if adx_min is not None else None
    vol = df["Volume"] if (vol_min_ratio is not None and "Volume" in df.columns) else None

    wins = losses = timeouts = ambiguous = 0
    total_R = 0.0
    n = len(df)

    for i in range(200, n - 60):
        a = atr.iloc[i]
        if pd.isna(a) or a == 0:
            continue
        if adx_min is not None:
            adx_val = adx.iloc[i-1]
            if pd.isna(adx_val) or adx_val <= adx_min:
                continue
        if vol_min_ratio is not None:
            if vol is None:
                continue
            vol_avg = vol.iloc[max(0, i-20):i].mean()
            if vol_avg == 0 or pd.isna(vol_avg) or pd.isna(vol.iloc[i-1]):
                continue
            if vol.iloc[i-1] < vol_avg * vol_min_ratio:
                continue

        bull_trend = ema50.iloc[i] > ema200.iloc[i]
        bear_trend = ema50.iloc[i] < ema200.iloc[i]
        pull_low = low.iloc[i-1]; pull_high = high.iloc[i-1]
        tol = atr.iloc[i - 1] * tol_mult  # use pullback bar's own ATR for proximity tolerance

        if bull_trend:
            touched = pull_low <= ema20.iloc[i-1] + tol
            body = close.iloc[i] - open_.iloc[i]
            rng = high.iloc[i] - low.iloc[i]
            body_ratio = body / rng if rng > 0 else 0
            if touched and body > 0 and body_ratio > 0.5 and close.iloc[i] > ema20.iloc[i] and i+1 < n:
                entry = open_.iloc[i+1]
                sl = pull_low - a * sl_mult
                risk = entry - sl
                if risk <= 0:
                    continue
                tp = entry + risk * rr
                resolved = False
                for j in range(i+1, min(i+61, n)):
                    sl_hit = low.iloc[j] <= sl
                    tp_hit = high.iloc[j] >= tp
                    if sl_hit and tp_hit:
                        ambiguous += 1; resolved = True; break
                    if sl_hit:
                        losses += 1; total_R -= 1; resolved = True; break
                    if tp_hit:
                        wins += 1; total_R += rr; resolved = True; break
                if not resolved:
                    timeouts += 1
                continue

        if bear_trend:
            touched = pull_high >= ema20.iloc[i-1] - tol
            body = open_.iloc[i] - close.iloc[i]
            rng = high.iloc[i] - low.iloc[i]
            body_ratio = body / rng if rng > 0 else 0
            if touched and body > 0 and body_ratio > 0.5 and close.iloc[i] < ema20.iloc[i] and i+1 < n:
                entry = open_.iloc[i+1]
                sl = pull_high + a * sl_mult
                risk = sl - entry
                if risk <= 0:
                    continue
                tp = entry - risk * rr
                resolved = False
                for j in range(i+1, min(i+61, n)):
                    sl_hit = high.iloc[j] >= sl
                    tp_hit = low.iloc[j] <= tp
                    if sl_hit and tp_hit:
                        ambiguous += 1; resolved = True; break
                    if sl_hit:
                        losses += 1; total_R -= 1; resolved = True; break
                    if tp_hit:
                        wins += 1; total_R += rr; resolved = True; break
                if not resolved:
                    timeouts += 1

    total = wins + losses + timeouts + ambiguous
    decided = wins + losses
    winrate = round(wins/decided*100, 1) if decided > 0 else 0
    return {
        "name": name, "wins": wins, "losses": losses, "timeouts": timeouts,
        "ambiguous": ambiguous, "winrate": winrate, "total_R": round(total_R, 2),
        "signals": total,
    }


def run_backtest():
    tz = pytz.timezone("Europe/Athens")
    now = datetime.now(tz).strftime("%d/%m/%Y %H:%M")
    results = []

    for name, symbol in PAIRS.items():
        try:
            r = backtest_pair(name, symbol)
            if r and r["signals"] > 0:
                results.append(r)
                print("Done: "+name)
        except Exception as e:
            print("Error "+name+": "+str(e))

    if not results:
        send_all("⚠️ Backtest: No results")
        return

    results.sort(key=lambda x: x["winrate"], reverse=True)
    total_w = sum(r["wins"] for r in results)
    total_l = sum(r["losses"] for r in results)
    total_t = sum(r.get("timeouts", 0) for r in results)
    total_a = sum(r.get("ambiguous", 0) for r in results)
    total = total_w + total_l + total_t + total_a
    # Match per-pair WR: exclude timeouts and ambiguous from the denominator
    decided_total = total_w + total_l
    overall_wr = round(total_w / decided_total * 100, 1) if decided_total > 0 else 0
    overall_R = sum(r["total_R"] for r in results)

    lines = ["📊 WEEKLY BACKTEST REPORT\n🕔 " + now + " | Last 90 days\n"]
    r_sign = "+" if overall_R >= 0 else ""
    lines.append("📈 Overall Win Rate: " + str(overall_wr) + "%")
    lines.append("✅ " + str(total_w) + "W  ❌ " + str(total_l) + "L  ⏳ " + str(total_t) + "T  ❓ " + str(total_a) + "A")
    lines.append("💰 Net R: " + r_sign + str(round(overall_R, 2)) + "R\n")

    for r in results:
        emoji = "🟢" if r["winrate"] >= 45 else "🟡" if r["winrate"] >= 35 else "🔴"
        r_str = "+" if r["total_R"] > 0 else ""
        timeout_str = ("/" + str(r.get("timeouts", 0)) + "T") if r.get("timeouts", 0) else ""
        ambiguous_str = ("/" + str(r.get("ambiguous", 0)) + "A") if r.get("ambiguous", 0) else ""
        lines.append(emoji + " " + r["name"] + ": " + str(r["winrate"]) + "% (" + str(r["wins"]) + "W/" + str(r["losses"]) + "L" + timeout_str + ambiguous_str + ") | " + r_str + str(r["total_R"]) + "R")

    best = results[0]
    lines.append("\n🏆 Best pair: " + best["name"] + " (" + str(best["winrate"]) + "% | " + str(best["signals"]) + " signals)")
    lines.append("Strategy: Pullback to EMA20 + confirmation | 1H | R:R set per pair (1.2-1.75)")

    send_all("\n".join(lines))
    print("Backtest report sent!")

    try:
        with open(JOURNAL_FILE) as f:
            journal_entries = json.load(f)
    except (json.JSONDecodeError, ValueError, OSError, FileNotFoundError) as e:
        print(f"journal load error for equity chart: {e}")
        journal_entries = []
    if journal_entries and chart is not None:
        try:
            equity_path = chart.make_equity_chart(journal_entries, rr=RR)
            send_channel_photo(equity_path, caption="📈 Equity curve — all closed trades to date")
        except Exception as chart_err:
            print(f"equity chart error: {chart_err}")


def main():
    print("Backtest bot started (pullback strategy, USD/CAD + Oil/USD + NZD/USD + BTC/USD + SOL/USD)...")
    sent_this_week = ""
    while True:
        try:
            tz = pytz.timezone("Europe/Athens")
            now = datetime.now(tz)
            week = now.strftime("%Y-%W")
            if now.weekday() == 6 and now.hour == 20 and now.minute < 10 and sent_this_week != week:
                # Mark done BEFORE running so a partial failure inside run_backtest()
                # doesn't cause a second run (and duplicate send) on the next loop tick.
                sent_this_week = week
                print("Running backtest...")
                run_backtest()
        except Exception as e:
            print("Error: "+str(e))
        time.sleep(300)


if __name__ == "__main__":
    main()
