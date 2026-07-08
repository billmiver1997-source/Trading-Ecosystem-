"""Generate annotated candlestick chart images for signal and result messages.

Shared by signal_strategy.py (entry chart) and performance_tracker.py (result chart).
Not a real TradingView screenshot — rendered from the same yfinance OHLC data the
strategy already trades on, with EMA20/50/200 + entry/SL/TP levels drawn on top.
"""
import os
import warnings
warnings.filterwarnings("ignore")
from datetime import datetime
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mplfinance as mpf
import yfinance as yf

CHARTS_DIR = os.getenv("CHARTS_DIR", "/root/tradingbot/charts")

_STYLE = mpf.make_mpf_style(
    base_mpf_style="nightclouds",
    marketcolors=mpf.make_marketcolors(
        up="#26a69a", down="#ef5350", edge="inherit", wick="inherit", volume="in",
    ),
    facecolor="#131722", figcolor="#131722", gridcolor="#2a2e39", gridstyle="--",
    rc={"axes.labelcolor": "#d1d4dc", "xtick.color": "#d1d4dc", "ytick.color": "#d1d4dc"},
)


def _fetch(symbol, period="7d"):
    df = yf.Ticker(symbol).history(period=period, interval="1h")
    if df is None or df.empty:
        return None
    df = df[["Open", "High", "Low", "Close"]]
    df.index = df.index.tz_localize(None) if df.index.tz is not None else df.index
    return df


def make_signal_chart(name, symbol, bias, entry, sl, tp, zone_low=None, zone_high=None):
    """Chart for the moment a signal fires: recent candles + EMAs + entry/SL/TP levels."""
    df = _fetch(symbol, period="7d")
    if df is None or len(df) < 30:
        return None
    df = df.iloc[-70:]

    close = df["Close"]
    addplots = [
        mpf.make_addplot(close.ewm(span=20).mean(), color="#2962ff", width=1.0),
        mpf.make_addplot(close.ewm(span=50).mean(), color="#ff6d00", width=1.0),
        mpf.make_addplot(close.ewm(span=200).mean(), color="#9e9e9e", width=1.0),
    ]

    hlines = dict(
        hlines=[entry, sl, tp],
        colors=["#e0e0e0", "#ef5350", "#26a69a"],
        linestyle="dashed", linewidths=1.2,
    )

    action = "BUY" if bias == "BULLISH" else "SELL"
    title = f"{name}  {action}  |  Entry {round(entry,5)}  SL {round(sl,5)}  TP {round(tp,5)}"

    os.makedirs(CHARTS_DIR, exist_ok=True)
    out_path = os.path.join(CHARTS_DIR, f"signal_{name.replace('/', '')}.png")
    try:
        fig, axes = mpf.plot(
            df, type="candle", style=_STYLE, addplot=addplots, hlines=hlines,
            title=title, figsize=(10, 6), returnfig=True, tight_layout=True,
        )
        fig.savefig(out_path, dpi=130)
        plt.close(fig)
        return out_path
    except Exception as e:
        print(f"make_signal_chart error {name}: {e}")
        return None


def make_result_chart(name, symbol, signal, entry, sl, tp, entry_time, result_label):
    """Chart for a closed trade: candles from entry to now, showing the full path to TP/SL."""
    df = _fetch(symbol, period="7d")
    if df is None or len(df) < 5:
        return None

    # Compare against a plain python datetime rather than a numpy/pandas Timestamp —
    # df.index's datetime64 resolution varies across pandas versions (e.g. pandas 3.x
    # defaults differently than 2.x) and searchsorted() with a mismatched-unit
    # Timestamp raises "Cannot losslessly convert units" on some of those versions.
    entry_dt = datetime.utcfromtimestamp(entry_time)
    # Pad a few candles before entry for context, keep everything after through to now
    idx_pos = int((df.index <= entry_dt).sum())
    start = max(0, idx_pos - 10)
    df = df.iloc[start:]
    if len(df) < 3:
        return None

    close = df["Close"]
    addplots = [
        mpf.make_addplot(close.ewm(span=20).mean(), color="#2962ff", width=1.0),
        mpf.make_addplot(close.ewm(span=50).mean(), color="#ff6d00", width=1.0),
    ]

    exit_price = tp if result_label == "WIN" else (entry if result_label == "BE" else sl)
    exit_color = "#26a69a" if result_label == "WIN" else ("#ffb300" if result_label == "BE" else "#ef5350")

    hlines = dict(
        hlines=[entry, sl, tp],
        colors=["#e0e0e0", "#ef5350", "#26a69a"],
        linestyle="dashed", linewidths=1.0,
    )

    label = {"WIN": "TP HIT", "LOSS": "SL HIT", "BE": "BREAKEVEN"}.get(result_label, result_label)
    title = f"{name}  {signal}  |  Entry {round(entry,5)}  →  {label} {round(exit_price,5)}"

    os.makedirs(CHARTS_DIR, exist_ok=True)
    out_path = os.path.join(CHARTS_DIR, f"result_{name.replace('/', '')}_{int(entry_time)}.png")
    try:
        fig, axes = mpf.plot(
            df, type="candle", style=_STYLE, addplot=addplots, hlines=hlines,
            title=title, figsize=(10, 6), returnfig=True, tight_layout=True,
        )
        axes[0].axhline(exit_price, color=exit_color, linewidth=1.6)
        fig.savefig(out_path, dpi=130)
        plt.close(fig)
        return out_path
    except Exception as e:
        print(f"make_result_chart error {name}: {e}")
        return None
