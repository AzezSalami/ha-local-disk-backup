"""The Local Disk Backup integration.

Registers a Home Assistant backup agent that writes backups to a directory on a
locally attached disk (a second internal drive, or an external USB drive), so
the disk shows up as a normal location in Settings > System > Backups.
"""

from __future__ import annotations

import os
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady

from .const import CONF_BACKUP_PATH, DATA_BACKUP_AGENT_LISTENERS, DOMAIN, LOGGER

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Local Disk Backup from a config entry."""
    path = Path(entry.data[CONF_BACKUP_PATH])

    def _check_target() -> str | None:
        """Return an error key if the target directory is unusable."""
        if not path.is_dir():
            return "directory_not_found"
        if not os.access(path, os.W_OK | os.X_OK):
            return "directory_not_writable"
        return None

    if error := await hass.async_add_executor_job(_check_target):
        # Not ready rather than failed: a USB disk may simply not be mounted
        # yet at startup, and HA will retry.
        raise ConfigEntryNotReady(f"{path}: {error}")

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    # Tell the backup manager to re-read the list of agents, so this disk
    # appears in the backup UI immediately.
    _async_notify_backup_listeners_soon(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    _async_notify_backup_listeners_soon(hass)
    return unload_ok


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


@callback
def _async_notify_backup_listeners(hass: HomeAssistant) -> None:
    """Notify the backup manager that the set of agents changed."""
    for listener in hass.data.get(DATA_BACKUP_AGENT_LISTENERS, []):
        listener()


@callback
def _async_notify_backup_listeners_soon(hass: HomeAssistant) -> None:
    """Notify backup listeners on the next event loop iteration.

    Deferred so the config entry has finished loading (or unloading) before the
    backup manager asks us for our agents.
    """
    hass.loop.call_soon(_async_notify_backup_listeners, hass)


__all__ = ["DOMAIN", "LOGGER", "async_setup_entry", "async_unload_entry"]
