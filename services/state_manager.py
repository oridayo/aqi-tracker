"""
State Manager Service for Discord AQI Tracker
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Manages runtime in-memory caching and Firebase synchronization for channel
subscriptions, per-channel custom settings, and baseline global bot settings.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, Any
from discord.ext import tasks

import config
import firebase_store

log = logging.getLogger("aqi-bot.state")

# ── Runtime State Storage ────────────────────────────────────────────────────
# Active channel subscriptions: {channel_id: {"city": str, "interval_hours": int, "last_posted_at": str, ...}}
subscribed_channels: dict[int, dict] = {}

# Baseline global settings
global_settings: dict[str, Any] = {
    "default_location": config.DEFAULT_LOCATION,
    "update_interval_hours": config.DEFAULT_INTERVAL_HOURS,
}

# Per-channel custom overrides: {channel_id: {"default_location": str, "interval_hours": int, ...}}
channel_settings: dict[int, dict] = {}

# Active background loop reference
_active_loop: Optional[tasks.Loop] = None


def register_scheduled_loop(loop: tasks.Loop) -> None:
    """Register active background loop for dynamic rescheduling."""
    global _active_loop
    _active_loop = loop


# ── Location & Interval Accessors (Channel Override with Global Fallback) ────
def get_channel_default_location(channel_id: Optional[int] = None) -> str:
    """Return effective default AQI location for a channel.
    If the channel has customized its location, return it; otherwise fall back to global default."""
    if channel_id and channel_id in channel_settings:
        loc = channel_settings[channel_id].get("default_location")
        if loc:
            return loc
    return global_settings.get("default_location", config.DEFAULT_LOCATION)


def get_channel_interval_hours(channel_id: Optional[int] = None) -> int:
    """Return effective auto-update interval for a channel.
    If the channel has customized its interval, return it; otherwise fall back to global default."""
    if channel_id and channel_id in channel_settings:
        hours = channel_settings[channel_id].get("interval_hours")
        if hours:
            return int(hours)
    # Check if subscription record has explicit interval_hours
    if channel_id and channel_id in subscribed_channels:
        hours = subscribed_channels[channel_id].get("interval_hours")
        if hours:
            return int(hours)
    return int(global_settings.get("update_interval_hours", config.DEFAULT_INTERVAL_HOURS))


def is_channel_location_custom(channel_id: Optional[int]) -> bool:
    """Check if channel has an explicit custom location override."""
    if not channel_id:
        return False
    return bool(channel_id in channel_settings and channel_settings[channel_id].get("default_location"))


def is_channel_interval_custom(channel_id: Optional[int]) -> bool:
    """Check if channel has an explicit custom interval override."""
    if not channel_id:
        return False
    return bool(channel_id in channel_settings and channel_settings[channel_id].get("interval_hours"))


# Backwards compatibility aliases
get_default_location = get_channel_default_location
get_update_interval_hours = get_channel_interval_hours


# ── Channel Settings Mutation & Persistence ──────────────────────────────────
async def update_channel_location(
    channel_id: int,
    location: str,
    channel_name: Optional[str] = None,
    guild_id: Optional[int] = None,
) -> dict:
    """Save channel-specific default AQI location to Firestore and memory cache."""
    if channel_id not in channel_settings:
        channel_settings[channel_id] = {}
    channel_settings[channel_id]["default_location"] = location

    data = {
        "channel_id": channel_id,
        "default_location": location,
    }
    if channel_name:
        data["channel_name"] = channel_name
    if guild_id:
        data["guild_id"] = guild_id

    # If channel is currently subscribed, update tracked city as well
    if channel_id in subscribed_channels:
        subscribed_channels[channel_id]["city"] = location
        await firebase_store.save_subscription(
            channel_id=channel_id,
            city=location,
            channel_name=channel_name or subscribed_channels[channel_id].get("channel_name"),
            guild_id=guild_id or subscribed_channels[channel_id].get("guild_id"),
            interval_hours=subscribed_channels[channel_id].get("interval_hours"),
            last_posted_at=subscribed_channels[channel_id].get("last_posted_at"),
        )

    saved = await firebase_store.save_settings(data, scope=str(channel_id))
    log.info(f"Updated channel {channel_id} default location to '{location}'")
    return saved


async def update_channel_interval(
    channel_id: int,
    hours: int,
    channel_name: Optional[str] = None,
    guild_id: Optional[int] = None,
) -> dict:
    """Save channel-specific auto-update interval to Firestore and memory cache."""
    if channel_id not in channel_settings:
        channel_settings[channel_id] = {}
    channel_settings[channel_id]["interval_hours"] = hours

    data = {
        "channel_id": channel_id,
        "interval_hours": hours,
    }
    if channel_name:
        data["channel_name"] = channel_name
    if guild_id:
        data["guild_id"] = guild_id

    # If channel is currently subscribed, update its subscription interval as well
    if channel_id in subscribed_channels:
        subscribed_channels[channel_id]["interval_hours"] = hours
        await firebase_store.save_subscription(
            channel_id=channel_id,
            city=subscribed_channels[channel_id].get("city", config.DEFAULT_LOCATION),
            channel_name=channel_name or subscribed_channels[channel_id].get("channel_name"),
            guild_id=guild_id or subscribed_channels[channel_id].get("guild_id"),
            interval_hours=hours,
            last_posted_at=subscribed_channels[channel_id].get("last_posted_at"),
        )

    saved = await firebase_store.save_settings(data, scope=str(channel_id))
    log.info(f"Updated channel {channel_id} auto-update interval to {hours} hour(s)")
    return saved


async def reset_channel_settings(channel_id: int) -> None:
    """Reset channel settings so it reverts back to inheriting from global settings."""
    channel_settings.pop(channel_id, None)
    await firebase_store.delete_settings(str(channel_id))

    # If subscription exists, revert its city to global default
    if channel_id in subscribed_channels:
        glob_loc = global_settings.get("default_location", config.DEFAULT_LOCATION)
        glob_hours = int(global_settings.get("update_interval_hours", config.DEFAULT_INTERVAL_HOURS))
        subscribed_channels[channel_id]["interval_hours"] = glob_hours
        await firebase_store.save_subscription(
            channel_id=channel_id,
            city=subscribed_channels[channel_id].get("city", glob_loc),
            channel_name=subscribed_channels[channel_id].get("channel_name"),
            guild_id=subscribed_channels[channel_id].get("guild_id"),
            interval_hours=glob_hours,
            last_posted_at=subscribed_channels[channel_id].get("last_posted_at"),
        )

    log.info(f"Reset channel {channel_id} settings to inherit from global")


# ── Global Settings Mutation & Persistence ───────────────────────────────────
async def update_global_settings(
    default_location: Optional[str] = None,
    interval_hours: Optional[int] = None,
    loop: Optional[tasks.Loop] = None,
) -> dict:
    """Save global baseline settings to Firestore and memory cache."""
    updates: dict[str, Any] = {}
    if default_location is not None:
        global_settings["default_location"] = default_location
        updates["default_location"] = default_location
    if interval_hours is not None:
        global_settings["update_interval_hours"] = interval_hours
        updates["update_interval_hours"] = interval_hours

    if updates:
        await firebase_store.save_settings(updates, scope="global")
        log.info(f"Updated global baseline settings: {updates}")

    return global_settings


# Aliases for backwards compatibility with previous callers
async def update_default_location(channel_or_guild_id: Optional[int], location: str) -> None:
    if channel_or_guild_id:
        await update_channel_location(channel_or_guild_id, location)
    else:
        await update_global_settings(default_location=location)


async def update_update_interval(hours: int, loop: Optional[tasks.Loop] = None) -> None:
    await update_global_settings(interval_hours=hours, loop=loop)


# ── Subscription Management ──────────────────────────────────────────────────
async def save_channel_subscription(
    channel_id: int,
    city: str,
    channel_name: Optional[str] = None,
    guild_id: Optional[int] = None,
    guild_name: Optional[str] = None,
    interval_hours: Optional[int] = None,
    loop: Optional[tasks.Loop] = None,
) -> dict:
    """Persist channel subscription to Firebase, update memory cache, and ensure loop runs."""
    eff_hours = interval_hours or get_channel_interval_hours(channel_id)
    now_iso = datetime.now(timezone.utc).isoformat()

    record = await firebase_store.save_subscription(
        channel_id=channel_id,
        city=city,
        channel_name=channel_name,
        guild_id=guild_id,
        guild_name=guild_name,
        interval_hours=eff_hours,
        last_posted_at=now_iso,
    )
    subscribed_channels[channel_id] = record

    target_loop = loop or _active_loop
    if target_loop is not None and not target_loop.is_running():
        target_loop.start()

    return record


async def delete_channel_subscription(
    channel_id: int,
    loop: Optional[tasks.Loop] = None,
) -> bool:
    """Delete subscription from Firebase, memory cache, and stop loop if empty."""
    success = await firebase_store.delete_subscription(channel_id)
    if channel_id in subscribed_channels:
        del subscribed_channels[channel_id]

    target_loop = loop or _active_loop
    if not subscribed_channels and target_loop is not None and target_loop.is_running():
        target_loop.cancel()

    return success


# ── Startup State Restoration ────────────────────────────────────────────────
async def load_state_from_firebase(loop: Optional[tasks.Loop] = None) -> None:
    """Restore subscriptions and settings (global + per-channel) from Firestore on startup."""
    if not firebase_store.is_available():
        log.info("Running with in-memory subscription store (Firebase not configured)")
        return

    # 1. Restore subscriptions
    try:
        persisted_subs = await firebase_store.get_all_subscriptions()
        subscribed_channels.update(persisted_subs)
        log.info(f"Loaded {len(persisted_subs)} subscription(s) from Firebase Firestore")
    except Exception as e:
        log.error(f"Failed to load subscriptions from Firebase: {e}")

    # 2. Restore settings
    try:
        persisted_settings = await firebase_store.get_all_settings()
        if "global" in persisted_settings:
            glob = persisted_settings["global"]
            if "default_location" in glob:
                global_settings["default_location"] = glob["default_location"]
            if "update_interval_hours" in glob:
                global_settings["update_interval_hours"] = int(glob["update_interval_hours"])

        for scope, data in persisted_settings.items():
            if scope != "global":
                try:
                    cid = int(scope)
                    channel_settings[cid] = data
                    # If channel is subscribed, sync its interval_hours
                    if cid in subscribed_channels and "interval_hours" in data:
                        subscribed_channels[cid]["interval_hours"] = int(data["interval_hours"])
                except ValueError:
                    pass

        log.info(
            f"Loaded settings from Firebase: global loc={global_settings['default_location']}, "
            f"global interval={global_settings['update_interval_hours']}h, "
            f"{len(channel_settings)} custom channel override(s)"
        )
    except Exception as e:
        log.error(f"Failed to load settings from Firebase: {e}")
