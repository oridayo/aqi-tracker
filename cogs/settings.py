"""
Settings Cog for Discord AQI Tracker
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Implements the /settings slash command dashboard for managing default locations,
update intervals, and active channel subscriptions.
"""

from __future__ import annotations

import logging
from typing import Optional, Literal
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

import config
from services.state_manager import (
    update_channel_location,
    update_channel_interval,
    update_global_settings,
    get_channel_default_location,
    get_channel_interval_hours,
)
from services.waqi_service import fetch_aqi_by_id, fetch_aqi_by_city
from ui.embeds import build_settings_embed
from ui.views import SettingsView

log = logging.getLogger("aqi-bot.cog.settings")


class SettingsCog(commands.Cog, name="Settings"):
    """Cog handling interactive bot settings, location overrides, and subscription management."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def get_session(self) -> aiohttp.ClientSession:
        """Retrieve the shared HTTP session from the bot instance."""
        session = getattr(self.bot, "http_session", None)
        if session is None or session.closed:
            raise RuntimeError("Bot HTTP session is not available.")
        return session

    def get_scheduled_loop(self):
        """Retrieve the scheduled AQI loop from AqiCog if loaded."""
        aqi_cog = self.bot.get_cog("AQI")
        return getattr(aqi_cog, "loop", None)

    # ── /settings command ─────────────────────────────────────────────────────
    @app_commands.command(
        name="settings",
        description="Configure bot settings: default location, auto-update interval, and subscriptions",
    )
    @app_commands.describe(
        default_location="Set default AQI city (e.g. Kuala Lumpur, Tokyo, Penang)",
        interval_hours="Set scheduled update interval in hours (e.g. 1, 2, 4, 6, 12, 24)",
    )
    @app_commands.checks.has_permissions(manage_channels=True)
    async def settings_command(
        self,
        interaction: discord.Interaction,
        default_location: Optional[str] = None,
        interval_hours: Optional[app_commands.Range[int, 1, 168]] = None,
    ):
        await interaction.response.defer()
        channel_id = interaction.channel_id
        guild_id = interaction.guild_id
        channel_name = getattr(interaction.channel, "name", None)
        session = self.get_session()
        loop = self.get_scheduled_loop()
        messages = []
        scope = "channel"

        # 1. Handle direct location parameter if supplied
        if default_location:
            try:
                if default_location.lower() == "kuala lumpur":
                    await fetch_aqi_by_id(session, config.DEFAULT_STATION_ID)
                else:
                    await fetch_aqi_by_city(session, default_location)

                if scope == "channel" and channel_id:
                    await update_channel_location(
                        channel_id=channel_id,
                        location=default_location,
                        channel_name=channel_name,
                        guild_id=guild_id,
                    )
                    messages.append(f"📍 Channel default location updated to **{default_location}**")
                else:
                    await update_global_settings(default_location=default_location, loop=loop)
                    messages.append(f"🌐 Global default location updated to **{default_location}**")
            except Exception as e:
                messages.append(f"⚠️ Could not set location: {e}")

        # 2. Handle direct interval parameter if supplied
        if interval_hours:
            try:
                if scope == "channel" and channel_id:
                    await update_channel_interval(
                        channel_id=channel_id,
                        hours=interval_hours,
                        channel_name=channel_name,
                        guild_id=guild_id,
                    )
                    messages.append(
                        f"⏱️ Channel update interval set to **every {interval_hours} hour{'s' if interval_hours > 1 else ''}**"
                    )
                else:
                    await update_global_settings(interval_hours=interval_hours, loop=loop)
                    messages.append(
                        f"🌐 Global update interval set to **every {interval_hours} hour{'s' if interval_hours > 1 else ''}**"
                    )
            except Exception as e:
                messages.append(f"⚠️ Could not set interval: {e}")

        # 3. Create interactive view and dashboard embed
        view = SettingsView(
            channel_id=channel_id,
            guild_id=guild_id,
            author_id=interaction.user.id,
            loop=loop,
            session=session,
        )
        embed = build_settings_embed(channel_id=channel_id, guild_id=guild_id)
        if messages:
            embed.description = "\n".join(messages) + "\n\n" + (embed.description or "")

        await interaction.followup.send(embed=embed, view=view)
        view.message = await interaction.original_response()

    # ── Error Handlers ───────────────────────────────────────────────────────
    @settings_command.error
    async def settings_permission_error_handler(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.MissingPermissions):
            embed = discord.Embed(
                title="🔒 Permission Denied",
                description="You need **Manage Channels** permission to configure settings or manage subscriptions.",
                colour=0xFF4444,
            )
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            raise error


async def setup(bot: commands.Bot):
    """Extension entry point for SettingsCog."""
    await bot.add_cog(SettingsCog(bot))
