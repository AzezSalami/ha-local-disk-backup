"""Constants for the Local Disk Backup integration."""

from __future__ import annotations

import logging
from typing import Final

DOMAIN: Final = "local_disk_backup"
LOGGER: Final = logging.getLogger(__package__)

CONF_BACKUP_PATH: Final = "backup_path"
CONF_KEEP_LAST: Final = "keep_last"

DEFAULT_KEEP_LAST: Final = 0  # 0 = keep everything, HA core retention still applies

# Key under which the backup manager's "agents changed" listeners are stored.
DATA_BACKUP_AGENT_LISTENERS: Final = f"{DOMAIN}.backup_agent_listeners"

# Read/write block size when streaming backups to and from disk.
CHUNK_SIZE: Final = 4 * 1024 * 1024

# Suffix used for the sidecar file that holds a backup's metadata.
METADATA_SUFFIX: Final = ".metadata.json"
TAR_SUFFIX: Final = ".tar"

# Paths that are normally reachable from inside the Home Assistant container.
# Used to give the user a hint in the config flow.
SUGGESTED_PATHS: Final = (
    "/media/habackup",
    "/share/habackup",
    "/mnt/backup_disk",
)
