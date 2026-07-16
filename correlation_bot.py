"""Daily cross-asset correlation heatmap — helps traders see which pairs are
moving together (correlation risk on "diversified" positions) or diverging
(a genuine hedge). Posted once a day to the news channel.
"""
import os
from dotenv import load_dotenv
load_dotenv("/root/tradingbot/.env")

import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pandas as pd
import yfinance as yf
import pytz
from datetime import datetime
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN_SIGNAL")
CHANNEL_ID = os.getenv("TELEGRAM_NEWS_CHANNEL")
if not TELEGRAM_TOKEN or not CHANNEL_ID:
    raise RuntimeError("TELEGRAM_TOKEN_SIGNAL and TELEGRAM_NEWS_CHANNEL must be set in .env")

SENT_STATE_FILE = "/root/tradingbot/sent_state_correlation.json"
_YF_EXECUTOR = ThreadPoolExecutor(max_workers=4)


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
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, SENT_STATE_FILE)
    except Exception as e:
        print(f"save sent state error: {e}")

CHARTS_DIR = os.getenv("CHARTS_DIR", "/root/tradingbot/charts")

PAIRS = {
    "EUR/USD": "EURUSD=X", "GBP/USD": "GBPUSD=X", "USD/JPY": "USDJPY=X",
    "AUD/USD": "AUDUSD=X", "USD/CAD": "USDCAD=X", "XAU/USD": "GC=F",
    "Oil/USD": "CL=F", "BTC/USD": "BTC-USD", "DXY": "DX-Y.NYB",
}

SEND_HOUR = 9  # Athens time — after the 08:00 news brief, before London fully opens

# Diverging blue<->red, neutral gray receding toward the dark chart background,
# per the dataviz skill's diverging-pair guidance (blue/red poles, gray midpoint,
# monotone lightness per arm — not the categorical CVD check, which doesn't apply
# to a sequential/diverging ramp).
_CMAP = LinearSegmentedColormap.from_list(
    "corr_diverging",
    [(0.0, "#1565c0"), (0.25, "#5c8fc9"), (0.5, "#383a42"), (0.75, "#d2695f"), (1.0, "#e0483d")],
)


def build_correlation_matrix(lookback_days=30):
    closes = {}
    for name, symbol in PAIRS.items():
        try:
            df = _YF_EXECUTOR.submit(yf.Ticker(symbol).history, period=f"{lookback_days + 10}d", interval="1d").result(timeout=20)
            if len(df) < lookback_days // 2:
                continue
            series = df["Close"].pct_change().dropna()
            # FX ("=X"), futures ("=F"), and crypto tickers each carry their own
            # exchange timezone in the index — combining them without normalizing
            # to date-only left almost every cross-asset pair correlation as NaN
            # (pandas aligns on the exact timestamp, not the calendar day).
            series.index = series.index.tz_localize(None).normalize() if series.index.tz is not None else series.index.normalize()
            closes[name] = series.iloc[-lookback_days:]
        except Exception as e:
            print(f"correlation fetch error {name}: {e}")
    if len(closes) < 2:
        return None
    # Use "any" so all pairs are correlated over the exact same date range;
    # "all" keeps rows where some markets are closed, making correlations incomparable.
    returns = pd.DataFrame(closes).dropna(how="any")
    return returns.corr()


def make_correlation_chart(corr):
    n = len(corr)
    labels = list(corr.columns)
    fig, ax = plt.subplots(figsize=(9, 8), facecolor="#131722")
    ax.set_facecolor("#131722")

    im = ax.imshow(corr.values, cmap=_CMAP, vmin=-1, vmax=1)

    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels(labels, rotation=45, ha="right", color="#d1d4dc", fontsize=10)
    ax.set_yticklabels(labels, color="#d1d4dc", fontsize=10)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(length=0)

    # Thin surface-colored gaps between cells, per mark spec guidance
    ax.set_xticks(np.arange(n + 1) - 0.5, minor=True)
    ax.set_yticks(np.arange(n + 1) - 0.5, minor=True)
    ax.grid(which="minor", color="#131722", linewidth=3)

    for i in range(n):
        for j in range(n):
            val = corr.values[i, j]
            ax.text(j, i, f"{val:.2f}", ha="center", va="center",
                     color="#ffffff", fontsize=9, fontweight="bold")

    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.ax.tick_params(colors="#d1d4dc")
    cbar.outline.set_visible(False)
    cbar.set_label("Correlation", color="#d1d4dc")

    tz = pytz.timezone("Europe/Athens")
    now = datetime.now(tz).strftime("%d/%m/%Y")
    ax.set_title(f"Cross-Asset Correlation — 30d  |  {now}", color="#e0e0e0", fontsize=13, fontweight="bold", pad=14)

    os.makedirs(CHARTS_DIR, exist_ok=True)
    out_path = os.path.join(CHARTS_DIR, "correlation_heatmap.png")
    try:
        plt.tight_layout()
        fig.savefig(out_path, dpi=130, facecolor="#131722")
        plt.close(fig)
        return out_path
    except Exception as e:
        print(f"make_correlation_chart error: {e}")
        plt.close(fig)
        return None


def send_channel_photo(photo_path, caption=""):
    if not photo_path or not os.path.exists(photo_path):
        return
    try:
        with open(photo_path, "rb") as pf:
            r = requests.post(
                "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendPhoto",
                files={"photo": ("correlation.png", pf, "image/png")},
                data={"chat_id": CHANNEL_ID, "caption": caption[:1024]}, timeout=20,
            )
        r.raise_for_status()
        print("Correlation heatmap sent!")
    except Exception as e:
        print(f"send_channel_photo error: {e}")
    finally:
        try:
            os.remove(photo_path)
        except OSError as e:
            print(f"Failed to delete chart {photo_path}: {e}")


def run_once():
    corr = build_correlation_matrix()
    if corr is None:
        print("Not enough data for correlation matrix")
        return
    path = make_correlation_chart(corr)
    send_channel_photo(path, caption="\U0001f9ea DAILY CORRELATION HEATMAP\n\n30-day cross-asset correlation — helps spot hidden concentration risk (or a genuine hedge) across open positions.")


def main():
    print("Correlation bot started...")
    sent_today = _load_sent_day()
    while True:
        try:
            tz = pytz.timezone("Europe/Athens")
            now = datetime.now(tz)
            today = now.strftime("%Y-%m-%d")
            if now.hour == SEND_HOUR and now.minute < 10 and sent_today != today:
                # Marked before running (partial-failure guard) AND persisted to disk
                # so a restart inside this window can't re-trigger a duplicate send.
                sent_today = today
                _save_sent_day(today)
                print("Running daily correlation heatmap...")
                run_once()
        except Exception as e:
            print(f"Main error: {e}")
        time.sleep(300)


if __name__ == "__main__":
    main()
