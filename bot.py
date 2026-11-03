import os
import re
import json
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)
import yt_dlp

# Load environment variables from .env file
load_dotenv()

# ======================= CONFIGURATION =======================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
DATABASE_URI = os.getenv("DATABASE_URI", "").strip()
DATABASE_NAME = os.getenv("DATABASE_NAME", "ott_notifier_db").strip()
CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "600"))
PORT = int(os.getenv("PORT", "8080"))
DATA_FILE = "shows_data.json"
# ==============================================================


# ------------------ DUMMY HTTP SERVER (KOYEB HEALTH CHECKS) ------------------
class HealthCheckHandler(BaseHTTPRequestHandler):
    """Responds to cloud platform health checks (Koyeb, Render, etc.)."""
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK - Hotstar Telegram Notifier is running!")

    def log_message(self, format, *args):
        # Silence HTTP access logs to keep terminal clean
        return


def start_health_server():
    try:
        server = HTTPServer(("0.0.0.0", PORT), HealthCheckHandler)
        print(f"[*] Health check server active on port {PORT} (Koyeb/Cloud compatible)")
        server.serve_forever()
    except Exception as e:
        print(f"[!] Health check server warning: {e}")


# ------------------ DATABASE LAYER (MONGODB & FALLBACK) ------------------
mongo_client = None
shows_col = None

if DATABASE_URI:
    try:
        from pymongo import MongoClient
        mongo_client = MongoClient(DATABASE_URI, serverSelectionTimeoutMS=5000)
        # Test connection
        mongo_client.admin.command("ping")
        db_instance = mongo_client[DATABASE_NAME]
        shows_col = db_instance["shows"]
        print(f"[✓] Connected to MongoDB Atlas! Using database: '{DATABASE_NAME}'")
    except Exception as e:
        print(f"[!] MongoDB connection failed ({e}). Falling back to local '{DATA_FILE}'.")
        mongo_client = None
        shows_col = None
else:
    print(f"[*] No DATABASE_URI provided. Using local file storage ('{DATA_FILE}').")


def load_local_db() -> dict:
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"shows": {}}
    return {"shows": {}}


def save_local_db(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def db_get_all_shows() -> dict:
    """Return dictionary of all tracked shows keyed by show_id."""
    if shows_col is not None:
        try:
            docs = list(shows_col.find({}))
            return {doc["show_id"]: doc for doc in docs}
        except Exception as e:
            print(f"[!] MongoDB read error: {e}")
    return load_local_db().get("shows", {})


def db_get_show(show_id: str) -> dict | None:
    """Retrieve single show document."""
    if shows_col is not None:
        try:
            return shows_col.find_one({"show_id": show_id})
        except Exception as e:
            print(f"[!] MongoDB find error: {e}")
    return load_local_db().get("shows", {}).get(show_id)


def db_save_new_show(show_data: dict):
    """Save or update full show document."""
    show_id = show_data["show_id"]
    if shows_col is not None:
        try:
            shows_col.update_one({"show_id": show_id}, {"$set": show_data}, upsert=True)
            return
        except Exception as e:
            print(f"[!] MongoDB save error: {e}")

    # Fallback to local file
    data = load_local_db()
    data.setdefault("shows", {})[show_id] = show_data
    save_local_db(data)


def db_add_subscriber(show_id: str, chat_id: int):
    """Add a chat_id to the subscribers list of a show."""
    if shows_col is not None:
        try:
            shows_col.update_one({"show_id": show_id}, {"$addToSet": {"subscribers": chat_id}})
            return
        except Exception as e:
            print(f"[!] MongoDB subscriber add error: {e}")

    data = load_local_db()
    shows = data.setdefault("shows", {})
    if show_id in shows:
        subs = shows[show_id].setdefault("subscribers", [])
        if chat_id not in subs:
            subs.append(chat_id)
            save_local_db(data)


def db_remove_subscriber(show_id: str, chat_id: int) -> str | None:
    """Remove chat_id from a show's subscribers. Delete show if no subscribers left."""
    if shows_col is not None:
        try:
            doc = shows_col.find_one({"show_id": show_id})
            if not doc:
                return None
            serial_name = doc.get("serial_name", "Show")
            shows_col.update_one({"show_id": show_id}, {"$pull": {"subscribers": chat_id}})
            # Check if empty
            updated = shows_col.find_one({"show_id": show_id})
            if updated and not updated.get("subscribers"):
                shows_col.delete_one({"show_id": show_id})
            return serial_name
        except Exception as e:
            print(f"[!] MongoDB remove subscriber error: {e}")

    data = load_local_db()
    shows = data.get("shows", {})
    if show_id in shows and chat_id in shows[show_id].get("subscribers", []):
        serial_name = shows[show_id].get("serial_name", "Show")
        shows[show_id]["subscribers"].remove(chat_id)
        if not shows[show_id]["subscribers"]:
            del shows[show_id]
        save_local_db(data)
        return serial_name
    return None


def db_add_seen_episode(show_id: str, ep_id: str):
    """Mark an episode ID as seen."""
    if shows_col is not None:
        try:
            shows_col.update_one({"show_id": show_id}, {"$addToSet": {"seen_episode_ids": ep_id}})
            return
        except Exception as e:
            print(f"[!] MongoDB add seen error: {e}")

    data = load_local_db()
    shows = data.get("shows", {})
    if show_id in shows:
        seen = set(shows[show_id].get("seen_episode_ids", []))
        seen.add(ep_id)
        shows[show_id]["seen_episode_ids"] = list(seen)
        save_local_db(data)


def db_get_user_shows(chat_id: int) -> list[dict]:
    """Retrieve all shows subscribed to by a particular chat_id."""
    if shows_col is not None:
        try:
            return list(shows_col.find({"subscribers": chat_id}))
        except Exception as e:
            print(f"[!] MongoDB user shows error: {e}")
    shows = load_local_db().get("shows", {})
    return [s for s in shows.values() if chat_id in s.get("subscribers", [])]


# ------------------ HELPERS & PARSING ------------------
def slugify(text: str) -> str:
    """Convert text into a clean URL slug."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def parse_show_url(url: str) -> tuple[str, str, str] | None:
    """Extract (show_slug, show_id, serial_name) from a Hotstar URL."""
    match = re.search(r"hotstar\.com/(?:[a-z]{2}/)?shows/([^/]+)/(\d+)", url)
    if not match:
        return None
    slug = match.group(1)
    show_id = match.group(2)
    serial_name = " ".join(word.capitalize() for word in slug.split("-"))
    return slug, show_id, serial_name


def parse_episode_details(raw_title: str) -> tuple[str, str]:
    """Extracts episode number and clean episode name."""
    match = re.search(r"(?:^|\b)(?:E|Ep|Episode)?\s*(\d{1,5})\s*[-:|–—]\s*(.*)$", raw_title, re.IGNORECASE)
    if match:
        return match.group(1).strip(), match.group(2).strip()

    fallback_num = re.search(r"\b(\d{1,5})\b", raw_title)
    ep_num = fallback_num.group(1) if fallback_num else "Latest"
    return ep_num, raw_title.strip()


def build_watch_link(show_slug: str, show_id: str, ep_name: str, ep_id: str) -> str:
    """Constructs the canonical Hotstar watch URL."""
    ep_slug = slugify(ep_name)
    if ep_slug:
        return f"https://www.hotstar.com/in/shows/{show_slug}/{show_id}/{ep_slug}/{ep_id}/watch"
    return f"https://www.hotstar.com/in/shows/{show_slug}/{show_id}/{ep_id}/watch"


def format_notification(serial_name: str, ep_name: str, ep_number: str,
                        season_number: str, language: str, from_ott: str,
                        watch_link: str, dt: datetime = None) -> str:
    """Outputs the exact requested notification layout."""
    now = dt or datetime.now()
    release_date = now.strftime("%d %b, %Y")  # e.g., 03 Nov, 2026
    release_day = now.strftime("%A")          # e.g., Tuesday

    return (
        f"⚡ #First_On_{from_ott}\n\n"
        f"Serial Name: {serial_name}\n"
        f"Episode Name: {ep_name}\n"
        f"Episode Number: {ep_number}\n"
        f"Season Number: {season_number}\n"
        f"From OTT: {from_ott}\n"
        f"Language: {language}\n"
        f"Release Date: {release_date}\n"
        f"Release Day: {release_day}\n\n"
        f"Link: {watch_link}"
    )


def fetch_episodes_sync(show_url: str) -> list[dict]:
    """Runs synchronous yt-dlp metadata extraction."""
    ydl_opts = {
        "extract_flat": "in_playlist",
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(show_url, download=False)
            return info.get("entries", []) if info else []
        except Exception as e:
            print(f"[!] Error fetching {show_url}: {e}")
            return []


# ------------------ TELEGRAM COMMAND HANDLERS ------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /start."""
    db_mode = f"MongoDB Atlas ({DATABASE_NAME})" if shows_col is not None else "Local Storage"
    welcome_text = (
        "👋 <b>Welcome to the JioHotstar Episode Notification Bot!</b>\n\n"
        "I monitor your chosen serials on JioHotstar and notify you the moment a new episode is released.\n\n"
        "<b>Available Commands:</b>\n"
        "➕ <code>/addshow &lt;url&gt; [language]</code> - Start tracking a show\n"
        "<i>Example:</i> <code>/addshow https://www.hotstar.com/in/shows/patharamattu/1260141539 Malayalam</code>\n\n"
        "➖ <code>/removeshow &lt;id_or_name&gt;</code> - Stop tracking a show\n"
        "<i>Example:</i> <code>/removeshow 1260141539</code>\n\n"
        "📋 <code>/listshows</code> - View shows tracked for this chat\n"
        "⚡ <code>/test</code> - Preview the notification format\n\n"
        f"💾 <b>Storage:</b> <code>{db_mode}</code>"
    )
    await update.message.reply_text(welcome_text, parse_mode="HTML")


async def cmd_addshow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /addshow <url> [language]."""
    chat_id = update.effective_chat.id
    args = context.args

    if not args:
        await update.message.reply_text(
            "⚠️ <b>Usage:</b>\n<code>/addshow &lt;hotstar_show_url&gt; [language]</code>\n\n"
            "<i>Example:</i>\n<code>/addshow https://www.hotstar.com/in/shows/patharamattu/1260141539 Malayalam</code>",
            parse_mode="HTML"
        )
        return

    url = args[0]
    language = args[1] if len(args) > 1 else "Malayalam"

    parsed = parse_show_url(url)
    if not parsed:
        await update.message.reply_text("❌ Invalid Hotstar show URL. Make sure it contains <code>/shows/name/id</code>.", parse_mode="HTML")
        return

    show_slug, show_id, serial_name = parsed
    status_msg = await update.message.reply_text(f"⏳ Inspecting <b>{serial_name}</b> and caching existing episodes...", parse_mode="HTML")

    entries = await asyncio.to_thread(fetch_episodes_sync, url)
    existing_show = db_get_show(show_id)

    if not existing_show:
        seen_ids = [str(e.get("id")) for e in entries if e and e.get("id")]
        show_data = {
            "show_id": show_id,
            "show_slug": show_slug,
            "serial_name": serial_name,
            "language": language,
            "from_ott": "Hotstar",
            "url": url,
            "subscribers": [chat_id],
            "seen_episode_ids": seen_ids,
        }
        db_save_new_show(show_data)
        cached_count = len(seen_ids)
    else:
        db_add_subscriber(show_id, chat_id)
        cached_count = len(existing_show.get("seen_episode_ids", []))

    await status_msg.edit_text(
        f"✅ <b>Now Tracking: {serial_name}</b>\n\n"
        f"• <b>Language:</b> {language}\n"
        f"• <b>Show ID:</b> <code>{show_id}</code>\n"
        f"• <b>Pre-cached Episodes:</b> {cached_count}\n\n"
        f"You will receive an instant alert here whenever a new episode drops!",
        parse_mode="HTML"
    )


async def cmd_removeshow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /removeshow <id_or_name>."""
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("⚠️ <b>Usage:</b> <code>/removeshow &lt;show_id_or_name&gt;</code>", parse_mode="HTML")
        return

    query = " ".join(context.args).lower().strip()
    user_shows = db_get_user_shows(chat_id)

    target_id = None
    for s in user_shows:
        if query == s["show_id"] or query == s.get("show_slug", "").lower() or query in s.get("serial_name", "").lower():
            target_id = s["show_id"]
            break

    if not target_id:
        await update.message.reply_text("❌ Show not found in your tracked list. Use <code>/listshows</code> to check.", parse_mode="HTML")
        return

    serial_name = db_remove_subscriber(target_id, chat_id)
    await update.message.reply_text(f"🗑️ <b>{serial_name}</b> has been removed from your tracking list.", parse_mode="HTML")


async def cmd_listshows(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /listshows."""
    chat_id = update.effective_chat.id
    user_shows = db_get_user_shows(chat_id)

    if not user_shows:
        await update.message.reply_text("ℹ️ You are not tracking any shows yet.\nUse <code>/addshow &lt;url&gt;</code> to start tracking!", parse_mode="HTML")
        return

    lines = [f"📺 <b>Your Tracked Shows ({len(user_shows)}):</b>\n"]
    for idx, s in enumerate(user_shows, 1):
        lines.append(
            f"<b>{idx}. {s['serial_name']}</b> ({s['language']})\n"
            f"   • ID: <code>{s['show_id']}</code>\n"
            f"   • Link: <a href='{s['url']}'>Hotstar Page</a>"
        )

    await update.message.reply_text("\n\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)


async def cmd_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /test - preview notification layout."""
    sample = format_notification(
        serial_name="Patharamattu",
        ep_name="Nandana Arrives to Arrest Abhi",
        ep_number="1116",
        season_number="1",
        language="Malayalam",
        from_ott="Hotstar",
        watch_link="https://www.hotstar.com/in/shows/patharamattu/1260141539/nandana-arrives-to-arrest-abhi/1641039866/watch"
    )
    await update.message.reply_text(sample)


# ------------------ BACKGROUND AUTO-MONITOR ------------------
async def background_monitor(app: Application):
    """Periodically inspects all tracked shows and sends alerts to subscribers."""
    while True:
        try:
            all_shows = db_get_all_shows()

            for show_id, show in all_shows.items():
                subscribers = show.get("subscribers", [])
                if not subscribers:
                    continue

                entries = await asyncio.to_thread(fetch_episodes_sync, show["url"])
                seen_ids = set(show.get("seen_episode_ids", []))

                for ep in entries:
                    ep_id = str(ep.get("id"))
                    if not ep_id or ep_id in seen_ids:
                        continue

                    raw_title = ep.get("title", "New Episode")
                    ep_num, ep_name = parse_episode_details(raw_title)
                    season_num = str(ep.get("season_number") or "1")

                    watch_link = build_watch_link(
                        show["show_slug"],
                        show["show_id"],
                        ep_name,
                        ep_id
                    )

                    alert_text = format_notification(
                        serial_name=show["serial_name"],
                        ep_name=ep_name,
                        ep_number=ep_num,
                        season_number=season_num,
                        language=show["language"],
                        from_ott=show.get("from_ott", "Hotstar"),
                        watch_link=watch_link
                    )

                    # Send to all subscribers of this show
                    for chat_id in subscribers:
                        try:
                            await app.bot.send_message(
                                chat_id=chat_id,
                                text=alert_text,
                                disable_web_page_preview=False
                            )
                        except Exception as send_err:
                            print(f"[!] Could not send to {chat_id}: {send_err}")

                    # Mark as seen in database
                    db_add_seen_episode(show_id, ep_id)
                    seen_ids.add(ep_id)
                    print(f"[✓] Broadcasted new episode of {show['serial_name']}: Ep {ep_num}")

        except Exception as e:
            print(f"[!] Error in background monitor: {e}")

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


async def post_init(application: Application):
    """Start background monitor task when bot launches."""
    asyncio.create_task(background_monitor(application))


# ------------------ MAIN ENTRYPOINT ------------------
def main():
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        print("[!] ERROR: TELEGRAM_BOT_TOKEN is not set.")
        print("[!] Create a .env file with your token or export TELEGRAM_BOT_TOKEN in your environment.")
        return

    # Start dummy HTTP health check server for Koyeb / Web Service health checks
    threading.Thread(target=start_health_server, daemon=True).start()

    print("[*] Starting Telegram Bot with interactive show management...")
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("addshow", cmd_addshow))
    app.add_handler(CommandHandler("removeshow", cmd_removeshow))
    app.add_handler(CommandHandler("listshows", cmd_listshows))
    app.add_handler(CommandHandler("test", cmd_test))

    app.run_polling()


if __name__ == "__main__":
    main()
