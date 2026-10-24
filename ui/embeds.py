"""
Embed Builders for Discord AQI Tracker
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Constructs rich Discord Embed cards for real-time air quality index reports,
health advisories, scheduled updates, and bot settings dashboards.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
import discord

import config
import firebase_store
from services.state_manager import (
    get_channel_default_location,
    get_channel_interval_hours,
    is_channel_location_custom,
    is_channel_interval_custom,
    global_settings,
    subscribed_channels,
)


def build_aqi_embed(data: dict) -> discord.Embed:
    """Create a rich embed from WAQI response data."""
    aqi_value = data.get("aqi", "N/A")
    city_info = data.get("city", {})
    city_name = city_info.get("name", "Unknown Station")
    city_url = city_info.get("url", "")

    # Determine AQI level metadata
    try:
        aqi_int = int(aqi_value)
        label, colour, emoji = config.aqi_meta(aqi_int)
    except (ValueError, TypeError):
        label, colour, emoji = "Unknown", 0x808080, "❓"

    embed = discord.Embed(
        title=f"{emoji}  Air Quality — {city_name}",
        url=city_url if city_url.startswith("http") else f"https://aqicn.org{city_url}" if city_url else None,
        colour=colour,
        timestamp=datetime.now(timezone.utc),
    )

    # ── Main AQI value ───────────────────────────────────────────────────
    aqi_display = f"# {aqi_value}\n**{label}**"
    embed.add_field(name="📊 AQI Index", value=aqi_display, inline=False)

    # ── Health advice ────────────────────────────────────────────────────
    advice = config.HEALTH_ADVICE.get(label, "")
    if advice:
        embed.add_field(name="💡 Health Advice", value=advice, inline=False)

    # ── Individual pollutants ────────────────────────────────────────────
    iaqi = data.get("iaqi", {})
    pollutant_map = {
        "pm25": ("PM2.5", "μg/m³"),
        "pm10": ("PM10", "μg/m³"),
        "o3":   ("Ozone (O₃)", "μg/m³"),
        "no2":  ("NO₂", "μg/m³"),
        "so2":  ("SO₂", "μg/m³"),
        "co":   ("CO", "mg/m³"),
    }

    pollutant_lines = []
    for key, (name, unit) in pollutant_map.items():
        if key in iaqi:
            val = iaqi[key].get("v", "—")
            pollutant_lines.append(f"**{name}**: `{val}` {unit}")

    if pollutant_lines:
        embed.add_field(
            name="🧪 Pollutants",
            value="\n".join(pollutant_lines),
            inline=True,
        )

    # ── Weather conditions ───────────────────────────────────────────────
    weather_map = {
        "t":  ("🌡️ Temp", "°C"),
        "h":  ("💧 Humidity", "%"),
        "w":  ("💨 Wind", "m/s"),
        "p":  ("🔵 Pressure", "hPa"),
        "d":  ("🌫️ Dew Point", "°C"),
    }

    weather_lines = []
    for key, (name, unit) in weather_map.items():
        if key in iaqi:
            val = iaqi[key].get("v", "—")
            weather_lines.append(f"**{name}**: `{val}` {unit}")

    if weather_lines:
        embed.add_field(
            name="🌤️ Weather",
            value="\n".join(weather_lines),
            inline=True,
        )

    # ── Dominant pollutant ───────────────────────────────────────────────
    dominant = data.get("dominentpol", None)
    if dominant:
        dom_name = pollutant_map.get(dominant, (dominant.upper(), ""))[0]
        embed.add_field(name="⚠️ Dominant Pollutant", value=f"**{dom_name}**", inline=True)

    # ── Data timestamp ───────────────────────────────────────────────────
    time_info = data.get("time", {})
    local_time = time_info.get("s", "Unknown")
    tz = time_info.get("tz", "")
    embed.set_footer(
        text=f"Station update: {local_time} ({tz}) • Data from WAQI / aqicn.org",
        icon_url="https://aqicn.org/images/iOS/ico_57.png",
    )

    # ── Attribution ──────────────────────────────────────────────────────
    attributions = data.get("attributions", [])
    if attributions:
        attr_text = " | ".join(
            f"[{a.get('name', 'Source')}]({a.get('url', '')})" for a in attributions[:3]
        )
        embed.add_field(name="📖 Sources", value=attr_text, inline=False)

    return embed


def build_settings_embed(channel_id: Optional[int] = None, guild_id: Optional[int] = None) -> discord.Embed:
    """Build a rich Discord embed showcasing current channel settings, global defaults, and active subscriptions."""
    current_loc = get_channel_default_location(channel_id)
    is_custom_loc = is_channel_location_custom(channel_id)
    current_hours = get_channel_interval_hours(channel_id)
    is_custom_hours = is_channel_interval_custom(channel_id)
    hour_text = f"{current_hours} hour{'s' if current_hours > 1 else ''}"

    global_loc = global_settings.get("default_location", config.DEFAULT_LOCATION)
    global_hours = int(global_settings.get("update_interval_hours", config.DEFAULT_INTERVAL_HOURS))

    ch_mention = f"<#{channel_id}>" if channel_id else "Current Channel"
    embed = discord.Embed(
        title=f"⚙️ AQI Tracker — Channel Settings ({ch_mention})",
        description="Settings for this channel. Channel updates override global defaults.",
        colour=0x3498DB,
        timestamp=datetime.now(timezone.utc),
    )

    loc_tag = "*(Channel Custom Override)*" if is_custom_loc else f"*(Inherited from Global: {global_loc})*"
    embed.add_field(
        name="📍 Default AQI Location",
        value=f"**{current_loc}** {loc_tag}\n*Used by `/aqi` & `/aqi_subscribe` when no city parameter is passed.*",
        inline=False,
    )

    hours_tag = "*(Channel Custom Override)*" if is_custom_hours else f"*(Inherited from Global: {global_hours}h)*"
    embed.add_field(
        name="⏱️ Auto-Update Schedule",
        value=f"Every **{hour_text}** {hours_tag}\n*How often this channel receives automatic AQI updates.*",
        inline=False,
    )

    # Status of this specific channel
    if channel_id and channel_id in subscribed_channels:
        sub_data = subscribed_channels[channel_id]
        city = sub_data.get("city", current_loc)
        time_str = str(sub_data.get("time_added", ""))[:19].replace("T", " ")
        embed.add_field(
            name="📢 Auto-Update Status (This Channel)",
            value=f"🟢 **Subscribed** — Tracking **{city}** every **{sub_data.get('interval_hours', current_hours)}h**\n*Active since:* `{time_str}` UTC",
            inline=False,
        )
    else:
        embed.add_field(
            name="📢 Auto-Update Status (This Channel)",
            value="⚪ **Not Subscribed** — Auto-posting is inactive for this channel.\nUse `/aqi_subscribe` to start auto-posting here.",
            inline=False,
        )

    # Active subscriptions for other channels in this server
    server_subs = [
        (cid, data) for cid, data in subscribed_channels.items()
        if (not guild_id or (isinstance(data, dict) and data.get("guild_id") == guild_id)) and cid != channel_id
    ]

    if server_subs:
        sub_lines = []
        for cid, data in server_subs[:10]:
            city = data.get("city", "Unknown") if isinstance(data, dict) else str(data)
            ch_name = data.get("channel_name", "") if isinstance(data, dict) else ""
            name_str = f" (#{ch_name})" if ch_name else ""
            sub_hours = data.get("interval_hours", 1)
            sub_lines.append(f"• <#{cid}>{name_str} → **{city}** *(every {sub_hours}h)*")

        if len(server_subs) > 10:
            sub_lines.append(f"*... and {len(server_subs) - 10} more*")

        embed.add_field(
            name=f"📋 Other Active Subscriptions in Server ({len(server_subs)})",
            value="\n".join(sub_lines),
            inline=False,
        )

    embed.set_footer(text="Use the interactive controls below to modify settings or unsubscribe channels.")
    return embed
