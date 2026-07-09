import os
from dotenv import load_dotenv
load_dotenv("/root/tradingbot/.env")

import asyncio
import logging
import json
import anthropic
import yfinance as yf
import pytz
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

TOKEN = os.getenv("TELEGRAM_TOKEN_MAIN")
if not TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN_MAIN is not set in environment")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OWNER_ID = 8626233751
USERS_FILE = "/root/tradingbot/users.json"

def load_users():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE) as f:
                data = json.load(f)
                # Migration: αν είναι παλιά μορφή (list of strings)
                if data and isinstance(data[0], str):
                    return {}
                return {u["id"]: u for u in data} if isinstance(data, list) else data
        except (json.JSONDecodeError, ValueError, OSError) as e:
            print(f"load_users error: {e}")
    return {}

def save_users(users):
    tmp = USERS_FILE + '.tmp'
    try:
        with open(tmp, 'w') as f:
            json.dump(list(users.values()), f, indent=2, ensure_ascii=False)
        os.replace(tmp, USERS_FILE)
    except Exception as e:
        print(f"save_users error: {e}")

def track_user(user, bot_name="main"):
    tz = pytz.timezone("Europe/Athens")
    now = datetime.now(tz).strftime("%d/%m/%Y %H:%M")
    users = load_users()
    uid = str(user.id)
    is_new = uid not in users
    if is_new:
        users[uid] = {
            "id": uid,
            "username": "@"+user.username if user.username else "no_username",
            "first_name": user.first_name or "",
            "last_name": user.last_name or "",
            "first_seen": now,
            "last_seen": now,
            "visits": 1,
            "bot": bot_name
        }
    else:
        users[uid]["last_seen"] = now
        users[uid]["visits"] = users[uid].get("visits", 0) + 1
        users[uid]["username"] = "@"+user.username if user.username else "no_username"
        users[uid]["first_name"] = user.first_name or ""
    save_users(users)
    return is_new, users[uid]
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
# httpx/httpcore log each request URL at INFO, which embeds the bot token
# (https://api.telegram.org/bot<TOKEN>/...) directly into the system journal.
# Silence them specifically rather than lowering the app's own log level.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

WELCOME = (
    "\U0001f680 Welcome to the Trading Nova Ecosystem!\n\n"
    "Your AI assistant for financial markets is active. "
    "Whether you are a beginner building your foundations or an experienced trader scaling your strategy, "
    "the Nova Ecosystem is created to elevate your edge.\n\n"
    "\u26a1 What you can explore here:\n\n"
    "\U0001f4da AI-Driven Education: Master Forex, Crypto, SMC, and Risk Management.\n\n"
    "\U0001f4ca Market Overview: Track live price feeds for 14 major asset pairs.\n\n"
    "\U0001f4b9 Elite Brokerage: Access institutional-grade trading conditions.\n\n"
    "\U0001f381 Nova Ecosystem: Unlock our premium Signals and News Bots.\n\n"
    "\U0001f447 Select an option below to begin your journey:"
)

def main_menu():
    return ReplyKeyboardMarkup([
        ["\U0001f4da Education", "\U0001f4b9 Brokers"],
        ["\U0001f4ca Market Overview", "\U0001f4f2 Our Community"],
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
            if len(df) < 25:  # need at least 24 bars back for the 24h change
                continue
            price = df["Close"].iloc[-1]
            change = ((df["Close"].iloc[-1] - df["Close"].iloc[-25]) / df["Close"].iloc[-25]) * 100
            emoji = "\U0001f7e2" if change > 0 else "\U0001f534"
            result.append(emoji+" "+name+": "+str(round(price,4))+" ("+("{:+.2f}".format(change))+"%)")
        except Exception as e:
            print(f"get_market_overview error {name}: {e}")
    tz = pytz.timezone("Europe/Athens")
    now = datetime.now(tz).strftime("%d/%m/%Y %H:%M")
    result.append("\n\U0001f554 "+now)
    return "\n".join(result)

def get_education(topic):
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
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
        prompt_text = prompts.get(topic, "")
        if not prompt_text:
            return "Education content for this topic is not available."
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt_text}]
        )
        return message.content[0].text
    except Exception as e:
        print(f"get_education error ({topic}): {e}")
        return "Education content temporarily unavailable. Please try again."

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME, reply_markup=main_menu())
    try:
        user = update.effective_user
        name = user.first_name or ""
        username = "@"+user.username if user.username else "no username"
        notify = "\U0001f514 NEW USER on Nova Main Bot!\n\nName: "+name+" | "+username+"\nID: "+str(user.id)
        await context.bot.send_message(chat_id=OWNER_ID, text=notify)
    except Exception as e:
        print(f"start notify error: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "\U0001f519 Back":
        await update.message.reply_text("Main menu:", reply_markup=main_menu())
    elif text == "\U0001f4da Education":
        edu_caption = "TMGM Academy - Access world-class trading education."
        try:
            with open("/opt/tradingbot/tmgm_logo.png", "rb") as photo:
                await context.bot.send_photo(chat_id=update.effective_chat.id, photo=photo, caption=edu_caption, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("TMGM Academy", url="https://www.tmgm.com/en/academy/overview")]]))
        except (FileNotFoundError, OSError) as e:
            print(f"Education logo missing: {e}")
        except Exception as e:
            print(f"send_photo error (education): {e}")
        await update.message.reply_text("Choose a topic:", reply_markup=edu_menu())
    elif text == "\U0001f4b9 Brokers":
        msg = ("💹 TMGM | Trade. Markets. Growth. Mastery.\n\nTMGM is an institutional-grade broker offering world-class trading conditions.\n\n📌 Key Features:\n- 12,000+ instruments (Forex, Stocks, Indices, Commodities, Crypto)\n- Leverage up to 1:500\n- Ultra-low spreads from 0.0 pips\n- MT4 & MT5 platforms\n- Regulated: ASIC (Australia) & VFSC\n- Fast execution & deep liquidity\n- 24/7 multilingual support\n\n🎯 Refer Code: IB1750034233G\n\nOpen your account and start trading with institutional conditions:")
        try:
            with open("/opt/tradingbot/tmgm_logo.png", "rb") as photo:
                await context.bot.send_photo(chat_id=update.effective_chat.id, photo=photo, caption=msg, reply_markup=broker_links())
        except (FileNotFoundError, OSError) as e:
            print(f"Broker logo missing: {e}")
            await update.message.reply_text(msg, reply_markup=broker_links())
        except Exception as e:
            print(f"send_photo error (brokers): {e}")
            await update.message.reply_text(msg, reply_markup=broker_links())
        await update.message.reply_text("Choose an option:", reply_markup=broker_menu())
    elif text == "\U0001f4ca Market Overview":
        await update.message.reply_text("\U0001f504 Loading...", reply_markup=main_menu())
        overview = await asyncio.to_thread(get_market_overview)
        await update.message.reply_text(overview, reply_markup=main_menu())

    elif text == "\U0001f4f2 Our Community":
        await update.message.reply_text("\U0001f4f2 Join our community:", reply_markup=community_links())
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
            with open("/opt/tradingbot/tmgm_logo.png", "rb") as photo:
                await context.bot.send_photo(chat_id=update.effective_chat.id, photo=photo, caption=msg, reply_markup=broker_links())
        except (FileNotFoundError, OSError) as e:
            print(f"TMGM info logo missing: {e}")
            await update.message.reply_text(msg, reply_markup=broker_links())
        except Exception as e:
            print(f"send_photo error (TMGM info): {e}")
            await update.message.reply_text(msg, reply_markup=broker_links())
    elif text == "\U0001f381 What You Get":
        msg = (
            "\U0001f381 WHAT YOU GET FOR FREE\n\n"
            "Open a TMGM account through our link:\n\n"
            "\U0001f4ca Trading Signals 24/7\n"
            "\U0001f4f0 News every 4 hours\n"
            "\U0001f9e0 Daily Market Sentiment\n"
            "\U0001f4c5 Economic Calendar\n"
            "\U0001f3af Performance Tracking\n\n"
            "100% FREE:"
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

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

if __name__ == "__main__":
    print("Trading Nova VA Bot started!")
    app.run_polling()
