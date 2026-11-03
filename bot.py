import os
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from dotenv import load_dotenv
import telegram.error
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

# Load environment variables
load_dotenv()

# Import database layer
import database as db

# Import modular OTT platforms router and helpers
from platforms import (
    parse_show_url,
    fetch_episodes,
    build_watch_link,
    search_episode_online,
    get_supported_platforms,
)
from platforms.base import parse_episode_details, extract_thumbnail_url

# ======================= TIMEZONE CONFIGURATION =======================
# Indian Standard Time (IST) ensures exact release date & day on foreign cloud servers (Koyeb, Render, AWS)
try:
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
except Exception:
    from datetime import timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))

# ======================= CONFIGURATION =======================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_ID = os.getenv("ADMIN_ID", "").strip()
CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "600"))
PORT = int(os.getenv("PORT", "8080"))
BOT_START_TIME = datetime.now(IST)
# ==============================================================


# ------------------ DUMMY HTTP SERVER (KOYEB HEALTH CHECKS) ------------------
class HealthCheckHandler(BaseHTTPRequestHandler):
    """Responds to cloud platform health checks (Koyeb, Render, etc.)."""
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK - Multi-OTT Telegram Notifier is running!")

    def log_message(self, format, *args):
        return


def start_health_server():
    try:
        server = HTTPServer(("0.0.0.0", PORT), HealthCheckHandler)
        print(f"[*] Health check server active on port {PORT} (Koyeb/Cloud compatible)")
        server.serve_forever()
    except Exception as e:
        print(f"[!] Health check server warning: {e}")


# ------------------ PRESENTATION & NOTIFICATIONS ------------------
def get_uptime() -> str:
    delta = datetime.now(IST) - BOT_START_TIME
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


def format_notification(serial_name: str, ep_name: str, ep_number: str,
                        season_number: str, language: str, from_ott: str,
                        watch_link: str, dt: datetime = None) -> str:
    now = dt or datetime.now(IST)
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


def build_inline_keyboard(watch_link: str, from_ott: str = "Hotstar", ep_title: str = None) -> InlineKeyboardMarkup:
    is_direct_watch = "/watch" in watch_link
    button_label = f"▶️ Watch on {from_ott}" if is_direct_watch else f"📺 Watch Latest on {from_ott}"
    keyboard = [
        [InlineKeyboardButton(button_label, url=watch_link)],
    ]
    if not is_direct_watch and ep_title:
        search_query = f"{from_ott} {ep_title} watch online"
        search_url = f"https://www.google.com/search?q={urllib.parse.quote(search_query)}"
        keyboard.append([InlineKeyboardButton("🔍 Search Episode Online", url=search_url)])

    keyboard.append([InlineKeyboardButton("↗️ Share Episode", url=f"https://t.me/share/url?url={watch_link}&text=New%20Episode%20Released!")])
    return InlineKeyboardMarkup(keyboard)


async def send_episode_alert(bot, chat_id: int, alert_text: str, watch_link: str, from_ott: str = "Hotstar", thumbnail_url: str = None, ep_title: str = None) -> bool:
    reply_markup = build_inline_keyboard(watch_link, from_ott=from_ott, ep_title=ep_title)

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
            print(f"[!] Photo delivery warning ({photo_err}), falling back to text message...")

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


# ------------------ TELEGRAM COMMAND HANDLERS ------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db_mode = db.get_storage_name()
    auth_status = "✅ Authorized" if db.is_authorized(user_id) else "🔒 Unauthorized"
    if db.is_admin(user_id):
        auth_status = "👑 Super Admin"

    if not db.is_authorized(user_id):
        unauth_msg = (
            f"👋 <b>Welcome to the Multi-OTT Episode Notification Bot!</b>\n\n"
            f"🔒 <b>Access Restricted:</b> You are not authorized yet.\n"
            f"🆔 <b>Your Telegram ID:</b> <code>{user_id}</code>\n\n"
            "Please send your ID to the administrator to request access."
        )
        await update.message.reply_text(unauth_msg, parse_mode="HTML")
        return

    admin_commands = ""
    if db.is_admin(user_id):
        admin_commands = (
            "\n<b>👑 Super Admin Commands:</b>\n"
            "📢 <code>/broadcast &lt;message&gt;</code> - Send message to all subscribers\n"
            "👤 <code>/adduser &lt;id&gt;</code> - Authorize a user\n"
            "🚫 <code>/removeuser &lt;id&gt;</code> - Revoke user access\n"
            "👥 <code>/listusers</code> - List authorized users\n"
        )

    supported_list = ", ".join(f"<b>{p}</b>" for p in get_supported_platforms())

    welcome_text = (
        "👋 <b>Welcome to the Multi-OTT Episode Notification Bot!</b>\n\n"
        f"Supported Platforms: {supported_list}.\n\n"
        "<b>Available Commands:</b>\n"
        "➕ <code>/addshow &lt;url&gt; [language]</code> - Start tracking a show\n"
        "<i>Example:</i> <code>/addshow https://www.hotstar.com/in/shows/patharamattu/1260141539 Malayalam</code>\n\n"
        "➖ <code>/removeshow &lt;id_or_name&gt;</code> - Stop tracking a show\n"
        "📋 <code>/listshows</code> - View shows tracked for this chat\n"
        "🔍 <code>/getepisode &lt;show_name&gt; [ep_num]</code> - On-demand episode lookup\n"
        "<i>Example:</i> <code>/getepisode Patharamattu 1116</code> (or omit number for latest)\n\n"
        "⚡ <code>/checknow</code> - Force instant check for new episodes\n"
        "📊 <code>/stats</code> - View bot metrics & server status\n"
        "🖼️ <code>/test</code> - Preview notification banner & watch button\n"
        f"{admin_commands}\n"
        f"💾 <b>Storage:</b> <code>{db_mode}</code>\n"
        f"🛡️ <b>Role:</b> {auth_status}"
    )
    await update.message.reply_text(welcome_text, parse_mode="HTML")


async def cmd_addshow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not db.is_authorized(user_id):
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return

    chat_id = update.effective_chat.id
    args = context.args

    if not args:
        await update.message.reply_text(
            "⚠️ <b>Usage:</b>\n<code>/addshow &lt;ott_show_url&gt; [language]</code>\n\n"
            "<i>Examples:</i>\n"
            "• Hotstar: <code>/addshow https://www.hotstar.com/in/shows/patharamattu/1260141539 Malayalam</code>\n"
            "• Zee5: <code>/addshow https://www.zee5.com/tv-shows/details/chembarathi/0-6-1188 Malayalam</code>\n"
            "• SonyLIV, SunNXT, and ManoramaMAX supported!",
            parse_mode="HTML"
        )
        return

    url = args[0].strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    language = args[1] if len(args) > 1 else "Malayalam"

    parsed = parse_show_url(url)
    if not parsed:
        await update.message.reply_text("❌ Could not parse show URL. Please check the link and try again.", parse_mode="HTML")
        return

    show_slug, show_id, serial_name, platform, canonical_url = parsed
    status_msg = await update.message.reply_text(f"⏳ Inspecting <b>{serial_name}</b> on <b>{platform}</b>...", parse_mode="HTML")

    entries = await asyncio.to_thread(fetch_episodes, canonical_url, platform)
    existing_show = db.db_get_show(show_id)

    if not existing_show:
        seen_ids = [str(e.get("id")) for e in entries if e and e.get("id")]
        show_data = {
            "show_id": show_id,
            "show_slug": show_slug,
            "serial_name": serial_name,
            "language": language,
            "from_ott": platform,
            "url": canonical_url,
            "subscribers": [chat_id],
            "seen_episode_ids": seen_ids,
            "cached_episodes": entries[:30],
        }
        db.db_save_new_show(show_data)
        cached_count = len(seen_ids)
    else:
        db.db_add_subscriber(show_id, chat_id)
        if entries:
            db.db_update_cached_episodes(show_id, entries)
        cached_count = len(existing_show.get("seen_episode_ids", []))

    await status_msg.edit_text(
        f"✅ <b>Now Tracking: {serial_name}</b>\n\n"
        f"• <b>Platform:</b> {platform}\n"
        f"• <b>Language:</b> {language}\n"
        f"• <b>Show ID:</b> <code>{show_id}</code>\n"
        f"• <b>Pre-cached Episodes:</b> {cached_count}\n\n"
        f"You will receive an instant alert with image banner & watch button whenever a new episode drops!",
        parse_mode="HTML"
    )


async def cmd_removeshow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not db.is_authorized(user_id):
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return

    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("⚠️ <b>Usage:</b> <code>/removeshow &lt;show_id_or_name&gt;</code>", parse_mode="HTML")
        return

    query = " ".join(context.args).lower().strip()
    user_shows = db.db_get_user_shows(chat_id)

    target_id = None
    for s in user_shows:
        if query == s["show_id"] or query == s.get("show_slug", "").lower() or query in s.get("serial_name", "").lower():
            target_id = s["show_id"]
            break

    if not target_id:
        await update.message.reply_text("❌ Show not found in your tracked list. Use <code>/listshows</code> to check.", parse_mode="HTML")
        return

    serial_name = db.db_remove_subscriber(target_id, chat_id)
    await update.message.reply_text(f"🗑️ <b>{serial_name}</b> has been removed from your tracking list.", parse_mode="HTML")


async def cmd_listshows(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not db.is_authorized(user_id):
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return

    chat_id = update.effective_chat.id
    user_shows = db.db_get_user_shows(chat_id)

    if not user_shows:
        await update.message.reply_text("ℹ️ You are not tracking any shows yet.\nUse <code>/addshow &lt;url&gt;</code> to start tracking!", parse_mode="HTML")
        return

    lines = [f"📺 <b>Your Tracked Shows ({len(user_shows)}):</b>\n"]
    for idx, s in enumerate(user_shows, 1):
        ott = s.get("from_ott", "Hotstar")
        lines.append(
            f"<b>{idx}. {s['serial_name']}</b> [{ott}] ({s['language']})\n"
            f"   • ID: <code>{s['show_id']}</code>\n"
            f"   • Link: <a href='{s['url']}'>{ott} Page</a>"
        )

    await update.message.reply_text("\n\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)


async def cmd_getepisode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not db.is_authorized(user_id):
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return

    if not context.args:
        await update.message.reply_text(
            "⚠️ <b>Usage:</b> <code>/getepisode &lt;show_name_or_id&gt; [episode_number]</code>\n\n"
            "<i>Examples:</i>\n"
            "• Specific episode: <code>/getepisode Patharamattu 1116</code>\n"
            "• Latest episode: <code>/getepisode Patharamattu</code>",
            parse_mode="HTML"
        )
        return

    args = context.args
    ep_num_query = None
    if len(args) > 1 and args[-1].isdigit():
        ep_num_query = args[-1]
        show_query = " ".join(args[:-1]).lower().strip()
    else:
        show_query = " ".join(args).lower().strip()

    all_shows = db.db_get_all_shows()
    matched_show = None

    for s_id, s in all_shows.items():
        if show_query == s_id or show_query == s.get("show_slug", "").lower() or show_query in s.get("serial_name", "").lower():
            matched_show = s
            break

    if not matched_show:
        await update.message.reply_text(
            f"❌ Show '{show_query}' not found in database.\nUse <code>/listshows</code> to see your tracked shows, or add it with <code>/addshow</code>.",
            parse_mode="HTML"
        )
        return

    status_msg = await update.message.reply_text(f"🔍 Searching episodes for <b>{matched_show['serial_name']}</b>...", parse_mode="HTML")

    from_ott = matched_show.get("from_ott", "Hotstar")
    episodes = matched_show.get("cached_episodes") or []

    # If cache is empty, attempt a fresh scrape
    if not episodes:
        episodes = await asyncio.to_thread(fetch_episodes, matched_show["url"], from_ott)
        if episodes:
            db.db_update_cached_episodes(matched_show["show_id"], episodes)

    target_ep = None
    if episodes:
        if ep_num_query:
            for ep in episodes:
                raw_title = str(ep.get("title", ""))
                ep_n, _ = parse_episode_details(raw_title)
                if (
                    ep_n == ep_num_query
                    or f"episode {ep_num_query}" in raw_title.lower()
                    or f"ep {ep_num_query}" in raw_title.lower()
                    or f"- {ep_num_query}" in raw_title
                    or raw_title.endswith(f" {ep_num_query}")
                ):
                    target_ep = ep
                    break
        else:
            target_ep = episodes[0]

    # Query search engine index if not found in cache/live scrape
    if not target_ep and ep_num_query:
        online_match = await asyncio.to_thread(
            search_episode_online,
            matched_show["serial_name"],
            matched_show["show_slug"],
            matched_show["show_id"],
            ep_num_query,
            from_ott
        )
        if online_match and online_match.get("id"):
            target_ep = online_match
            # Cache it so future lookups are instant
            cached = matched_show.get("cached_episodes") or []
            cached.insert(0, target_ep)
            db.db_update_cached_episodes(matched_show["show_id"], cached)

    # Fallback if specific episode wasn't found in list or scraper was throttled
    if not target_ep:
        if ep_num_query:
            target_ep = {
                "id": matched_show["show_id"],
                "title": f"Episode {ep_num_query}",
                "season_number": "1",
                "url": matched_show["url"],
            }
        elif episodes:
            target_ep = episodes[0]
        else:
            # Construct latest episode details from show
            seen = matched_show.get("seen_episode_ids", [])
            latest_id = str(seen[-1]) if seen else matched_show["show_id"]
            target_ep = {
                "id": latest_id,
                "title": "Latest Episode",
                "season_number": "1",
                "url": matched_show["url"],
            }

    try:
        await status_msg.delete()
    except Exception:
        pass

    raw_title = target_ep.get("title", "Episode")
    ep_num, ep_name = parse_episode_details(raw_title)
    if ep_num_query and (not ep_num or ep_num == "Latest"):
        ep_num = ep_num_query
        if ep_name == "Episode" or ep_name == "Latest Episode":
            ep_name = f"Episode {ep_num_query}"

    season_num = str(target_ep.get("season_number") or "1")
    ep_id = str(target_ep.get("id"))
    thumbnail_url = extract_thumbnail_url(target_ep)

    watch_link = build_watch_link(
        matched_show["show_slug"],
        matched_show["show_id"],
        ep_name,
        ep_id,
        platform_name=from_ott,
        raw_url=target_ep.get("url")
    )

    alert_text = format_notification(
        serial_name=matched_show["serial_name"],
        ep_name=ep_name,
        ep_number=ep_num,
        season_number=season_num,
        language=matched_show["language"],
        from_ott=from_ott,
        watch_link=watch_link
    )

    await send_episode_alert(
        context.bot,
        chat_id=update.effective_chat.id,
        alert_text=alert_text,
        watch_link=watch_link,
        from_ott=from_ott,
        thumbnail_url=thumbnail_url,
        ep_title=f"{matched_show['serial_name']} {ep_name}"
    )


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db.is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Only the Super Admin can broadcast messages.")
        return

    if not context.args:
        await update.message.reply_text("⚠️ <b>Usage:</b> <code>/broadcast &lt;announcement text&gt;</code>", parse_mode="HTML")
        return

    broadcast_text = " ".join(context.args)
    target_chats = db.db_get_all_target_chats()

    if not target_chats:
        await update.message.reply_text("ℹ️ No users or channels found in the database to broadcast to.")
        return

    progress_msg = await update.message.reply_text(f"⏳ Broadcasting to {len(target_chats)} chats...")

    success_count = 0
    fail_count = 0
    message_payload = f"📢 <b>Announcement from Admin:</b>\n\n{broadcast_text}"

    for chat_id in target_chats:
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=message_payload,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            success_count += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            print(f"[!] Broadcast failed for {chat_id}: {e}")
            fail_count += 1

    await progress_msg.edit_text(
        f"✅ <b>Broadcast Completed!</b>\n\n"
        f"• <b>Delivered:</b> {success_count}\n"
        f"• <b>Failed:</b> {fail_count}\n"
        f"• <b>Total:</b> {len(target_chats)}",
        parse_mode="HTML"
    )


async def cmd_checknow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not db.is_authorized(user_id):
        await update.message.reply_text("⛔ You are not authorized to trigger manual checks.")
        return

    status_msg = await update.message.reply_text("⏳ Running instant check across all tracked OTT shows...")
    new_count = await check_and_broadcast_episodes(context.application)
    await status_msg.edit_text(f"✅ Check complete! Found and alerted <b>{new_count}</b> new episode(s).", parse_mode="HTML")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not db.is_authorized(user_id):
        await update.message.reply_text("⛔ You are not authorized to view bot stats.")
        return

    uptime_str = get_uptime()
    all_shows = db.db_get_all_shows()
    total_shows = len(all_shows)
    total_episodes_cached = sum(len(s.get("seen_episode_ids", [])) for s in all_shows.values())
    total_users = len(db.db_get_authorized_users())
    storage_type = db.get_storage_name()

    platforms_count = {}
    for s in all_shows.values():
        p = s.get("from_ott", "Hotstar")
        platforms_count[p] = platforms_count.get(p, 0) + 1
    platform_summary = ", ".join(f"{k}: {v}" for k, v in platforms_count.items()) or "None"

    stats_text = (
        "📊 <b>Bot Statistics & Status</b>\n\n"
        f"🕒 <b>Current IST:</b> {datetime.now(IST).strftime('%d %b %Y, %I:%M %p')}\n"
        f"⏱️ <b>Uptime:</b> {uptime_str}\n"
        f"💾 <b>Database:</b> {storage_type}\n"
        f"📺 <b>Tracked Shows:</b> {total_shows} ({platform_summary})\n"
        f"🎬 <b>Total Episodes Tracked:</b> {total_episodes_cached}\n"
        f"👥 <b>Authorized Users:</b> {total_users}\n"
        f"🔄 <b>Check Interval:</b> {CHECK_INTERVAL_SECONDS}s ({CHECK_INTERVAL_SECONDS // 60}m)\n"
        f"🌐 <b>Health Port:</b> {PORT}"
    )
    await update.message.reply_text(stats_text, parse_mode="HTML")


async def cmd_adduser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db.is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Only the Super Admin can authorize new users.")
        return

    if not context.args:
        await update.message.reply_text("⚠️ <b>Usage:</b> <code>/adduser &lt;telegram_user_id&gt;</code>", parse_mode="HTML")
        return

    try:
        target_id = int(context.args[0].strip())
    except ValueError:
        await update.message.reply_text("❌ User ID must be a numeric Telegram ID.", parse_mode="HTML")
        return

    db.db_add_user(target_id)
    await update.message.reply_text(f"✅ User <code>{target_id}</code> is now authorized to use this bot!", parse_mode="HTML")


async def cmd_removeuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db.is_admin(update.effective_user.id):
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

    db.db_remove_user(target_id)
    await update.message.reply_text(f"🗑️ User <code>{target_id}</code> authorization has been revoked.", parse_mode="HTML")


async def cmd_listusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db.is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Only the Super Admin can list users.")
        return

    users = db.db_get_authorized_users()
    lines = [f"👥 <b>Authorized Users ({len(users)}):</b>\n"]
    for u in sorted(users):
        tag = " 👑 (Super Admin)" if ADMIN_ID and str(u) == str(ADMIN_ID) else ""
        lines.append(f"• <code>{u}</code>{tag}")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not db.is_authorized(user_id):
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
    sample_poster = "https://img10.hotstar.com/image/upload/f_auto,q_90,w_1200/sources/r1/cms/prod/8549/1648549-i-124b89dc1555"
    await send_episode_alert(context.bot, update.effective_chat.id, sample_text, watch_link, from_ott="Hotstar", thumbnail_url=sample_poster)


# ------------------ TELEGRAM ERROR HANDLER ------------------
async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if isinstance(context.error, telegram.error.Conflict):
        print("\n[⚠️ CONFLICT ERROR] Another instance of this bot is polling getUpdates!")
        print("[⚠️ CONFLICT ERROR] 1. Stop 'python bot.py' if running locally on your PC.")
        print("[⚠️ CONFLICT ERROR] 2. In Koyeb, verify Instance Count is set to 1.\n")
        await asyncio.sleep(5)
    elif isinstance(context.error, telegram.error.NetworkError):
        print(f"[!] Telegram network warning: {context.error}")
        await asyncio.sleep(3)
    else:
        print(f"[!] Telegram unhandled error: {context.error}")


# ------------------ BACKGROUND AUTO-MONITOR & CHECK ENGINE ------------------
async def check_and_broadcast_episodes(app: Application) -> int:
    new_episodes_count = 0
    try:
        all_shows = db.db_get_all_shows()

        for show_id, show in all_shows.items():
            subscribers = show.get("subscribers", [])
            if not subscribers:
                continue

            from_ott = show.get("from_ott", "Hotstar")
            entries = await asyncio.to_thread(fetch_episodes, show["url"], from_ott)
            seen_ids = set(show.get("seen_episode_ids", []))

            if entries:
                db.db_update_cached_episodes(show_id, entries)

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
                    ep_id,
                    platform_name=from_ott,
                    raw_url=ep.get("url")
                )

                alert_text = format_notification(
                    serial_name=show["serial_name"],
                    ep_name=ep_name,
                    ep_number=ep_num,
                    season_number=season_num,
                    language=show["language"],
                    from_ott=from_ott,
                    watch_link=watch_link
                )

                for chat_id in subscribers:
                    await send_episode_alert(
                        app.bot,
                        chat_id=chat_id,
                        alert_text=alert_text,
                        watch_link=watch_link,
                        from_ott=from_ott,
                        thumbnail_url=thumbnail_url
                    )

                db.db_add_seen_episode(show_id, ep_id)
                seen_ids.add(ep_id)
                new_episodes_count += 1
                print(f"[✓] Broadcasted new episode of {show['serial_name']} ({from_ott}): Ep {ep_num} ({ep_id})")

    except Exception as e:
        print(f"[!] Error checking episodes: {e}")

    return new_episodes_count


async def background_monitor(app: Application):
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

    print("[*] Starting Modular Multi-OTT Telegram Bot...")
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    app.add_error_handler(global_error_handler)

    # Core Show Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("addshow", cmd_addshow))
    app.add_handler(CommandHandler("removeshow", cmd_removeshow))
    app.add_handler(CommandHandler("listshows", cmd_listshows))

    # On-Demand Lookup & Control Commands
    app.add_handler(CommandHandler("getepisode", cmd_getepisode))
    app.add_handler(CommandHandler("find", cmd_getepisode))
    app.add_handler(CommandHandler("checknow", cmd_checknow))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("test", cmd_test))

    # Super Admin Commands
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CommandHandler("adduser", cmd_adduser))
    app.add_handler(CommandHandler("removeuser", cmd_removeuser))
    app.add_handler(CommandHandler("listusers", cmd_listusers))

    app.run_polling()


if __name__ == "__main__":
    main()
