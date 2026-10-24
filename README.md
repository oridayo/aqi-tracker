# 🌍 AQI Tracker — Discord Bot with Firebase Integration

A Discord bot that fetches **real-time Air Quality Index (AQI)** data from the [WAQI (World Air Quality Index)](https://waqi.info) open data platform, posts colour-coded rich embeds to Discord channels, and persists channel subscriptions and timestamps to **Google Cloud Firebase Firestore**. Default station: **Kuala Lumpur (H5780)**.

---

## 📑 Table of Contents

- [Features](#-features)
- [Architecture & Process Flow](#-architecture--process-flow)
- [Firebase Data Storage](#-firebase-data-storage)
  - [Firestore Collection & Document Schema](#firestore-collection--document-schema)
  - [Operations: Store, Retrieve, Delete](#operations-store-retrieve-delete)
- [Slash Commands](#-slash-commands)
- [Embed Breakdown](#-embed-breakdown)
- [Setup Guide](#-setup-guide)
  - [Prerequisites](#prerequisites)
  - [Step 1: Clone & Install Dependencies](#step-1--clone--install-dependencies)
  - [Step 2: Discord Bot Setup](#step-2--discord-bot-setup)
  - [Step 3: WAQI API Token](#step-3--waqi-api-token)
  - [Step 4: Google Firebase Setup](#step-4--google-firebase-setup)
  - [Step 5: Configure Environment](#step-5--configure-environment)
  - [Step 6: Run the Bot](#step-6--run-the-bot)
- [Configuration Reference](#-configuration-reference)
- [API Reference](#-api-reference)
- [AQI Colour Scale](#-aqi-colour-scale)
- [Project Structure](#-project-structure)
- [License](#-license)

---

## ✨ Features

| Feature | Description |
|---|---|
| `/settings` | **Interactive Settings Dashboard**: Configure default location, update interval in hours, and unsubscribe channels |
| `/aqi` | Fetch current AQI for configured default location or search **any city worldwide** |
| `/aqi city:<name>` | Search and fetch AQI for **any city worldwide** |
| `/aqi_subscribe` | Auto-post scheduled AQI updates to a channel (**persisted in Firebase**) |
| `/aqi_unsubscribe` | Stop auto-posting and **delete channel details from Firebase** |
| `/aqi_subscriptions` | List all active channel subscriptions and **time added** stored in Firebase |
| **Firebase Firestore** | Permanent cloud persistence for channel subscriptions & bot/server settings |
| **Graceful Fallback** | Runs seamlessly in in-memory mode if Firebase is not yet configured |
| **Rich Embeds** | Colour-coded severity, pollutant breakdown, weather conditions, health advice |
| **Health Advice** | Context-aware recommendations per US EPA AQI breakpoints |
| **Multi-Channel** | Subscribe multiple channels across different servers to distinct cities |

---

## 🔄 Architecture & Process Flow

### High-Level Architecture

```
┌──────────────────┐               HTTPS/JSON               ┌──────────────────┐
│  WAQI API        │◄──────────────────────────────────────►│   bot.py         │
│  api.waqi.info   │                                        │  (discord.py)    │
└──────────────────┘                                        └───────┬─────┬────┘
                                                                    │     │
                                              Discord Gateway (WSS) │     │ Google Firebase SDK
                                                                    │     │ (Firestore)
                                                            ┌───────▼─┐ ┌─▼──────────────────┐
                                                            │ Discord │ │ Google Cloud       │
                                                            │ Server  │ │ Firebase Firestore │
                                                            └─────────┘ └────────────────────┘
```

---

### Startup Sequence (`on_ready`)

When the bot starts up, it connects to Firebase and restores all subscriptions so no scheduled feeds are lost:

```
1. python bot.py
     │
     ▼
2. Load .env file (DISCORD_TOKEN, WAQI_API_TOKEN, FIREBASE_KEY_PATH, etc.)
     │
     ▼
3. Validate bot & WAQI tokens (fail fast if missing)
     │
     ▼
4. bot.run() → Connects to Discord Gateway via WebSocket
     │
     ▼
5. on_ready() event fires:
     ├── Initialize aiohttp.ClientSession (HTTP connection pool)
     ├── Initialize Firebase Admin SDK (firebase_store.init_firebase)
     │     ├── If credentials found: Connect to Google Cloud Firestore
     │     └── If not found: Log warning and fall back to in-memory mode
     ├── Retrieve all persisted subscriptions from Firestore (firebase_store.get_all_subscriptions)
     │     └── Populate runtime subscribed_channels dictionary
     ├── Sync application slash commands with Discord
     ├── If AQI_CHANNEL_ID set in .env and not in Firestore:
     │     └── Save default channel to Firestore & runtime dict
     └── If any channels are subscribed:
           └── Start the background scheduled_aqi_update task loop
```

---

### `/aqi` Command Flow (Instant Lookup)

```
User types /aqi [city]
     │
     ▼
Interaction deferred (Discord shows "Bot is thinking...")
     │
     ▼
city argument provided?
  ├── YES → fetch_aqi_by_city()
  │           ├── GET https://api.waqi.info/search/?keyword={city}&token=...
  │           ├── Select best-match station UID
  │           └── GET https://api.waqi.info/feed/@{station_uid}/?token=...
  └── NO  → fetch_aqi_by_id()
              └── GET https://api.waqi.info/feed/@5780/?token=...
     │
     ▼
build_embed() constructs a rich Discord Embed:
  • AQI value + colour-coded EPA severity level
  • Health advice text
  • Individual pollutant levels (PM2.5, PM10, O₃, NO₂, SO₂, CO)
  • Weather readings (temp, humidity, wind, pressure, dew point)
  • Dominant pollutant indicator
  • Attributions & station timestamp
     │
     ▼
Send embed as interaction followup
```

---

### `/aqi_subscribe` Command Flow (Store to Firebase)

```
User types /aqi_subscribe [city]
     │
     ▼
Permission Check: User must hold "Manage Channels" permission
     │
     ▼
Interaction deferred
     │
     ▼
Extract channel metadata:
  • channel_id, channel_name, guild_id, guild_name, city
  • Current UTC timestamp (time_added)
     │
     ▼
firebase_store.save_subscription()
  ├── Runs in non-blocking thread
  └── Writes/Updates document in Firestore: collection 'subscriptions', doc ID '{channel_id}'
     │
     ▼
Update runtime in-memory dictionary `subscribed_channels[channel_id]`
     │
     ▼
Start background update loop `scheduled_aqi_update` (if not already running)
     │
     ▼
Send confirmation embed showing:
  • Subscribed city & update interval
  • Channel name & ID
  • Time added timestamp
  • Storage confirmation (Google Firebase Firestore)
```

---

### `/aqi_unsubscribe` Command Flow (Delete from Firebase)

```
User types /aqi_unsubscribe
     │
     ▼
Permission Check: User must hold "Manage Channels" permission
     │
     ▼
Interaction deferred
     │
     ▼
firebase_store.delete_subscription(channel_id)
  └── Deletes document '{channel_id}' from Firestore collection 'subscriptions'
     │
     ▼
Remove channel_id from runtime dictionary
     │
     ▼
Are any subscribed channels left?
  ├── NO  → Cancel background scheduled_aqi_update loop
  └── YES → Keep loop running for remaining channels
     │
     ▼
Send confirmation embed ("Unsubscribed and removed from Firebase")
```

---

### Scheduled Update Loop Flow

```
Every AQI_UPDATE_INTERVAL minutes (default: 60):
     │
     ▼
scheduled_aqi_update() executes
     │
     ▼
Iterate over copy of subscribed_channels items:
  For each (channel_id, subscription_record):
     │
     ├── Resolve Discord channel object via bot.get_channel(channel_id)
     │     └── If channel was deleted / inaccessible:
     │           ├── Delete from Firebase (firebase_store.delete_subscription)
     │           └── Remove from runtime dict
     │
     ├── Fetch latest AQI data from WAQI API
     │
     ├── Build rich embed with "⏰ Scheduled AQI Update"
     │     └── Footer displays "Active since: {time_added}"
     │
     └── Post embed to the channel
```

---

## 💾 Firebase Data Storage

### Firestore Collection & Document Schema

Subscriptions are stored in Google Cloud Firestore under the top-level collection **`subscriptions`**. Each document ID corresponds to the Discord **`channel_id`** (as a string).

```
Firestore Database
 ├── 📁 subscriptions (Collection)
 │    ├── 📄 "112233445566778899" (Document)
 │    │    ├── channel_id:   112233445566778899           (Number)
 │    │    ├── channel_name: "air-quality-alerts"         (String)
 │    │    ├── guild_id:     998877665544332211           (Number)
 │    │    ├── guild_name:   "Community Server"           (String)
 │    │    ├── city:         "Kuala Lumpur"               (String)
 │    │    ├── time_added:   "2026-10-24T07:35:00.123456" (String, ISO 8601 UTC)
 │    │    └── updated_at:   "2026-10-24T07:35:00.123456" (String, ISO 8601 UTC)
 │    │
 │    └── 📄 "223344556677889900" (Document)
 │         ├── channel_id:   223344556677889900
 │         ├── channel_name: "general"
 │         ├── guild_id:     998877665544332211
 │         ├── guild_name:   "Community Server"
 │         ├── city:         "Tokyo"
 │         ├── time_added:   "2026-10-24T08:12:15.654321"
 │         └── updated_at:   "2026-10-24T08:12:15.654321"
 │
 └── 📁 settings (Collection)
      ├── 📄 "global" (Document)
      │    ├── default_location:      "Kuala Lumpur"     (String)
      │    ├── update_interval_hours: 1                  (Number)
      │    └── updated_at:            "2026-10-24T08:30:00.000000"
      │
      └── 📄 "<guild_id>" (Document)
           ├── default_location:      "Tokyo"            (String)
           └── updated_at:            "2026-10-24T08:35:00.000000"
```

### Operations: Store, Retrieve, Delete

| Operation | Trigger | Firestore Action | Notes |
|---|---|---|---|
| **Store** | `/aqi_subscribe` or startup default channel | `db.collection("subscriptions").document(channel_id).set(data)` | Preserves original `time_added` if record exists; updates `city` and `updated_at`. |
| **Retrieve** | Bot startup (`on_ready`) & `/aqi_subscriptions` | `db.collection("subscriptions").stream()` | Restores all subscriptions so schedules persist across bot reboots. |
| **Delete** | `/aqi_unsubscribe` or channel deleted | `db.collection("subscriptions").document(channel_id).delete()` | Permanently purges channel record from cloud database. |

---

## 🤖 Slash Commands

### 1. `/settings`
Interactive dashboard to configure bot settings and manage channel subscriptions.
- **Parameters:**
  - `default_location` *(Optional, string)*: Set the server default AQI city (e.g. `Tokyo`, `Kuala Lumpur`, `Penang`).
  - `interval_hours` *(Optional, integer 1–168)*: Set the auto-update interval in hours (e.g. `1`, `2`, `4`, `12`, `24`).
- **Permissions:** Requires **Manage Channels** permission.
- **Interactive Features:**
  - 📍 **Set Location Button**: Opens a modal to enter and validate any city worldwide against the WAQI API.
  - ⏱️ **Set Interval Button**: Opens a modal to change the auto-update frequency to any number of hours (1 to 168).
  - 📢 **Subscription Select Menu**: Lists all active channel subscriptions in the server.
  - 🗑️ **Unsubscribe Selected Button**: Instantly removes selected channels from Firebase Firestore and stops their schedules.
  - 🔄 **Refresh Button**: Refreshes settings and channel subscription statuses.

### 2. `/aqi`
Get real-time Air Quality Index data for any station or city.
- **Parameters:**
  - `city` *(Optional, string)*: City name to look up. Defaults to the configured server default (or Kuala Lumpur).
- **Permissions:** Available to all members.
- **Examples:**
  - `/aqi` (uses server default location)
  - `/aqi city:Tokyo`
  - `/aqi city:London`

### 3. `/aqi_subscribe`
Auto-post scheduled AQI updates to the current channel and save details to Firebase.
- **Parameters:**
  - `city` *(Optional, string)*: City to track. Defaults to the server default (or Kuala Lumpur).
- **Permissions:** Requires **Manage Channels**.
- **Result:** Saves channel details, guild details, tracked city, and `time_added` to Firebase Firestore. Starts auto-posting on the configured hourly schedule.

### 4. `/aqi_unsubscribe`
Stop auto-posting to the current channel and delete the channel details from Firebase.
- **Permissions:** Requires **Manage Channels**.
- **Result:** Permanently removes the channel's document from Firestore and halts scheduled posts to the channel.

### 5. `/aqi_subscriptions`
List all channels currently registered for auto-posting along with their tracked cities, channel names, and timestamps added.
- **Permissions:** Available to all members (ephemeral response visible only to you).

---

## 🎨 Embed Breakdown

Every AQI card posted by the bot displays comprehensive environmental data:

| Section | Field | Description |
|---|---|---|
| **Title** | `{emoji} Air Quality — {city_name}` | Direct link to official station page |
| **📊 AQI Index** | `# {value}` + Level Name | Colour-matched to severity |
| **💡 Health Advice** | Contextual Health Advisory | Targeted advice based on US EPA breakpoints |
| **🧪 Pollutants** | Individual readings | PM2.5, PM10, Ozone (O₃), NO₂, SO₂, CO with units |
| **🌤️ Weather** | Microclimate conditions | Temperature (°C), Humidity (%), Wind speed (m/s), Pressure (hPa), Dew Point (°C) |
| **⚠️ Dominant Pollutant**| Main driver | Highlights primary air pollutant |
| **📖 Sources** | Data attribution links | Official measuring agencies & sensors |
| **Footer** | Timestamp & Tracking details | Station measurement time + subscription active duration |

---

## 🚀 Setup Guide

### Prerequisites

- **Python 3.10+** (tested on Python 3.14)
- A **Discord Bot Token**
- A **WAQI API Token** (free)
- A **Google Cloud / Firebase Project** (free tier is 100% sufficient)

---

### Step 1 — Clone & Install Dependencies

In your project directory:

```powershell
# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate

# Install dependencies including firebase-admin
pip install -r requirements.txt
```

---

### Step 2 — Discord Bot Setup

1. Open the [Discord Developer Portal](https://discord.com/developers/applications).
2. Click **New Application** and give it a name.
3. In the **Bot** tab:
   - Click **Reset Token** and copy your bot token.
   - You do **not** require privileged intents.
4. In the **OAuth2 → URL Generator** tab:
   - Check scopes: `bot`, `applications.commands`
   - Check permissions: `Send Messages`, `Embed Links`, `View Channels`
5. Open the generated invite link in your browser and invite the bot to your server.

---

### Step 3 — WAQI API Token

1. Go to [aqicn.org/data-platform/token/](https://aqicn.org/data-platform/token/).
2. Enter your name and email to request a free instant API token.
3. Confirm via the email received and copy your token.

---

### Step 4 — Google Firebase Setup

1. Go to the [Firebase Console](https://console.firebase.google.com/).
2. Click **Add project** (or use an existing Google Cloud project) and follow the prompts.
3. In the left sidebar, click **Build** → **Firestore Database**:
   - Click **Create database**.
   - Select your preferred cloud location.
   - Choose **Production mode** (or Test mode).
4. Generate your service account private key:
   - Click the gear icon ⚙️ next to **Project Overview** → **Project settings**.
   - Switch to the **Service accounts** tab.
   - Click **Generate new private key** → confirm with **Generate key**.
5. Save the downloaded `.json` file into your project folder as `serviceAccountKey.json`.
   > **Security Note:** `serviceAccountKey.json` is already listed in `.gitignore` so your private key will never be accidentally committed to source control.

---

### Step 5 — Configure Environment

Copy `.env.example` to `.env`:

```powershell
copy .env.example .env
```

Open `.env` and configure your credentials:

```env
# Discord Bot Token
DISCORD_TOKEN=your_discord_bot_token_here

# WAQI API Token
WAQI_API_TOKEN=your_waqi_api_token_here

# (Optional) Default channel ID to auto-post to on startup
AQI_CHANNEL_ID=

# (Optional) Update interval in minutes (default: 60)
AQI_UPDATE_INTERVAL=60

# Path to your Firebase service account private key
FIREBASE_KEY_PATH=serviceAccountKey.json
```

---

### Step 6 — Run the Bot

```powershell
python bot.py
```

Console output should confirm Firebase connection and slash command synchronization:

```
INFO │ aqi-bot.firebase │ Initializing Firebase with credentials from: serviceAccountKey.json
INFO │ aqi-bot.firebase │ ✅ Firebase Firestore connected successfully!
INFO │ aqi-bot.firebase │ Firebase: Loaded 2 subscription(s)
INFO │ aqi-bot          │ Logged in as AQI Tracker#1234 (ID: 1234567890)
INFO │ aqi-bot          │ Synced 4 slash commands
INFO │ aqi-bot          │ ✅ Bot is ready!
```

---

## ⚙️ Configuration Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `DISCORD_TOKEN` | ✅ Yes | — | Secret token for your Discord bot application |
| `WAQI_API_TOKEN` | ✅ Yes | — | WAQI / aqicn.org API key |
| `FIREBASE_KEY_PATH` | Recommended | `serviceAccountKey.json` | Path to Firebase service account private key JSON file |
| `AQI_UPDATE_INTERVAL` | No | `60` | Schedule interval in minutes for recurring AQI posts |
| `AQI_CHANNEL_ID` | No | *(empty)* | Discord channel ID to automatically subscribe on launch |

---

## 📡 API Reference

The bot communicates with the WAQI REST API endpoints:

1. **Station Feed (by ID)**:
   ```http
   GET https://api.waqi.info/feed/@5780/?token=YOUR_TOKEN
   ```
   Retrieves detailed station observations (air pollutants, meteorology, health metrics). Station ID `5780` corresponds to Kuala Lumpur (H5780).

2. **City Keyword Search**:
   ```http
   GET https://api.waqi.info/search/?keyword={city}&token=YOUR_TOKEN
   ```
   Searches for measuring stations matching a city name worldwide.

- Official WAQI documentation: [aqicn.org/json-api/doc/](https://aqicn.org/json-api/doc/)

---

## 🎨 AQI Colour Scale

Based on the official **US EPA Air Quality Index Breakpoints**:

| AQI Range | Category | Embed Colour | Emoji | Health Statement |
|---|---|---|---|---|
| **0 – 50** | Good | `#009966` | 🟢 | Satisfactory air quality; little or no risk. |
| **51 – 100** | Moderate | `#FFDE33` | 🟡 | Acceptable quality; unusually sensitive people may be affected. |
| **101 – 150** | Unhealthy for Sensitive Groups | `#FF9933` | 🟠 | Sensitive groups may experience health effects. |
| **151 – 200** | Unhealthy | `#CC0033` | 🔴 | Everyone may begin to experience health effects. |
| **201 – 300** | Very Unhealthy | `#660099` | 🟣 | Health alert: serious health impacts for the general public. |
| **301 – 500+** | Hazardous | `#7E0023` | ⛔ | Emergency conditions: entire population likely to be affected. |

---

## 📁 Project Structure

```
api-tracker/
├── bot.py                  # Main entry point & custom AqiBot class (lifecycle & events)
├── config.py               # Environment configuration, EPA thresholds, health advice, defaults
├── firebase_store.py       # Google Cloud Firestore persistence (subscriptions & settings)
├── cogs/                   # Modular command groups and scheduled background tasks
│   ├── __init__.py
│   ├── aqi.py              # /aqi, /aqi_subscribe, /aqi_unsubscribe, /aqi_subscriptions, task loop
│   └── settings.py         # /settings command and view orchestration
├── services/               # Core business logic and external API services
│   ├── __init__.py
│   ├── state_manager.py    # Subscriptions & settings cache, getter/setters, Firebase sync
│   └── waqi_service.py     # WAQI API REST client (search and station lookup)
├── ui/                     # Presentation layer: Discord UI components & rich embeds
│   ├── __init__.py
│   ├── embeds.py           # Embed cards (AQI reports, health advisories, settings dashboard)
│   └── views.py            # Discord Views, Modals, and Select Menus
├── requirements.txt        # Project dependencies (discord.py, firebase-admin, aiohttp, etc.)
├── .env                    # Active credentials and configuration (git-ignored)
├── .env.example            # Configuration template
├── .gitignore              # Protects .env, virtual environments, and Firebase JSON keys
└── README.md               # Project documentation
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
