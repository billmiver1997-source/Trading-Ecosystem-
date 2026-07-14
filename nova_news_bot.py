import os
from dotenv import load_dotenv
load_dotenv("/root/tradingbot/.env")

import asyncio
import random
import requests
import anthropic
import feedparser
import pytz
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

TOKEN = os.getenv("TELEGRAM_TOKEN_NEWS")
if not TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN_NEWS is not set in environment")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    raise RuntimeError("ANTHROPIC_API_KEY is not set in environment")
# Create once at module level — avoids rebuilding the client on every summary call
_anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

MAIN_MENU = ReplyKeyboardMarkup([
    ["🇺🇦 Ukraine", "🇬🇷 Ελλάδα"],
    ["💹 Finance", "🌍 Geopolitics"],
    ["🛒 Markets", "📰 Latest News"],
    ["📅 Calendar", "🧠 Sentiment"],
], resize_keyboard=True)

KEYWORDS = {
    "ukraine": ["ukraine","zelensky","kyiv","kharkiv","donbas","russia ukraine","war ukraine","ceasefire ukraine","zelenskyy","ukraine war","nato ukraine"],
    "finance": ["fed","rate","inflation","gdp","central bank","ecb","boe","interest rate","recession","bond","yield","dollar","forex","currency","gold","oil","crypto","bitcoin","market rally","market crash","stock"],
    "geopolitics": ["trump","election","nato","sanctions","iran","israel","china","taiwan","russia","war","attack","missile","nuclear","coup","president","government","diplomacy","treaty"],
    "markets": ["trade","tariff","import","export","supply chain","commodity","wto","imf","world bank","gdp growth","economic growth","manufacturing","retail","consumer","employment","jobs"]
}

GREEK_FEEDS = [
    "https://www.naftemporiki.gr/feed/",
    "https://www.naftemporiki.gr/category/economy/feed/",
    "https://www.naftemporiki.gr/category/stock-market/feed/",
    "https://www.iefimerida.gr/rss.xml",
    "https://www.protothema.gr/rss/",
    "https://www.in.gr/feed/",
]

GREECE_KEYWORDS = [
    "ελλάδα","ελληνικ","κυβέρνηση","βουλή","μητσοτάκης","τσίπρας","σύριζα","νέα δημοκρατία",
    "χρηματιστήριο","επένδυσ","επιχείρηση","εξαγωγ","εισαγωγ","εμπόριο","οικονομία",
    "υπουργ","πρωθυπουργ","δημόσιο","φορολογ","ασφαλιστικ","συντάξ","μισθ",
    "τουρισμ","ναυτιλ","ελληνοτουρκ","αιγαίο","κύπρ","νατο ελλάδα",
    "επιχειρηματ","startup","επενδυτ","χρηματοδότ","αγορά","τράπεζ"
]

GREECE_EXCLUDE = [
    "bitcoin","crypto","κρυπτο","ethereum","nft","defi",
    "ιταλία","γερμανία","γαλλία","ισπανία","αμερική","τουρκία","ρωσία","ουκρανία"
]

UKRAINE_FEEDS = [
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://rss.reuters.com/reuters/worldNews",
    "https://www.ukrinform.net/rss/block-lastnews",
    "https://kyivindependent.com/feed/",
    "https://feeds.skynews.com/feeds/rss/world.xml",
]

UKRAINE_KEYWORDS = [
    "ukraine","zelensky","kyiv","kharkiv","donbas","zaporizhzhia",
    "zelenskyy","ukraine war","nato ukraine","russian","kremlin",
    "mariupol","dnipro","odesa","kherson","lviv","putin ukraine",
    "ukrainian army","ceasefire","peace talks","volodymyr",
    "ukrainian economy","ukraine invest","ukraine rebuild",
    "ukraine politics","verkhovna rada","ukrainian government"
]

def get_news(category):
    if category == "greece":
        feeds = GREEK_FEEDS
    elif category == "ukraine":
        feeds = UKRAINE_FEEDS
    else:
        feeds = [
            "https://feeds.bbci.co.uk/news/world/rss.xml",
            "https://rss.reuters.com/reuters/worldNews",
            "https://www.forexlive.com/feed/news",
            "https://feeds.skynews.com/feeds/rss/world.xml"
        ]
    headlines = []
    for feed_url in feeds:
        try:
            _resp = requests.get(feed_url, timeout=10)
            _resp.raise_for_status()  # treat 4xx/5xx as errors, not empty feeds
            feed = feedparser.parse(_resp.text)
            entries = feed.entries[:]
            random.shuffle(entries)
            for entry in entries[:30]:
                title = entry.get("title","")
                title_lower = title.lower()
                if category == "greece":
                    if any(ex in title_lower for ex in GREECE_EXCLUDE):
                        continue
                    if any(k in title_lower for k in GREECE_KEYWORDS):
                        if title not in headlines:
                            headlines.append(title)
                elif category == "ukraine":
                    if any(k in title_lower for k in UKRAINE_KEYWORDS):
                        if title not in headlines:
                            headlines.append(title)
                else:
                    if any(k in title_lower for k in KEYWORDS[category]):
                        if title not in headlines:
                            headlines.append(title)
                if len(headlines) >= 10:
                    break
        except Exception as e:
            print(f"Feed parse error {feed_url}: {e}")
            continue
        if len(headlines) >= 10:
            break
    return headlines[:10]

SUMMARY_STYLES = {
    "ukraine": [
        "You are a Ukrainian war correspondent. Write a structured briefing in Ukrainian. 3 sections: ⚔️ ВІЙСЬКОВІ ДІЇ (military), 🏛 ПОЛІТИКА (politics), 💰 ЕКОНОМІКА (economy). Each section 2-3 sentences. Plain text, emojis.",
        "You are a foreign correspondent covering Ukraine. Write in Ukrainian. Lead with the most critical military development, then key political and economic updates. 4-6 sentences total. Plain text, emojis.",
        "You are an analyst at a Ukrainian news agency. Write in Ukrainian. Pick the 3 most important stories and explain each in 2 sentences: what happened + what it means. Plain text, emojis.",
    ],
    "greece": [
        "Είσαι δημοσιογράφος οικονομικής εφημερίδας. Γράψε στα Ελληνικά. Παρουσίασε τις 4-5 πιο σημαντικές ειδήσεις με σύντομη ανάλυση. Χρησιμοποίησε emojis.",
        "Σύνοψε αυτές τις ειδήσεις για την Ελλάδα στα Ελληνικά. Ξεκίνα με την πιο σημαντική, δώσε συνοπτική ανάλυση για κάθε μία. 5-7 προτάσεις. Emojis.",
        "Είσαι αναλυτής της ελληνικής αγοράς. Γράψε στα Ελληνικά. Ποια είναι η κυρίαρχη τάση στις σημερινές ειδήσεις; Τι σημαίνει για επενδυτές και επιχειρήσεις; 4-6 προτάσεις. Emojis.",
    ],
    "finance": [
        "You are a senior market analyst briefing traders. Plain text only, no markdown. Pick the 4-5 most market-moving stories, explain each in one line with trading implication. Use emojis.",
        "You are a forex and macro analyst. Plain text. What are the dominant themes in today's financial news? Explain the top stories and connect the dots — what should traders be watching? 4-6 sentences. Emojis.",
        "You are a trading desk analyst. Plain text. Pick the 3 most impactful financial stories and write 2 sentences each: what happened + what it means for EUR/USD, Gold, or risk sentiment. Emojis.",
    ],
    "geopolitics": [
        "You are a geopolitical risk analyst for a trading firm. Plain text. What are the key developments and how do they impact markets — safe havens, oil, currency flows? 4-5 sentences. Emojis.",
        "You are an intelligence analyst briefing traders on geopolitical risk. Plain text. Cover the top 3-4 stories: what's happening, who's affected, and the market risk (escalation / de-escalation). Emojis.",
        "You are a foreign affairs expert. Plain text. Pick the most significant geopolitical developments and explain in plain terms what they mean for traders — which markets react, which safe havens benefit. 4-6 sentences. Emojis.",
    ],
    "markets": [
        "You are a market intelligence analyst. Plain text. Summarize the top stories on trade, commodities and economic data. For each: what happened + market impact. 4-5 bullet-style lines. Emojis.",
        "You are a commodities and trade analyst. Plain text. What are the dominant themes in today's market news? Highlight supply/demand shifts, tariff moves, or economic surprises. 4-5 sentences. Emojis.",
        "You are a global markets analyst. Plain text. Pick the 3-4 most significant market/trade stories and explain what they signal — supply chain shifts, commodity trends, economic direction. Be specific. Emojis.",
    ],
}

def get_ai_summary(headlines, category):
    if not headlines:
        return "No recent news found for this category."
    try:
        styles = SUMMARY_STYLES.get(category, [
            "Summarize these headlines for traders. Pick the most important stories and explain each clearly. Use emojis. Plain text."
        ])
        system_prompt = random.choice(styles)
        message = _anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=450,
            timeout=25,  # SDK default is 600s — too long for a user waiting on a button press
            system=system_prompt,
            messages=[{"role":"user","content":"Headlines:\n"+"\n".join(headlines)}]
        )
        return message.content[0].text if message.content else "AI summary temporarily unavailable."
    except Exception as e:
        print(f"get_ai_summary error ({category}): {e}")
        return "AI summary temporarily unavailable."

TITLES = {
    "ukraine": "\U0001f1fa\U0001f1e6 UKRAINE NEWS",
    "finance": "\U0001f4b9 FINANCE NEWS",
    "greece": "🇬🇷 Ελληνικά Νέα",
    "geopolitics": "\U0001f30d GEOPOLITICS",
    "markets": "\U0001f6d2 MARKETS"
}

def _fetch_calendar_today():
    """Sync helper: fetch today's (or tomorrow's) economic calendar for asyncio.to_thread."""
    try:
        tz2 = pytz.timezone("Europe/Athens")
        today = datetime.now(tz2).strftime("%Y-%m-%d")
        now_str = datetime.now(tz2).strftime("%d/%m/%Y")
        h = {"User-Agent":"Mozilla/5.0","X-Requested-With":"XMLHttpRequest","Referer":"https://www.investing.com/economic-calendar/"}
        d = {"dateFrom":today,"dateTo":today,"importance[]":["2","3"]}
        r = requests.post("https://www.investing.com/economic-calendar/Service/getCalendarFilteredData",headers=h,data=d,timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.json().get("data",""),"html.parser")
        rows = soup.find_all("tr",id=lambda x: x and x.startswith("eventRowId_"))
        events = []
        for row in rows[:8]:
            try:
                tds = row.find_all("td")
                if len(tds) < 4: continue
                ev_time = tds[0].text.strip()
                currency = tds[1].text.strip()
                ev_name = tds[3].text.strip()
                if currency in ["USD","EUR","GBP","JPY","CHF","AUD","CAD","NZD"]:
                    events.append("📍 "+ev_time+" | "+currency+" | "+ev_name)
            except Exception as e:
                print(f"Calendar row parse error (today): {e}")
                continue
        msg = "📅 FOREX CALENDAR | "+now_str+chr(10)+chr(10)
        if events:
            msg += chr(10).join(events)
        else:
            tomorrow = (datetime.now(tz2) + timedelta(days=1)).strftime("%Y-%m-%d")
            d2 = {"dateFrom":tomorrow,"dateTo":tomorrow,"importance[]":["2","3"]}
            r2 = requests.post("https://www.investing.com/economic-calendar/Service/getCalendarFilteredData",headers=h,data=d2,timeout=15)
            r2.raise_for_status()
            soup2 = BeautifulSoup(r2.json().get("data",""),"html.parser")
            rows2 = soup2.find_all("tr",id=lambda x: x and x.startswith("eventRowId_"))
            tomorrow_events = []
            for row in rows2[:8]:
                try:
                    tds = row.find_all("td")
                    if len(tds) < 4: continue
                    ev_time = tds[0].text.strip()
                    currency = tds[1].text.strip()
                    ev_name = tds[3].text.strip() if len(tds)>3 else ""
                    if currency in ["USD","EUR","GBP","JPY","CHF","AUD","CAD","NZD"]:
                        tomorrow_events.append("📍 "+ev_time+" | "+currency+" | "+ev_name)
                except Exception as e:
                    print(f"Calendar row parse error (tomorrow): {e}")
                    continue
            if tomorrow_events:
                msg += "📌 No major events today."+chr(10)+chr(10)+"📆 TOMORROW:"+chr(10)+chr(10)+chr(10).join(tomorrow_events)
            else:
                msg += "No major forex events today or tomorrow."
        msg += chr(10)+chr(10)+"📊 Full calendar sent at 07:00!"
        return msg
    except Exception as e:
        print(f"_fetch_calendar_today error: {e}")
        return "📅 Economic calendar temporarily unavailable. Please try again later."


def _fetch_sentiment():
    """Sync helper: fetch Fear & Greed index for asyncio.to_thread."""
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        r.raise_for_status()
        data = r.json()["data"][0]
        value = int(data["value"])
        classification = data["value_classification"]
        if value >= 75: emoji = "🟢"
        elif value >= 55: emoji = "🟡"
        elif value >= 45: emoji = "🟠"
        elif value >= 25: emoji = "🔴"
        else: emoji = "💥"
        bar = "█"*(value//10)+"░"*(10-value//10)
        return "🧠 MARKET SENTIMENT"+chr(10)+chr(10)+"Fear & Greed: "+emoji+" "+str(value)+"/100"+chr(10)+"["+bar+"]"+chr(10)+classification
    except Exception as e:
        print(f"_fetch_sentiment error: {e}")
        return "🧠 Sentiment data temporarily unavailable. Please try again later."


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "📰 Nova News Bot\n\n"
        "On-demand market intelligence, filtered by AI. Pick a category and get a briefing in seconds — "
        "no noise, no clickbait, just the stories that actually move markets.\n\n"
        "What's inside:\n"
        "💹 Finance — central banks, rates, macro data, forex & crypto moves\n"
        "🌍 Geopolitics — wars, sanctions, elections, diplomacy and their market impact\n"
        "🛒 Markets — trade, commodities, supply chains, economic indicators\n"
        "🇺🇦 Ukraine — live war updates from multiple sources\n"
        "🇬🇷 Ελλάδα — Greek financial and economic news\n"
        "📅 Calendar — today's high-impact economic events\n"
        "🧠 Sentiment — Fear & Greed Index, live\n\n"
        "👇 Choose a category:\n\n"
        "⚠️ All content is for informational purposes only. Not financial advice."
    )
    await update.message.reply_text(msg, reply_markup=MAIN_MENU)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    text = update.message.text
    tz = pytz.timezone("Europe/Athens")
    now = datetime.now(tz).strftime("%d/%m/%Y %H:%M")

    category_map = {
        "\U0001f1fa\U0001f1e6 Ukraine": "ukraine",
        "🇬🇷 Ελλάδα": "greece",
        "\U0001f4b9 Finance": "finance",
        "\U0001f30d Geopolitics": "geopolitics",
        "\U0001f6d2 Markets": "markets"
    }

    if text in category_map:
        await update.message.reply_text("\U0001f504 Loading latest news...", reply_markup=MAIN_MENU)
        category = category_map[text]
        try:
            headlines = await asyncio.to_thread(get_news, category)
            summary = await asyncio.to_thread(get_ai_summary, headlines, category)
            await update.message.reply_text(
                TITLES[category]+" | "+now+"\n\n"+summary+"\n\n\U0001f4f0 Full coverage: @tradingNovaNews",
                reply_markup=MAIN_MENU
            )
        except Exception as e:
            print(f"handle_message news error: {e}")
            await update.message.reply_text("Error fetching news. Please try again.", reply_markup=MAIN_MENU)

    elif text == "📅 Calendar":
        await update.message.reply_text("🔄 Loading...", reply_markup=MAIN_MENU)
        try:
            msg = await asyncio.to_thread(_fetch_calendar_today)
            await update.message.reply_text(msg, reply_markup=MAIN_MENU)
        except Exception as e:
            print(f"Calendar handler error: {e}")
            await update.message.reply_text("📅 Calendar temporarily unavailable. Please try again.", reply_markup=MAIN_MENU)

    elif text == "🧠 Sentiment":
        await update.message.reply_text("🔄 Loading...", reply_markup=MAIN_MENU)
        try:
            msg = await asyncio.to_thread(_fetch_sentiment)
            await update.message.reply_text(msg, reply_markup=MAIN_MENU)
        except Exception as e:
            print(f"Sentiment handler error: {e}")
            await update.message.reply_text("🧠 Sentiment data temporarily unavailable. Please try again.", reply_markup=MAIN_MENU)

    elif text == "\U0001f4f0 Latest News":
        await update.message.reply_text("\U0001f504 Loading...", reply_markup=MAIN_MENU)

        def _fetch_latest_news():
            all_h = []
            feeds = ["https://feeds.bbci.co.uk/news/world/rss.xml","https://www.forexlive.com/feed/news"]
            keywords = ["war","fed","rate","trump","oil","gold","ukraine","iran","market","crash","rally"]
            for feed_url in feeds:
                try:
                    _resp = requests.get(feed_url, timeout=10)
                    _resp.raise_for_status()  # treat 4xx/5xx as errors, not empty feeds
                    feed = feedparser.parse(_resp.text)
                    for entry in feed.entries[:15]:
                        title = entry.get("title","")
                        if any(k in title.lower() for k in keywords):
                            all_h.append(title)
                        if len(all_h) >= 8:
                            break
                except Exception as e:
                    print(f"Feed parse error {feed_url}: {e}")
                    continue
                if len(all_h) >= 8:
                    break
            if not all_h:
                return None
            try:
                latest_styles = [
                    "You are a financial news editor. Plain text only. Pick the 5 most market-relevant headlines and write each as one punchy line with an emoji. End with one sentence on what's dominating the tape right now.",
                    "You are a senior forex analyst. Plain text. From these headlines pick the 3-4 most important for traders. For each: what happened and what's the market implication. Be sharp. Emojis.",
                    "You are a trading desk analyst sharing a quick news hit. Plain text. Lead with the biggest headline, then list 3-4 others. Flag anything high-impact. Short lines, emojis.",
                ]
                system = random.choice(latest_styles)
                message = _anthropic_client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=350,
                    timeout=25,  # SDK default is 600s — too long for a user waiting on a button press
                    system=system,
                    messages=[{"role":"user","content":"Headlines:\n\n"+"\n".join(all_h[:8])}]
                )
                return message.content[0].text if message.content else "\n".join("• "+h for h in all_h[:5])
            except Exception as e:
                print(f"Latest news AI error: {e}")
                return "\n".join("• "+h for h in all_h[:5])

        try:
            summary_text = await asyncio.to_thread(_fetch_latest_news)
        except Exception as e:
            print(f"Latest news fetch error: {e}")
            summary_text = None
        if summary_text is None:
            await update.message.reply_text(
                "\U0001f4f0 No major market news found right now.\n\n\U0001f4f0 Full coverage: @tradingNovaNews",
                reply_markup=MAIN_MENU
            )
            return
        await update.message.reply_text(
            "\U0001f4f0 LATEST NEWS | "+now+"\n\n"+summary_text+"\n\n\U0001f4f0 @tradingNovaNews",
            reply_markup=MAIN_MENU
        )

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

if __name__ == "__main__":
    print("Nova News Bot started!")
    app.run_polling()
