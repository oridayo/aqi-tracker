"""
WAQI API Service for Discord AQI Tracker
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Handles fetching air quality data from the World Air Quality Index (WAQI)
REST API via numeric station IDs or keyword city searches.
"""

from __future__ import annotations

import logging
import aiohttp

import config

log = logging.getLogger("aqi-bot.waqi")


async def fetch_aqi_by_id(session: aiohttp.ClientSession, station_id: int) -> dict:
    """Fetch real-time AQI data for a station by its numeric ID."""
    url = f"{config.WAQI_BASE}/feed/@{station_id}/?token={config.WAQI_TOKEN}"
    async with session.get(url) as resp:
        data = await resp.json()

    if data.get("status") != "ok":
        raise ValueError(data.get("data", "Unknown API error from WAQI"))

    return data["data"]


async def fetch_aqi_by_city(session: aiohttp.ClientSession, city: str) -> dict:
    """Fetch real-time AQI data for a city name (searches WAQI, then fetches best match)."""
    search_url = f"{config.WAQI_BASE}/search/?keyword={city}&token={config.WAQI_TOKEN}"
    async with session.get(search_url) as resp:
        search = await resp.json()

    if search.get("status") != "ok" or not search.get("data"):
        raise ValueError(f"No stations found for **{city}**")

    # Pick the first (best-match) station
    best = search["data"][0]
    station_uid = best["uid"]
    return await fetch_aqi_by_id(session, station_uid)
