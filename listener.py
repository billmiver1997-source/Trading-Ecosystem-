import os
from dotenv import load_dotenv
load_dotenv("/root/tradingbot/.env")

import fcntl
import random
import requests
import feedparser
import json
import time
import pandas as pd
import yfinance as yf
import anthropic
import pytz
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN_SIGNAL")
if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN_SIGNAL is not set in environment")
USERS_FILE = "/root/tradingbot/users.json"
PROFILES_FILE = "/root/tradingbot/user_profiles.json"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OWNER_ID = os.getenv("OWNER_ID", "8626233751")

if not ANTHROPIC_API_KEY:
    print("Warning: ANTHROPIC_API_KEY not set — AI features (analysis, news) will be unavailable")

_anthropic_client = None
_anthropic_lock = Lock()
_analysis_cache = {}  # pair_name -> (timestamp, result_text)
_analysis_cache_lock = Lock()
_ANALYSIS_TTL = 900   # 15 minutes

def _get_anthropic():
    global _anthropic_client
    with _anthropic_lock:
        if _anthropic_client is None:
            _anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        return _anthropic_client

SYMBOLS = {
    "USD/CHF": "USDCHF=X", "AUD/USD": "AUDUSD=X", "EUR/USD": "EURUSD=X",
    "EUR/CHF": "EURCHF=X", "GBP/USD": "GBPUSD=X", "USD/CAD": "USDCAD=X",
    "NZD/USD": "NZDUSD=X", "XAU/USD": "GC=F", "Silver/USD": "SI=F",
    "Copper/USD": "HG=F", "Oil/USD": "CL=F", "BTC/USD": "BTC-USD",
    "SOL/USD": "SOL-USD", "DXY": "DX-Y.NYB",
    "USD/JPY": "USDJPY=X",
}

ALIASES = {
    "eurusd": "EUR/USD", "gbpusd": "GBP/USD", "xauusd": "XAU/USD",
    "gold": "XAU/USD", "btc": "BTC/USD", "bitcoin": "BTC/USD",
    "sol": "SOL/USD", "oil": "Oil/USD", "silver": "Silver/USD",
    "copper": "Copper/USD", "dxy": "DXY", "usdchf": "USD/CHF",
    "audusd": "AUD/USD", "usdcad": "USD/CAD", "nzdusd": "NZD/USD",
    "eurchf": "EUR/CHF", "gbp": "GBP/USD", "eur": "EUR/USD",
    "xau": "XAU/USD", "btcusd": "BTC/USD", "solusd": "SOL/USD",
    "usdjpy": "USD/JPY", "jpy": "USD/JPY",
    "🇯🇵 usd/jpy": "USD/JPY", "🇳🇿 nzd/usd": "NZD/USD",
    "chf": "USD/CHF"
}

WELCOME = (
    "\U0001f4c8 Welcome to Trading Nova Signal\n\n"
    "This is your trading command centre. Live signals, AI analysis, market sentiment, news, risk tools \u2014 all in one place.\n\n"
    "Signals cover 12 instruments:\n"
    "\U0001fa99 XAU/USD \u2022 \U0001f1ea\U0001f1fa EUR/USD \u2022 \U0001f1ec\U0001f1e7 GBP/USD\n"
    "\U0001f7e1 BTC/USD \u2022 \U0001f535 SOL/USD \u2022 \u26fd Oil/USD\n"
    "USD/JPY \u2022 USD/CHF \u2022 AUD/USD \u2022 USD/CAD \u2022 NZD/USD \u2022 Silver\n\n"
    "Signals are sent only when a high-quality setup is confirmed \u2014 not on a fixed schedule, not for the sake of activity.\n\n"
    "Use the menu below to explore what's available \U0001f447\n\n"
    "\u26a0\ufe0f All signals and content are for educational purposes only. Not financial advice. "
    "Trading involves substantial risk of loss. Never risk more than you can afford to lose."
)

def load_users():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError, OSError) as e:
            print(f"load_users JSON error: {e}")
    return []

def save_users(users):
    tmp = USERS_FILE + '.tmp'
    try:
        with open(tmp, 'w') as f:
            json.dump(users, f)
        os.replace(tmp, USERS_FILE)
    except Exception as e:
        print(f"save_users error: {e}")

def load_profiles():
    if os.path.exists(PROFILES_FILE):
        try:
            with open(PROFILES_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError, OSError) as e:
            print(f"load_profiles error: {e}")
    return {}

def save_profile(user_id, username, first_name):
    lock_path = PROFILES_FILE + '.lock'
    with open(lock_path, 'a') as _lf:
        fcntl.flock(_lf, fcntl.LOCK_EX)
        try:
            profiles = load_profiles()
            if str(user_id) not in profiles:
                tz = pytz.timezone("Europe/Athens")
                profiles[str(user_id)] = {
                    "username": username or "",
                    "first_name": first_name or "",
                    "joined": datetime.now(tz).strftime("%d/%m/%Y %H:%M")
                }
                tmp = PROFILES_FILE + '.tmp'
                try:
                    with open(tmp, 'w') as f:
                        json.dump(profiles, f)
                    os.replace(tmp, PROFILES_FILE)
                except Exception as e:
                    print(f"save_profile error: {e}")
        finally:
            fcntl.flock(_lf, fcntl.LOCK_UN)

PERSONAL_JOURNAL_FILE = "/root/tradingbot/personal_journal.json"

def _load_personal_journal():
    if os.path.exists(PERSONAL_JOURNAL_FILE):
        try:
            with open(PERSONAL_JOURNAL_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError, OSError) as e:
            print(f"load_personal_journal error: {e}")
    return {}

def _update_personal_journal(chat_id_str, mutate_fn):
    """Load-modify-save under an exclusive lock. mutate_fn receives this user's
    {"open": [...], "closed": [...]} dict and mutates it in place."""
    lock_path = PERSONAL_JOURNAL_FILE + '.lock'
    with open(lock_path, 'a') as _lf:
        fcntl.flock(_lf, fcntl.LOCK_EX)
        try:
            journal = _load_personal_journal()
            user_entry = journal.setdefault(chat_id_str, {"open": [], "closed": []})
            mutate_fn(user_entry)
            tmp = PERSONAL_JOURNAL_FILE + '.tmp'
            with open(tmp, 'w') as f:
                json.dump(journal, f)
            os.replace(tmp, PERSONAL_JOURNAL_FILE)
        except Exception as e:
            print(f"update_personal_journal error: {e}")
        finally:
            fcntl.flock(_lf, fcntl.LOCK_UN)

def answer_callback(callback_id):
    try:
        requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/answerCallbackQuery",
            json={"callback_query_id": callback_id}, timeout=5)
    except Exception as e:
        print(f"answer_callback error: {e}")

def get_updates(offset=None):
    params = {"timeout": 30}
    if offset is not None:  # 0 is a valid offset — do not treat it as falsy
        params["offset"] = offset
    try:
        r = requests.get("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/getUpdates", params=params, timeout=35)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"get_updates error: {e}")
        # Sleep before returning so a network outage doesn't spin the main loop at full speed
        time.sleep(5)
        return {"result": []}

def send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text[:4096]}
    if reply_markup:
        # Pass dict directly — requests json= serialises the whole payload, so do NOT json.dumps here
        payload["reply_markup"] = reply_markup
    try:
        r = requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendMessage", json=payload, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"send_message error to {chat_id}: {e}")

def send_typing(chat_id):
    try:
        requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendChatAction",
            json={"chat_id": chat_id, "action": "typing"}, timeout=5)
    except Exception as e:
        print(f"send_typing error: {e}")

def main_menu():
    return {
        "keyboard": [
            [{"text": "📊 Analysis"}, {"text": "🧠 Sentiment"}],
            [{"text": "📅 Calendar"}, {"text": "📋 Status"}],
            [{"text": "🧮 Risk Calculator"}, {"text": "💥 Volatility Alert"}],
            [{"text": "💼 Portfolio"}, {"text": "📓 Trade Journal"}],
            [{"text": "📝 My Trades"}, {"text": "📜 Signal History"}],
            [{"text": "📍 S&R Levels"}],
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False,
        "input_field_placeholder": "Choose an option..."
    }
def pairs_menu():
    return {
        "keyboard": [
            [{"text": "\U0001f1ea\U0001f1fa EUR/USD"}, {"text": "\U0001f1ec\U0001f1e7 GBP/USD"}],
            [{"text": "\U0001fa99 XAU/USD"}, {"text": "\U0001f7e1 BTC/USD"}],
            [{"text": "\U0001f535 SOL/USD"}, {"text": "\u26fd Oil/USD"}],
            [{"text": "\U0001f1fa\U0001f1f8 USD/CHF"}, {"text": "\U0001f1e6\U0001f1fa AUD/USD"}],
            [{"text": "\U0001f1e8\U0001f1e6 USD/CAD"}, {"text": "🥈 Silver/USD"}],
            [{"text": "🟠 Copper/USD"}, {"text": "🇯🇵 USD/JPY"}],
            [{"text": "🇳🇿 NZD/USD"}],
            [{"text": "\U0001f519 Back to Menu"}],
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False,
        "input_field_placeholder": "Choose an option..."
    }

def links_menu():
    return {
        "inline_keyboard": [
            [{"text": "\U0001f4f2 Telegram Group", "url": "https://t.me/tradingNovaNews"}],
            [{"text": "\U0001f4b9 Equiti Global", "url": "https://equiti.com"}],
            [{"text": "\U0001f4b0 PU Prime", "url": "https://puprime.com"}],
            [{"text": "\U0001f3a6 TikTok", "url": "https://tiktok.com"}],
            [{"text": "\U0001f4f7 Instagram", "url": "https://instagram.com"}],
            [{"text": "\U0001f426 X (Twitter)", "url": "https://x.com"}],
        ]
    }

def get_analysis(pair_name):
    with _analysis_cache_lock:
        cached = _analysis_cache.get(pair_name)
        if cached and time.time() - cached[0] < _ANALYSIS_TTL:
            return cached[1] + "\n\n🕐 Cached result (< 15 min old)"
    # Fetch outside lock so concurrent requests for different pairs don't serialize
    result = _fetch_analysis(pair_name)
    with _analysis_cache_lock:
        _analysis_cache[pair_name] = (time.time(), result)
    return result

def _fetch_analysis(pair_name):
    symbol = SYMBOLS.get(pair_name)
    if not symbol:
        return "Pair not found."
    try:
        df = yf.Ticker(symbol).history(period="5d", interval="15m")
        if len(df) < 50:
            return "Not enough data."
        close = df["Close"]
        high = df["High"]
        low = df["Low"]
        ema20 = close.ewm(span=20).mean().iloc[-1]
        ema50 = close.ewm(span=50).mean().iloc[-1]
        delta = close.diff()
        # Wilder's EMA (com=13) matches charting platforms; simple rolling() diverges in trends
        gain = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
        loss = loss.replace(0, 1e-10)  # prevent NaN RSI on all-flat windows
        rsi = (100 - (100 / (1 + gain / loss))).iloc[-1]
        prev_close = close.shift(1)
        true_range = pd.concat([high-low, (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
        atr = true_range.rolling(14).mean().iloc[-1]
        price = close.iloc[-1]
        bb_mid = close.rolling(20).mean().iloc[-1]
        bb_std = close.rolling(20).std().iloc[-1]
        bb_upper = bb_mid + 2 * bb_std
        bb_lower = bb_mid - 2 * bb_std
        macd_line = close.ewm(span=12).mean() - close.ewm(span=26).mean()
        macd = macd_line.iloc[-1]
        macd_sig = macd_line.ewm(span=9).mean().iloc[-1]
        atr_pct = round((atr / price) * 100, 3)

        client = _get_anthropic()
        system_prompt = "You are a professional forex and commodities analyst. Respond in plain text only — no markdown, no asterisks. Always include a specific numeric ENTRY, SL, and TP. Use emojis sparingly."
        analysis_styles = [
            "Give a complete analysis of {pair} on the 15-minute timeframe. Cover: market bias, key levels, momentum, and a clear trade idea (BUY/SELL/WAIT) with entry, SL, and TP. Be direct and specific.",
            "Review {pair} live. Start with what the chart is telling you right now. Then: is there a trade here? If yes — entry, SL, TP and why. If no — what to wait for. Write like you're talking to a fellow trader.",
            "For {pair}: what is the dominant trend, what are the key levels price is reacting to, and what is your trade recommendation? Give exact levels. Include a risk note at the end. Confident, concise.",
            "Analyze {pair} and give your honest read: trend, momentum, key zone to watch. Then one clear recommendation: BUY / SELL / WAIT — with levels and reasoning. Don't hedge. Be direct.",
        ]
        style = random.choice(analysis_styles).format(pair=pair_name)
        data_context = (
            "\n\nLive data (15m timeframe, 5-day window):\n"
            "Price: "+str(round(price,5))+"\n"
            "EMA20: "+str(round(ema20,5))+" | EMA50: "+str(round(ema50,5))+"\n"
            "RSI: "+str(round(rsi,1))+" | MACD: "+str(round(macd,5))+" | Signal: "+str(round(macd_sig,5))+"\n"
            "ATR: "+str(round(atr,5))+" ("+str(atr_pct)+"% of price)\n"
            "Bollinger Bands: "+str(round(bb_lower,5))+" / "+str(round(bb_upper,5))+"\n"
            "5D High: "+str(round(high.max(),5))+" | 5D Low: "+str(round(low.min(),5))
        )
        prompt = style + data_context
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            system=system_prompt,
            messages=[{"role":"user","content":prompt}]
        )
        tz = pytz.timezone("Europe/Athens")
        now = datetime.now(tz).strftime("%d/%m/%Y %H:%M")
        return pair_name+" | "+now+"\n\n"+message.content[0].text
    except Exception as e:
        print(f"get_analysis error ({pair_name}): {e}")
        return "Analysis temporarily unavailable. Please try again."

def get_sentiment():
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        r.raise_for_status()
        data = r.json()["data"][0]
        value = int(data["value"])
        classification = data["value_classification"]
        if value >= 75: emoji = "\U0001f7e2"
        elif value >= 55: emoji = "\U0001f7e1"
        elif value >= 45: emoji = "\U0001f7e0"
        else: emoji = "\U0001f534"
        bar = "\u2588"*(value//10)+"\u2591"*(10-value//10)
        return "\U0001f9e0 MARKET SENTIMENT\n\nCrypto Fear & Greed:\n"+emoji+" "+str(value)+"/100 - "+classification+"\n["+bar+"]"
    except Exception as e:
        print(f"get_sentiment error: {e}")
        return "Sentiment data unavailable."

def get_status():
    trades_file = "/root/tradingbot/open_trades.json"
    stats_file = "/root/tradingbot/trade_stats.json"
    trades = []
    stats = {"wins":0,"losses":0}
    if os.path.exists(trades_file):
        try:
            with open(trades_file) as f:
                trades = json.load(f)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"get_status trades JSON error: {e}")
    if os.path.exists(stats_file):
        try:
            with open(stats_file) as f:
                stats = json.load(f)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"get_status stats JSON error: {e}")
    total = stats.get("wins",0)+stats.get("losses",0)
    wr = round((stats.get("wins",0)/total)*100,1) if total > 0 else 0
    tz = pytz.timezone("Europe/Athens")
    now = datetime.now(tz).strftime("%d/%m/%Y %H:%M")
    lines = ["\U0001f4ca TRADING STATUS | "+now+"\n"]
    if trades:
        lines.append("\U0001f4cc Open Trades ("+str(len(trades))+"):")
        for t in trades:
            try:
                lines.append("- "+t["name"]+" "+t["signal"]+" @ "+str(round(t["entry"],4)))
            except (KeyError, TypeError) as e:
                print(f"get_status trade format error: {e}")
                lines.append("- [malformed trade entry]")
    else:
        lines.append("No open trades right now.")
    lines.append("\n\U0001f4ca Stats: "+str(stats.get("wins",0))+"W / "+str(stats.get("losses",0))+"L | WR: "+str(wr)+"%")
    return "\n".join(lines)

def set_commands():
    try:
        r = requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/setMyCommands", timeout=10, json={
            "commands": [
                {"command": "start", "description": "Start & main menu"},
                {"command": "analysis", "description": "Get analysis: /analysis EURUSD"},
                {"command": "sentiment", "description": "Market sentiment"},
                {"command": "status", "description": "Trading status & open trades"},
                {"command": "links", "description": "Our social links"},
                {"command": "stats", "description": "Bot statistics (admin only)"},
                {"command": "news", "description": "Latest market headlines"},
                {"command": "calendar", "description": "Economic calendar today"},
                {"command": "journal", "description": "Trade journal"},
                {"command": "portfolio", "description": "Open signals P&L"},
                {"command": "mytrades", "description": "Log & track your own trades"},
                {"command": "history", "description": "Signal history & stats"},
                {"command": "sr", "description": "Support & Resistance levels"},
                {"command": "risk", "description": "Risk/lot size calculator"},
                {"command": "volatility", "description": "Volatility report"},
                {"command": "mtf", "description": "Multi-timeframe analysis: /mtf EURUSD"},
                {"command": "ibtracker", "description": "IB client tracker"},
                {"command": "commission", "description": "Commission calculator"},
            ]
        })
        r.raise_for_status()
    except Exception as e:
        print(f"set_commands error: {e}")

def handle_message(chat_id, text, username, first_name=""):
    text = text.strip()
    # Strip @botname suffix that Telegram appends to commands in group chats
    if text.startswith("/") and "@" in text:
        text = text.split("@")[0]
    text_lower = text.lower()

    if text_lower in ["/start", "start"]:
        lock_path = USERS_FILE + ".lock"
        with open(lock_path, "a") as _lf:
            fcntl.flock(_lf, fcntl.LOCK_EX)
            try:
                users = load_users()
                # users.json may be a mixed list (strings from this bot, dicts from
                # main_bot.py). Normalise to string IDs before checking membership so
                # we don't append duplicate string entries for existing dict entries.
                existing_ids = {item.get("id", "") if isinstance(item, dict) else item for item in users}
                if str(chat_id) not in existing_ids:
                    users.append(str(chat_id))
                    save_users(users)
            finally:
                fcntl.flock(_lf, fcntl.LOCK_UN)
        save_profile(chat_id, username, first_name)
        send_message(chat_id, WELCOME, main_menu())

    elif text_lower == "/stats":
        if str(chat_id) == OWNER_ID:
            profiles = load_profiles()
            total = len(profiles)
            users = load_users()
            lines = ["📊 BOT STATS\n", f"👥 Unique users: {total}", f"📋 In broadcast list: {len(users)}\n", "🕐 Last 10 joined:"]
            items = list(profiles.items())[-10:]
            for uid, data in reversed(items):
                uname = "@"+data["username"] if data["username"] else data["first_name"] or f"ID:{uid}"
                lines.append(f"• {uname} | {data['joined']}")
            send_message(chat_id, "\n".join(lines), main_menu())
        else:
            send_message(chat_id, "❌ Not authorized.", main_menu())


    elif text_lower in ["/menu", "\U0001f519 back to menu"]:
        send_message(chat_id, "Main menu:", main_menu())

    elif text_lower in ["/links", "\U0001f517 links"]:
        send_message(chat_id, "Our channels & brokers:", links_menu())

    elif text_lower in ["\U0001f9e0 sentiment", "/sentiment"]:
        send_typing(chat_id)
        send_message(chat_id, get_sentiment(), main_menu())

    elif text_lower in ["\U0001f4cb status", "/status"]:
        send_message(chat_id, get_status(), main_menu())

    elif text_lower in ["📅 calendar", "/calendar"]:
        send_typing(chat_id)
        try:
            from bs4 import BeautifulSoup
            tz = pytz.timezone("Europe/Athens")
            today = datetime.now(tz).strftime("%Y-%m-%d")
            now_str = datetime.now(tz).strftime("%d/%m/%Y")
            h = {"User-Agent":"Mozilla/5.0","X-Requested-With":"XMLHttpRequest","Referer":"https://www.investing.com/economic-calendar/"}
            d = {"dateFrom":today,"dateTo":today,"importance[]":["2","3"]}
            r = requests.post("https://www.investing.com/economic-calendar/Service/getCalendarFilteredData",headers=h,data=d,timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.json().get("data",""),"html.parser")
            rows_inv = soup.find_all("tr",id=lambda x: x and x.startswith("eventRowId_"))
            events = []
            for row in rows_inv[:10]:
                try:
                    tds = row.find_all("td")
                    if len(tds) < 3: continue
                    ev_time = tds[0].text.strip()
                    currency = tds[1].text.strip()
                    ev_name = tds[3].text.strip() if len(tds)>3 else ""
                    forecast = tds[4].text.strip() if len(tds)>4 else ""
                    previous = tds[5].text.strip() if len(tds)>5 else ""
                    if currency in ["USD","EUR","GBP","JPY","CHF","AUD","CAD","NZD"]:
                        line = ev_time+" | "+currency+" | "+ev_name
                        if forecast: line += " F:"+forecast
                        if previous: line += " P:"+previous
                        events.append(line)
                except Exception as e:
                    print(f"Calendar row parse error: {e}")
                    continue
            msg = "📅 FOREX CALENDAR | "+now_str+"\n\n"
            if events:
                msg += "\n".join(["📍 "+e for e in events])
            else:
                msg += "No major forex events today."
            msg += "\n\n📊 Full calendar sent at 07:00 every morning!"
            send_message(chat_id, msg, main_menu())
        except Exception as e:
            print(f"Calendar handler error: {e}")
            send_message(chat_id, "📅 Economic calendar sent every morning at 07:00!", main_menu())
    elif text_lower in ["🌍 news", "/news"]:
        send_typing(chat_id)
        try:
            tz = pytz.timezone("Europe/Athens")
            now_str = datetime.now(tz).strftime("%d/%m/%Y %H:%M")
            keywords = ["war","attack","fed","rate","inflation","trump","tariff","oil","gold","dollar","ukraine","iran","china","russia","market","crash","rally","ceasefire","ecb","boe","sanctions"]
            headlines = []
            for feed_url in ["https://www.forexlive.com/feed/news","https://feeds.bbci.co.uk/news/world/rss.xml"]:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries[:15]:
                    title = entry.get("title","")
                    if any(k in title.lower() for k in keywords) and title not in headlines:
                        headlines.append(title)
                    if len(headlines) >= 8:
                        break
                if len(headlines) >= 8:
                    break
            if not headlines:
                send_message(chat_id, "🌍 No major market headlines right now.\n\n📰 Full coverage: @tradingNovaNews", main_menu())
                return
            client = _get_anthropic()
            news_text = "\n".join(headlines[:8])
            news_styles = [
                "You are a financial news editor for traders. Plain text, no markdown. From these headlines, pick the 5 most market-relevant stories. Write each as one punchy line with an emoji. End with one sentence on the key theme tying them together.",
                "You are a senior forex analyst. Plain text only. Pick the 3-4 most impactful headlines and explain in 2-3 lines what they mean for traders right now. Use emojis. No lists — write it as a natural briefing.",
                "You are a trading desk analyst sharing breaking news with your team. Plain text. Highlight the top stories, flag any high-impact events, and add your read on what to watch. 4-6 lines. Emojis.",
                "You are a market intelligence analyst. Plain text only. From these headlines, identify the dominant theme (geopolitical risk / central bank moves / commodity pressure / etc.) and explain the top 3-4 stories that support it. Be sharp and direct. Emojis.",
            ]
            style = random.choice(news_styles)
            headers = ["📰 LATEST NEWS", "📡 MARKET INTELLIGENCE", "🗞 BREAKING MARKET NEWS", "📊 MARKET UPDATE"]
            message = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1000,
                system=style,
                messages=[{"role":"user","content":"Headlines:\n\n"+news_text}]
            )
            send_message(chat_id, random.choice(headers)+"\n🕔 "+now_str+"\n\n"+message.content[0].text+"\n\n📰 Full coverage: @tradingNovaNews", main_menu())
        except Exception as e:
            print(f"News handler error: {e}")
            send_message(chat_id, "🌍 Latest news at @tradingNovaNews", main_menu())

    elif text_lower in ["\U0001f4ca analysis", "/analysis"]:
        send_message(chat_id, "Choose a pair:", pairs_menu())

    elif text_lower.startswith("/analysis "):
        pair_input = text_lower[len("/analysis "):].strip()
        pair_name = ALIASES.get(pair_input) or next((k for k in SYMBOLS if k.lower() == pair_input), pair_input.upper())
        send_typing(chat_id)
        send_message(chat_id, get_analysis(pair_name), main_menu())

    elif any(text_lower.replace(" ","").replace("/","") == k.replace(" ","").replace("/","") for k in ALIASES.keys()):
        normalized = text_lower.replace(" ","").replace("/","")
        # Find the original key whose normalized form matches, then look up the pair
        key = next(k for k in ALIASES.keys() if k.replace(" ","").replace("/","") == normalized)
        pair_name = ALIASES.get(key, normalized.upper())
        send_typing(chat_id)
        send_message(chat_id, get_analysis(pair_name), main_menu())

    elif any(emoji in text for emoji in ["🇪🇺","🇬🇧","🪙","🟡","🔵","⛽","🇺🇸","🇦🇺","🥈","🟠","🇯🇵","🇳🇿","🇨🇦"]):
        for k, v in ALIASES.items():
            if k in text_lower or v.lower() in text_lower:
                send_typing(chat_id)
                send_message(chat_id, get_analysis(v), main_menu())
                return
        # Emoji detected but no matching pair found — show pair picker
        send_message(chat_id, "Choose a pair:", pairs_menu())

    elif text_lower in ["🧮 risk calculator", "/risk"]:
        send_message(chat_id, "🧮 RISK CALCULATOR\n\nEnter your trade details and I'll calculate the correct lot size based on your account balance, risk percentage and stop loss distance.\n\nFormat:\n\nBALANCE: 1000\nRISK: 1\nSL PIPS: 20\nPAIR: EURUSD\n\nExample: 1% risk on a $1,000 account with a 20-pip SL on EUR/USD.", main_menu())

    elif text_lower.startswith("balance:"):
        try:
            parts = {}
            for ln in text.split("\n"):
                if ":" in ln:
                    k, v = ln.split(":", 1)
                    parts[k.strip().upper()] = v.strip()
            balance = float(parts.get("BALANCE", 0))
            risk_pct = float(parts.get("RISK", 1))
            sl_pips = float(parts.get("SL PIPS", 20))
            if balance <= 0:
                raise ValueError("Balance must be > 0")
            if risk_pct <= 0 or risk_pct > 100:
                raise ValueError("Risk % must be between 0 and 100")
            if sl_pips <= 0:
                raise ValueError("SL pips must be > 0")
            pair = parts.get("PAIR", "EURUSD").upper()
            risk_amount = balance * (risk_pct / 100)
            # Approximate USD pip value per standard lot by instrument type
            _pip_vals = {
                "XAUUSD": 1.0, "GOLD": 1.0,       # Gold: 100oz*$0.01=$1/pip
                "SILVERUSD": 5.0, "SILVER": 5.0,  # Silver: 5000oz*$0.001=$5/pip
                "OILUSD": 10.0, "OIL": 10.0,      # Oil: 1000bbl*$0.01=$10/pip
                "BTCUSD": 1.0, "BTC": 1.0,        # BTC: 1 BTC*$1=$1/pip
                "SOLUSD": 0.1, "SOL": 0.1,        # SOL estimate
            }
            pair_key = pair.replace("/", "").upper()
            if pair_key in _pip_vals:
                pip_value = _pip_vals[pair_key]
            elif "JPY" in pair:
                pip_value = 7  # ~$6.67-7 per pip per lot at 145-150 JPY/USD
            else:
                pip_value = 10  # Standard forex: $10/pip/lot
            lots = round(risk_amount / (sl_pips * pip_value), 2)
            msg = "🧮 RISK CALCULATOR\n\nBalance: $"+str(balance)+"\nRisk: "+str(risk_pct)+"% = $"+str(round(risk_amount,2))+"\nSL: "+str(sl_pips)+" pips\nPair: "+pair+"\n\n🎯 Recommended Lots: "+str(lots)+"\n\nRisk/Reward 1:2\nTP = "+str(sl_pips*2)+" pips"
            send_message(chat_id, msg, main_menu())
        except Exception as e:
            print(f"Risk calculator error: {e}")
            send_message(chat_id, "Format:\nBALANCE: 1000\nRISK: 1\nSL PIPS: 20\nPAIR: EURUSD", main_menu())

    elif text_lower in ["💥 volatility alert", "/volatility"]:
        send_typing(chat_id)
        try:
            vpairs = {"EUR/USD":"EURUSD=X","GBP/USD":"GBPUSD=X","XAU/USD":"GC=F","BTC/USD":"BTC-USD","Oil/USD":"CL=F","USD/JPY":"USDJPY=X","USD/CHF":"USDCHF=X","SOL/USD":"SOL-USD","AUD/USD":"AUDUSD=X"}

            def _fetch_vol(args):
                vname, vsymbol = args
                try:
                    df = yf.Ticker(vsymbol).history(period="5d", interval="1h")
                    if len(df) < 20: return vname, None
                    prev_close = df["Close"].shift(1)
                    tr = pd.concat([df["High"]-df["Low"], (df["High"]-prev_close).abs(), (df["Low"]-prev_close).abs()], axis=1).max(axis=1)
                    atr_series = tr.rolling(14).mean()
                    atr = atr_series.iloc[-1]
                    avg_atr = atr_series.mean()
                    if pd.isna(atr) or pd.isna(avg_atr) or avg_atr == 0:
                        return vname, None
                    pct = round((atr/avg_atr)*100, 0)
                    return vname, {"atr": round(atr, 4), "pct": int(pct)}
                except Exception as e:
                    print(f"Volatility pair error {vname}: {e}")
                    return vname, None

            with ThreadPoolExecutor(max_workers=8) as ex:
                vol_results = dict(ex.map(_fetch_vol, vpairs.items()))

            vlines = ["💥 VOLATILITY REPORT\n"]
            alerts = []
            for vname in vpairs:
                data = vol_results.get(vname)
                if not data: continue
                pct = data["pct"]
                if pct > 150: emoji = "🔴"; alerts.append(vname)
                elif pct > 120: emoji = "🟠"
                else: emoji = "🟢"
                vlines.append(emoji+" "+vname+": ATR "+str(data["atr"])+" ("+str(pct)+"% of avg)")
            if alerts:
                vlines.append("\n🚨 HIGH VOLATILITY: "+" | ".join(alerts))
            send_message(chat_id, "\n".join(vlines), main_menu())
        except Exception as e:
            print(f"Volatility handler error: {e}")
            send_message(chat_id, "💥 Volatility data temporarily unavailable.", main_menu())

    elif text_lower in ["/mtf", "mtf"]:
        send_message(chat_id, "📊 MTF ANALYSIS\n\nSpecify a pair: /mtf EURUSD\n\nExample: /mtf XAUUSD", main_menu())

    elif text_lower.startswith("/mtf ") or text_lower.startswith("mtf "):
        send_typing(chat_id)
        try:
            pair_input = (text_lower[len("/mtf "):] if text_lower.startswith("/mtf ") else text_lower[len("mtf "):]).strip()
            pair_name = ALIASES.get(pair_input) or next((k for k in SYMBOLS if k.lower() == pair_input), pair_input.upper())
            symbol = SYMBOLS.get(pair_name)
            if not symbol:
                send_message(chat_id, "Pair not found. Example: mtf EURUSD", main_menu())
            else:
                def _fetch_tf(args):
                    tf, period = args
                    try:
                        df = yf.Ticker(symbol).history(period=period, interval=tf)
                        if len(df) < 50: return tf, None
                        close = df["Close"]
                        ema20 = close.ewm(span=20).mean().iloc[-1]
                        ema50 = close.ewm(span=50).mean().iloc[-1]
                        delta = close.diff()
                        gain = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
                        loss_s = (-delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
                        loss_s = loss_s.replace(0, 1e-10)
                        rsi = (100-(100/(1+gain/loss_s))).iloc[-1]
                        macd_line = close.ewm(span=12).mean()-close.ewm(span=26).mean()
                        macd_v = macd_line.iloc[-1]
                        macd_sig = macd_line.ewm(span=9).mean().iloc[-1]
                        if ema20 > ema50 and macd_v > macd_sig and rsi > 50:
                            bias = "BULLISH 🟢"
                        elif ema20 < ema50 and macd_v < macd_sig and rsi < 50:
                            bias = "BEARISH 🔴"
                        else:
                            bias = "NEUTRAL 🟡"
                        return tf, bias, round(rsi, 1)
                    except Exception as e:
                        print(f"MTF tf error {tf}: {e}")
                        return tf, None, None

                tf_order = [("15m","5d"),("1h","10d"),("4h","30d")]
                with ThreadPoolExecutor(max_workers=3) as ex:
                    tf_raw = list(ex.map(_fetch_tf, tf_order))
                results = []
                for row in tf_raw:
                    tf = row[0]; bias = row[1]; rsi_v = row[2]
                    if bias:
                        results.append(tf+": "+bias+" | RSI:"+str(rsi_v))
                if not results:
                    send_message(chat_id, "📊 MTF ANALYSIS\n"+pair_name+"\n\n⚠️ Insufficient data for all timeframes.", main_menu())
                    return
                biases = [r.split(":", 1)[1].split("|")[0].strip() for r in results]
                # Only declare ALIGNED when 2+ TFs agree on a non-neutral direction
                non_neutral = [b for b in biases if "NEUTRAL" not in b]
                overall = ("🟢 ALIGNED - Strong signal!" if (len(set(non_neutral)) == 1 and len(non_neutral) >= 2)
                           else "🟡 MIXED - Wait for alignment")
                tz = pytz.timezone("Europe/Athens")
                now = datetime.now(tz).strftime("%d/%m/%Y %H:%M")
                msg = "📊 MTF ANALYSIS\n"+pair_name+" | "+now+"\n\n"
                msg += "\n".join(results)
                msg += "\n\n"+overall
                send_message(chat_id, msg, main_menu())
        except Exception as e:
            print(f"MTF handler error: {e}")
            send_message(chat_id, "📊 MTF analysis temporarily unavailable.", main_menu())

    elif text_lower in ["💼 portfolio", "/portfolio"]:
        try:
            trades_file = "/root/tradingbot/open_trades.json"
            trades = []
            if os.path.exists(trades_file):
                try:
                    with open(trades_file) as f:
                        trades = json.load(f)
                except (json.JSONDecodeError, ValueError) as e:
                    print(f"Portfolio trades JSON error: {e}")
            if not trades:
                send_message(chat_id, "💼 PORTFOLIO\n\nNo open signals right now.", main_menu())
            else:
                _pip_sizes = {
                    "XAU/USD": 0.01, "Silver/USD": 0.001, "Oil/USD": 0.01,
                    "BTC/USD": 1.0, "SOL/USD": 0.01, "DXY": 0.001,
                }

                def _fetch_pl(t):
                    symbol = SYMBOLS.get(t["name"], "")
                    if not symbol: return t, None
                    try:
                        df = yf.Ticker(symbol).history(period="1d", interval="5m")
                        if len(df) == 0:
                            df = yf.Ticker(symbol).history(period="5d", interval="1h")
                        return t, float(df["Close"].iloc[-1])
                    except Exception as e:
                        print(f"Portfolio P&L error for {t.get('name','?')}: {e}")
                        return t, None

                with ThreadPoolExecutor(max_workers=8) as ex:
                    pl_results = list(ex.map(_fetch_pl, trades))

                total_pl = 0
                lines_p = ["💼 PORTFOLIO | Open Signals\n"]
                for t, price in pl_results:
                    if price is None:
                        lines_p.append("🟡 "+t["name"]+" "+t["signal"]+" @ "+str(round(t["entry"],4)))
                        continue
                    entry = t["entry"]
                    pip_size = _pip_sizes.get(t["name"], 0.01 if "JPY" in t["name"] else 0.0001)
                    if t["signal"] == "BUY":
                        pl_pips = round((price - entry) / pip_size, 1)
                    elif t["signal"] == "SELL":
                        pl_pips = round((entry - price) / pip_size, 1)
                    else:
                        print(f"Portfolio: unrecognized signal '{t['signal']}' for {t.get('name','?')}")
                        pl_pips = 0.0
                    pl_emoji = "🟢" if pl_pips > 0 else "🔴"
                    total_pl += pl_pips
                    lines_p.append(pl_emoji+" "+t["name"]+" "+t["signal"]+" @ "+str(round(entry,4))+" | "+str(pl_pips)+" pips")
                total_emoji = "🟢" if total_pl > 0 else ("🟡" if total_pl == 0 else "🔴")
                lines_p.append("\n"+total_emoji+" Total: "+str(round(total_pl,1))+" pips est.")
                send_message(chat_id, "\n".join(lines_p), main_menu())
        except Exception as e:
            print(f"Portfolio handler error: {e}")
            send_message(chat_id, "💼 Portfolio data temporarily unavailable.", main_menu())

    elif text_lower in ["📝 my trades", "/mytrades"]:
        try:
            journal = _load_personal_journal()
            entry = journal.get(str(chat_id), {"open": [], "closed": []})
            open_trades = entry.get("open", [])
            closed_trades = entry.get("closed", [])
            if not open_trades and not closed_trades:
                send_message(chat_id,
                    "📝 MY TRADES\n\nNo personal trades logged yet.\n\n"
                    "Log one:\nADD: EURUSD BUY 1.1200 SL:1.1150 TP:1.1300 LOTS:0.1\n\n"
                    "Close one:\nCLOSE: EURUSD EXIT:1.1250", main_menu())
            else:
                lines_mt = ["📝 MY TRADES\n"]
                if open_trades:
                    lines_mt.append("Open (" + str(len(open_trades)) + "):")

                    def _fetch_pl(t):
                        canonical = ALIASES.get(t["pair"].lower(), t["pair"])
                        symbol = SYMBOLS.get(canonical)
                        if not symbol:
                            return t, None
                        try:
                            df = yf.Ticker(symbol).history(period="1d", interval="5m")
                            if len(df) == 0:
                                df = yf.Ticker(symbol).history(period="5d", interval="1h")
                            return t, float(df["Close"].iloc[-1])
                        except Exception as e:
                            print(f"My Trades P&L error for {t.get('pair','?')}: {e}")
                            return t, None

                    with ThreadPoolExecutor(max_workers=8) as ex:
                        pl_results = list(ex.map(_fetch_pl, open_trades))
                    for t, price in pl_results:
                        if price is None:
                            lines_mt.append("🟡 " + t["pair"] + " " + t["side"] + " @ " + str(t["entry"]) + " (price unavailable)")
                            continue
                        pip_size = 0.01 if "JPY" in t["pair"].upper() else 0.0001
                        if t["side"] == "BUY":
                            pl_pips = round((price - t["entry"]) / pip_size, 1)
                        else:
                            pl_pips = round((t["entry"] - price) / pip_size, 1)
                        emoji = "🟢" if pl_pips > 0 else ("🔴" if pl_pips < 0 else "🟡")
                        lines_mt.append(emoji + " " + t["pair"] + " " + t["side"] + " @ " + str(t["entry"]) + " | " + str(pl_pips) + " pips")
                if closed_trades:
                    wins = sum(1 for t in closed_trades if t["result"] == "WIN")
                    losses = sum(1 for t in closed_trades if t["result"] == "LOSS")
                    total_pips = round(sum(t["pips"] for t in closed_trades), 1)
                    lines_mt.append("\n📊 History: " + str(wins) + "W / " + str(losses) + "L | " + str(total_pips) + " pips total")
                    for t in closed_trades[-5:]:
                        e = "🟢" if t["result"] == "WIN" else "🔴"
                        lines_mt.append(e + " " + t["pair"] + " " + t["side"] + " | " + str(t["pips"]) + " pips")
                send_message(chat_id, "\n".join(lines_mt), main_menu())
        except Exception as e:
            print(f"My Trades handler error: {e}")
            send_message(chat_id, "📝 My Trades temporarily unavailable.", main_menu())

    elif text_lower.startswith("add:"):
        try:
            parts = text.upper().replace("ADD:","").strip().split()
            pair = parts[0]
            side = parts[1]
            entry = float(parts[2])
            sl = float([p for p in parts if p.startswith("SL:")][0].replace("SL:",""))
            tp = float([p for p in parts if p.startswith("TP:")][0].replace("TP:",""))
            lots = float([p for p in parts if p.startswith("LOTS:")][0].replace("LOTS:",""))
            new_trade = {"pair": pair, "side": side, "entry": entry, "sl": sl, "tp": tp,
                         "lots": lots, "opened": time.time()}
            _update_personal_journal(str(chat_id), lambda u: u["open"].append(new_trade))
            send_message(chat_id, "📝 Trade logged!\n\n"+pair+" "+side+" @ "+str(entry)+"\nSL: "+str(sl)+" | TP: "+str(tp)+"\nLots: "+str(lots)+"\n\nClose it later with:\nCLOSE: "+pair+" EXIT:<price>", main_menu())
        except Exception as e:
            print(f"Personal journal add error: {e}")
            send_message(chat_id, "Format:\nADD: EURUSD BUY 1.1200 SL:1.1150 TP:1.1300 LOTS:0.1", main_menu())

    elif text_lower.startswith("close:"):
        try:
            parts = text.upper().replace("CLOSE:","").strip().split()
            pair = parts[0]
            exit_price = float([p for p in parts if p.startswith("EXIT:")][0].replace("EXIT:",""))

            result_holder = {}
            def _close(u):
                for i, t in enumerate(u["open"]):
                    if t["pair"] == pair:
                        pip_size = 0.01 if "JPY" in pair else 0.0001
                        if t["side"] == "BUY":
                            pips = round((exit_price - t["entry"]) / pip_size, 1)
                        else:
                            pips = round((t["entry"] - exit_price) / pip_size, 1)
                        closed = dict(t, exit=exit_price, result="WIN" if pips >= 0 else "LOSS",
                                      pips=pips, closed=time.time())
                        u["open"].pop(i)
                        u["closed"].append(closed)
                        u["closed"] = u["closed"][-100:]
                        result_holder["closed"] = closed
                        return
            _update_personal_journal(str(chat_id), _close)

            if "closed" in result_holder:
                c = result_holder["closed"]
                emoji = "🟢" if c["result"] == "WIN" else "🔴"
                send_message(chat_id, emoji+" Trade closed!\n\n"+c["pair"]+" "+c["side"]+" @ "+str(c["entry"])+" ➡️ "+str(exit_price)+"\nResult: "+str(c["pips"])+" pips ("+c["result"]+")", main_menu())
            else:
                send_message(chat_id, "No open personal trade found for "+pair+".\n\nCheck 📝 My Trades for your open positions.", main_menu())
        except Exception as e:
            print(f"Personal journal close error: {e}")
            send_message(chat_id, "Format:\nCLOSE: EURUSD EXIT:1.1250", main_menu())

    elif text_lower in ["📓 trade journal", "/journal"]:
        try:
            journal_file = "/root/tradingbot/journal.json"
            if not os.path.exists(journal_file):
                send_message(chat_id, "📓 TRADE JOURNAL\n\nNo entries yet.\n\nAdd entry:\nJOURNAL: EURUSD BUY WIN +50pips Good entry at support", main_menu())
            else:
                try:
                    with open(journal_file) as f:
                        entries = json.load(f)
                except (json.JSONDecodeError, ValueError) as e:
                    print(f"Journal read error: {e}")
                    entries = []
                if not entries:
                    send_message(chat_id, "📓 No journal entries yet.", main_menu())
                    return
                lines_j = ["📓 TRADE JOURNAL\n"]
                for entry in entries[-5:]:
                    result_emoji = "🟢" if entry.get("result","") == "WIN" else "🔴"
                    lines_j.append(result_emoji+" "+entry.get("pair","?")+" "+entry.get("side","?")+" | "+entry.get("result","")+" "+entry.get("pips","")+"\n   "+entry.get("note",""))
                send_message(chat_id, "\n".join(lines_j), main_menu())
        except Exception as e:
            print(f"Journal handler error: {e}")
            send_message(chat_id, "📓 Trade journal temporarily unavailable.", main_menu())

    elif text_lower.startswith("journal:"):
        try:
            journal_file = "/root/tradingbot/journal.json"
            parts = text.upper().replace("JOURNAL:","").strip().split()
            pair = parts[0]
            side = parts[1]
            result = parts[2]
            pips = parts[3] if len(parts) > 3 else ""
            note = " ".join(parts[4:]).lower() if len(parts) > 4 else ""
            lock_path = journal_file + '.lock'
            with open(lock_path, 'a') as _lf:
                fcntl.flock(_lf, fcntl.LOCK_EX)
                try:
                    entries = []
                    if os.path.exists(journal_file):
                        try:
                            with open(journal_file) as f:
                                entries = json.load(f)
                        except (json.JSONDecodeError, ValueError) as e:
                            print(f"Journal JSON error: {e}")
                    entries.append({"pair":pair,"side":side,"result":result,"pips":pips,"note":note,"date":datetime.now(pytz.timezone("Europe/Athens")).strftime("%d/%m/%Y")})
                    _tmp = journal_file + '.tmp'
                    with open(_tmp, 'w') as f:
                        json.dump(entries, f)
                    os.replace(_tmp, journal_file)
                finally:
                    fcntl.flock(_lf, fcntl.LOCK_UN)
            send_message(chat_id, "📓 Journal entry added!", main_menu())
        except Exception as e:
            print(f"Journal add error: {e}")
            send_message(chat_id, "Format:\nJOURNAL: EURUSD BUY WIN +50pips Good entry at support", main_menu())

    elif text_lower in ["💰 ib tracker", "/ibtracker"]:
        try:
            ib_file = "/root/tradingbot/ib_clients.json"
            if not os.path.exists(ib_file):
                send_message(chat_id, "💰 IB TRACKER\n\nNo clients yet.\n\nAdd a client:\nCLIENT: John BROKER:puprime LOTS:50 GOLD:10", main_menu())
            else:
                try:
                    with open(ib_file) as f:
                        clients = json.load(f)
                except (json.JSONDecodeError, ValueError) as e:
                    print(f"IB clients JSON error: {e}")
                    clients = []
                if not clients:
                    send_message(chat_id, "💰 No clients yet.", main_menu())
                else:
                    total_earn = 0
                    lines_ib = ["💰 IB TRACKER\n"]
                    for c in clients:
                        broker = c.get("broker","puprime").lower()
                        lots = c.get("lots",0)
                        gold = c.get("gold",0)
                        if broker == "puprime":
                            earn = lots*18 + gold*25
                        else:
                            earn = lots*7 + gold*5
                        total_earn += earn
                        lines_ib.append("👤 "+c["name"]+" | "+broker.upper()+" | "+str(lots)+"L FX + "+str(gold)+"L Gold = $"+str(earn))
                    lines_ib.append("\n💰 Total Earnings: $"+str(total_earn))
                    send_message(chat_id, "\n".join(lines_ib), main_menu())
        except Exception as e:
            print(f"IB tracker handler error: {e}")
            send_message(chat_id, "💰 IB tracker temporarily unavailable.", main_menu())

    elif text_lower.startswith("client:"):
        try:
            ib_file = "/root/tradingbot/ib_clients.json"
            parts = text.upper().replace("CLIENT:","").strip().split()
            name = parts[0]
            broker = [p for p in parts if p.startswith("BROKER:")][0].replace("BROKER:","").lower()
            lots = float([p for p in parts if p.startswith("LOTS:")][0].replace("LOTS:",""))
            gold = float([p for p in parts if p.startswith("GOLD:")][0].replace("GOLD:","")) if any(p.startswith("GOLD:") for p in parts) else 0
            lock_path = ib_file + '.lock'
            with open(lock_path, 'a') as _lf:
                fcntl.flock(_lf, fcntl.LOCK_EX)
                try:
                    clients = []
                    if os.path.exists(ib_file):
                        try:
                            with open(ib_file) as f:
                                clients = json.load(f)
                        except (json.JSONDecodeError, ValueError) as e:
                            print(f"IB clients JSON error: {e}")
                    existing = [c for c in clients if c["name"] == name]
                    if existing:
                        existing[0]["lots"] = lots
                        existing[0]["gold"] = gold
                        existing[0]["broker"] = broker
                    else:
                        clients.append({"name":name,"broker":broker,"lots":lots,"gold":gold})
                    _tmp = ib_file + '.tmp'
                    with open(_tmp, 'w') as f:
                        json.dump(clients, f)
                    os.replace(_tmp, ib_file)
                finally:
                    fcntl.flock(_lf, fcntl.LOCK_UN)
            send_message(chat_id, "👤 Client "+name+" saved!", main_menu())
        except Exception as e:
            print(f"IB client add error: {e}")
            send_message(chat_id, "Format:\nCLIENT: John BROKER:puprime LOTS:50 GOLD:10", main_menu())

    elif text_lower in ["🧮 commission calc", "/commission"]:
        send_message(chat_id, "🧮 COMMISSION CALCULATOR\n\nCalculate your IB earnings:\n\nCALC: puprime LOTS:100 GOLD:20\n\nPU Prime rates:\nForex: $18/lot\nGold: $25/lot\n\nEquiti rates:\nForex: $7/lot\nGold: $5/lot", main_menu())

    elif text_lower.startswith("calc:"):
        try:
            parts = text.upper().replace("CALC:","").strip().split()
            broker = parts[0].lower()
            lots = float([p for p in parts if p.startswith("LOTS:")][0].replace("LOTS:",""))
            gold = float([p for p in parts if p.startswith("GOLD:")][0].replace("GOLD:","")) if any(p.startswith("GOLD:") for p in parts) else 0
            if broker == "puprime":
                fx_earn = lots * 18
                gold_earn = gold * 25
            else:
                fx_earn = lots * 7
                gold_earn = gold * 5
            total = fx_earn + gold_earn
            msg = "🧮 COMMISSION CALCULATOR\n\nBroker: "+broker.upper()+"\nForex lots: "+str(lots)+" x $"+("18" if broker=="puprime" else "7")+" = $"+str(fx_earn)+"\nGold lots: "+str(gold)+" x $"+("25" if broker=="puprime" else "5")+" = $"+str(gold_earn)+"\n\n💰 Total earnings: $"+str(total)
            send_message(chat_id, msg, main_menu())
        except Exception as e:
            print(f"Commission calc error: {e}")
            send_message(chat_id, "Format:\nCALC: puprime LOTS:100 GOLD:20", main_menu())

    elif text_lower in ["📜 signal history", "/history"]:
        try:
            stats_file = "/root/tradingbot/trade_stats.json"
            last_signals_file = "/root/tradingbot/last_signals_smc.json"
            stats = {"wins":0,"losses":0}
            if os.path.exists(stats_file):
                try:
                    with open(stats_file) as f:
                        stats = json.load(f)
                except (json.JSONDecodeError, ValueError, OSError) as e:
                    print(f"signal history stats JSON error: {e}")
            last_signals = {}
            if os.path.exists(last_signals_file):
                try:
                    with open(last_signals_file) as f:
                        last_signals = json.load(f)
                except (json.JSONDecodeError, ValueError, OSError) as e:
                    print(f"signal history last_signals JSON error: {e}")
            total = stats.get("wins",0)+stats.get("losses",0)
            wr = round((stats.get("wins",0)/total)*100,1) if total > 0 else 0
            lines_h = ["📜 SIGNAL HISTORY"]
            lines_h.append("🟢 Wins: "+str(stats.get("wins",0))+" | 🔴 Losses: "+str(stats.get("losses",0))+" | WR: "+str(wr)+"%")
            lines_h.append("Last signals:")
            tz_athens = pytz.timezone("Europe/Athens")
            sorted_signals = sorted(last_signals.items(), key=lambda x: x[1].get("time", 0))
            for pair_key, data in sorted_signals[-10:]:
                sig = data.get("signal","")
                t = data.get("time",0)
                # Keys are stored as "PAIR_DIRECTION" (e.g. "EUR/USD_BUY") for direction-aware
                # cooldown; strip the suffix so the display shows just the pair name.
                if pair_key.endswith("_BUY"):
                    pair = pair_key[:-4]
                    sig = sig or "BUY"
                elif pair_key.endswith("_SELL"):
                    pair = pair_key[:-5]
                    sig = sig or "SELL"
                else:
                    pair = pair_key  # legacy format — no suffix
                sig_emoji = "🟢" if sig == "BUY" else "🔴"
                time_str = datetime.fromtimestamp(t, tz=tz_athens).strftime("%d/%m %H:%M") if t else ""
                lines_h.append(sig_emoji+" "+pair+" "+sig+" | "+time_str)
            send_message(chat_id, "\n".join(lines_h), main_menu())
        except Exception as e:
            print(f"Signal history handler error: {e}")
            send_message(chat_id, "📜 Signal history temporarily unavailable.", main_menu())

    elif text_lower in ["📍 s&r levels", "/sr"]:
        send_typing(chat_id)
        try:
            pairs = {"EUR/USD":"EURUSD=X","GBP/USD":"GBPUSD=X","XAU/USD":"GC=F","BTC/USD":"BTC-USD","Oil/USD":"CL=F","USD/JPY":"USDJPY=X","USD/CHF":"USDCHF=X","AUD/USD":"AUDUSD=X","NZD/USD":"NZDUSD=X","USD/CAD":"USDCAD=X","SOL/USD":"SOL-USD","Silver/USD":"SI=F","Copper/USD":"HG=F","DXY":"DX-Y.NYB"}

            def _fetch_sr(args):
                name, symbol = args
                try:
                    df = yf.Ticker(symbol).history(period="30d", interval="1d")
                    if len(df) < 10: return name, None
                    price = df["Close"].iloc[-1]
                    res = sorted([h for h in df["High"].values if h > price])
                    sup = sorted([l for l in df["Low"].values if l < price], reverse=True)
                    return name, {
                        "price": round(price, 4),
                        "r1": round(res[0], 4) if res else "N/A",
                        "r2": round(res[1], 4) if len(res) > 1 else "N/A",
                        "s1": round(sup[0], 4) if sup else "N/A",
                        "s2": round(sup[1], 4) if len(sup) > 1 else "N/A",
                    }
                except Exception as e:
                    print(f"S&R pair error {name}: {e}")
                    return name, None

            with ThreadPoolExecutor(max_workers=8) as ex:
                sr_results = dict(ex.map(_fetch_sr, pairs.items()))

            lines_sr = ["📍 SUPPORT & RESISTANCE"]
            for name in pairs:
                data = sr_results.get(name)
                if not data: continue
                lines_sr.append("\n"+name+" | "+str(data["price"]))
                lines_sr.append("🔴 R2: "+str(data["r2"])+" | R1: "+str(data["r1"]))
                lines_sr.append("🟢 S1: "+str(data["s1"])+" | S2: "+str(data["s2"]))
            send_message(chat_id, "\n".join(lines_sr), main_menu())
        except Exception as e:
            print(f"S&R handler error: {e}")
            send_message(chat_id, "📍 S&R levels temporarily unavailable.", main_menu())

    elif len(text.strip()) >= 4:
        # Free-form question — anything that didn't match a known command/button
        # and isn't just noise gets a general AI answer instead of "use the menu".
        send_typing(chat_id)
        try:
            client = _get_anthropic()
            message = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                system=(
                    "You are the Trading Nova assistant, answering a free-form question in a "
                    "trading Telegram bot. Be direct and concise (under 120 words). Respond in "
                    "plain text only — no markdown, no asterisks, no numbered-list formatting "
                    "symbols. If the question is really asking for a specific pair's live "
                    "analysis, mention they can use /analysis <pair> for a chart-based read — "
                    "only suggest a pair name from this exact supported list, never a ticker "
                    "outside it: EURUSD, GBPUSD, USDCHF, AUDUSD, USDCAD, NZDUSD, USDJPY, XAUUSD, "
                    "SILVER, COPPER, OIL, BTC, SOL, DXY. If it's off-topic for trading/markets, "
                    "answer briefly and naturally anyway — don't refuse or lecture about scope."
                ),
                messages=[{"role": "user", "content": text[:500]}],
            )
            answer = message.content[0].text if message.content else None
            send_message(chat_id, answer or "Couldn't come up with an answer for that — try rephrasing?", main_menu())
        except Exception as e:
            print(f"Free-form Q&A error: {e}")
            send_message(chat_id, "Couldn't reach the AI just now — try again in a moment, or use the menu below:", main_menu())

    else:
        send_message(chat_id, "Use the menu below:", main_menu())

def _process_update(update):
    try:
        msg = update.get("message", {})
        chat_id = str(msg.get("chat", {}).get("id", ""))
        text = msg.get("text", "")
        username = msg.get("from", {}).get("username", "")
        first_name = msg.get("from", {}).get("first_name", "")
        if chat_id:
            # /start already sends the full WELCOME + keyboard — skip the extra
            # "Menu restored:" message that _ensure_keyboard would otherwise prepend.
            raw_cmd = text.strip().lower().split("@")[0] if text else ""
            if raw_cmd in ("/start", "start"):
                with _keyboard_sent_lock:
                    _keyboard_sent.add(chat_id)
            _ensure_keyboard(chat_id)
        if text and chat_id:
            handle_message(chat_id, text, username, first_name)
        callback = update.get("callback_query", {})
        if callback:
            cb_chat_id = str(callback.get("message", {}).get("chat", {}).get("id", ""))
            cb_data = callback.get("data", "")
            cb_id = callback.get("id", "")
            cb_username = callback.get("from", {}).get("username", "")
            cb_first_name = callback.get("from", {}).get("first_name", "")
            answer_callback(cb_id)
            if cb_data == "cmd_news":
                handle_message(cb_chat_id, "🌍 news", cb_username, cb_first_name)
            elif cb_data == "cmd_analysis":
                handle_message(cb_chat_id, "📊 analysis", cb_username, cb_first_name)
            elif cb_data == "cmd_sentiment":
                handle_message(cb_chat_id, "🧠 sentiment", cb_username, cb_first_name)
            elif cb_data == "cmd_calendar":
                handle_message(cb_chat_id, "📅 calendar", cb_username, cb_first_name)
            elif cb_data == "cmd_status":
                handle_message(cb_chat_id, "📋 status", cb_username, cb_first_name)
    except Exception as e:
        print(f"_process_update error: {e}")

_keyboard_sent = set()  # chat_ids that already have the keyboard
_keyboard_sent_lock = Lock()
_update_executor = ThreadPoolExecutor(max_workers=20, thread_name_prefix="update")

def _ensure_keyboard(chat_id):
    """Send keyboard to a chat if it hasn't received one since the last restart."""
    with _keyboard_sent_lock:
        if chat_id in _keyboard_sent:
            return
        _keyboard_sent.add(chat_id)
    # Send outside the lock so we don't hold it during a network call
    send_message(chat_id, "📋 Menu restored:", main_menu())

def main():
    set_commands()
    offset = None
    print("Listener started...")
    while True:
        try:
            result = get_updates(offset)
            for update in result.get("result", []):
                offset = update["update_id"] + 1
                _update_executor.submit(_process_update, update)
        except Exception as e:
            print("Error: "+str(e))
            time.sleep(5)

if __name__ == "__main__":
    main()
