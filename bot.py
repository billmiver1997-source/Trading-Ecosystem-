import os
from dotenv import load_dotenv
load_dotenv("/root/tradingbot/.env")

import asyncio
import fcntl
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

if not TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN_MAIN is not set in environment")
if not ANTHROPIC_API_KEY:
    raise RuntimeError("ANTHROPIC_API_KEY is not set in environment")

def load_profiles():
    if os.path.exists(PROFILES_FILE):
        try:
            with open(PROFILES_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError, OSError) as e:
            logging.error("load_profiles error: %s", e)
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
                    logging.error("save_profile error: %s", e)
        finally:
            fcntl.flock(_lf, fcntl.LOCK_UN)

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
            prev_price = prev.iloc[-1] if len(prev) > 0 else df["Close"].iloc[-25]
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
    system = (
        "You are a trading educator at Trading Nova. Write in plain text only — "
        "no markdown, no asterisks, no bold/italic formatting. Use emojis naturally throughout. "
        "Be direct, practical, and engaging. Real examples over theory. "
        "Write like a mentor talking to a student, not a textbook. Never be generic."
    )
    prompts = {
        "forex": (
            "Teach a complete beginner what Forex trading is. Cover: what it is, how currency pairs work "
            "(use EUR/USD as an example), what actually moves prices (interest rates, economic data, capital flows), "
            "and why so many retail traders participate. Give one concrete real-world example. "
            "Engaging, practical, 180-200 words. Use emojis."
        ),
        "crypto": (
            "Teach a beginner about cryptocurrency trading. Cover: how crypto markets differ from forex "
            "(24/7, high volatility, sentiment-driven), Bitcoin vs altcoins and how BTC dominance affects the market, "
            "what actually moves crypto prices (news, on-chain data, macro), and one honest insight about the risk. "
            "180-200 words. Emojis."
        ),
        "cfd": (
            "Explain CFD (Contract for Difference) trading so a beginner truly understands it. Cover: what a CFD actually is, "
            "how you profit whether price goes up OR down, how leverage amplifies both gains and losses, "
            "why traders use CFDs instead of buying the asset directly, and the key risks to know before starting. "
            "Use a simple real-world analogy. 180-200 words. Emojis."
        ),
        "smc": (
            "Teach Smart Money Concepts as used by professional traders. Cover: who Smart Money is (banks, hedge funds, institutions) "
            "and why they move markets differently than retail traders, "
            "Break of Structure (BOS) — what it means when price breaks a key high or low, "
            "Change of Character (CHoCH) — the first sign a trend is reversing, "
            "Order Blocks — where institutions placed large orders that act as future support/resistance, "
            "Fair Value Gaps (FVG) — price imbalances that tend to get filled. "
            "Explain how retail traders use this to trade WITH institutions, not against them. "
            "Be specific. 180-200 words. Emojis."
        ),
        "risk": (
            "Teach risk management as the single most important skill in trading. Cover: "
            "the 1-2% rule (never risk more than 1-2% of your account on one trade and why), "
            "position sizing — how to calculate your lot size based on account balance, risk %, and stop loss distance, "
            "the Risk:Reward ratio and why a minimum 1:2 R:R matters even with a 40% win rate, "
            "and the psychology of protecting capital first, profits second. "
            "Include one concrete calculation example. Be direct — this is what separates traders who last from those who don't. "
            "180-200 words. Emojis."
        ),
        "indicators": (
            "Explain the 4 most important technical indicators and how traders actually use them — not just what they are. "
            "RSI: what overbought/oversold really means and when NOT to fade it, "
            "MACD: how the crossover and histogram tell you about momentum shifts, "
            "EMA: why dynamic levels matter more than static ones and the golden/death cross, "
            "Bollinger Bands: reading volatility compression (squeeze) and breakouts. "
            "Most importantly: explain how these 4 work TOGETHER to confirm a signal, not as isolated tools. "
            "180-200 words. Emojis."
        ),
        "patterns": (
            "Teach the most reliable chart patterns and WHY they work, not just what they look like. "
            "Head & Shoulders: what the left shoulder, head, and right shoulder represent in terms of buyer exhaustion, "
            "Double Top/Bottom: why the second test of a level is so significant, "
            "Triangle (ascending/descending/symmetrical): what the tightening range signals about the coming move, "
            "Flag/Pennant: why strong momentum after a pause tends to continue. "
            "For each: entry, invalidation level, and the psychological reason behind the pattern. "
            "180-200 words. Emojis."
        ),
        "glossary": (
            "Write a trading glossary every beginner must memorize before they risk real money. "
            "Define each term practically — not dictionary definitions, but what it means IN A TRADE: "
            "Pip (the smallest price move and why it matters for P&L), "
            "Lot size (standard/mini/micro and how it connects to pip value), "
            "Leverage (power and danger in one number), "
            "Spread (the hidden cost of every trade), "
            "Margin and Margin Call (what happens when a trade goes wrong), "
            "Swap/Rollover (overnight cost or credit), "
            "Liquidity (why some pairs are safer to trade), "
            "Volatility (risk and opportunity), "
            "Bull/Bear market (more than just up/down). "
            "180-200 words. Emojis."
        ),
        "cryptotrading": (
            "Explain how crypto trading actually works for someone ready to go beyond just buying and holding. "
            "Cover: spot trading (owning the asset) vs futures/perpetuals (trading the price without owning), "
            "how leverage in crypto is even more dangerous than in forex and why, "
            "CEX vs DEX — centralized vs decentralized exchanges and the trade-offs, "
            "Bitcoin dominance and how it affects altcoin seasons, "
            "and 3 specific things that make crypto fundamentally different from forex trading. "
            "Be honest about the risk-reward reality. 180-200 words. Emojis."
        ),
        "defi": (
            "Explain DeFi for someone with a trading background who wants to understand the space. "
            "Cover: what DeFi actually is vs traditional finance and what problem it solves, "
            "DEX vs CEX — the difference in custody, fees, and slippage, "
            "liquidity pools: how they work, what impermanent loss is, and why people still provide liquidity, "
            "staking: what you're actually doing and the difference between real yield and inflation rewards, "
            "NFTs: what they represent beyond the hype and where actual utility exists. "
            "Be practical — what does a trader need to know to navigate this space safely? 180-200 words. Emojis."
        ),
        "psychology": (
            "Teach trading psychology — the real reason most traders fail, and it's not their strategy. "
            "Cover: FOMO and how chasing entries after missing a move is one of the most expensive habits in trading, "
            "revenge trading — the emotional spiral after a loss that turns one bad trade into an account blowup, "
            "discipline — following your plan when your gut screams otherwise, "
            "process vs outcome — understanding that a well-executed trade that loses is still a good trade, "
            "and one specific mental technique professionals use to stay neutral. "
            "Use a scenario most traders will immediately recognise. 180-200 words. Emojis."
        ),
        "howtostart": (
            "Write an honest, step-by-step guide for someone who wants to start trading today. "
            "Step 1 — Education first: what to study and in what order (markets, risk, then strategy), "
            "Step 2 — Choose a broker: what actually matters (regulation, spreads, platform), "
            "Step 3 — Demo trading: what to do on demo and for how long before going live, "
            "Step 4 — Risk management before your first live trade: the one rule you cannot break, "
            "Step 5 — Start with micro lots: why small size is not about money, it's about building discipline. "
            "Be honest about the timeline — profitable trading takes months to years, not days. "
            "180-200 words. Emojis."
        ),
    }
    prompt_text = prompts.get(topic)
    if not prompt_text:
        return "Education content for this topic is not available."
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=system,
            messages=[{"role": "user", "content": prompt_text}]
        )
        return message.content[0].text
    except Exception as e:
        logging.error("Education API error for topic '%s': %s", topic, e)
        return "Education content temporarily unavailable. Please try again later."

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    name = user.first_name or ""
    await asyncio.to_thread(save_profile, user.id, user.username or "", name)
    await update.message.reply_text(get_welcome(name), reply_markup=main_menu())
    try:
        username = "@"+user.username if user.username else "no username"
        notify = "\U0001f514 NEW USER\n\nName: "+name+" | "+username+"\nID: "+str(user.id)
        await context.bot.send_message(chat_id=OWNER_ID, text=notify)
    except Exception as e:
        logging.error("Owner notify error: %s", e)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
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
            "Perfect starting point \U0001f5fa️\n\n"
            "Most people who lose money in trading skip the fundamentals. Don't be that trader.\n\n"
            "Here's the order that actually works:\n\n"
            "1️⃣ Forex Basics — understand what you're actually trading and why prices move\n"
            "2️⃣ Risk Management — this alone separates traders who last from those who don't\n"
            "3️⃣ Chart Patterns + Indicators — learn to read what the market is doing\n"
            "4️⃣ Smart Money Concepts — how institutions move price and how to follow them\n"
            "5️⃣ Signals Bot — watch real trades with Entry, SL & TP as they happen\n\n"
            "One topic at a time. Tap \U0001f4da Education below \U0001f447"
        )
        await update.message.reply_text(msg, reply_markup=main_menu())

    elif text == "\U0001f4c8 I'm Experienced":
        msg = (
            "Good. Here's what the ecosystem gives you \U0001f4bc\n\n"
            "\U0001f4ca Live prices — 14 pairs updated in real time\n"
            "\U0001f4c8 Signals — BUY/SELL with Entry, SL & TP, sent only when a real setup exists\n"
            "\U0001f4f0 News — AI-filtered briefings 6x daily, no noise\n"
            "\U0001f4c5 Economic Calendar — know what's moving markets before it happens\n"
            "\U0001f9e0 Daily Sentiment — Fear & Greed, DXY, Gold, VIX in one read\n"
            "\U0001f4ca MTF Analysis — 15m/1H/4H alignment check for any pair on demand\n\n"
            "Join the channels below and you're set \U0001f447"
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
        await update.message.reply_text("What do you want to learn today?", reply_markup=edu_menu())
    elif text == "\U0001f4b9 Brokers":
        msg = ("💹 TMGM | Trade. Markets. Growth. Mastery.\n\nThe broker powering the Nova ecosystem. Regulated, institutional-grade, and trusted by traders worldwide.\n\n📌 12,000+ instruments — Forex, Stocks, Indices, Commodities, Crypto\n📌 Spreads from 0.0 pips — on major pairs\n📌 Leverage up to 1:500\n📌 MT4 & MT5 — fully supported\n📌 ASIC & VFSC regulated\n📌 Fast execution, deep liquidity\n📌 24/7 multilingual support\n\n🎯 Referral Code: IB1750034233G\n\nOpen your account and unlock the full Nova ecosystem:")
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
            "One ecosystem. Everything a trader needs, in one place.\n\n"
            "\U0001f4c8 Signals — live BUY/SELL signals with Entry, SL & TP. Sent only when a real setup is detected, not on a schedule.\n"
            "\U0001f4f0 News — AI-filtered market intelligence 6x daily. No noise, no clickbait. Just what matters for your positions.\n"
            "\U0001f4c5 Calendar — high-impact economic events every morning at 08:00 so you're never caught off guard.\n"
            "\U0001f9e0 Sentiment — daily read on Fear & Greed, DXY, Gold and VIX. Know what the market is feeling before you trade.\n"
            "\U0001f4ca Updates — daily trading tips, psychology insights, and weekly market previews.\n\n"
            "\U0001f447 Join below:"
        )
        await update.message.reply_text(msg, reply_markup=community_links())
    elif text == "\U0001f4b9 TMGM Info":
        msg = (
            "\U0001f4b9 TMGM | Trade. Markets. Growth. Mastery.\n\n"
            "TMGM is the broker behind the Nova ecosystem — regulated, institutional-grade, and built for serious traders.\n\n"
            "What sets them apart:\n\n"
            "📌 12,000+ instruments — Forex, Stocks, Indices, Commodities, Crypto. One account, all markets.\n"
            "📌 Spreads from 0.0 pips — on major pairs, no hidden markups.\n"
            "📌 Leverage up to 1:500 — professional conditions for those who know how to use it.\n"
            "📌 MT4 & MT5 — the platforms traders actually use, fully supported.\n"
            "📌 ASIC regulated (Australia) + VFSC — your capital is protected.\n"
            "📌 Fast execution, deep liquidity — no requotes, no slippage games.\n"
            "📌 24/7 multilingual support — real people, real answers.\n\n"
            "\U0001f3af Referral Code: IB1750034233G\n\n"
            "Open your live account and unlock the full Nova ecosystem:"
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
            "Open a TMGM account through our referral link and get full access to the Nova ecosystem at no cost:\n\n"
            "\U0001f4c8 Trading Signals — BUY/SELL alerts for 12 pairs including Gold, BTC, EUR/USD & more. Each signal includes Entry, SL and TP. Sent only when a high-quality setup is detected.\n\n"
            "\U0001f4f0 News Intelligence — AI-filtered market briefings 6x per day. No noise. Geopolitics, macro, commodities — filtered to what actually moves your trades.\n\n"
            "\U0001f9e0 Market Sentiment — daily report on Fear & Greed, DXY direction, Gold trend and VIX. Know the macro mood before you open a position.\n\n"
            "\U0001f4c5 Economic Calendar — high-impact events every morning at 08:00 so you can plan around volatility, not be surprised by it.\n\n"
            "\U0001f4ca Analysis on Demand — ask for a live AI analysis of any pair, any time, directly in the Signals Bot.\n\n"
            "Takes 3 minutes to open an account \U0001f447"
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
