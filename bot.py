import os
from dotenv import load_dotenv
load_dotenv("/root/tradingbot/.env")

import asyncio
import logging
import json
import anthropic
import yfinance as yf
import pytz
import pandas as pd
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

TOKEN = os.getenv("TELEGRAM_TOKEN_MAIN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OWNER_ID = 8626233751
PROFILES_FILE = "/root/tradingbot/user_profiles.json"
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

def load_profiles():
    if os.path.exists(PROFILES_FILE):
        try:
            with open(PROFILES_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError, OSError) as e:
            logging.error("load_profiles error: %s", e)
    return {}

def save_profile(user_id, username, first_name):
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
            logging.error("save_profile error: %s", e)

def get_welcome(name=""):
    greeting = f"Hey {name}! \U0001f44b" if name else "Hey! \U0001f44b"
    return (
        greeting + " Welcome to Trading Nova.\n\n"
        "We give traders the same tools institutions use \u2014 "
        "signals, news, and analysis \u2014 completely free.\n\n"
        "Here\u2019s what you\u2019ll get:\n"
        "\U0001f4c8 Live signals \u2014 Gold, BTC, EUR/USD & 10+ pairs\n"
        "\U0001f4f0 AI news briefings \u2014 5x daily, only what moves markets\n"
        "\U0001f9e0 Daily sentiment \u2014 Fear & Greed, DXY, VIX\n"
        "\U0001f4c5 Economic calendar \u2014 every morning at 08:00\n"
        "\U0001f4da Education \u2014 Forex, Crypto, SMC, Risk Management\n\n"
        "\U0001f447 What do you want to explore first?\n\n"
        "⚠️ Disclaimer: All content is for educational purposes only and does not constitute financial advice. Trading involves substantial risk of loss. Never invest more than you can afford to lose."
    )

def main_menu():
    return ReplyKeyboardMarkup([
        ["\U0001f680 Quick Start", "\U0001f4ca Market Overview"],
        ["\U0001f4da Education", "\U0001f4b9 Brokers"],
        ["\U0001f4f2 Our Community"],
    ], resize_keyboard=True)

def quick_start_menu():
    return ReplyKeyboardMarkup([
        ["\U0001f331 I'm a Beginner", "\U0001f4c8 I'm Experienced"],
        ["\U0001f519 Back"],
    ], resize_keyboard=True)

def edu_menu():
    return ReplyKeyboardMarkup([
        ["\U0001f4d6 Forex Basics", "\U0001f4d6 Crypto Basics"],
        ["\U0001f4d6 What is CFD?", "\U0001f4d6 What is SMC?"],
        ["\U0001f4d6 Risk Management", "\U0001f4d6 Indicators Guide"],
        ["\U0001f4d6 Chart Patterns", "\U0001f4d6 Trading Glossary"],
        ["\U0001f4d6 Crypto Trading", "\U0001f4d6 DeFi & Web3"],
        ["\U0001f4d6 Trading Psychology", "\U0001f4d6 How to Start"],
        ["\U0001f519 Back"],
    ], resize_keyboard=True)

def broker_menu():
    return ReplyKeyboardMarkup([
        ["\U0001f4b9 TMGM Info"],
        ["\U0001f381 What You Get"],
        ["\U0001f519 Back"],
    ], resize_keyboard=True)

def broker_links():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("\U0001f4b9 Open TMGM Account", url="https://portal.tmgm.com/register?node=MTg3NjEz&language=en")],
    ])

def community_links():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("\U0001f4f0 News Channel", url="https://t.me/tradingNovaNews")],
        [InlineKeyboardButton("\U0001f4c8 Signals Channel", url="https://t.me/novasignalschannel1")],
        [InlineKeyboardButton("\U0001f4e2 Updates Channel", url="https://t.me/TradingVM")],
        [InlineKeyboardButton("\U0001f4ca Signals Bot", url="https://t.me/TradingNovaSignal_bot")],
        [InlineKeyboardButton("\U0001f4f0 News Bot", url="https://t.me/tradingNovaNewsva_bot")],
        [InlineKeyboardButton("\U0001f4ac Telegram Chat", url="https://t.me/+rERowe5ucMA4ODM0")],
        [InlineKeyboardButton("\U0001f3a6 TikTok", url="https://www.tiktok.com/@nova.ecosystem?_r=1&_t=ZN-978yb8ClCUQ")],
        [InlineKeyboardButton("\U0001f4f7 Instagram", url="https://www.instagram.com/novaecosystemf?igsh=NmEzeHUwcDZ1ejZ2&utm_source=qr")],
    ])

def get_market_overview():
    pairs = {
        "\U0001f1ea\U0001f1fa EUR/USD": "EURUSD=X",
        "\U0001f1ec\U0001f1e7 GBP/USD": "GBPUSD=X",
        "\U0001f1fa\U0001f1f8 USD/CHF": "USDCHF=X",
        "\U0001f1ef\U0001f1f5 USD/JPY": "USDJPY=X",
        "\U0001f1e6\U0001f1fa AUD/USD": "AUDUSD=X",
        "\U0001f1f3\U0001f1ff NZD/USD": "NZDUSD=X",
        "\U0001f1e8\U0001f1e6 USD/CAD": "USDCAD=X",
        "\U0001fa99 XAU/USD": "GC=F",
        "\U0001f948 Silver/USD": "SI=F",
        "\U0001f7e0 Copper/USD": "HG=F",
        "\u26fd Oil/USD": "CL=F",
        "\U0001f7e1 BTC/USD": "BTC-USD",
        "\U0001f535 SOL/USD": "SOL-USD",
        "\U0001f4b5 DXY": "DX-Y.NYB",
    }
    result = ["\U0001f4ca MARKET OVERVIEW\n"]
    for name, symbol in pairs.items():
        try:
            df = yf.Ticker(symbol).history(period="5d", interval="1h")
            if len(df) < 25:
                continue
            price = df["Close"].iloc[-1]
            cutoff = df.index[-1] - pd.Timedelta(hours=24)
            prev = df["Close"][df.index <= cutoff]
            prev_price = prev.iloc[-1] if len(prev) > 0 else df["Close"].iloc[-24]
            change = ((price - prev_price) / prev_price) * 100
            emoji = "\U0001f7e2" if change > 0 else "\U0001f534"
            result.append(emoji+" "+name+": "+str(round(price,4))+" ("+("{:+.2f}".format(change))+"%)")
        except Exception as e:
            logging.error("Market overview error for %s: %s", name, e)
    tz = pytz.timezone("Europe/Athens")
    now = datetime.now(tz).strftime("%d/%m/%Y %H:%M")
    result.append("\n\U0001f554 "+now)
    return "\n".join(result)

def get_education(topic):
    prompts = {
        "forex": "Explain Forex trading for a beginner. Max 200 words. Use emojis. Plain text only.",
        "crypto": "Explain cryptocurrency trading for a beginner. Max 200 words. Use emojis. Plain text only.",
        "cfd": "Explain CFD trading for a beginner. Max 200 words. Use emojis. Plain text only.",
        "smc": "Explain Smart Money Concepts: Order Blocks, FVG, BOS, CHoCH. Max 200 words. Use emojis. Plain text only.",
        "risk": "Explain risk management in trading. Max 200 words. Use emojis. Plain text only.",
        "indicators": "Explain RSI, MACD, EMA, Bollinger Bands. Max 200 words. Use emojis. Plain text only.",
        "patterns": "Explain chart patterns: Head and Shoulders, Double Top/Bottom, Triangle, Flag. Max 200 words. Use emojis. Plain text only.",
        "glossary": "Trading glossary: Pip, Lot, Leverage, Spread, Margin, Swap, Liquidity, Volatility, Bull/Bear. Use emojis. Plain text only.",
        "cryptotrading": "Explain crypto trading: spot vs futures, leverage, exchanges. Max 200 words. Use emojis. Plain text only.",
        "defi": "Explain DeFi, DEX vs CEX, staking, NFTs. Max 200 words. Use emojis. Plain text only.",
        "psychology": "Explain trading psychology: FOMO, revenge trading, discipline. Max 200 words. Use emojis. Plain text only.",
        "howtostart": "Step by step guide to start trading for a complete beginner. Max 200 words. Use emojis. Plain text only.",
    }
    prompt_text = prompts.get(topic)
    if not prompt_text:
        return "Education content for this topic is not available."
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt_text}]
        )
        return message.content[0].text
    except Exception as e:
        logging.error("Education API error for topic '%s': %s", topic, e)
        return "Education content temporarily unavailable. Please try again later."

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    name = user.first_name or ""
    save_profile(user.id, user.username or "", name)
    await update.message.reply_text(get_welcome(name), reply_markup=main_menu())
    try:
        username = "@"+user.username if user.username else "no username"
        notify = "\U0001f514 NEW USER\n\nName: "+name+" | "+username+"\nID: "+str(user.id)
        await context.bot.send_message(chat_id=OWNER_ID, text=notify)
    except Exception as e:
        print(f"Owner notify error: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "\U0001f519 Back":
        await update.message.reply_text("Main menu:", reply_markup=main_menu())

    elif text == "\U0001f680 Quick Start":
        await update.message.reply_text(
            "Let's personalise your experience.\n\nAre you new to trading or already active in the markets?",
            reply_markup=quick_start_menu()
        )

    elif text == "\U0001f331 I'm a Beginner":
        msg = (
            "Perfect! Here's your beginner roadmap \U0001f5fa️\n\n"
            "1️⃣ Forex Basics — understand how currency markets work\n"
            "2️⃣ Risk Management — the #1 skill every trader needs\n"
            "3️⃣ What is SMC? — how institutions move the market\n"
            "4️⃣ Market Overview — check live prices\n"
            "5️⃣ Join our Signals Bot — follow real trades as they happen\n\n"
            "Take it step by step. Tap \U0001f4da Education below to start \U0001f447"
        )
        await update.message.reply_text(msg, reply_markup=main_menu())

    elif text == "\U0001f4c8 I'm Experienced":
        msg = (
            "Welcome back, trader \U0001f4bc\n\n"
            "Here's what's most useful for you:\n\n"
            "\U0001f4ca Market Overview — live prices for 14 pairs\n"
            "\U0001f4c8 Signals Bot — BUY/SELL alerts with Entry, SL & TP\n"
            "\U0001f4f0 News Bot — AI-filtered news on demand by category\n"
            "\U0001f4c5 Economic Calendar — plan around high-impact events\n"
            "\U0001f9e0 Daily Sentiment — Fear & Greed, DXY, VIX\n\n"
            "Jump straight into our ecosystem \U0001f447"
        )
        await update.message.reply_text(msg, reply_markup=community_links())

    elif text == "\U0001f4da Education":
        edu_caption = "TMGM Academy - Access world-class trading education."
        try:
            with open("/root/tradingbot/tmgm_logo.png", "rb") as photo:
                await context.bot.send_photo(chat_id=update.effective_chat.id, photo=photo, caption=edu_caption, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("TMGM Academy", url="https://www.tmgm.com/en/academy/overview")]]))
        except Exception as e:
            logging.warning("Education photo send failed: %s", e)
            await update.message.reply_text(edu_caption, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("TMGM Academy", url="https://www.tmgm.com/en/academy/overview")]]))
        await update.message.reply_text("Choose a topic:", reply_markup=edu_menu())
    elif text == "\U0001f4b9 Brokers":
        msg = ("💹 TMGM | Trade. Markets. Growth. Mastery.\n\nTMGM is an institutional-grade broker offering world-class trading conditions.\n\n📌 Key Features:\n- 12,000+ instruments (Forex, Stocks, Indices, Commodities, Crypto)\n- Leverage up to 1:500\n- Ultra-low spreads from 0.0 pips\n- MT4 & MT5 platforms\n- Regulated: ASIC (Australia) & VFSC\n- Fast execution & deep liquidity\n- 24/7 multilingual support\n\n🎯 Refer Code: IB1750034233G\n\nOpen your account and start trading with institutional conditions:")
        try:
            with open("/root/tradingbot/tmgm_logo.png", "rb") as photo:
                await context.bot.send_photo(chat_id=update.effective_chat.id, photo=photo, caption=msg, reply_markup=broker_links())
        except Exception as e:
            logging.warning("Brokers photo send failed: %s", e)
            await update.message.reply_text(msg, reply_markup=broker_links())
        # Show navigation keyboard so TMGM Info / What You Get buttons are reachable
        await update.message.reply_text("Explore more:", reply_markup=broker_menu())
    elif text == "\U0001f4ca Market Overview":
        await update.message.reply_text("\U0001f504 Loading...", reply_markup=main_menu())
        overview = await asyncio.to_thread(get_market_overview)
        await update.message.reply_text(overview, reply_markup=main_menu())

    elif text == "\U0001f4f2 Our Community":
        msg = (
            "\U0001f4f2 THE NOVA ECOSYSTEM\n\n"
            "Everything below is free when you trade through our partner brokers:\n\n"
            "\U0001f4c8 Signals Bot — live BUY/SELL signals 24/7\n"
            "\U0001f4f0 News Bot — AI briefings 5x daily, by category\n"
            "\U0001f4c5 Calendar alerts every morning at 08:00\n"
            "\U0001f9e0 Daily market sentiment reports\n"
            "\U0001f3af Weekly backtest results every Sunday\n\n"
            "\U0001f447 Tap to join:"
        )
        await update.message.reply_text(msg, reply_markup=community_links())
    elif text == "\U0001f4b9 TMGM Info":
        msg = (
            "\U0001f4b9 TMGM | Trade. Markets. Growth. Mastery.\n\n"
            "TMGM is an institutional-grade broker offering world-class trading conditions.\n\n"
            "\U0001f4cc Key Features:\n"
            "- 12,000+ instruments (Forex, Stocks, Indices, Commodities, Crypto)\n"
            "- Leverage up to 1:500\n"
            "- Ultra-low spreads from 0.0 pips\n"
            "- MT4 & MT5 platforms\n"
            "- Regulated: ASIC (Australia) & VFSC\n"
            "- Fast execution & deep liquidity\n"
            "- 24/7 multilingual support\n\n"
            "\U0001f3af Refer Code: IB1750034233G\n\n"
            "Open your account and start trading with institutional conditions:"
        )
        try:
            with open("/root/tradingbot/tmgm_logo.png", "rb") as photo:
                await context.bot.send_photo(chat_id=update.effective_chat.id, photo=photo, caption=msg, reply_markup=broker_links())
        except Exception as e:
            logging.warning("TMGM Info photo send failed: %s", e)
            await update.message.reply_text(msg, reply_markup=broker_links())
    elif text == "\U0001f381 What You Get":
        msg = (
            "\U0001f381 WHAT YOU GET — 100% FREE\n\n"
            "Open a TMGM account through our referral link and unlock:\n\n"
            "\U0001f4c8 Trading Signals — 24/7 BUY/SELL for Gold, BTC & Forex\n"
            "\U0001f4f0 News Briefings — AI-filtered, 5x daily\n"
            "\U0001f9e0 Market Sentiment — daily Fear & Greed + DXY + VIX\n"
            "\U0001f4c5 Economic Calendar — every morning at 08:00\n"
            "\U0001f3af Performance Tracker — live win rate & P&L\n"
            "\U0001f4ca Weekly Backtests — strategy results every Sunday\n\n"
            "Open your account in under 3 minutes \U0001f447"
        )
        await update.message.reply_text(msg, reply_markup=broker_links())
    elif text == "\U0001f4d6 Forex Basics":
        await update.message.reply_text("\U0001f504 Loading...", reply_markup=edu_menu())
        await update.message.reply_text(await asyncio.to_thread(get_education, "forex"), reply_markup=edu_menu())
    elif text == "\U0001f4d6 Crypto Basics":
        await update.message.reply_text("\U0001f504 Loading...", reply_markup=edu_menu())
        await update.message.reply_text(await asyncio.to_thread(get_education, "crypto"), reply_markup=edu_menu())
    elif text == "\U0001f4d6 What is CFD?":
        await update.message.reply_text("\U0001f504 Loading...", reply_markup=edu_menu())
        await update.message.reply_text(await asyncio.to_thread(get_education, "cfd"), reply_markup=edu_menu())
    elif text == "\U0001f4d6 What is SMC?":
        await update.message.reply_text("\U0001f504 Loading...", reply_markup=edu_menu())
        await update.message.reply_text(await asyncio.to_thread(get_education, "smc"), reply_markup=edu_menu())
    elif text == "\U0001f4d6 Risk Management":
        await update.message.reply_text("\U0001f504 Loading...", reply_markup=edu_menu())
        await update.message.reply_text(await asyncio.to_thread(get_education, "risk"), reply_markup=edu_menu())
    elif text == "\U0001f4d6 Indicators Guide":
        await update.message.reply_text("\U0001f504 Loading...", reply_markup=edu_menu())
        await update.message.reply_text(await asyncio.to_thread(get_education, "indicators"), reply_markup=edu_menu())
    elif text == "\U0001f4d6 Chart Patterns":
        await update.message.reply_text("\U0001f504 Loading...", reply_markup=edu_menu())
        await update.message.reply_text(await asyncio.to_thread(get_education, "patterns"), reply_markup=edu_menu())
    elif text == "\U0001f4d6 Trading Glossary":
        await update.message.reply_text("\U0001f504 Loading...", reply_markup=edu_menu())
        await update.message.reply_text(await asyncio.to_thread(get_education, "glossary"), reply_markup=edu_menu())
    elif text == "\U0001f4d6 Crypto Trading":
        await update.message.reply_text("\U0001f504 Loading...", reply_markup=edu_menu())
        await update.message.reply_text(await asyncio.to_thread(get_education, "cryptotrading"), reply_markup=edu_menu())
    elif text == "\U0001f4d6 DeFi & Web3":
        await update.message.reply_text("\U0001f504 Loading...", reply_markup=edu_menu())
        await update.message.reply_text(await asyncio.to_thread(get_education, "defi"), reply_markup=edu_menu())
    elif text == "\U0001f4d6 Trading Psychology":
        await update.message.reply_text("\U0001f504 Loading...", reply_markup=edu_menu())
        await update.message.reply_text(await asyncio.to_thread(get_education, "psychology"), reply_markup=edu_menu())
    elif text == "\U0001f4d6 How to Start":
        await update.message.reply_text("\U0001f504 Loading...", reply_markup=edu_menu())
        await update.message.reply_text(await asyncio.to_thread(get_education, "howtostart"), reply_markup=edu_menu())

    else:
        await update.message.reply_text("Choose an option below \U0001f447", reply_markup=main_menu())

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user is None or user.id != OWNER_ID:
        await update.message.reply_text("❌ Not authorized.")
        return
    profiles = load_profiles()
    total = len(profiles)
    lines = ["📊 BOT STATS\n", f"👥 Unique users: {total}\n", "🕐 Last 10 joined:"]
    items = list(profiles.items())[-10:]
    for uid, data in reversed(items):
        uname = "@"+data["username"] if data["username"] else data["first_name"] or f"ID:{uid}"
        lines.append(f"• {uname} | {data.get('joined', 'N/A')}")
    await update.message.reply_text("\n".join(lines), reply_markup=main_menu())

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("stats", stats))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

if __name__ == "__main__":
    print("Trading Nova VA Bot started!")
    app.run_polling()
