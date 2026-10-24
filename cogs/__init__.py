"""
Cogs Package for Discord AQI Tracker
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Modular command groups and scheduled background tasks for AQI tracking and settings.
"""

from cogs.aqi import AqiCog
from cogs.settings import SettingsCog

__all__ = ["AqiCog", "SettingsCog"]
