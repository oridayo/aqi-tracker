"""
Discord AQI Tracker Bot — Main Entry Point
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Fetches real-time Air Quality Index data from WAQI (World Air Quality Index)
and posts rich embeds to Discord channels.
Persists channel subscriptions and settings to Google Cloud Firebase Firestore.

Architecture:
  • config.py               — Configuration, environment, and EPA breakpoints
  • firebase_store.py       — Firestore database persistence
  • services/waqi_service.py — WAQI API client
  • services/state_manager.py— Centralized state, caching, and settings management
  • ui/embeds.py            — Rich embed cards
  • ui/views.py             — Interactive UI views, modals, and selects
  • cogs/aqi.py             — AQI commands and automated task scheduler
  • cogs/settings.py        — Bot configuration dashboard
"""

from __future__ import annotations

import logging
from typing import Optional
import aiohttp
import discord
from discord.ext import commands

import config
import firebase_store
from cogs.aqi import AqiCog
from cogs.settings import SettingsCog
from services.state_manager import (
    subscribed_channels,
    global_settings,
    channel_settings,
    get_channel_default_location,
    get_channel_interval_hours,
    is_channel_location_custom,
    is_channel_interval_custom,
    get_default_location,
    get_update_interval_hours,
    update_channel_location,
    update_channel_interval,
    reset_channel_settings,
    update_global_settings,
    update_default_location,
    update_update_interval,
    save_channel_subscription,
    delete_channel_subscription,
    load_state_from_firebase,
    register_scheduled_loop,
)
from services.waqi_service import fetch_aqi_by_id, fetch_aqi_by_city
from ui.embeds import build_aqi_embed, build_settings_embed
from ui.views import (
    LocationModal,
    IntervalModal,
    GlobalSettingsModal,
    SubscriptionSelect,
    SettingsView,
)

# Aliases for backwards compatibility
build_embed = build_aqi_embed
DEFAULT_STATION_ID = config.DEFAULT_STATION_ID

# ── Logging Configuration ────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s",
)
log = logging.getLogger("aqi-bot")


# ── Custom Bot Class with Modern Lifecycle Hooks ─────────────────────────────
class AqiBot(commands.Bot):
    """Custom Bot client managing aiohttp session and extension loading."""

    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self.http_session: Optional[aiohttp.ClientSession] = None
        self.aqi_cog = AqiCog(self)
        self.settings_cog = SettingsCog(self)
        register_scheduled_loop(self.aqi_cog.loop)

    async def setup_hook(self):
        """Asynchronous initialization: session creation, cog loading, and state restore."""
        # 1. Initialize HTTP session
        self.http_session = aiohttp.ClientSession()

        # 2. Add modular Cogs
        await self.add_cog(self.aqi_cog)
        await self.add_cog(self.settings_cog)

        # 3. Connect to Firebase Firestore
        fb_connected = firebase_store.init_firebase(config.FIREBASE_KEY_PATH)

        # 4. Restore subscriptions and settings from Firestore
        if fb_connected:
            await load_state_from_firebase(loop=self.aqi_cog.loop)

    async def close(self):
        """Gracefully close HTTP session before disconnecting."""
        if self.http_session and not self.http_session.closed:
            await self.http_session.close()
        await super().close()


bot = AqiBot()
# Backwards compatibility alias
scheduled_aqi_update = bot.aqi_cog.loop


# ── Bot Events ───────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    log.info(f"Logged in as {bot.user} (ID: {bot.user.id})")

    # 1. Sync application slash commands with Discord
    try:
        synced = await bot.tree.sync()
        log.info(f"Synced {len(synced)} slash commands")
    except Exception as e:
        log.error(f"Failed to sync commands: {e}")

    # 2. Register default channel from .env if configured and not yet present
    if config.AQI_CHANNEL_ID:
        try:
            cid = int(config.AQI_CHANNEL_ID)
            if cid not in subscribed_channels:
                aqi_cog: Optional[AqiCog] = bot.get_cog("AQI")
                loop = aqi_cog.loop if aqi_cog else None
                await save_channel_subscription(
                    channel_id=cid,
                    city=get_default_location(),
                    channel_name="default-env-channel",
                    loop=loop,
                )
        except ValueError:
            log.warning("AQI_CHANNEL_ID is not a valid integer — skipping auto-post setup")

    # 3. Start scheduled update loop if channels are subscribed
    aqi_cog: Optional[AqiCog] = bot.get_cog("AQI")
    if aqi_cog and subscribed_channels and not aqi_cog.scheduled_aqi_update.is_running():
        aqi_cog.scheduled_aqi_update.start()

    log.info("✅ Bot is ready!")


# ── Entry Point ──────────────────────────────────────────────────────────────
def main():
    if not config.DISCORD_TOKEN:
        log.error("DISCORD_TOKEN is not set! Add it to your .env file.")
        raise SystemExit(1)
    if not config.WAQI_TOKEN:
        log.error("WAQI_API_TOKEN is not set! Add it to your .env file.")
        raise SystemExit(1)

    log.info("Starting AQI Tracker bot…")
    bot.run(config.DISCORD_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
