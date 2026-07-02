import os
from dotenv import load_dotenv
load_dotenv("/root/tradingbot/.env")

import requests
import anthropic
import feedparser
import pytz
import json
import time
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

TOKEN = os.getenv("TELEGRAM_TOKEN_NEWS")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

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
    import random
    for feed_url in feeds:
        try:
            feed = feedparser.parse(feed_url)
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
    return headlines[:10]

def get_ai_summary(headlines, category):
    if not headlines:
        return "No recent news found for this category."
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompts = {
        "ukraine": "You are a Ukrainian news editor. Based on these headlines write a structured summary in Ukrainian language. Format it in 3 sections: ⚔️ ВІЙСЬКОВІ ДІЇ (military updates), 🏛 ПОЛІТИКА (political news), 💰 ЕКОНОМІКА (economic news). Each section 2-3 sentences. Use emojis. Plain text only.",
        "greece": "Σύνοψε αυτές τις ειδήσεις για την Ελλάδα. Γράψε στα Ελληνικά. 5-8 σύντομες παράγραφοι με emoji.",
        "finance": "Summarize these financial news for traders. 5-8 short bullet points. Simple English. Use emojis.",
        "geopolitics": "Summarize these geopolitical news. 5-8 short bullet points. Simple English. Use emojis.",
        "markets": "Summarize these market/trade news for investors. 5-8 short bullet points. Simple English. Use emojis."
    }
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        messages=[{"role":"user","content":prompts[category]+"\n\nHeadlines:\n"+"\n".join(headlines)}]
    )
    return message.content[0].text

TITLES = {
    "ukraine": "\U0001f1fa\U0001f1e6 UKRAINE NEWS",
    "finance": "\U0001f4b9 FINANCE NEWS",
    "greece": "🇬🇷 Ελληνικά Νέα",
    "geopolitics": "\U0001f30d GEOPOLITICS",
    "markets": "\U0001f6d2 MARKETS"
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "📰 Welcome to the Nova News Bot\n\n"
        "Stay ahead of the markets with real time, on demand financial intelligence, "
        "global news, and sentiment analysis. Customize your feed and access the exact "
        "insights you need, precisely when you need them.\n\n"
        "🧠 Powered by AI to filter the noise and deliver high impact market data.\n\n"
        "👇 Select a category below to fetch the latest updates:"
    )
    await update.message.reply_text(msg, reply_markup=MAIN_MENU)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        headlines = get_news(category)
        summary = get_ai_summary(headlines, category)
        await update.message.reply_text(
            TITLES[category]+" | "+now+"\n\n"+summary+"\n\n\U0001f4f0 Full coverage: @tradingNovaNews",
            reply_markup=MAIN_MENU
        )

    elif text in ["📅 Calendar"]:
        await update.message.reply_text("🔄 Loading...", reply_markup=MAIN_MENU)
        try:
            import requests as req2
            from bs4 import BeautifulSoup
            from datetime import datetime as dt5
            tz2 = pytz.timezone("Europe/Athens")
            today = dt5.now(tz2).strftime("%Y-%m-%d")
            now_str = dt5.now(tz2).strftime("%d/%m/%Y")
            h = {"User-Agent":"Mozilla/5.0","X-Requested-With":"XMLHttpRequest","Referer":"https://www.investing.com/economic-calendar/"}
            d = {"dateFrom":today,"dateTo":today,"importance[]":["2","3"]}
            r = req2.post("https://www.investing.com/economic-calendar/Service/getCalendarFilteredData",headers=h,data=d,timeout=15)
            soup = BeautifulSoup(r.json().get("data",""),"html.parser")
            rows = soup.find_all("tr",id=lambda x: x and x.startswith("eventRowId_"))
            events = []
            for row in rows[:8]:
                try:
                    tds = row.find_all("td")
                    if len(tds) < 3: continue
                    ev_time = tds[0].text.strip()
                    currency = tds[1].text.strip()
                    ev_name = tds[3].text.strip() if len(tds)>3 else ""
                    if currency in ["USD","EUR","GBP","JPY","CHF","AUD","CAD","NZD"]:
                        events.append("📍 "+ev_time+" | "+currency+" | "+ev_name)
                except: continue
            msg = "📅 FOREX CALENDAR | "+now_str+chr(10)+chr(10)
            if events:
                msg += chr(10).join(events)
            else:
                from datetime import timedelta
                tomorrow = (dt5.now(tz2) + timedelta(days=1)).strftime("%Y-%m-%d")
                d2 = {"dateFrom":tomorrow,"dateTo":tomorrow,"importance[]":["2","3"]}
                r2 = req2.post("https://www.investing.com/economic-calendar/Service/getCalendarFilteredData",headers=h,data=d2,timeout=15)
                soup2 = BeautifulSoup(r2.json().get("data",""),"html.parser")
                rows2 = soup2.find_all("tr",id=lambda x: x and x.startswith("eventRowId_"))
                tomorrow_events = []
                for row in rows2[:8]:
                    try:
                        tds = row.find_all("td")
                        if len(tds) < 3: continue
                        ev_time = tds[0].text.strip()
                        currency = tds[1].text.strip()
                        ev_name = tds[3].text.strip() if len(tds)>3 else ""
                        if currency in ["USD","EUR","GBP","JPY","CHF","AUD","CAD","NZD"]:
                            tomorrow_events.append("📍 "+ev_time+" | "+currency+" | "+ev_name)
                    except: continue
                if tomorrow_events:
                    msg += "📌 No major events today."+chr(10)+chr(10)+"📆 TOMORROW:"+chr(10)+chr(10)+chr(10).join(tomorrow_events)
                else:
                    msg += "No major forex events today or tomorrow."
            msg += chr(10)+chr(10)+"📊 Full calendar sent at 07:00!"
            await update.message.reply_text(msg, reply_markup=MAIN_MENU)
        except Exception as e:
            await update.message.reply_text("Error: "+str(e), reply_markup=MAIN_MENU)

    elif text in ["🧠 Sentiment"]:
        await update.message.reply_text("🔄 Loading...", reply_markup=MAIN_MENU)
        try:
            import requests as req3
            r = req3.get("https://api.alternative.me/fng/?limit=1", timeout=10)
            data = r.json()["data"][0]
            value = int(data["value"])
            classification = data["value_classification"]
            if value >= 75: emoji = "🟢"
            elif value >= 55: emoji = "🟡"
            elif value >= 45: emoji = "🟠"
            else: emoji = "🔴"
            bar = "█"*(value//10)+"░"*(10-value//10)
            msg = "🧠 MARKET SENTIMENT"+chr(10)+chr(10)+"Fear & Greed: "+emoji+" "+str(value)+"/100"+chr(10)+"["+bar+"]"+chr(10)+classification
            await update.message.reply_text(msg, reply_markup=MAIN_MENU)
        except Exception as e:
            await update.message.reply_text("Error: "+str(e), reply_markup=MAIN_MENU)

    elif text == "\U0001f4f0 Latest News":
        await update.message.reply_text("\U0001f504 Loading...", reply_markup=MAIN_MENU)
        all_headlines = []
        feeds = ["https://feeds.bbci.co.uk/news/world/rss.xml","https://www.forexlive.com/feed/news"]
        keywords = ["war","fed","rate","trump","oil","gold","ukraine","iran","market","crash","rally"]
        for feed_url in feeds:
            try:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries[:15]:
                    title = entry.get("title","")
                    if any(k in title.lower() for k in keywords):
                        all_headlines.append(title)
                    if len(all_headlines) >= 8:
                        break
            except:
                continue
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role":"user","content":"Pick 5 most important headlines for traders. One short line each with emoji. Simple English.\n\n"+"\n".join(all_headlines[:8])}]
        )
        await update.message.reply_text(
            "\U0001f4f0 LATEST NEWS | "+now+"\n\n"+message.content[0].text+"\n\n\U0001f4f0 @tradingNovaNews",
            reply_markup=MAIN_MENU
        )

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

if __name__ == "__main__":
    print("Nova News Bot started!")
    app.run_polling()
