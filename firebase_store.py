"""
Firebase Firestore Storage Module for Discord AQI Tracker
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Handles persistent storage of channel subscriptions in Google Cloud Firestore.
Stores, retrieves, and deletes channel details along with timestamps for auto-posting.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import firebase_admin
from firebase_admin import credentials, firestore

log = logging.getLogger("aqi-bot.firebase")

COLLECTION_NAME = "subscriptions"
SETTINGS_COLLECTION_NAME = "settings"
_db: Optional[firestore.firestore.Client] = None
_is_initialized = False
_in_memory_settings: dict[str, dict] = {}


def init_firebase(cred_path: Optional[str] = None) -> bool:
    """Initialize Firebase Admin SDK using a service account JSON file or default credentials."""
    global _db, _is_initialized

    if _is_initialized:
        return True

    # 1. Check specified path or environment variables
    path = (
        cred_path
        or os.getenv("FIREBASE_KEY_PATH")
        or os.getenv("FIREBASE_CREDENTIALS_PATH")
        or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    )

    # 2. Check standard fallback filename in current workspace if none was passed
    if not path and os.path.exists("serviceAccountKey.json"):
        path = "serviceAccountKey.json"

    try:
        if path and os.path.exists(path):
            log.info(f"Initializing Firebase with credentials from: {path}")
            cred = credentials.Certificate(path)
            firebase_admin.initialize_app(cred)
        else:
            log.info("Attempting Firebase initialization with default application credentials...")
            firebase_admin.initialize_app()

        _db = firestore.client()
        _is_initialized = True
        log.info("✅ Firebase Firestore connected successfully!")
        return True

    except Exception as e:
        log.warning(
            f"⚠️ Firebase initialization skipped or failed: {e}\n"
            "Channel subscriptions will be kept in-memory for this session.\n"
            "To enable persistent Firebase storage, provide a valid service account JSON file "
            "and set FIREBASE_KEY_PATH in your .env file."
        )
        _db = None
        _is_initialized = False
        return False


def is_available() -> bool:
    """Return True if Firestore client is initialized and ready."""
    return _is_initialized and _db is not None


# ── Synchronous Firestore helpers (run in worker threads) ────────────────────

def _sync_save_subscription(
    channel_id: int,
    city: str,
    channel_name: Optional[str] = None,
    guild_id: Optional[int] = None,
    guild_name: Optional[str] = None,
    interval_hours: Optional[int] = None,
    last_posted_at: Optional[str] = None,
) -> dict:
    if not _db:
        return {}

    doc_ref = _db.collection(COLLECTION_NAME).document(str(channel_id))
    doc = doc_ref.get()

    now_iso = datetime.now(timezone.utc).isoformat()
    existing_data = doc.to_dict() if doc.exists else {}

    # Preserve original time_added if document already exists
    time_added = existing_data.get("time_added") or existing_data.get("subscribed_at") or now_iso

    data = {
        "channel_id": channel_id,
        "channel_name": channel_name or existing_data.get("channel_name", ""),
        "guild_id": guild_id or existing_data.get("guild_id"),
        "guild_name": guild_name or existing_data.get("guild_name", ""),
        "city": city,
        "interval_hours": interval_hours or existing_data.get("interval_hours", 1),
        "last_posted_at": last_posted_at or existing_data.get("last_posted_at", time_added),
        "time_added": time_added,
        "updated_at": now_iso,
    }

    doc_ref.set(data)
    log.info(f"Firebase: Saved subscription for channel {channel_id} ({city})")
    return data


def _sync_get_all_subscriptions() -> dict[int, dict]:
    if not _db:
        return {}

    docs = _db.collection(COLLECTION_NAME).stream()
    subscriptions: dict[int, dict] = {}
    for doc in docs:
        data = doc.to_dict()
        try:
            cid = int(data.get("channel_id", doc.id))
            subscriptions[cid] = data
        except (ValueError, TypeError):
            continue

    log.info(f"Firebase: Loaded {len(subscriptions)} subscription(s)")
    return subscriptions


def _sync_get_subscription(channel_id: int) -> Optional[dict]:
    if not _db:
        return None

    doc = _db.collection(COLLECTION_NAME).document(str(channel_id)).get()
    if doc.exists:
        return doc.to_dict()
    return None


def _sync_delete_subscription(channel_id: int) -> bool:
    if not _db:
        return False

    doc_ref = _db.collection(COLLECTION_NAME).document(str(channel_id))
    doc_ref.delete()
    log.info(f"Firebase: Deleted subscription for channel {channel_id}")
    return True


def _sync_save_settings(settings: dict, scope: str = "global") -> dict:
    if not _db:
        return {}

    doc_ref = _db.collection(SETTINGS_COLLECTION_NAME).document(scope)
    doc = doc_ref.get()

    now_iso = datetime.now(timezone.utc).isoformat()
    existing_data = doc.to_dict() if doc.exists else {}

    data = {
        **existing_data,
        **settings,
        "updated_at": now_iso,
    }

    doc_ref.set(data, merge=True)
    log.info(f"Firebase: Saved settings for scope '{scope}'")
    return data


def _sync_get_settings(scope: str = "global") -> dict:
    if not _db:
        return {}

    doc = _db.collection(SETTINGS_COLLECTION_NAME).document(scope).get()
    if doc.exists:
        return doc.to_dict() or {}
    return {}


def _sync_get_all_settings() -> dict[str, dict]:
    if not _db:
        return {}

    docs = _db.collection(SETTINGS_COLLECTION_NAME).stream()
    all_settings: dict[str, dict] = {}
    for doc in docs:
        all_settings[doc.id] = doc.to_dict()

    log.info(f"Firebase: Loaded {len(all_settings)} settings record(s)")
    return all_settings


def _sync_delete_settings(scope: str) -> bool:
    if not _db:
        return False

    doc_ref = _db.collection(SETTINGS_COLLECTION_NAME).document(scope)
    doc_ref.delete()
    log.info(f"Firebase: Deleted settings for scope '{scope}'")
    return True


# ── Asynchronous non-blocking wrappers ───────────────────────────────────────

async def save_subscription(
    channel_id: int,
    city: str,
    channel_name: Optional[str] = None,
    guild_id: Optional[int] = None,
    guild_name: Optional[str] = None,
    interval_hours: Optional[int] = None,
    last_posted_at: Optional[str] = None,
) -> dict:
    """Save or update channel subscription details and time added to Firestore."""
    if not is_available():
        return {
            "channel_id": channel_id,
            "channel_name": channel_name or "",
            "guild_id": guild_id,
            "guild_name": guild_name or "",
            "city": city,
            "interval_hours": interval_hours or 1,
            "last_posted_at": last_posted_at or datetime.now(timezone.utc).isoformat(),
            "time_added": datetime.now(timezone.utc).isoformat(),
        }
    return await asyncio.to_thread(
        _sync_save_subscription,
        channel_id=channel_id,
        city=city,
        channel_name=channel_name,
        guild_id=guild_id,
        guild_name=guild_name,
        interval_hours=interval_hours,
        last_posted_at=last_posted_at,
    )


async def get_all_subscriptions() -> dict[int, dict]:
    """Retrieve all channel subscriptions from Firestore."""
    if not is_available():
        return {}
    return await asyncio.to_thread(_sync_get_all_subscriptions)


async def get_subscription(channel_id: int) -> Optional[dict]:
    """Retrieve details for a single channel subscription."""
    if not is_available():
        return None
    return await asyncio.to_thread(_sync_get_subscription, channel_id)


async def delete_subscription(channel_id: int) -> bool:
    """Delete a channel subscription from Firestore."""
    if not is_available():
        return True
    return await asyncio.to_thread(_sync_delete_subscription, channel_id)


async def save_settings(settings: dict, scope: str = "global") -> dict:
    """Save or update settings for global or a specific channel/guild scope."""
    if not is_available():
        now_iso = datetime.now(timezone.utc).isoformat()
        current = _in_memory_settings.get(scope, {})
        updated = {**current, **settings, "updated_at": now_iso}
        _in_memory_settings[scope] = updated
        return updated
    return await asyncio.to_thread(_sync_save_settings, settings, scope)


async def get_settings(scope: str = "global") -> dict:
    """Retrieve settings for global or a specific channel/guild scope."""
    if not is_available():
        return _in_memory_settings.get(scope, {})
    return await asyncio.to_thread(_sync_get_settings, scope)


async def get_all_settings() -> dict[str, dict]:
    """Retrieve all settings documents from Firestore."""
    if not is_available():
        return dict(_in_memory_settings)
    return await asyncio.to_thread(_sync_get_all_settings)


async def delete_settings(scope: str) -> bool:
    """Delete a settings document from Firestore or in-memory cache."""
    if not is_available():
        _in_memory_settings.pop(scope, None)
        return True
    return await asyncio.to_thread(_sync_delete_settings, scope)


