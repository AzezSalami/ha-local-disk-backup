"""Diagnostic sensors for Local Disk Backup."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_BACKUP_PATH, DOMAIN, METADATA_SUFFIX, LOGGER


@dataclass(slots=True)
class DiskStats:
    """Snapshot of the backup folder's state."""

    free_bytes: int | None = None
    total_bytes: int | None = None
    backup_count: int | None = None
    available: bool = False


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the diagnostic sensors."""
    path = Path(entry.data[CONF_BACKUP_PATH])
    async_add_entities(
        [
            BackupDiskFreeSpaceSensor(entry, path),
            BackupDiskCountSensor(entry, path),
        ],
        update_before_add=True,
    )


class _BaseDiskSensor(SensorEntity):
    """Shared plumbing for the disk sensors."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = True

    def __init__(self, entry: ConfigEntry, path: Path) -> None:
        self._path = path
        self._entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Local Disk Backup",
            model=str(path),
            entry_type=DeviceEntryType.SERVICE,
        )

    def _read_stats(self) -> DiskStats:
        """Collect disk stats. Runs in the executor."""
        if not self._path.is_dir():
            return DiskStats(available=False)
        try:
            usage = shutil.disk_usage(self._path)
            count = sum(1 for _ in self._path.glob(f"*{METADATA_SUFFIX}"))
        except OSError as err:
            LOGGER.debug("Could not read stats for %s: %s", self._path, err)
            return DiskStats(available=False)
        return DiskStats(
            free_bytes=usage.free,
            total_bytes=usage.total,
            backup_count=count,
            available=True,
        )


class BackupDiskFreeSpaceSensor(_BaseDiskSensor):
    """Free space on the backup disk."""

    _attr_translation_key = "free_space"
    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_native_unit_of_measurement = UnitOfInformation.GIGABYTES
    _attr_suggested_display_precision = 1
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, entry: ConfigEntry, path: Path) -> None:
        super().__init__(entry, path)
        self._attr_unique_id = f"{entry.entry_id}_free_space"

    async def async_update(self) -> None:
        """Refresh the sensor."""
        stats = await self.hass.async_add_executor_job(self._read_stats)
        self._attr_available = stats.available
        if stats.free_bytes is None:
            self._attr_native_value = None
            return
        self._attr_native_value = stats.free_bytes / 1_000_000_000
        if stats.total_bytes:
            self._attr_extra_state_attributes = {
                "total_gb": round(stats.total_bytes / 1_000_000_000, 1),
                "path": str(self._path),
            }


class BackupDiskCountSensor(_BaseDiskSensor):
    """Number of backups stored on the disk."""

    _attr_translation_key = "backup_count"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, entry: ConfigEntry, path: Path) -> None:
        super().__init__(entry, path)
        self._attr_unique_id = f"{entry.entry_id}_backup_count"

    async def async_update(self) -> None:
        """Refresh the sensor."""
        stats = await self.hass.async_add_executor_job(self._read_stats)
        self._attr_available = stats.available
        self._attr_native_value = stats.backup_count
