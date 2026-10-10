"""Config flow for Local Disk Backup."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
)

from .const import (
    CONF_BACKUP_PATH,
    CONF_KEEP_LAST,
    DEFAULT_KEEP_LAST,
    DOMAIN,
    SUGGESTED_PATHS,
)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_BACKUP_PATH): TextSelector(),
        vol.Optional("name"): TextSelector(),
    }
)

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_KEEP_LAST, default=DEFAULT_KEEP_LAST): NumberSelector(
            NumberSelectorConfig(min=0, max=365, step=1, mode=NumberSelectorMode.BOX)
        ),
    }
)


def _validate_path(raw_path: str) -> tuple[str | None, str]:
    """Validate a directory, returning (error_key, resolved_path).

    Runs in the executor: it touches the filesystem.
    """
    try:
        path = Path(raw_path).expanduser()
    except (ValueError, RuntimeError):
        return "invalid_path", raw_path

    if not path.is_absolute():
        return "not_absolute", str(path)

    resolved = path.resolve()

    if not resolved.exists():
        return "directory_not_found", str(resolved)
    if not resolved.is_dir():
        return "not_a_directory", str(resolved)
    if not os.access(resolved, os.W_OK | os.X_OK):
        return "directory_not_writable", str(resolved)

    # Writing backups onto the same filesystem as /config defeats the purpose,
    # but some people genuinely want it, so warn via the log rather than block.
    try:
        probe = resolved / ".local_disk_backup_write_test"
        probe.write_bytes(b"")
        probe.unlink()
    except OSError:
        return "directory_not_writable", str(resolved)

    return None, str(resolved)


class LocalDiskBackupConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Local Disk Backup."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask the user for the folder to store backups in."""
        errors: dict[str, str] = {}

        if user_input is not None:
            error, resolved = await self.hass.async_add_executor_job(
                _validate_path, user_input[CONF_BACKUP_PATH]
            )
            if error:
                errors[CONF_BACKUP_PATH] = error
            else:
                await self.async_set_unique_id(resolved)
                self._abort_if_unique_id_configured()
                title = user_input.get("name") or f"Disk ({Path(resolved).name})"
                return self.async_create_entry(
                    title=title,
                    data={CONF_BACKUP_PATH: resolved},
                    options={CONF_KEEP_LAST: DEFAULT_KEEP_LAST},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA,
                user_input or {CONF_BACKUP_PATH: SUGGESTED_PATHS[0]},
            ),
            errors=errors,
            description_placeholders={"examples": ", ".join(SUGGESTED_PATHS)},
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> LocalDiskBackupOptionsFlow:
        """Return the options flow."""
        return LocalDiskBackupOptionsFlow()


class LocalDiskBackupOptionsFlow(OptionsFlow):
    """Handle options for Local Disk Backup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage retention options."""
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_KEEP_LAST: int(user_input[CONF_KEEP_LAST])}
            )

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, dict(self.config_entry.options)
            ),
        )
