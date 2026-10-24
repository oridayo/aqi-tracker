"""
UI Package for Discord AQI Tracker
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Contains embed builders and interactive Discord UI views, buttons, and modals.
"""

from ui.embeds import build_aqi_embed, build_settings_embed
from ui.views import LocationModal, IntervalModal, GlobalSettingsModal, SubscriptionSelect, SettingsView

__all__ = [
    "build_aqi_embed",
    "build_settings_embed",
    "LocationModal",
    "IntervalModal",
    "GlobalSettingsModal",
    "SubscriptionSelect",
    "SettingsView",
]
