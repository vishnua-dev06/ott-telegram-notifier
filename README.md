# Multi-OTT Episode Notification & Lookup Telegram Bot ⚡

An automated, modular Telegram bot that monitors and tracks TV serials and shows across **JioHotstar**, **Zee5**, **SonyLIV**, **SunNXT**, and **ManoramaMAX**. Features instant release alerts, on-demand episode lookups, poster banners, direct watch buttons, and full admin broadcast controls.

---

## ⚡ Supported OTT Platforms

- 🌟 **JioHotstar** (`hotstar.com`)
- 🟣 **Zee5** (`zee5.com`)
- 🔵 **SonyLIV** (`sonyliv.com`)
- 🟡 **SunNXT** (`sunnxt.com`)
- 🔴 **ManoramaMAX** (`manoramamax.com`)

---

## 📂 Modular Architecture

```text
ott-telegram-notifier/
│
├── platforms/
│   ├── __init__.py          # Unified router: auto-detects platform and delegates
│   ├── base.py              # Common helpers (slugify, title parsing, headers)
│   ├── hotstar.py           # JioHotstar Next.js scraper & URL builder
│   ├── zee5.py              # Zee5 scraper & URL builder
│   ├── sonyliv.py           # SonyLIV scraper & URL builder
│   ├── sunnxt.py            # SunNXT scraper & URL builder
│   └── manoramamax.py       # ManoramaMAX scraper & URL builder
│
├── database.py              # MongoDB Atlas & Local JSON persistence layer
├── bot.py                   # Telegram bot commands & background scheduler
├── requirements.txt         # Dependencies
├── Dockerfile               # Container build
└── README.md                # Documentation
```

---

## 🚀 Key Features

- **Modular Platform Structure**: Each OTT service lives in its own dedicated file under `platforms/` for easy upgrades and isolated debugging.
- **🔍 On-Demand Episode Lookup (`/getepisode` / `/find`)**: Search and retrieve any past or latest episode link with full poster banner on demand.
- **📢 Admin Broadcast (`/broadcast`)**: Send announcements to all bot subscribers and channels with one command.
- **🖼️ Episode Thumbnail Banners**: High-definition poster images automatically delivered with captions.
- **🎬 Interactive Watch Buttons**: Dynamically tailored buttons (e.g., `🎬 Watch on JioHotstar`, `🎬 Watch on Zee5`, `🎬 Watch on SunNXT`).
- **🛡️ Admin Lock & User Access**: Authorize specific users with `/adduser` or manage privately.
- **⚡ Instant Force Check (`/checknow`)**: Trigger an immediate scan across all OTT providers.
- **📊 Real-time Stats (`/stats`)**: Monitor bot uptime, database health, tracked shows per OTT platform.
- **💾 MongoDB Atlas Persistence**: Stores all shows, subscribers, and released episode IDs forever (`DATABASE_URI` and `DATABASE_NAME`).
- **Anti-Spam Deduplication**: Automatically pre-caches existing episodes so old ones aren't spammed.
- **Koyeb & Cloud Compatible**: Built-in HTTP health check server on port 8080.

---

## 🤖 Bot Commands Reference

### 🎬 Show Management & On-Demand Lookups
| Command | Description | Example |
| :--- | :--- | :--- |
| `/start` | Welcome message, user ID & role status | `/start` |
| `/addshow <url> [language]` | Start tracking a show (any supported OTT) | `/addshow https://www.hotstar.com/in/shows/patharamattu/1260141539 Malayalam` |
| `/removeshow <id_or_name>` | Stop tracking a show | `/removeshow 1260141539` |
| `/listshows` | View shows tracked in this chat | `/listshows` |
| `/getepisode <show> [num]` | Fetch specific or latest episode link | `/getepisode Patharamattu 1116` or `/getepisode Patharamattu` |
| `/find <show> [num]` | Alias for `/getepisode` | `/find Chembarathi 120` |
| `/checknow` | Force immediate check for new episodes | `/checknow` |
| `/stats` | View bot uptime, database & metrics | `/stats` |
| `/test` | Preview notification with banner & buttons | `/test` |

### 👑 Super Admin Commands (`ADMIN_ID` only)
| Command | Description | Example |
| :--- | :--- | :--- |
| `/broadcast <message>` | Send announcement to all subscribers | `/broadcast 📢 New shows added!` |
| `/adduser <user_id>` | Authorize a user to use the bot | `/adduser 123456789` |
| `/removeuser <user_id>` | Revoke access from a user | `/removeuser 123456789` |
| `/listusers` | List all authorized users | `/listusers` |

---

## ⚙️ Environment Variables

| Variable | Required | Description |
| :--- | :--- | :--- |
| `TELEGRAM_BOT_TOKEN` | **Yes** | Bot token from [@BotFather](https://t.me/BotFather) |
| `ADMIN_ID` | Optional | Your numeric Telegram ID (from [@userinfobot](https://t.me/userinfobot)) |
| `DATABASE_URI` | Optional | MongoDB Atlas connection string (`mongodb+srv://...`) |
| `DATABASE_NAME` | Optional | MongoDB database name (default: `ott_notifier_db`) |
| `CHECK_INTERVAL_SECONDS` | Optional | Periodic check frequency in seconds (default: `600`) |
| `PORT` | Optional | Health check port for Koyeb (default: `8080`) |

---

## ☁️ Deployment on Koyeb

1. Push your repository to GitHub.
2. In [Koyeb](https://app.koyeb.com), connect `vishnua-dev06/ott-telegram-notifier`.
3. Set your environment variables:
   - `TELEGRAM_BOT_TOKEN`
   - `ADMIN_ID`
   - `DATABASE_URI`
   - `DATABASE_NAME`
   - `PORT` = `8080`
4. Deploy!
