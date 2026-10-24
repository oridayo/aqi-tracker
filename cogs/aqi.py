"""
AQI Commands & Background Scheduler Cog
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Implements slash commands (/aqi, /aqi_subscribe, /aqi_unsubscribe, /aqi_subscriptions)
and the recurring background update loop.
"""

from __future__ import annotations

import logging
from typing import Optional
from datetime import datetime, timezone
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
import firebase_store
from services.state_manager import (
    subscribed_channels,
    get_channel_default_location,
    get_channel_interval_hours,
    save_channel_subscription,
    delete_channel_subscription,
)
from services.waqi_service import fetch_aqi_by_id, fetch_aqi_by_city
from ui.embeds import build_aqi_embed

log = logging.getLogger("aqi-bot.cog.aqi")


class AqiCog(commands.Cog, name="AQI"):
    """Cog handling real-time AQI queries, channel subscriptions, and automated scheduling."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Expose loop on cog instance so other cogs or services can change its interval
        self.loop = self.scheduled_aqi_update

    def cog_unload(self):
        """Cancel scheduled loop when cog is unloaded."""
        if self.scheduled_aqi_update.is_running():
            self.scheduled_aqi_update.cancel()

    def get_session(self) -> aiohttp.ClientSession:
        """Retrieve the shared HTTP session from the bot instance."""
        session = getattr(self.bot, "http_session", None)
        if session is None or session.closed:
            raise RuntimeError("Bot HTTP session is not available.")
        return session

    # ── /aqi command ─────────────────────────────────────────────────────────
    @app_commands.command(name="aqi", description="Get real-time Air Quality Index data")
    @app_commands.describe(city="City name to look up (leave blank for channel default or Kuala Lumpur)")
    async def aqi_command(self, interaction: discord.Interaction, city: Optional[str] = None):
        await interaction.response.defer(thinking=True)
        session = self.get_session()

        try:
            target_city = city or get_channel_default_location(interaction.channel_id)
            if target_city.lower() == "kuala lumpur":
                data = await fetch_aqi_by_id(session, config.DEFAULT_STATION_ID)
            else:
                data = await fetch_aqi_by_city(session, target_city)

            embed = build_aqi_embed(data)
            await interaction.followup.send(embed=embed)

        except ValueError as e:
            embed = discord.Embed(
                title="❌ Error",
                description=str(e),
                colour=0xFF4444,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            log.exception("AQI fetch failed")
            embed = discord.Embed(
                title="❌ Something went wrong",
                description=f"```{e}```\nPlease try again later.",
                colour=0xFF4444,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /aqi_subscribe command ───────────────────────────────────────────────
    @app_commands.command(
        name="aqi_subscribe",
        description="Auto-post AQI updates to this channel on a schedule",
    )
    @app_commands.describe(city="City to track (defaults to channel setting or Kuala Lumpur)")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def aqi_subscribe_command(self, interaction: discord.Interaction, city: Optional[str] = None):
        await interaction.response.defer()
        channel_id = interaction.channel_id
        channel = interaction.channel
        channel_name = getattr(channel, "name", str(channel_id))
        guild_id = interaction.guild_id
        guild_name = interaction.guild.name if interaction.guild else None
        station = city or get_channel_default_location(channel_id)
        hours = get_channel_interval_hours(channel_id)

        # Save to Firestore & memory cache
        await save_channel_subscription(
            channel_id=channel_id,
            city=station,
            channel_name=channel_name,
            guild_id=guild_id,
            guild_name=guild_name,
            interval_hours=hours,
            loop=self.scheduled_aqi_update,
        )

        hour_text = f"{hours} hour{'s' if hours > 1 else ''}"

        embed = discord.Embed(
            title="✅ Subscribed to AQI Updates!",
            description=(
                f"This channel will receive **{station}** AQI updates "
                f"every **{hour_text}**.\n\n"
                f"Use `/aqi_unsubscribe` or `/settings` to manage."
            ),
            colour=0x009966,
        )
        await interaction.followup.send(embed=embed)

    # ── /aqi_unsubscribe command ────────────────────────────────────────────
    @app_commands.command(
        name="aqi_unsubscribe",
        description="Stop auto-posting AQI updates",
    )
    @app_commands.checks.has_permissions(manage_channels=True)
    async def aqi_unsubscribe_command(self, interaction: discord.Interaction):
        await interaction.response.defer()
        channel_id = interaction.channel_id
        was_subscribed = channel_id in subscribed_channels

        await delete_channel_subscription(channel_id, loop=self.scheduled_aqi_update)

        if was_subscribed:
            embed = discord.Embed(
                title="🛑 Unsubscribed",
                description="AQI auto-updates have been stopped.",
                colour=0xFF9933,
            )
        else:
            embed = discord.Embed(
                title="ℹ️ Not Subscribed",
                description="You are not subscribed to any AQI Updates. \nUse /aqi_subscribe to subscribe.",
                colour=0x808080,
            )
        await interaction.followup.send(embed=embed)

    # ── /aqi_subscriptions command ──────────────────────────────────────────
    @app_commands.command(
        name="aqi_subscriptions",
        description="List all active AQI channel subscriptions",
    )
    async def aqi_subscriptions_command(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not subscribed_channels:
            embed = discord.Embed(
                title="📋 Active Subscriptions",
                description="There are currently no active channel subscriptions.",
                colour=0x808080,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        lines = []
        for cid, data in subscribed_channels.items():
            city = data.get("city", "Unknown") if isinstance(data, dict) else str(data)
            time_added = data.get("time_added", "N/A") if isinstance(data, dict) else "N/A"
            ch_name = data.get("channel_name", "") if isinstance(data, dict) else ""
            name_str = f" (#{ch_name})" if ch_name else ""
            sub_hours = data.get("interval_hours", 1) if isinstance(data, dict) else 1
            lines.append(f"• <#{cid}>{name_str} → **{city}** *(every {sub_hours}h)*\n  *Added:* `{time_added}`")

        embed = discord.Embed(
            title=f"📋 Active Subscriptions ({len(subscribed_channels)})",
            description="\n".join(lines),
            colour=0x009966,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── Scheduled Task: Auto-Post AQI Updates ────────────────────────────────
    @tasks.loop(minutes=15)
    async def scheduled_aqi_update(self):
        log.info(f"Running periodic AQI scheduler check for {len(subscribed_channels)} channel(s)")
        session = self.get_session()
        now = datetime.now(timezone.utc)

        for channel_id, data in list(subscribed_channels.items()):
            interval_h = data.get("interval_hours") or get_channel_interval_hours(channel_id)
            last_posted_str = data.get("last_posted_at") or data.get("time_added")

            # Check if this channel is due for an update
            is_due = False
            if not last_posted_str:
                is_due = True
            else:
                try:
                    clean_ts = last_posted_str.replace("Z", "+00:00")
                    last_dt = datetime.fromisoformat(clean_ts)
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=timezone.utc)
                    elapsed_secs = (now - last_dt).total_seconds()
                    # Trigger if elapsed time >= interval (with 60s tolerance for tick scheduling)
                    if elapsed_secs >= (interval_h * 3600 - 60):
                        is_due = True
                except Exception:
                    is_due = True

            if not is_due:
                continue

            channel = self.bot.get_channel(channel_id)
            if channel is None:
                log.warning(f"Channel {channel_id} not found — removing subscription from Firebase")
                await delete_channel_subscription(channel_id, loop=self.scheduled_aqi_update)
                continue

            city_name = data.get("city", config.DEFAULT_LOCATION)
            try:
                if city_name.lower() == "kuala lumpur":
                    data_resp = await fetch_aqi_by_id(session, config.DEFAULT_STATION_ID)
                else:
                    data_resp = await fetch_aqi_by_city(session, city_name)

                embed = build_aqi_embed(data_resp)
                embed.set_author(name=f"⏰ Scheduled AQI Update (Every {interval_h}h)")

                time_added = data.get("time_added")
                if time_added:
                    current_footer = embed.footer.text if embed.footer else ""
                    clean_time = time_added.split(".")[0].replace("T", " ")
                    embed.set_footer(
                        text=f"{current_footer} • Active since: {clean_time} UTC" if current_footer else f"Active since: {clean_time} UTC",
                        icon_url=embed.footer.icon_url if embed.footer else None,
                    )

                await channel.send(embed=embed)

                # Update last posted timestamp
                now_iso = now.isoformat()
                data["last_posted_at"] = now_iso
                await firebase_store.save_subscription(
                    channel_id=channel_id,
                    city=city_name,
                    channel_name=data.get("channel_name"),
                    guild_id=data.get("guild_id"),
                    interval_hours=interval_h,
                    last_posted_at=now_iso,
                )

            except Exception as e:
                log.exception(f"Scheduled update failed for channel {channel_id}: {e}")

    @scheduled_aqi_update.before_loop
    async def before_scheduled_update(self):
        await self.bot.wait_until_ready()

    # ── Error Handlers ───────────────────────────────────────────────────────
    @aqi_subscribe_command.error
    @aqi_unsubscribe_command.error
    async def aqi_permission_error_handler(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            embed = discord.Embed(
                title="🔒 Permission Denied",
                description="You need **Manage Channels** permission to subscribe/unsubscribe AQI updates.",
                colour=0xFF4444,
            )
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            raise error


async def setup(bot: commands.Bot):
    """Extension entry point for AqiCog."""
    await bot.add_cog(AqiCog(bot))
