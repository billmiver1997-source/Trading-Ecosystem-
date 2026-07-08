"""Generate annotated candlestick chart images for signal and result messages.

Shared by signal_strategy.py (entry chart) and performance_tracker.py (result chart).
Not a real TradingView screenshot — rendered from the same yfinance OHLC data the
strategy already trades on, with EMA20/50/200, nearest support/resistance, and
entry/SL/TP levels drawn on top.
"""
import os
import warnings
warnings.filterwarnings("ignore")
from datetime import datetime, timezone
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

ENTRY_COLOR = "#e0e0e0"
SL_COLOR = "#ef5350"
TP_COLOR = "#26a69a"
SR_COLOR = "#ba68c8"


def _fetch(symbol, period="7d"):
    df = yf.Ticker(symbol).history(period=period, interval="1h")
    if df is None or df.empty:
        return None
    df = df[["Open", "High", "Low", "Close"]]
    df.index = df.index.tz_localize(None) if df.index.tz is not None else df.index
    return df


def _swing_points(df, window=4):
    """Local pivot highs/lows — a candle whose high/low is the extreme within a
    window on both sides. Far more meaningful than the single nearest wick,
    which is often just noise a couple of pips from the current price."""
    highs = df["High"]; lows = df["Low"]
    swing_highs, swing_lows = [], []
    for i in range(window, len(df) - window):
        seg_h = highs.iloc[i - window:i + window + 1]
        seg_l = lows.iloc[i - window:i + window + 1]
        if highs.iloc[i] == seg_h.max():
            swing_highs.append(highs.iloc[i])
        if lows.iloc[i] == seg_l.min():
            swing_lows.append(lows.iloc[i])
    return swing_highs, swing_lows


def _nearest_sr(df, price, window=4, min_dist_pct=0.0015):
    """Nearest genuine swing high above price / swing low below price, each
    required to sit at least ~0.15% away so a level essentially equal to the
    entry price (pure noise) never gets drawn as if it were a real zone."""
    swing_highs, swing_lows = _swing_points(df, window)
    above = [h for h in swing_highs if h > price * (1 + min_dist_pct)]
    below = [l for l in swing_lows if l < price * (1 - min_dist_pct)]
    resistance = float(min(above)) if above else None
    support = float(max(below)) if below else None
    return support, resistance


def _apply_levels(ax, df, entry, sl, tp, support, resistance):
    """Draw entry/SL/TP + support/resistance as full-width lines with right-edge
    labels, and widen the y/x limits so every level is guaranteed to be visible —
    the previous version let mplfinance auto-scale to candle data only, which
    silently clipped SL/TP off-screen whenever they sat outside the recent range."""
    n = len(df)
    values = [df["Low"].min(), df["High"].max(), entry, sl, tp]
    if support is not None:
        values.append(support)
    if resistance is not None:
        values.append(resistance)
    lo, hi = min(values), max(values)
    pad = (hi - lo) * 0.15 if hi > lo else abs(hi) * 0.01 or 1
    lo, hi = lo - pad, hi + pad
    ax.set_ylim(lo, hi)
    ax.set_xlim(-1, n + 9)

    levels = []
    if support is not None:
        ax.axhline(support, color=SR_COLOR, linestyle="dotted", linewidth=1.1, alpha=0.8)
        levels.append((support, "SUPPORT", SR_COLOR))
    if resistance is not None:
        ax.axhline(resistance, color=SR_COLOR, linestyle="dotted", linewidth=1.1, alpha=0.8)
        levels.append((resistance, "RESIST", SR_COLOR))
    ax.axhline(entry, color=ENTRY_COLOR, linestyle="dashed", linewidth=1.3)
    levels.append((entry, "ENTRY", ENTRY_COLOR))
    ax.axhline(sl, color=SL_COLOR, linestyle="dashed", linewidth=1.3)
    levels.append((sl, "SL", SL_COLOR))
    ax.axhline(tp, color=TP_COLOR, linestyle="dashed", linewidth=1.3)
    levels.append((tp, "TP", TP_COLOR))

    # Push apart labels that would otherwise overlap (e.g. a support/resistance
    # level sitting almost exactly at the entry price).
    min_gap = (hi - lo) * 0.045
    levels.sort(key=lambda t: t[0])
    adjusted = []
    for y, text, color in levels:
        if adjusted and y - adjusted[-1][0] < min_gap:
            y = adjusted[-1][0] + min_gap
        adjusted.append((y, text, color))
    for y, text, color in adjusted:
        ax.text(n + 0.6, y, text, color=color, fontsize=9, fontweight="bold",
                 va="center", ha="left",
                 bbox=dict(boxstyle="round,pad=0.2", facecolor="#131722", edgecolor=color, linewidth=1))


def make_signal_chart(name, symbol, bias, entry, sl, tp, zone_low=None, zone_high=None):
    """Chart for the moment a signal fires: recent candles + EMAs + S/R + entry/SL/TP."""
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

    support, resistance = _nearest_sr(df, entry)

    action = "BUY" if bias == "BULLISH" else "SELL"
    title = f"{name}  {action}  |  Entry {round(entry,5)}  SL {round(sl,5)}  TP {round(tp,5)}"

    os.makedirs(CHARTS_DIR, exist_ok=True)
    out_path = os.path.join(CHARTS_DIR, f"signal_{name.replace('/', '')}.png")
    try:
        fig, axes = mpf.plot(
            df, type="candle", style=_STYLE, addplot=addplots,
            title=title, figsize=(10, 6), returnfig=True, tight_layout=True,
        )
        _apply_levels(axes[0], df, entry, sl, tp, support, resistance)
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
    entry_dt = datetime.fromtimestamp(entry_time, tz=timezone.utc).replace(tzinfo=None)
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

    support, resistance = _nearest_sr(df, entry)

    exit_price = tp if result_label == "WIN" else (entry if result_label == "BE" else sl)
    exit_color = TP_COLOR if result_label == "WIN" else ("#ffb300" if result_label == "BE" else SL_COLOR)

    label = {"WIN": "TP HIT", "LOSS": "SL HIT", "BE": "BREAKEVEN"}.get(result_label, result_label)
    title = f"{name}  {signal}  |  Entry {round(entry,5)}  →  {label} {round(exit_price,5)}"

    os.makedirs(CHARTS_DIR, exist_ok=True)
    out_path = os.path.join(CHARTS_DIR, f"result_{name.replace('/', '')}_{int(entry_time)}.png")
    try:
        fig, axes = mpf.plot(
            df, type="candle", style=_STYLE, addplot=addplots,
            title=title, figsize=(10, 6), returnfig=True, tight_layout=True,
        )
        # Drawn before _apply_levels' labels so the thick exit marker never
        # paints over the ENTRY/SL/TP text (it sits at the same y as one of them).
        axes[0].axhline(exit_price, color=exit_color, linewidth=2.0, zorder=1)
        _apply_levels(axes[0], df, entry, sl, tp, support, resistance)
        fig.savefig(out_path, dpi=130)
        plt.close(fig)
        return out_path
    except Exception as e:
        print(f"make_result_chart error {name}: {e}")
        return None
