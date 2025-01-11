from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform

from . import econest_intelligent

PLATFORMS = [Platform.SENSOR]

type EconestConfigEntry = ConfigEntry[cyberiot_intelligent.CyberiotApollo]


async def async_setup_entry(hass: HomeAssistant, entry: EconestConfigEntry) -> bool:
    entry.runtime_data = econest_intelligent.EconestEnergy(hass, entry.data["serial_number"], entry.data["host"])
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    return unload_ok
