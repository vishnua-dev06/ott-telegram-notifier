import os
import re
import json
import asyncio
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
CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "600"))
DATA_FILE = os.getenv("DATA_FILE", "shows_data.json")
# ==============================================================


# ------------------ DATA PERSISTENCE ------------------
def load_db() -> dict:
    """Load shows and subscriber database."""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"shows": {}}
    return {"shows": {}}


def save_db(data: dict):
    """Save database to disk."""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


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
    welcome_text = (
        "👋 <b>Welcome to the JioHotstar Episode Notification Bot!</b>\n\n"
        "I monitor your chosen serials on JioHotstar and notify you the moment a new episode is released.\n\n"
        "<b>Available Commands:</b>\n"
        "➕ <code>/addshow &lt;url&gt; [language]</code> - Start tracking a show\n"
        "<i>Example:</i> <code>/addshow https://www.hotstar.com/in/shows/patharamattu/1260141539 Malayalam</code>\n\n"
        "➖ <code>/removeshow &lt;id_or_name&gt;</code> - Stop tracking a show\n"
        "<i>Example:</i> <code>/removeshow 1260141539</code>\n\n"
        "📋 <code>/listshows</code> - View shows tracked for this chat\n"
        "⚡ <code>/test</code> - Preview the notification format"
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

    db = load_db()
    shows = db.setdefault("shows", {})

    if show_id not in shows:
        seen_ids = [str(e.get("id")) for e in entries if e and e.get("id")]
        shows[show_id] = {
            "show_id": show_id,
            "show_slug": show_slug,
            "serial_name": serial_name,
            "language": language,
            "from_ott": "Hotstar",
            "url": url,
            "subscribers": [chat_id],
            "seen_episode_ids": seen_ids,
        }
        cached_count = len(seen_ids)
    else:
        if chat_id not in shows[show_id]["subscribers"]:
            shows[show_id]["subscribers"].append(chat_id)
        cached_count = len(shows[show_id].get("seen_episode_ids", []))

    save_db(db)

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
    db = load_db()
    shows = db.get("shows", {})

    found_id = None
    for s_id, s_info in shows.items():
        if chat_id in s_info.get("subscribers", []):
            if query == s_id or query == s_info.get("show_slug", "").lower() or query in s_info.get("serial_name", "").lower():
                found_id = s_id
                break

    if not found_id:
        await update.message.reply_text("❌ Show not found in your tracked list. Use <code>/listshows</code> to check.", parse_mode="HTML")
        return

    serial_name = shows[found_id]["serial_name"]
    shows[found_id]["subscribers"].remove(chat_id)

    if not shows[found_id]["subscribers"]:
        del shows[found_id]

    save_db(db)
    await update.message.reply_text(f"🗑️ <b>{serial_name}</b> has been removed from your tracking list.", parse_mode="HTML")


async def cmd_listshows(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /listshows."""
    chat_id = update.effective_chat.id
    db = load_db()
    user_shows = [s for s in db.get("shows", {}).values() if chat_id in s.get("subscribers", [])]

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
            db = load_db()
            shows = db.get("shows", {})

            for show_id, show in list(shows.items()):
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

                    for chat_id in subscribers:
                        try:
                            await app.bot.send_message(
                                chat_id=chat_id,
                                text=alert_text,
                                disable_web_page_preview=False
                            )
                        except Exception as send_err:
                            print(f"[!] Could not send to {chat_id}: {send_err}")

                    seen_ids.add(ep_id)
                    show["seen_episode_ids"] = list(seen_ids)
                    save_db(db)
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
