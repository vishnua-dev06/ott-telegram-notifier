# JioHotstar Episode Notification Telegram Bot ⚡

An automated Telegram bot that monitors your favorite TV serials and shows on JioHotstar and instantly sends formatted release notifications with direct watch links.

---

## ⚡ Features

- **MongoDB Atlas Cloud Database**: Persists your tracked shows, subscribers, and released episode IDs forever across server restarts.
- **Selective Tracking**: Users and channel admins can add and remove specific shows on demand.
- **Exact Layout Formatting**: Sends alerts matching your desired layout including Serial Name, Episode Name, Episode Number, Season Number, Language, Release Date, Release Day, and Direct Link.
- **Anti-Spam / Deduplication**: Automatically caches previous episodes when a show is added so users are only notified about new releases.
- **Lightweight & Fast**: Uses `yt-dlp` in metadata-only mode without downloading video streams.
- **Async Non-blocking Architecture**: Built with `python-telegram-bot` and asynchronous background loops.
- **Koyeb & Cloud Compatible**: Built-in HTTP health check server on port 8080.

---

## 📱 Notification Preview

```text
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
```

---

## 🤖 Bot Commands

| Command | Description | Example |
| :--- | :--- | :--- |
| `/start` | Welcome message & command guide | `/start` |
| `/addshow <url> [language]` | Start tracking a show | `/addshow https://www.hotstar.com/in/shows/patharamattu/1260141539 Malayalam` |
| `/removeshow <id_or_name>` | Stop tracking a show | `/removeshow 1260141539` |
| `/listshows` | View shows tracked in this chat | `/listshows` |
| `/test` | Send sample notification format | `/test` |

---

## ⚙️ Environment Variables

| Variable | Required | Description |
| :--- | :--- | :--- |
| `TELEGRAM_BOT_TOKEN` | **Yes** | Bot token from [@BotFather](https://t.me/BotFather) |
| `DATABASE_URI` | Optional | MongoDB Atlas connection string (e.g. `mongodb+srv://...`) |
| `DATABASE_NAME` | Optional | MongoDB database name (default: `ott_notifier_db`) |
| `CHECK_INTERVAL_SECONDS` | Optional | Check frequency in seconds (default: `600`) |
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

Edit `.env` with your values:
```env
TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
DATABASE_URI=mongodb+srv://username:password@cluster.mongodb.net/?retryWrites=true&w=majority
DATABASE_NAME=ott_notifier_db
CHECK_INTERVAL_SECONDS=600
PORT=8080
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
   - `DATABASE_URI`
   - `DATABASE_NAME`
   - `PORT` = `8080`
3. Deploy! Koyeb will verify health on port 8080 and run the bot 24/7.
