"""
Interactive Discord UI Components for AQI Tracker
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Contains Discord Modals, Select Menus, and Views powering the /settings
dashboard and subscription management workflows with per-channel overrides
and global default fallbacks.
"""

from __future__ import annotations

import logging
from typing import Optional
import aiohttp
import discord
from discord.ext import tasks

import config
import firebase_store
from services.state_manager import (
    subscribed_channels,
    get_channel_default_location,
    get_channel_interval_hours,
    is_channel_location_custom,
    is_channel_interval_custom,
    update_channel_location,
    update_channel_interval,
    reset_channel_settings,
    update_global_settings,
    global_settings,
    delete_channel_subscription,
)
from services.waqi_service import fetch_aqi_by_id, fetch_aqi_by_city
from ui.embeds import build_settings_embed

log = logging.getLogger("aqi-bot.ui")


class LocationModal(discord.ui.Modal, title="Set Channel AQI Location"):
    location_input = discord.ui.TextInput(
        label="City or Station Name",
        placeholder="e.g. Kuala Lumpur, Tokyo, London, Penang...",
        min_length=2,
        max_length=100,
        required=True,
    )

    def __init__(self, view: SettingsView):
        super().__init__()
        self.settings_view = view
        self.location_input.default = get_channel_default_location(view.channel_id)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        new_loc = self.location_input.value.strip()

        session = self.settings_view.session or aiohttp.ClientSession()
        close_session_after = self.settings_view.session is None

        try:
            if new_loc.lower() == "kuala lumpur":
                data = await fetch_aqi_by_id(session, config.DEFAULT_STATION_ID)
                resolved_name = "Kuala Lumpur"
            else:
                data = await fetch_aqi_by_city(session, new_loc)
                city_info = data.get("city", {})
                resolved_name = city_info.get("name", new_loc)

            ch_name = getattr(interaction.channel, "name", None)
            await update_channel_location(
                channel_id=self.settings_view.channel_id,
                location=new_loc,
                channel_name=ch_name,
                guild_id=self.settings_view.guild_id,
            )
            await self.settings_view.refresh()

            await interaction.followup.send(
                f"✅ Default AQI location for <#{self.settings_view.channel_id}> set to **{new_loc}** (`{resolved_name}`).",
                ephemeral=True,
            )
        except ValueError as e:
            await interaction.followup.send(
                f"❌ Station lookup failed: {e}. Please check the city name and try again.",
                ephemeral=True,
            )
        except Exception as e:
            log.exception("Failed to update channel location")
            await interaction.followup.send(f"❌ Error updating location: {e}", ephemeral=True)
        finally:
            if close_session_after and not session.closed:
                await session.close()


class IntervalModal(discord.ui.Modal, title="Set Channel Update Interval"):
    interval_input = discord.ui.TextInput(
        label="Update Interval (in Hours)",
        placeholder="Enter number of hours (e.g. 1, 2, 4, 6, 12, 24)",
        min_length=1,
        max_length=3,
        required=True,
    )

    def __init__(self, view: SettingsView):
        super().__init__()
        self.settings_view = view
        self.interval_input.default = str(get_channel_interval_hours(view.channel_id))

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        val = self.interval_input.value.strip()

        try:
            hours = int(val)
            if hours < 1 or hours > 168:
                raise ValueError("Interval must be between 1 and 168 hours (up to 7 days).")
        except ValueError as e:
            await interaction.followup.send(
                f"❌ Invalid interval: {e}",
                ephemeral=True,
            )
            return

        try:
            ch_name = getattr(interaction.channel, "name", None)
            await update_channel_interval(
                channel_id=self.settings_view.channel_id,
                hours=hours,
                channel_name=ch_name,
                guild_id=self.settings_view.guild_id,
            )
            await self.settings_view.refresh()
            await interaction.followup.send(
                f"✅ Auto-update interval for <#{self.settings_view.channel_id}> updated to **every {hours} hour{'s' if hours > 1 else ''}**.",
                ephemeral=True,
            )
        except Exception as e:
            log.exception("Failed to update channel interval")
            await interaction.followup.send(f"❌ Error updating interval: {e}", ephemeral=True)


class GlobalSettingsModal(discord.ui.Modal, title="Update Global Baseline Defaults"):
    location_input = discord.ui.TextInput(
        label="Global Default Location",
        placeholder="e.g. Kuala Lumpur, Tokyo, London",
        min_length=2,
        max_length=100,
        required=True,
    )
    interval_input = discord.ui.TextInput(
        label="Global Update Interval (Hours)",
        placeholder="e.g. 1, 2, 4, 6, 12, 24",
        min_length=1,
        max_length=3,
        required=True,
    )

    def __init__(self, view: SettingsView):
        super().__init__()
        self.settings_view = view
        self.location_input.default = global_settings.get("default_location", config.DEFAULT_LOCATION)
        self.interval_input.default = str(global_settings.get("update_interval_hours", config.DEFAULT_INTERVAL_HOURS))

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        new_loc = self.location_input.value.strip()
        val_hours = self.interval_input.value.strip()

        try:
            hours = int(val_hours)
            if hours < 1 or hours > 168:
                raise ValueError("Interval must be between 1 and 168 hours.")
        except ValueError as e:
            await interaction.followup.send(f"❌ Invalid interval: {e}", ephemeral=True)
            return

        session = self.settings_view.session or aiohttp.ClientSession()
        close_session_after = self.settings_view.session is None

        try:
            if new_loc.lower() == "kuala lumpur":
                data = await fetch_aqi_by_id(session, config.DEFAULT_STATION_ID)
                resolved_name = "Kuala Lumpur"
            else:
                data = await fetch_aqi_by_city(session, new_loc)
                city_info = data.get("city", {})
                resolved_name = city_info.get("name", new_loc)

            await update_global_settings(default_location=new_loc, interval_hours=hours, loop=self.settings_view.loop)
            await self.settings_view.refresh()

            await interaction.followup.send(
                f"✅ Global baseline defaults updated:\n• Location: **{new_loc}** (`{resolved_name}`)\n• Interval: **Every {hours}h**\n*All channels without custom overrides will use these defaults.*",
                ephemeral=True,
            )
        except Exception as e:
            log.exception("Failed to update global settings")
            await interaction.followup.send(f"❌ Error updating global settings: {e}", ephemeral=True)
        finally:
            if close_session_after and not session.closed:
                await session.close()


class SubscriptionSelect(discord.ui.Select):
    def __init__(self, server_subs: list[tuple[int, dict]]):
        options = []
        for cid, data in server_subs[:25]:
            city = data.get("city", "Unknown") if isinstance(data, dict) else str(data)
            ch_name = data.get("channel_name", "") if isinstance(data, dict) else ""
            label = f"#{ch_name}" if ch_name else f"Channel {cid}"
            sub_hours = data.get("interval_hours", 1) if isinstance(data, dict) else 1
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=str(cid),
                    description=f"{city} • Every {sub_hours}h"[:100],
                    emoji="📢",
                )
            )

        super().__init__(
            placeholder="Select other channel(s) to unsubscribe...",
            min_values=1,
            max_values=len(options),
            options=options,
            row=2,
        )

    async def callback(self, interaction: discord.Interaction):
        if isinstance(self.view, SettingsView):
            self.view.selected_channel_ids = [int(v) for v in self.values]
        await interaction.response.defer()


class SettingsView(discord.ui.View):
    def __init__(
        self,
        channel_id: int,
        guild_id: Optional[int],
        author_id: int,
        loop: Optional[tasks.Loop] = None,
        session: Optional[aiohttp.ClientSession] = None,
    ):
        super().__init__(timeout=300)
        self.channel_id = channel_id
        self.guild_id = guild_id
        self.author_id = author_id
        self.loop = loop
        self.session = session
        self.message: Optional[discord.Message] = None
        self.selected_channel_ids: list[int] = []
        self.select_menu: Optional[SubscriptionSelect] = None
        self.build_components()

    def get_other_server_subs(self) -> list[tuple[int, dict]]:
        return [
            (cid, data) for cid, data in subscribed_channels.items()
            if (not self.guild_id or (isinstance(data, dict) and data.get("guild_id") == self.guild_id))
            and cid != self.channel_id
        ]

    def build_components(self):
        self.clear_items()

        # Row 0: Channel Primary Controls
        btn_loc = discord.ui.Button(
            label="Set Location",
            emoji="📍",
            style=discord.ButtonStyle.primary,
            row=0,
        )
        btn_loc.callback = self.on_location_click
        self.add_item(btn_loc)

        btn_interval = discord.ui.Button(
            label="Set Interval",
            emoji="⏱️",
            style=discord.ButtonStyle.secondary,
            row=0,
        )
        btn_interval.callback = self.on_interval_click
        self.add_item(btn_interval)

        # Row 1: Overrides Reset, Channel Unsubscribe, Refresh
        has_custom = is_channel_location_custom(self.channel_id) or is_channel_interval_custom(self.channel_id)
        if has_custom:
            btn_reset = discord.ui.Button(
                label="Reset to Global",
                emoji="↩️",
                style=discord.ButtonStyle.secondary,
                row=0,
            )
            btn_reset.callback = self.on_reset_click
            self.add_item(btn_reset)

        if self.channel_id in subscribed_channels:
            btn_unsub_this = discord.ui.Button(
                label="Unsubscribe This Channel",
                emoji="🛑",
                style=discord.ButtonStyle.danger,
                row=1,
            )
            btn_unsub_this.callback = self.on_unsubscribe_this_click
            self.add_item(btn_unsub_this)

        btn_refresh = discord.ui.Button(
            label="Refresh",
            emoji="🔄",
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        btn_refresh.callback = self.on_refresh_click
        self.add_item(btn_refresh)

        # Row 2 & 3: Other Subscribed Channels Management (if any)
        other_subs = self.get_other_server_subs()
        if other_subs:
            self.select_menu = SubscriptionSelect(other_subs)
            self.add_item(self.select_menu)

            btn_unsub_sel = discord.ui.Button(
                label="Unsubscribe Selected",
                emoji="🗑️",
                style=discord.ButtonStyle.danger,
                row=3,
            )
            btn_unsub_sel.callback = self.on_unsubscribe_selected_click
            self.add_item(btn_unsub_sel)
        else:
            self.select_menu = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild:
            perms = interaction.user.guild_permissions
            if perms.manage_channels or perms.administrator:
                return True
            await interaction.response.send_message(
                "🔒 You need **Manage Channels** permission to modify bot settings.",
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            if self.message:
                await self.message.edit(view=self)
        except Exception:
            pass

    async def on_location_click(self, interaction: discord.Interaction):
        await interaction.response.send_modal(LocationModal(self))

    async def on_interval_click(self, interaction: discord.Interaction):
        await interaction.response.send_modal(IntervalModal(self))

    async def on_global_click(self, interaction: discord.Interaction):
        await interaction.response.send_modal(GlobalSettingsModal(self))

    async def on_reset_click(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await reset_channel_settings(self.channel_id)
        await self.refresh()
        await interaction.followup.send(
            f"↩️ Successfully reset <#{self.channel_id}> settings to inherit from global defaults.",
            ephemeral=True,
        )

    async def on_unsubscribe_this_click(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await delete_channel_subscription(self.channel_id, loop=self.loop)
        await self.refresh()
        await interaction.followup.send(
            f"🛑 Successfully unsubscribed <#{self.channel_id}> from AQI auto-updates.",
            ephemeral=True,
        )

    async def on_refresh_click(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self.refresh()

    async def on_unsubscribe_selected_click(self, interaction: discord.Interaction):
        if not self.selected_channel_ids:
            await interaction.response.send_message(
                "⚠️ Please select at least one channel from the dropdown list before clicking Unsubscribe.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        removed_cids = list(self.selected_channel_ids)
        removed_mentions = []
        for cid in removed_cids:
            await delete_channel_subscription(cid, loop=self.loop)
            removed_mentions.append(f"<#{cid}>")

        self.selected_channel_ids.clear()
        await self.refresh()
        await interaction.followup.send(
            f"🛑 Successfully unsubscribed {len(removed_cids)} channel(s): {', '.join(removed_mentions)}",
            ephemeral=True,
        )

    async def refresh(self):
        self.build_components()
        embed = build_settings_embed(channel_id=self.channel_id, guild_id=self.guild_id)
        if self.message:
            try:
                await self.message.edit(embed=embed, view=self)
            except Exception as e:
                log.warning(f"Could not edit message directly: {e}")
