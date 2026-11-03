# JioHotstar Episode Notification Telegram Bot ⚡

An automated Telegram bot that monitors your favorite TV serials and shows on JioHotstar and instantly sends formatted release notifications with direct watch links.

---

## ⚡ Features

- **Selective Tracking**: Users and channel admins can add and remove specific shows on demand.
- **Exact Layout Formatting**: Sends alerts matching your desired layout including Serial Name, Episode Name, Episode Number, Season Number, Language, Release Date, Release Day, and Direct Link.
- **Anti-Spam / Deduplication**: Automatically caches previous episodes when a show is added so users are only notified about new releases.
- **Lightweight & Fast**: Uses `yt-dlp` in metadata-only mode without downloading video streams.
- **Async Non-blocking Architecture**: Built with `python-telegram-bot` and asynchronous background loops.

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

## 🚀 Setup & Installation

### 1. Clone the Repository
```bash
git clone https://github.com/YOUR_USERNAME/hotstar-telegram-notifier.git
cd hotstar-telegram-notifier
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Edit `.env` with your Telegram Bot Token (from [@BotFather](https://t.me/BotFather)):
```env
TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
CHECK_INTERVAL_SECONDS=600
DATA_FILE=shows_data.json
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

## 🐳 Docker Deployment

To run with Docker Compose:
```bash
docker compose up -d --build
```

---

## ☁️ Cloud Deployment (Render / Railway / VPS)

- **Render**: Connect repository, create a **Background Worker**, and set the `TELEGRAM_BOT_TOKEN` environment variable.
- **Railway**: Connect repository and set environment variables.
- **VPS / Linux**: Run in background using `systemd` or `pm2`:
  ```bash
  pm2 start bot.py --name "hotstar-bot" --interpreter python3
  ```

---

## 📄 License
This project is for educational and personal notification purposes only.
