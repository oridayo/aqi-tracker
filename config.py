"""
Configuration module for Discord AQI Tracker
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Contains environment variables, API endpoints, EPA breakpoint scales,
health advisories, and system defaults.
"""

from __future__ import annotations

import os
from dotenv import load_dotenv

# ── Load environment variables ───────────────────────────────────────────────
load_dotenv()

DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")
WAQI_TOKEN: str = os.getenv("WAQI_API_TOKEN", "")
AQI_CHANNEL_ID: str = os.getenv("AQI_CHANNEL_ID", "")
AQI_UPDATE_INTERVAL: int = int(os.getenv("AQI_UPDATE_INTERVAL", "60"))  # minutes
FIREBASE_KEY_PATH: str = os.getenv("FIREBASE_KEY_PATH", "")

# ── WAQI API & Default Location ──────────────────────────────────────────────
WAQI_BASE: str = "https://api.waqi.info"
DEFAULT_STATION_ID: int = 5780  # Kuala Lumpur (H5780)
DEFAULT_LOCATION: str = "Kuala Lumpur"
DEFAULT_INTERVAL_HOURS: int = max(1, AQI_UPDATE_INTERVAL // 60)

# ── AQI colour thresholds (US EPA breakpoints) ───────────────────────────────
AQI_LEVELS: list[tuple[int, str, int, str]] = [
    (50,  "Good",                        0x009966, "🟢"),
    (100, "Moderate",                     0xFFDE33, "🟡"),
    (150, "Unhealthy for Sensitive",      0xFF9933, "🟠"),
    (200, "Unhealthy",                    0xCC0033, "🔴"),
    (300, "Very Unhealthy",               0x660099, "🟣"),
    (500, "Hazardous",                    0x7E0023, "⛔"),
]


def aqi_meta(value: int) -> tuple[str, int, str]:
    """Return (label, colour, emoji) for an AQI value based on US EPA breakpoints."""
    for threshold, label, colour, emoji in AQI_LEVELS:
        if value <= threshold:
            return label, colour, emoji
    return "Hazardous", 0x7E0023, "⛔"


# ── Health recommendation per AQI range ──────────────────────────────────────
HEALTH_ADVICE: dict[str, str] = {
    "Good": "Air quality is satisfactory. Enjoy outdoor activities! 🌳",
    "Moderate": "Air quality is acceptable. Unusually sensitive people should consider limiting prolonged outdoor exertion.",
    "Unhealthy for Sensitive": "Members of sensitive groups may experience health effects. General public is less likely to be affected.",
    "Unhealthy": "Everyone may begin to experience health effects. Sensitive groups may experience more serious effects.",
    "Very Unhealthy": "Health alert: everyone may experience more serious health effects. Avoid outdoor activities.",
    "Hazardous": "Health warning of emergency conditions. The entire population is likely to be affected. Stay indoors!",
}
