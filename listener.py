import os
from dotenv import load_dotenv
load_dotenv("/root/tradingbot/.env")

import requests
import json
import time
import yfinance as yf
import anthropic
import pytz
from datetime import datetime

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN_SIGNAL")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
USERS_FILE = "/root/tradingbot/users.json"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

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
    "\U0001f4c8 Welcome to Trading Nova Signal!\n\n"
    "Here you will find signals based on indicators and important Fundamental News.\n\n"
    "You will receive signals for:\n"
    "\U0001fa99 XAU/USD | \U0001f1ea\U0001f1fa EUR/USD | \U0001f1ec\U0001f1e7 GBP/USD\n"
    "\U0001f7e1 BTC/USD | \U0001f535 SOL/USD | \u26fd Oil/USD\n"
    "...and many more!\n\n"
    "\U0001f3af Signals are sent only when a real opportunity is detected.\n\n"
    "Use the menu below to get started \U0001f447"
)

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE) as f:
            return json.load(f)
    return []

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f)

def answer_callback(callback_id):
    try:
        requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/answerCallbackQuery",
            json={"callback_query_id": callback_id})
    except Exception as e:
        print(f"answer_callback error: {e}")

def get_updates(offset=None):
    params = {"timeout": 30}
    if offset:
        params["offset"] = offset
    r = requests.get("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/getUpdates", params=params, timeout=35)
    return r.json()

def send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text[:4000]}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendMessage", json=payload)

def send_typing(chat_id):
    requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/sendChatAction",
        json={"chat_id": chat_id, "action": "typing"})

def inline_main_menu():
    return json.dumps({"inline_keyboard": [
        [{"text": "📊 Analysis", "callback_data": "cmd_analysis"}, {"text": "🧠 Sentiment", "callback_data": "cmd_sentiment"}],
        [{"text": "📅 Calendar", "callback_data": "cmd_calendar"}, {"text": "📋 Status", "callback_data": "cmd_status"}],
            [{"text": "🌍 News", "callback_data": "cmd_news"}],
    ]})

def main_menu():
    return {
        "keyboard": [
            [{"text": "📊 Analysis"}, {"text": "🧠 Sentiment"}],
            [{"text": "📅 Calendar"}, {"text": "📋 Status"}],
            [{"text": "🧮 Risk Calculator"}, {"text": "💥 Volatility Alert"}],
            [{"text": "💼 Portfolio"}, {"text": "📓 Trade Journal"}],
        [{"text": "📜 Signal History"}, {"text": "📍 S&R Levels"}],
        ],
        "resize_keyboard": True,
        "one_time_keyboard": True,
        "input_field_placeholder": "Choose an option..."
    }
def pairs_menu():
    return {
        "keyboard": [
            [{"text": "\U0001f1ea\U0001f1fa EUR/USD"}, {"text": "\U0001f1ec\U0001f1e7 GBP/USD"}],
            [{"text": "\U0001fa99 XAU/USD"}, {"text": "\U0001f7e1 BTC/USD"}],
            [{"text": "\U0001f535 SOL/USD"}, {"text": "\u26fd Oil/USD"}],
            [{"text": "\U0001f1fa\U0001f1f8 USD/CHF"}, {"text": "\U0001f1e6\U0001f1fa AUD/USD"}],
            [{"text": "🥈 Silver/USD"}, {"text": "🟠 Copper/USD"}],
            [{"text": "🇯🇵 USD/JPY"}, {"text": "🇳🇿 NZD/USD"}],
            [{"text": "\U0001f519 Back to Menu"}],
        ],
        "resize_keyboard": True,
        "one_time_keyboard": True,
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
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = -delta.clip(upper=0).rolling(14).mean()
        rsi = (100 - (100 / (1 + gain / loss))).iloc[-1]
        atr = (high - low).rolling(14).mean().iloc[-1]
        price = close.iloc[-1]
        bb_mid = close.rolling(20).mean().iloc[-1]
        bb_upper = (bb_mid + 2*close.rolling(20).std()).iloc[-1]
        bb_lower = (bb_mid - 2*close.rolling(20).std()).iloc[-1]
        macd = (close.ewm(span=12).mean() - close.ewm(span=26).mean()).iloc[-1]

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        prompt = "Expert forex analyst. Plain text only, no markdown. Quick analysis for "+pair_name+". Format: TREND / SIGNAL: BUY or SELL or WAIT / ENTRY / SL / TP / RISK NOTE. Data: Price="+str(round(price,5))+" EMA20="+str(round(ema20,5))+" EMA50="+str(round(ema50,5))+" RSI="+str(round(rsi,1))+" MACD="+str(round(macd,5))+" ATR="+str(round(atr,5))+" BBup="+str(round(bb_upper,5))+" BBlo="+str(round(bb_lower,5))
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{"role":"user","content":prompt}]
        )
        tz = pytz.timezone("Europe/Athens")
        now = datetime.now(tz).strftime("%d/%m/%Y %H:%M")
        return pair_name+" | "+now+"\n\n"+message.content[0].text
    except Exception as e:
        return "Error: "+str(e)

def get_sentiment():
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
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
        with open(trades_file) as f:
            trades = json.load(f)
    if os.path.exists(stats_file):
        with open(stats_file) as f:
            stats = json.load(f)
    total = stats["wins"]+stats["losses"]
    wr = round((stats["wins"]/total)*100,1) if total > 0 else 0
    tz = pytz.timezone("Europe/Athens")
    now = datetime.now(tz).strftime("%d/%m/%Y %H:%M")
    lines = ["\U0001f4ca TRADING STATUS | "+now+"\n"]
    if trades:
        lines.append("\U0001f4cc Open Trades ("+str(len(trades))+"):")
        for t in trades:
            lines.append("- "+t["name"]+" "+t["signal"]+" @ "+str(round(t["entry"],4)))
    else:
        lines.append("No open trades right now.")
    return "\n".join(lines)

def set_commands():
    requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/setMyCommands", json={
        "commands": [
            {"command": "start", "description": "Start & main menu"},
            {"command": "analysis", "description": "Get analysis: /analysis EURUSD"},
            {"command": "sentiment", "description": "Market sentiment"},
            {"command": "status", "description": "Trading status & open trades"},
            {"command": "links", "description": "Our social links"},
        ]
    })

def handle_message(chat_id, text, username):
    text = text.strip()
    text_lower = text.lower()

    if text_lower in ["/start", "start"]:
        users = load_users()
        if str(chat_id) not in users:
            users.append(str(chat_id))
            save_users(users)
        send_message(chat_id, WELCOME, main_menu())


    elif text_lower in ["/menu", "\U0001f519 back to menu"]:
        send_message(chat_id, "Main menu:", main_menu())

    elif text_lower in ["\U0001f4b1 pairs"]:
        send_message(chat_id, "Choose a pair for analysis:", pairs_menu())

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
            from datetime import datetime
            tz = pytz.timezone("Europe/Athens")
            today = datetime.now(tz).strftime("%Y-%m-%d")
            now_str = datetime.now(tz).strftime("%d/%m/%Y")
            h = {"User-Agent":"Mozilla/5.0","X-Requested-With":"XMLHttpRequest","Referer":"https://www.investing.com/economic-calendar/"}
            d = {"dateFrom":today,"dateTo":today,"importance[]":["2","3"]}
            r = requests.post("https://www.investing.com/economic-calendar/Service/getCalendarFilteredData",headers=h,data=d,timeout=15)
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
            send_message(chat_id, "📅 Economic calendar sent every morning at 07:00!", main_menu())
    elif text_lower in ["🌍 news", "/news"]:
        send_typing(chat_id)
        try:
            import feedparser
            from datetime import datetime
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
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            news_text = "\n".join(headlines[:8])
            message = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                messages=[{"role":"user","content":"From these headlines pick the 5 most important for traders. Write each as one short line with an emoji. Then add one sentence summary. Simple English. Plain text.\n\n"+news_text}]
            )
            send_message(chat_id, "📰 LATEST NEWS\n🕔 "+now_str+"\n\n"+message.content[0].text+"\n\n📰 Full news: @tradingNovaNews", main_menu())
        except Exception as e:
            send_message(chat_id, "🌍 Latest news at @tradingNovaNews", main_menu())

    elif text_lower in ["\U0001f4ca analysis", "/analysis"]:
        send_message(chat_id, "Choose a pair:", pairs_menu())

    elif text_lower.startswith("/analysis "):
        pair_input = text_lower.replace("/analysis ","").strip()
        pair_name = ALIASES.get(pair_input, pair_input.upper())
        send_typing(chat_id)
        send_message(chat_id, get_analysis(pair_name), main_menu())

    elif any(text_lower.replace(" ","").replace("/","") == k for k in ALIASES.keys()):
        key = text_lower.replace(" ","").replace("/","")
        pair_name = ALIASES.get(key, key.upper())
        send_typing(chat_id)
        send_message(chat_id, get_analysis(pair_name), main_menu())

    elif any(emoji in text for emoji in ["🇪🇺","🇬🇧","🪙","🟡","🔵","⛽","🇺🇸","🇦🇺","🥈","🟠","🇯🇵","🇳🇿"]):
        for k, v in ALIASES.items():
            if k in text_lower or v.lower() in text_lower:
                send_typing(chat_id)
                send_message(chat_id, get_analysis(v), main_menu())
                return

    elif text_lower in ["🧮 risk calculator", "/risk"]:
        send_message(chat_id, "🧮 RISK CALCULATOR\n\nSend your details like this:\n\nBALANCE: 1000\nRISK: 1\nSL PIPS: 20\nPAIR: EURUSD", main_menu())

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
            pair = parts.get("PAIR", "EURUSD").upper()
            risk_amount = balance * (risk_pct / 100)
            pip_value = 10 if "JPY" not in pair else 1000
            lots = round(risk_amount / (sl_pips * pip_value), 2)
            msg = "🧮 RISK CALCULATOR\n\nBalance: $"+str(balance)+"\nRisk: "+str(risk_pct)+"% = $"+str(round(risk_amount,2))+"\nSL: "+str(sl_pips)+" pips\nPair: "+pair+"\n\n🎯 Recommended Lots: "+str(lots)+"\n\nRisk/Reward 1:2\nTP = "+str(sl_pips*2)+" pips"
            send_message(chat_id, msg, main_menu())
        except:
            send_message(chat_id, "Format:\nBALANCE: 1000\nRISK: 1\nSL PIPS: 20\nPAIR: EURUSD", main_menu())

    elif text_lower in ["💥 volatility alert", "/volatility"]:
        send_typing(chat_id)
        try:
            import yfinance as yf
            pairs = {"EUR/USD":"EURUSD=X","GBP/USD":"GBPUSD=X","XAU/USD":"GC=F","BTC/USD":"BTC-USD","Oil/USD":"CL=F","USD/JPY":"USDJPY=X","USD/CHF":"USDCHF=X","AUD/USD":"AUDUSD=X","NZD/USD":"NZDUSD=X","USD/CAD":"USDCAD=X","SOL/USD":"SOL-USD","Silver/USD":"SI=F","Copper/USD":"HG=F","DXY":"DX-Y.NYB"}
            vlines = ["💥 VOLATILITY REPORT\n"]
            alerts = []
            vpairs = {"EUR/USD":"EURUSD=X","GBP/USD":"GBPUSD=X","XAU/USD":"GC=F","BTC/USD":"BTC-USD","Oil/USD":"CL=F","USD/JPY":"USDJPY=X","USD/CHF":"USDCHF=X","SOL/USD":"SOL-USD","AUD/USD":"AUDUSD=X"}
            for vname, vsymbol in vpairs.items():
                try:
                    df = yf.Ticker(vsymbol).history(period="5d", interval="1h")
                    if len(df) < 20: continue
                    atr = ((df["High"]-df["Low"]).rolling(14).mean()).iloc[-1]
                    avg_atr = ((df["High"]-df["Low"]).rolling(14).mean()).mean()
                    pct = round((atr/avg_atr)*100, 0)
                    if pct > 150: emoji = "🔴"; alerts.append(vname)
                    elif pct > 120: emoji = "🟠"
                    else: emoji = "🟢"
                    vlines.append(emoji+" "+vname+": ATR "+str(round(atr,4))+" ("+str(int(pct))+"% of avg)")
                except Exception as e:
                    print(f"Volatility pair error {vname}: {e}")
            if alerts:
                vlines.append("\n🚨 HIGH VOLATILITY: "+" | ".join(alerts))
            send_message(chat_id, "\n".join(vlines), main_menu())
        except Exception as e:
            send_message(chat_id, "Error: "+str(e), main_menu())

    elif text_lower.startswith("/mtf ") or text_lower.startswith("mtf "):
        send_typing(chat_id)
        try:
            import yfinance as yf
            pair_input = text_lower.replace("/mtf ","").replace("mtf ","").strip()
            pair_name = ALIASES.get(pair_input, pair_input.upper())
            symbol = SYMBOLS.get(pair_name)
            if not symbol:
                send_message(chat_id, "Pair not found. Example: mtf EURUSD", main_menu())
            else:
                results = []
                for tf, period in [("15m","5d"),("1h","10d"),("4h","30d")]:
                    df = yf.Ticker(symbol).history(period=period, interval=tf)
                    if len(df) < 50: continue
                    close = df["Close"]
                    ema20 = close.ewm(span=20).mean().iloc[-1]
                    ema50 = close.ewm(span=50).mean().iloc[-1]
                    delta = close.diff()
                    gain = delta.clip(lower=0).rolling(14).mean()
                    loss = -delta.clip(upper=0).rolling(14).mean()
                    rsi = (100-(100/(1+gain/loss))).iloc[-1]
                    macd = (close.ewm(span=12).mean()-close.ewm(span=26).mean()).iloc[-1]
                    macd_sig = (close.ewm(span=12).mean()-close.ewm(span=26).mean()).ewm(span=9).mean().iloc[-1]
                    if ema20 > ema50 and macd > macd_sig and rsi > 50:
                        bias = "BULLISH 🟢"
                    elif ema20 < ema50 and macd < macd_sig and rsi < 50:
                        bias = "BEARISH 🔴"
                    else:
                        bias = "NEUTRAL 🟡"
                    results.append(tf+": "+bias+" | RSI:"+str(round(rsi,1)))
                agreement = len(set([r.split(":")[1].split("|")[0].strip() for r in results]))
                overall = "🟢 ALIGNED - Strong signal!" if agreement == 1 else "🟡 MIXED - Wait for alignment"
                from datetime import datetime as dt2
                tz = pytz.timezone("Europe/Athens")
                now = dt2.now(tz).strftime("%d/%m/%Y %H:%M")
                msg = "📊 MTF ANALYSIS\n"+pair_name+" | "+now+"\n\n"
                msg += "\n".join(results)
                msg += "\n\n"+overall
                send_message(chat_id, msg, main_menu())
        except Exception as e:
            send_message(chat_id, "Error: "+str(e), main_menu())

    elif text_lower in ["💼 portfolio", "/portfolio"]:
        try:
            import yfinance as yf2
            trades_file = "/root/tradingbot/open_trades.json"
            trades = []
            if os.path.exists(trades_file):
                with open(trades_file) as f:
                    trades = json.load(f)
            if not trades:
                send_message(chat_id, "💼 PORTFOLIO\n\nNo open signals right now.", main_menu())
            else:
                total_pl = 0
                lines_p = ["💼 PORTFOLIO | Open Signals\n"]
                for t in trades:
                    symbol = SYMBOLS.get(t["name"], "")
                    if not symbol:
                        continue
                    try:
                        df = yf2.Ticker(symbol).history(period="5d", interval="1h")
                        price = df["Close"].iloc[-1]
                        entry = t["entry"]
                        if t["signal"] == "BUY":
                            pl_pips = round((price - entry) / entry * 10000, 1)
                            pl_usd = round((price - entry) * 10000, 2)
                        else:
                            pl_pips = round((entry - price) / entry * 10000, 1)
                            pl_usd = round((entry - price) * 10000, 2)
                        pl_emoji = "🟢" if pl_pips > 0 else "🔴"
                        total_pl += pl_usd
                        lines_p.append(pl_emoji+" "+t["name"]+" "+t["signal"]+" @ "+str(round(entry,4))+" | "+str(pl_pips)+" pips")
                    except:
                        lines_p.append("🟡 "+t["name"]+" "+t["signal"]+" @ "+str(round(t["entry"],4)))
                total_emoji = "🟢" if total_pl > 0 else "🔴"
                lines_p.append("\n"+total_emoji+" Total: "+str(round(total_pl,2))+" USD est.")
                send_message(chat_id, "\n".join(lines_p), main_menu())
        except Exception as e:
            send_message(chat_id, "Error: "+str(e), main_menu())

    elif text_lower.startswith("add:"):
        try:
            port_file = "/root/tradingbot/portfolio.json"
            parts = text.upper().replace("ADD:","").strip().split()
            pair = parts[0]
            side = parts[1]
            entry = float(parts[2])
            sl = float([p for p in parts if p.startswith("SL:")][0].replace("SL:",""))
            tp = float([p for p in parts if p.startswith("TP:")][0].replace("TP:",""))
            lots = float([p for p in parts if p.startswith("LOTS:")][0].replace("LOTS:",""))
            trades = []
            if os.path.exists(port_file):
                with open(port_file) as f:
                    trades = json.load(f)
            trades.append({"pair":pair,"side":side,"entry":entry,"sl":sl,"tp":tp,"lots":lots})
            with open(port_file,"w") as f:
                json.dump(trades,f)
            send_message(chat_id, "💼 Trade added!\n\n"+pair+" "+side+" @ "+str(entry)+"\nSL: "+str(sl)+" | TP: "+str(tp)+"\nLots: "+str(lots), main_menu())
        except:
            send_message(chat_id, "Format:\nADD: EURUSD BUY 1.1200 SL:1.1150 TP:1.1300 LOTS:0.1", main_menu())

    elif text_lower in ["📓 trade journal", "/journal"]:
        try:
            journal_file = "/root/tradingbot/journal.json"
            if not os.path.exists(journal_file):
                send_message(chat_id, "📓 TRADE JOURNAL\n\nNo entries yet.\n\nAdd entry:\nJOURNAL: EURUSD BUY WIN +50pips Good entry at support", main_menu())
            else:
                with open(journal_file) as f:
                    entries = json.load(f)
                if not entries:
                    send_message(chat_id, "📓 No journal entries yet.", main_menu())
                    return
                lines_j = ["📓 TRADE JOURNAL\n"]
                for e in entries[-5:]:
                    result_emoji = "🟢" if e.get("result","") == "WIN" else "🔴"
                    lines_j.append(result_emoji+" "+e["pair"]+" "+e["side"]+" | "+e.get("result","")+" "+e.get("pips","")+"\n   "+e.get("note",""))
                send_message(chat_id, "\n".join(lines_j), main_menu())
        except Exception as e:
            send_message(chat_id, "Error: "+str(e), main_menu())

    elif text_lower.startswith("journal:"):
        try:
            journal_file = "/root/tradingbot/journal.json"
            parts = text.upper().replace("JOURNAL:","").strip().split()
            pair = parts[0]
            side = parts[1]
            result = parts[2]
            pips = parts[3] if len(parts) > 3 else ""
            note = " ".join(parts[4:]).lower() if len(parts) > 4 else ""
            entries = []
            if os.path.exists(journal_file):
                with open(journal_file) as f:
                    entries = json.load(f)
            from datetime import datetime as dt3
            entries.append({"pair":pair,"side":side,"result":result,"pips":pips,"note":note,"date":dt3.now().strftime("%d/%m/%Y")})
            with open(journal_file,"w") as f:
                json.dump(entries,f)
            send_message(chat_id, "📓 Journal entry added!", main_menu())
        except:
            send_message(chat_id, "Format:\nJOURNAL: EURUSD BUY WIN +50pips Good entry at support", main_menu())

    elif text_lower in ["💰 ib tracker", "/ibtracker"]:
        try:
            ib_file = "/root/tradingbot/ib_clients.json"
            if not os.path.exists(ib_file):
                send_message(chat_id, "💰 IB TRACKER\n\nNo clients yet.\n\nAdd a client:\nCLIENT: John BROKER: puprime LOTS: 50 GOLD: 10", main_menu())
            else:
                with open(ib_file) as f:
                    clients = json.load(f)
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
            send_message(chat_id, "Error: "+str(e), main_menu())

    elif text_lower.startswith("client:"):
        try:
            ib_file = "/root/tradingbot/ib_clients.json"
            parts = text.upper().replace("CLIENT:","").strip().split()
            name = parts[0]
            broker = [p for p in parts if p.startswith("BROKER:")][0].replace("BROKER:","").lower()
            lots = float([p for p in parts if p.startswith("LOTS:")][0].replace("LOTS:",""))
            gold = float([p for p in parts if p.startswith("GOLD:")][0].replace("GOLD:","")) if any(p.startswith("GOLD:") for p in parts) else 0
            clients = []
            if os.path.exists(ib_file):
                with open(ib_file) as f:
                    clients = json.load(f)
            existing = [c for c in clients if c["name"] == name]
            if existing:
                existing[0]["lots"] = lots
                existing[0]["gold"] = gold
            else:
                clients.append({"name":name,"broker":broker,"lots":lots,"gold":gold})
            with open(ib_file,"w") as f:
                json.dump(clients,f)
            send_message(chat_id, "👤 Client "+name+" saved!", main_menu())
        except:
            send_message(chat_id, "Format:\nCLIENT: John BROKER: puprime LOTS: 50 GOLD: 10", main_menu())

    elif text_lower in ["🧮 commission calc", "/commission"]:
        send_message(chat_id, "🧮 COMMISSION CALCULATOR\n\nCalculate your IB earnings:\n\nCALC: puprime LOTS: 100 GOLD: 20\n\nPU Prime rates:\nForex: $18/lot\nGold: $25/lot\n\nEquiti rates:\nForex: $7/lot\nGold: $5/lot", main_menu())

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
        except:
            send_message(chat_id, "Format:\nCALC: puprime LOTS: 100 GOLD: 20", main_menu())

    elif text_lower in ["📜 signal history", "/history"]:
        try:
            trades_file = "/root/tradingbot/open_trades.json"
            stats_file = "/root/tradingbot/trade_stats.json"
            last_signals_file = "/root/tradingbot/last_signals_smc.json"
            stats = {"wins":0,"losses":0}
            if os.path.exists(stats_file):
                with open(stats_file) as f:
                    stats = json.load(f)
            last_signals = {}
            if os.path.exists(last_signals_file):
                with open(last_signals_file) as f:
                    last_signals = json.load(f)
            total = stats["wins"]+stats["losses"]
            wr = round((stats["wins"]/total)*100,1) if total > 0 else 0
            from datetime import datetime as dt4
            lines_h = ["📜 SIGNAL HISTORY"]
            lines_h.append("🟢 Wins: "+str(stats["wins"])+" | 🔴 Losses: "+str(stats["losses"])+" | WR: "+str(wr)+"%")
            lines_h.append("Last signals:")
            for pair, data in list(last_signals.items())[-10:]:
                sig = data.get("signal","")
                t = data.get("time",0)
                sig_emoji = "🟢" if sig == "BUY" else "🔴"
                time_str = dt4.fromtimestamp(t).strftime("%d/%m %H:%M") if t else ""
                lines_h.append(sig_emoji+" "+pair+" "+sig+" | "+time_str)
            send_message(chat_id, "\n".join(lines_h), main_menu())
        except Exception as e:
            send_message(chat_id, "Error: "+str(e), main_menu())

    elif text_lower in ["📍 s&r levels", "/sr"]:
        send_typing(chat_id)
        try:
            import yfinance as yf
            pairs = {"EUR/USD":"EURUSD=X","GBP/USD":"GBPUSD=X","XAU/USD":"GC=F","BTC/USD":"BTC-USD","Oil/USD":"CL=F","USD/JPY":"USDJPY=X","USD/CHF":"USDCHF=X","AUD/USD":"AUDUSD=X","NZD/USD":"NZDUSD=X","USD/CAD":"USDCAD=X","SOL/USD":"SOL-USD","Silver/USD":"SI=F","Copper/USD":"HG=F","DXY":"DX-Y.NYB"}
            lines_sr = ["📍 SUPPORT & RESISTANCE"]
            for name, symbol in pairs.items():
                try:
                    df = yf.Ticker(symbol).history(period="30d", interval="1d")
                    if len(df) < 10: continue
                    price = df["Close"].iloc[-1]
                    highs = df["High"].nlargest(3).values
                    lows = df["Low"].nsmallest(3).values
                    r1 = round(highs[0],4)
                    r2 = round(highs[1],4)
                    s1 = round(lows[0],4)
                    s2 = round(lows[1],4)
                    lines_sr.append("\n"+name+" | "+str(round(price,4)))
                    lines_sr.append("🔴 R2: "+str(r2)+" | R1: "+str(r1))
                    lines_sr.append("🟢 S1: "+str(s1)+" | S2: "+str(s2))
                except Exception as e:
                    print(f"S&R pair error {name}: {e}")
            send_message(chat_id, "\n".join(lines_sr), main_menu())
        except Exception as e:
            send_message(chat_id, "Error: "+str(e), main_menu())

def main():
    set_commands()
    offset = None
    print("Listener started...")
    while True:
        try:
            result = get_updates(offset)
            for update in result.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = msg.get("text", "")
                username = msg.get("from", {}).get("username", "")
                if text and chat_id:
                    handle_message(chat_id, text, username)
                callback = update.get("callback_query", {})
                if callback:
                    cb_chat_id = str(callback.get("message", {}).get("chat", {}).get("id", ""))
                    cb_data = callback.get("data", "")
                    cb_id = callback.get("id", "")
                    answer_callback(cb_id)
                    if cb_data == "cmd_news":
                        handle_message(cb_chat_id, "🌍 news", "")
                    elif cb_data == "cmd_analysis":
                        handle_message(cb_chat_id, "📊 analysis", "")
                    elif cb_data == "cmd_sentiment":
                        handle_message(cb_chat_id, "🧠 sentiment", "")
                    elif cb_data == "cmd_calendar":
                        handle_message(cb_chat_id, "📅 calendar", "")
                    elif cb_data == "cmd_status":
                        handle_message(cb_chat_id, "📋 status", "")
                    elif cb_data == "open_menu":
                        requests.post("https://api.telegram.org/bot"+TELEGRAM_TOKEN+"/editMessageText",
                            json={"chat_id": cb_chat_id, "message_id": callback.get("message",{}).get("message_id"), "text": WELCOME, "reply_markup": inline_main_menu()})
        except Exception as e:
            print("Error: "+str(e))
            time.sleep(5)

if __name__ == "__main__":
    main()
