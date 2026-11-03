import os
import re
import json
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
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
ADMIN_ID = os.getenv("ADMIN_ID", "").strip()
DATABASE_URI = os.getenv("DATABASE_URI", "").strip()
DATABASE_NAME = os.getenv("DATABASE_NAME", "ott_notifier_db").strip()
CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "600"))
PORT = int(os.getenv("PORT", "8080"))
DATA_FILE = "shows_data.json"
BOT_START_TIME = datetime.now()
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
users_col = None

if DATABASE_URI:
    try:
        from pymongo import MongoClient
        mongo_client = MongoClient(DATABASE_URI, serverSelectionTimeoutMS=5000)
        mongo_client.admin.command("ping")
        db_instance = mongo_client[DATABASE_NAME]
        shows_col = db_instance["shows"]
        users_col = db_instance["authorized_users"]
        print(f"[✓] Connected to MongoDB Atlas! Using database: '{DATABASE_NAME}'")
    except Exception as e:
        print(f"[!] MongoDB connection failed ({e}). Falling back to local '{DATA_FILE}'.")
        mongo_client = None
        shows_col = None
        users_col = None
else:
    print(f"[*] No DATABASE_URI provided. Using local file storage ('{DATA_FILE}').")


def load_local_db() -> dict:
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"shows": {}, "authorized_users": []}
    return {"shows": {}, "authorized_users": []}


def save_local_db(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# --- Shows DB Functions ---
def db_get_all_shows() -> dict:
    if shows_col is not None:
        try:
            docs = list(shows_col.find({}))
            return {doc["show_id"]: doc for doc in docs}
        except Exception as e:
            print(f"[!] MongoDB read error: {e}")
    return load_local_db().get("shows", {})


def db_get_show(show_id: str) -> dict | None:
    if shows_col is not None:
        try:
            return shows_col.find_one({"show_id": show_id})
        except Exception as e:
            print(f"[!] MongoDB find error: {e}")
    return load_local_db().get("shows", {}).get(show_id)


def db_save_new_show(show_data: dict):
    show_id = show_data["show_id"]
    if shows_col is not None:
        try:
            shows_col.update_one({"show_id": show_id}, {"$set": show_data}, upsert=True)
            return
        except Exception as e:
            print(f"[!] MongoDB save error: {e}")

    data = load_local_db()
    data.setdefault("shows", {})[show_id] = show_data
    save_local_db(data)


def db_add_subscriber(show_id: str, chat_id: int):
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
    if shows_col is not None:
        try:
            doc = shows_col.find_one({"show_id": show_id})
            if not doc:
                return None
            serial_name = doc.get("serial_name", "Show")
            shows_col.update_one({"show_id": show_id}, {"$pull": {"subscribers": chat_id}})
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
    if shows_col is not None:
        try:
            return list(shows_col.find({"subscribers": chat_id}))
        except Exception as e:
            print(f"[!] MongoDB user shows error: {e}")
    shows = load_local_db().get("shows", {})
    return [s for s in shows.values() if chat_id in s.get("subscribers", [])]


# --- User Authorization DB Functions ---
def db_get_authorized_users() -> set:
    users = set()
    if ADMIN_ID:
        try:
            users.add(int(ADMIN_ID))
        except ValueError:
            pass

    if users_col is not None:
        try:
            docs = list(users_col.find({}))
            for d in docs:
                users.add(d["user_id"])
            return users
        except Exception as e:
            print(f"[!] MongoDB get users error: {e}")

    local_users = load_local_db().get("authorized_users", [])
    users.update(local_users)
    return users


def db_add_user(user_id: int):
    if users_col is not None:
        try:
            users_col.update_one({"user_id": user_id}, {"$set": {"user_id": user_id, "added_at": datetime.utcnow()}}, upsert=True)
            return
        except Exception as e:
            print(f"[!] MongoDB add user error: {e}")

    data = load_local_db()
    users = set(data.setdefault("authorized_users", []))
    users.add(user_id)
    data["authorized_users"] = list(users)
    save_local_db(data)


def db_remove_user(user_id: int):
    if users_col is not None:
        try:
            users_col.delete_one({"user_id": user_id})
            return
        except Exception as e:
            print(f"[!] MongoDB remove user error: {e}")

    data = load_local_db()
    users = set(data.get("authorized_users", []))
    users.discard(user_id)
    data["authorized_users"] = list(users)
    save_local_db(data)


# ------------------ PERMISSIONS & ROLES ------------------
def is_admin(user_id: int) -> bool:
    """Check if user matches the configured ADMIN_ID."""
    if not ADMIN_ID:
        return True  # If no ADMIN_ID configured, anyone can run admin commands
    return str(user_id) == str(ADMIN_ID)


def is_authorized(user_id: int) -> bool:
    """Check if user is authorized to use the bot."""
    if not ADMIN_ID:
        return True  # No auth restriction if ADMIN_ID is empty
    if is_admin(user_id):
        return True
    return user_id in db_get_authorized_users()


def get_uptime() -> str:
    delta = datetime.now() - BOT_START_TIME
    days = delta.days
    hours, rem = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m {seconds}s")
    return " ".join(parts)


# ------------------ HELPERS & PARSING ------------------
def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def parse_show_url(url: str) -> tuple[str, str, str] | None:
    match = re.search(r"hotstar\.com/(?:[a-z]{2}/)?shows/([^/]+)/(\d+)", url)
    if not match:
        return None
    slug = match.group(1)
    show_id = match.group(2)
    serial_name = " ".join(word.capitalize() for word in slug.split("-"))
    return slug, show_id, serial_name


def parse_episode_details(raw_title: str) -> tuple[str, str]:
    match = re.search(r"(?:^|\b)(?:E|Ep|Episode)?\s*(\d{1,5})\s*[-:|–—]\s*(.*)$", raw_title, re.IGNORECASE)
    if match:
        return match.group(1).strip(), match.group(2).strip()

    fallback_num = re.search(r"\b(\d{1,5})\b", raw_title)
    ep_num = fallback_num.group(1) if fallback_num else "Latest"
    return ep_num, raw_title.strip()


def build_watch_link(show_slug: str, show_id: str, ep_name: str, ep_id: str) -> str:
    ep_slug = slugify(ep_name)
    if ep_slug:
        return f"https://www.hotstar.com/in/shows/{show_slug}/{show_id}/{ep_slug}/{ep_id}/watch"
    return f"https://www.hotstar.com/in/shows/{show_slug}/{show_id}/{ep_id}/watch"


def format_notification(serial_name: str, ep_name: str, ep_number: str,
                        season_number: str, language: str, from_ott: str,
                        watch_link: str, dt: datetime = None) -> str:
    now = dt or datetime.now()
    release_date = now.strftime("%d %b, %Y")
    release_day = now.strftime("%A")

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


def extract_thumbnail_url(ep_entry: dict) -> str | None:
    """Extract best quality thumbnail from yt-dlp entry."""
    thumb = ep_entry.get("thumbnail")
    if thumb and isinstance(thumb, str) and thumb.startswith("http"):
        return thumb

    thumbs = ep_entry.get("thumbnails")
    if thumbs and isinstance(thumbs, list):
        for t in reversed(thumbs):
            if isinstance(t, dict) and t.get("url"):
                return t["url"]

    poster = ep_entry.get("poster")
    if poster and isinstance(poster, str) and poster.startswith("http"):
        return poster

    return None


def build_inline_keyboard(watch_link: str) -> InlineKeyboardMarkup:
    """Creates interactive 'Watch Now' and 'Share' buttons."""
    keyboard = [
        [InlineKeyboardButton("🎬 Watch on JioHotstar", url=watch_link)],
        [InlineKeyboardButton("↗️ Share Episode", url=f"https://t.me/share/url?url={watch_link}&text=New%20Episode%20Released!")]
    ]
    return InlineKeyboardMarkup(keyboard)


async def send_episode_alert(bot, chat_id: int, alert_text: str, watch_link: str, thumbnail_url: str = None) -> bool:
    """Sends notification with thumbnail banner and inline buttons."""
    reply_markup = build_inline_keyboard(watch_link)

    if thumbnail_url:
        try:
            await bot.send_photo(
                chat_id=chat_id,
                photo=thumbnail_url,
                caption=alert_text,
                reply_markup=reply_markup
            )
            return True
        except Exception as photo_err:
            print(f"[!] Could not send photo ({photo_err}), falling back to text message...")

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=alert_text,
            reply_markup=reply_markup,
            disable_web_page_preview=False
        )
        return True
    except Exception as e:
        print(f"[!] Failed to deliver message to {chat_id}: {e}")
        return False


def fetch_episodes_sync(show_url: str) -> list[dict]:
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
    user_id = update.effective_user.id
    db_mode = f"MongoDB Atlas ({DATABASE_NAME})" if shows_col is not None else "Local Storage"
    auth_status = "✅ Authorized" if is_authorized(user_id) else "🔒 Unauthorized"
    if is_admin(user_id):
        auth_status = "👑 Super Admin"

    if not is_authorized(user_id):
        unauth_msg = (
            f"👋 <b>Welcome to the JioHotstar Episode Notification Bot!</b>\n\n"
            f"🔒 <b>Access Restricted:</b> You are not authorized yet.\n"
            f"🆔 <b>Your Telegram ID:</b> <code>{user_id}</code>\n\n"
            "Please send your ID to the administrator to request access."
        )
        await update.message.reply_text(unauth_msg, parse_mode="HTML")
        return

    admin_commands = ""
    if is_admin(user_id):
        admin_commands = (
            "\n<b>👑 Super Admin Commands:</b>\n"
            "👤 <code>/adduser &lt;id&gt;</code> - Authorize a user\n"
            "🚫 <code>/removeuser &lt;id&gt;</code> - Revoke user access\n"
            "👥 <code>/listusers</code> - List authorized users\n"
        )

    welcome_text = (
        "👋 <b>Welcome to the JioHotstar Episode Notification Bot!</b>\n\n"
        "I monitor your chosen serials on JioHotstar and notify you the moment a new episode is released.\n\n"
        "<b>Available Commands:</b>\n"
        "➕ <code>/addshow &lt;url&gt; [language]</code> - Start tracking a show\n"
        "<i>Example:</i> <code>/addshow https://www.hotstar.com/in/shows/patharamattu/1260141539 Malayalam</code>\n\n"
        "➖ <code>/removeshow &lt;id_or_name&gt;</code> - Stop tracking a show\n"
        "📋 <code>/listshows</code> - View shows tracked for this chat\n"
        "⚡ <code>/checknow</code> - Manually force check for new episodes right now\n"
        "📊 <code>/stats</code> - View bot statistics & status\n"
        "🖼️ <code>/test</code> - Preview notification with banner & buttons\n"
        f"{admin_commands}\n"
        f"💾 <b>Storage:</b> <code>{db_mode}</code>\n"
        f"🛡️ <b>Role:</b> {auth_status}"
    )
    await update.message.reply_text(welcome_text, parse_mode="HTML")


async def cmd_addshow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /addshow <url> [language]."""
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return

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
        f"You will receive an instant alert with image banner & watch button whenever a new episode drops!",
        parse_mode="HTML"
    )


async def cmd_removeshow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /removeshow <id_or_name>."""
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return

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
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return

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


async def cmd_checknow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /checknow - forces manual immediate check."""
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("⛔ You are not authorized to trigger manual checks.")
        return

    status_msg = await update.message.reply_text("⏳ Running instant Hotstar check across all tracked shows...")
    new_count = await check_and_broadcast_episodes(context.application)
    await status_msg.edit_text(f"✅ Check complete! Found and alerted <b>{new_count}</b> new episode(s).", parse_mode="HTML")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /stats - bot health and metrics."""
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("⛔ You are not authorized to view bot stats.")
        return

    uptime_str = get_uptime()
    all_shows = db_get_all_shows()
    total_shows = len(all_shows)
    total_episodes_cached = sum(len(s.get("seen_episode_ids", [])) for s in all_shows.values())
    total_users = len(db_get_authorized_users())
    storage_type = f"MongoDB Atlas ({DATABASE_NAME})" if shows_col is not None else "Local JSON"

    stats_text = (
        "📊 <b>Bot Statistics & Status</b>\n\n"
        f"⏱️ <b>Uptime:</b> {uptime_str}\n"
        f"💾 <b>Database:</b> {storage_type}\n"
        f"📺 <b>Tracked Shows:</b> {total_shows}\n"
        f"🎬 <b>Total Episodes Tracked:</b> {total_episodes_cached}\n"
        f"👥 <b>Authorized Users:</b> {total_users}\n"
        f"🔄 <b>Check Interval:</b> {CHECK_INTERVAL_SECONDS}s ({CHECK_INTERVAL_SECONDS // 60}m)\n"
        f"🌐 <b>Health Port:</b> {PORT}"
    )
    await update.message.reply_text(stats_text, parse_mode="HTML")


async def cmd_adduser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /adduser <user_id> (Admin only)."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Only the Super Admin can authorize new users.")
        return

    if not context.args:
        await update.message.reply_text("⚠️ <b>Usage:</b> <code>/adduser &lt;telegram_user_id&gt;</code>", parse_mode="HTML")
        return

    try:
        target_id = int(context.args[0].strip())
    except ValueError:
        await update.message.reply_text("❌ User ID must be a numeric Telegram ID (e.g. <code>123456789</code>).", parse_mode="HTML")
        return

    db_add_user(target_id)
    await update.message.reply_text(f"✅ User <code>{target_id}</code> is now authorized to use this bot!", parse_mode="HTML")


async def cmd_removeuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /removeuser <user_id> (Admin only)."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Only the Super Admin can revoke users.")
        return

    if not context.args:
        await update.message.reply_text("⚠️ <b>Usage:</b> <code>/removeuser &lt;telegram_user_id&gt;</code>", parse_mode="HTML")
        return

    try:
        target_id = int(context.args[0].strip())
    except ValueError:
        await update.message.reply_text("❌ User ID must be a numeric Telegram ID.", parse_mode="HTML")
        return

    if ADMIN_ID and str(target_id) == str(ADMIN_ID):
        await update.message.reply_text("❌ You cannot remove the Super Admin.", parse_mode="HTML")
        return

    db_remove_user(target_id)
    await update.message.reply_text(f"🗑️ User <code>{target_id}</code> authorization has been revoked.", parse_mode="HTML")


async def cmd_listusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /listusers (Admin only)."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Only the Super Admin can list users.")
        return

    users = db_get_authorized_users()
    lines = [f"👥 <b>Authorized Users ({len(users)}):</b>\n"]
    for u in sorted(users):
        tag = " 👑 (Super Admin)" if ADMIN_ID and str(u) == str(ADMIN_ID) else ""
        lines.append(f"• <code>{u}</code>{tag}")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /test - preview full notification with image and button."""
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return

    watch_link = "https://www.hotstar.com/in/shows/patharamattu/1260141539/nandana-arrives-to-arrest-abhi/1641039866/watch"
    sample_text = format_notification(
        serial_name="Patharamattu",
        ep_name="Nandana Arrives to Arrest Abhi",
        ep_number="1116",
        season_number="1",
        language="Malayalam",
        from_ott="Hotstar",
        watch_link=watch_link
    )
    # Sample high quality banner image for visual test
    sample_poster = "https://img10.hotstar.com/image/upload/f_auto,q_90,w_1200/sources/r1/cms/prod/8549/1648549-i-124b89dc1555"
    await send_episode_alert(context.bot, update.effective_chat.id, sample_text, watch_link, thumbnail_url=sample_poster)


# ------------------ BACKGROUND AUTO-MONITOR & CHECK ENGINE ------------------
async def check_and_broadcast_episodes(app: Application) -> int:
    """Core checking engine: checks all tracked shows and sends alerts. Returns count of new episodes found."""
    new_episodes_count = 0
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
                thumbnail_url = extract_thumbnail_url(ep)

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

                # Broadcast to all subscribers with photo banner & watch button
                for chat_id in subscribers:
                    await send_episode_alert(
                        app.bot,
                        chat_id=chat_id,
                        alert_text=alert_text,
                        watch_link=watch_link,
                        thumbnail_url=thumbnail_url
                    )

                # Mark as seen in database
                db_add_seen_episode(show_id, ep_id)
                seen_ids.add(ep_id)
                new_episodes_count += 1
                print(f"[✓] Broadcasted new episode of {show['serial_name']}: Ep {ep_num} ({ep_id})")

    except Exception as e:
        print(f"[!] Error checking episodes: {e}")

    return new_episodes_count


async def background_monitor(app: Application):
    """Background loop running on CHECK_INTERVAL_SECONDS."""
    while True:
        await check_and_broadcast_episodes(app)
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


async def post_init(application: Application):
    asyncio.create_task(background_monitor(application))


# ------------------ MAIN ENTRYPOINT ------------------
def main():
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        print("[!] ERROR: TELEGRAM_BOT_TOKEN is not set.")
        print("[!] Create a .env file with your token or export TELEGRAM_BOT_TOKEN in your environment.")
        return

    threading.Thread(target=start_health_server, daemon=True).start()

    print("[*] Starting Telegram Bot with visual upgrades & admin controls...")
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("addshow", cmd_addshow))
    app.add_handler(CommandHandler("removeshow", cmd_removeshow))
    app.add_handler(CommandHandler("listshows", cmd_listshows))
    app.add_handler(CommandHandler("checknow", cmd_checknow))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("test", cmd_test))

    # Super Admin Commands
    app.add_handler(CommandHandler("adduser", cmd_adduser))
    app.add_handler(CommandHandler("removeuser", cmd_removeuser))
    app.add_handler(CommandHandler("listusers", cmd_listusers))

    app.run_polling()


if __name__ == "__main__":
    main()
