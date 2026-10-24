"""
Services Package for Discord AQI Tracker
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Provides WAQI API client and centralized application state management.
"""

from services.waqi_service import fetch_aqi_by_id, fetch_aqi_by_city
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

__all__ = [
    "fetch_aqi_by_id",
    "fetch_aqi_by_city",
    "subscribed_channels",
    "global_settings",
    "channel_settings",
    "get_channel_default_location",
    "get_channel_interval_hours",
    "is_channel_location_custom",
    "is_channel_interval_custom",
    "get_default_location",
    "get_update_interval_hours",
    "update_channel_location",
    "update_channel_interval",
    "reset_channel_settings",
    "update_global_settings",
    "update_default_location",
    "update_update_interval",
    "save_channel_subscription",
    "delete_channel_subscription",
    "load_state_from_firebase",
    "register_scheduled_loop",
]
