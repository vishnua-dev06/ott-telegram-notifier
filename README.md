# JioHotstar Episode Notification Telegram Bot ⚡

An automated Telegram bot that monitors your favorite TV serials and shows on JioHotstar and instantly sends formatted release notifications with episode poster banners, direct watch buttons, and complete admin authorization controls.

---

## ⚡ Features

- **🖼️ Episode Thumbnail Banners**: Delivers high-definition episode posters / thumbnails directly in Telegram.
- **🎬 Inline "Watch Now" Button**: One-tap interactive button to jump straight into the episode on JioHotstar or share it.
- **🛡️ Admin Lock & Authorization**: Protect your bot! Authorize specific users with `/adduser` or keep it private to your ID.
- **⚡ Instant Check (`/checknow`)**: Force immediate Hotstar scan on demand without waiting for the timer.
- **📊 Real-time Stats (`/stats`)**: Monitor uptime, database connection, tracked shows, and total cached episodes.
- **💾 MongoDB Atlas Persistence**: Stores all shows, subscribers, and released episode IDs forever across server restarts (`DATABASE_URI` and `DATABASE_NAME`).
- **Selective Tracking**: Users and channel admins can add and remove specific shows on demand.
- **Anti-Spam / Deduplication**: Pre-caches existing episodes so old episodes are never spammed.
- **Koyeb & Cloud Compatible**: Built-in HTTP health check server on port 8080.

---

## 📱 Notification Preview

```text
[ 🖼️ Episode Banner Image ]

⚡ #First_On_Hotstar

Serial Name: Patharamattu
Episode Name: Nandana Arrives to Arrest Abhi
Episode Number: 1116
Season Number: 1
From OTT: Hotstar
Language: Malayalam
Release Date: 03 Nov, 2026
Release Day: Tuesday

Link: https://www.hotstar.com/in/shows/patharamattu/1260141539/nandana-arrives-to-arrest-abhi/1641039866/watch

[ 🎬 Watch on JioHotstar ]   [ ↗️ Share Episode ]
```

---

## 🤖 Bot Commands Reference

### General & Authorized Commands
| Command | Description | Example |
| :--- | :--- | :--- |
| `/start` | Welcome message, user ID & role status | `/start` |
| `/addshow <url> [language]` | Start tracking a show | `/addshow https://www.hotstar.com/in/shows/patharamattu/1260141539 Malayalam` |
| `/removeshow <id_or_name>` | Stop tracking a show | `/removeshow 1260141539` |
| `/listshows` | View shows tracked in this chat | `/listshows` |
| `/checknow` | Force immediate check for new episodes | `/checknow` |
| `/stats` | View bot uptime, database & metrics | `/stats` |
| `/test` | Preview notification with banner & buttons | `/test` |

### 👑 Super Admin Commands (`ADMIN_ID` only)
| Command | Description | Example |
| :--- | :--- | :--- |
| `/adduser <user_id>` | Authorize a user to use the bot | `/adduser 123456789` |
| `/removeuser <user_id>` | Revoke access from a user | `/removeuser 123456789` |
| `/listusers` | List all authorized users | `/listusers` |

---

## ⚙️ Environment Variables

| Variable | Required | Description |
| :--- | :--- | :--- |
| `TELEGRAM_BOT_TOKEN` | **Yes** | Bot token from [@BotFather](https://t.me/BotFather) |
| `ADMIN_ID` | Optional | Your Telegram numeric User ID (from [@userinfobot](https://t.me/userinfobot)) |
| `DATABASE_URI` | Optional | MongoDB Atlas connection string (`mongodb+srv://...`) |
| `DATABASE_NAME` | Optional | MongoDB database name (default: `ott_notifier_db`) |
| `CHECK_INTERVAL_SECONDS` | Optional | Periodic check frequency in seconds (default: `600`) |
| `PORT` | Optional | Health check port for Koyeb (default: `8080`) |

---

## 🚀 Setup & Installation

### 1. Clone the Repository
```bash
git clone https://github.com/vishnua-dev06/ott-telegram-notifier.git
cd ott-telegram-notifier
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Run the Bot
```bash
python bot.py
```

---

## ☁️ Koyeb Deployment

1. Create a **Web Service** on [Koyeb](https://app.koyeb.com) linked to `vishnua-dev06/ott-telegram-notifier`.
2. Add environment variables:
   - `TELEGRAM_BOT_TOKEN`
   - `ADMIN_ID`
   - `DATABASE_URI`
   - `DATABASE_NAME`
   - `PORT` = `8080`
3. Deploy!
