"""Backup agent platform for Local Disk Backup.

This is the file that makes the integration show up in
Settings > System > Backups as a selectable backup location.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
import json
import os
from pathlib import Path
from typing import Any

from homeassistant.components.backup import AgentBackup, BackupAgent, BackupAgentError
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .const import (
    CHUNK_SIZE,
    CONF_BACKUP_PATH,
    CONF_KEEP_LAST,
    DATA_BACKUP_AGENT_LISTENERS,
    DEFAULT_KEEP_LAST,
    DOMAIN,
    LOGGER,
    METADATA_SUFFIX,
    TAR_SUFFIX,
)

try:  # Added in HA 2025.5; fall back for older cores.
    from homeassistant.components.backup import BackupNotFound
except ImportError:  # pragma: no cover

    class BackupNotFound(BackupAgentError):  # type: ignore[no-redef]
        """Raised when a backup is not found."""


async def async_get_backup_agents(
    hass: HomeAssistant,
    **kwargs: Any,
) -> list[BackupAgent]:
    """Return one backup agent per configured disk."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    return [LocalDiskBackupAgent(hass, entry) for entry in entries]


@callback
def async_register_backup_agents_listener(
    hass: HomeAssistant,
    *,
    listener: Callable[[], None],
    **kwargs: Any,
) -> Callable[[], None]:
    """Register a listener to be called when the set of agents changes.

    :return: A function to unregister the listener.
    """
    hass.data.setdefault(DATA_BACKUP_AGENT_LISTENERS, []).append(listener)

    @callback
    def remove_listener() -> None:
        """Remove the listener."""
        hass.data[DATA_BACKUP_AGENT_LISTENERS].remove(listener)
        if not hass.data[DATA_BACKUP_AGENT_LISTENERS]:
            hass.data.pop(DATA_BACKUP_AGENT_LISTENERS)

    return remove_listener


class LocalDiskBackupAgent(BackupAgent):
    """Store Home Assistant backups in a folder on a locally attached disk.

    Each backup is written as two files:
      <backup_id>.tar            the backup archive itself
      <backup_id>.metadata.json  the AgentBackup metadata, so listing is cheap
    """

    domain = DOMAIN

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise the agent."""
        self._hass = hass
        self._entry = entry
        self.name = entry.title
        self.unique_id = entry.entry_id
        self._path = Path(entry.data[CONF_BACKUP_PATH])
        self._write_lock = asyncio.Lock()

    @property
    def _keep_last(self) -> int:
        """Number of backups to keep on this disk; 0 means unlimited."""
        return int(self._entry.options.get(CONF_KEEP_LAST, DEFAULT_KEEP_LAST))

    def _tar_path(self, backup_id: str) -> Path:
        return self._path / f"{backup_id}{TAR_SUFFIX}"

    def _meta_path(self, backup_id: str) -> Path:
        return self._path / f"{backup_id}{METADATA_SUFFIX}"

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    async def async_upload_backup(
        self,
        *,
        open_stream: Callable[[], Coroutine[Any, Any, AsyncIterator[bytes]]],
        backup: AgentBackup,
        on_progress: Callable[..., None] | None = None,
        **kwargs: Any,
    ) -> None:
        """Write a backup to the disk.

        :param open_stream: Returns an async iterator yielding the backup bytes.
        :param backup: Metadata describing the backup.
        :param on_progress: Callback used to report upload progress.
        """
        tar_path = self._tar_path(backup.backup_id)
        tmp_path = tar_path.with_name(f"{tar_path.name}.writing")

        async with self._write_lock:
            try:
                await self._hass.async_add_executor_job(self._ensure_dir)
                stream = await open_stream()
                await self._async_write_stream(stream, tmp_path, on_progress)
                await self._hass.async_add_executor_job(
                    self._commit, tmp_path, tar_path, backup
                )
            except BackupAgentError:
                await self._hass.async_add_executor_job(self._discard, tmp_path)
                raise
            except Exception as err:
                await self._hass.async_add_executor_job(self._discard, tmp_path)
                raise BackupAgentError(
                    f"Failed to write backup to {tar_path}: {err}"
                ) from err

        await self._async_enforce_retention()

    async def _async_write_stream(
        self,
        stream: AsyncIterator[bytes],
        tmp_path: Path,
        on_progress: Callable[..., None] | None,
    ) -> None:
        """Stream bytes to a temporary file, buffering to keep I/O chunky."""
        handle = await self._hass.async_add_executor_job(
            self._open_for_write, tmp_path
        )
        written = 0
        buffer: list[bytes] = []
        buffered = 0

        def _flush(data: bytes) -> None:
            handle.write(data)

        try:
            async for chunk in stream:
                buffer.append(chunk)
                buffered += len(chunk)
                if buffered >= CHUNK_SIZE:
                    payload = b"".join(buffer)
                    buffer.clear()
                    buffered = 0
                    await self._hass.async_add_executor_job(_flush, payload)
                    written += len(payload)
                    if on_progress is not None:
                        on_progress(bytes_uploaded=written)
            if buffer:
                payload = b"".join(buffer)
                await self._hass.async_add_executor_job(_flush, payload)
                written += len(payload)
                if on_progress is not None:
                    on_progress(bytes_uploaded=written)
        finally:
            await self._hass.async_add_executor_job(handle.close)

    @staticmethod
    def _open_for_write(path: Path) -> Any:
        return path.open("wb")

    def _ensure_dir(self) -> None:
        """Make sure the target directory exists and is writable."""
        if not self._path.is_dir():
            raise BackupAgentError(
                f"Backup folder {self._path} is not available. "
                "Is the disk mounted?"
            )
        if not os.access(self._path, os.W_OK | os.X_OK):
            raise BackupAgentError(f"Backup folder {self._path} is not writable")

    def _commit(self, tmp_path: Path, tar_path: Path, backup: AgentBackup) -> None:
        """Atomically move the finished archive into place and write metadata."""
        tmp_path.replace(tar_path)
        self._meta_path(backup.backup_id).write_text(
            json.dumps(backup.as_dict()), encoding="utf-8"
        )

    @staticmethod
    def _discard(tmp_path: Path) -> None:
        """Remove a partially written file."""
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError as err:  # pragma: no cover
            LOGGER.warning("Could not remove partial backup %s: %s", tmp_path, err)

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    async def async_download_backup(
        self,
        backup_id: str,
        **kwargs: Any,
    ) -> AsyncIterator[bytes]:
        """Return an async iterator over the backup archive."""
        tar_path = self._tar_path(backup_id)
        if not await self._hass.async_add_executor_job(tar_path.is_file):
            raise BackupNotFound(f"Backup {backup_id} not found on {self._path}")
        return self._async_iter_file(tar_path)

    async def _async_iter_file(self, path: Path) -> AsyncIterator[bytes]:
        """Yield the file's contents in chunks, reading off the event loop."""
        handle = await self._hass.async_add_executor_job(self._open_for_read, path)
        try:
            while True:
                chunk = await self._hass.async_add_executor_job(
                    handle.read, CHUNK_SIZE
                )
                if not chunk:
                    break
                yield chunk
        finally:
            await self._hass.async_add_executor_job(handle.close)

    @staticmethod
    def _open_for_read(path: Path) -> Any:
        return path.open("rb")

    # ------------------------------------------------------------------
    # List / get / delete
    # ------------------------------------------------------------------

    async def async_list_backups(self, **kwargs: Any) -> list[AgentBackup]:
        """List the backups stored on this disk."""
        return await self._hass.async_add_executor_job(self._list_backups)

    def _list_backups(self) -> list[AgentBackup]:
        if not self._path.is_dir():
            LOGGER.debug("Backup folder %s is not available", self._path)
            return []

        backups: list[AgentBackup] = []
        for meta_file in sorted(self._path.glob(f"*{METADATA_SUFFIX}")):
            backup_id = meta_file.name[: -len(METADATA_SUFFIX)]
            if not self._tar_path(backup_id).is_file():
                LOGGER.debug("Skipping %s: archive missing", meta_file.name)
                continue
            try:
                data = json.loads(meta_file.read_text(encoding="utf-8"))
                backups.append(AgentBackup.from_dict(data))
            except (OSError, ValueError, KeyError, TypeError) as err:
                LOGGER.warning("Ignoring unreadable metadata %s: %s", meta_file, err)
        return backups

    async def async_get_backup(
        self,
        backup_id: str,
        **kwargs: Any,
    ) -> AgentBackup:
        """Return a single backup."""
        for backup in await self.async_list_backups():
            if backup.backup_id == backup_id:
                return backup
        raise BackupNotFound(f"Backup {backup_id} not found on {self._path}")

    async def async_delete_backup(
        self,
        backup_id: str,
        **kwargs: Any,
    ) -> None:
        """Delete a backup and its metadata."""
        tar_path = self._tar_path(backup_id)
        meta_path = self._meta_path(backup_id)

        def _delete() -> bool:
            existed = tar_path.is_file() or meta_path.is_file()
            tar_path.unlink(missing_ok=True)
            meta_path.unlink(missing_ok=True)
            return existed

        try:
            existed = await self._hass.async_add_executor_job(_delete)
        except OSError as err:
            raise BackupAgentError(f"Failed to delete backup {backup_id}: {err}") from err

        if not existed:
            raise BackupNotFound(f"Backup {backup_id} not found on {self._path}")

    # ------------------------------------------------------------------
    # Retention
    # ------------------------------------------------------------------

    async def _async_enforce_retention(self) -> None:
        """Delete the oldest backups beyond the configured limit."""
        keep_last = self._keep_last
        if keep_last <= 0:
            return

        backups = await self.async_list_backups()
        if len(backups) <= keep_last:
            return

        # AgentBackup.date is an ISO-8601 string, which sorts chronologically.
        backups.sort(key=lambda backup: backup.date, reverse=True)
        for backup in backups[keep_last:]:
            LOGGER.debug("Retention: removing %s from %s", backup.backup_id, self._path)
            try:
                await self.async_delete_backup(backup.backup_id)
            except BackupAgentError as err:
                LOGGER.warning("Retention cleanup failed for %s: %s", backup.backup_id, err)
