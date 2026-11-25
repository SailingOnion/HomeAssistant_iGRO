"""Config flow for iGro integration."""

from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
import voluptuous as vol

from .const import (
    CONF_DB_PATH,
    CONF_LEAF_TEMP_OFFSET_C,
    CONF_MEDIA_PATH,
    CONF_PANEL_ICON,
    CONF_PANEL_TITLE,
    DEFAULT_DB_FILENAME,
    DEFAULT_LEAF_TEMP_OFFSET_C,
    DEFAULT_MEDIA_DIRNAME,
    DEFAULT_PANEL_ICON,
    DEFAULT_PANEL_TITLE,
    DOMAIN,
)


class IGroConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for iGro."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(
                title=user_input.get(CONF_PANEL_TITLE, DEFAULT_PANEL_TITLE),
                data=user_input,
            )

        schema = vol.Schema(
            {
                vol.Optional(CONF_PANEL_TITLE, default=DEFAULT_PANEL_TITLE): str,
                vol.Optional(CONF_PANEL_ICON, default=DEFAULT_PANEL_ICON): str,
                vol.Optional(CONF_DB_PATH, default=DEFAULT_DB_FILENAME): str,
                vol.Optional(CONF_MEDIA_PATH, default=DEFAULT_MEDIA_DIRNAME): str,
                vol.Optional(
                    CONF_LEAF_TEMP_OFFSET_C, default=DEFAULT_LEAF_TEMP_OFFSET_C
                ): vol.All(vol.Coerce(float), vol.Range(min=-10.0, max=5.0)),
            }
        )

        return self.async_show_form(step_id="user", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> IGroOptionsFlowHandler:
        """Get the options flow for this handler."""
        return IGroOptionsFlowHandler(config_entry)


class IGroOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle iGro options flow."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage iGro options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = {**self._config_entry.data, **self._config_entry.options}
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_PANEL_TITLE,
                    default=current.get(CONF_PANEL_TITLE, DEFAULT_PANEL_TITLE),
                ): str,
                vol.Optional(
                    CONF_PANEL_ICON,
                    default=current.get(CONF_PANEL_ICON, DEFAULT_PANEL_ICON),
                ): str,
                vol.Optional(
                    CONF_LEAF_TEMP_OFFSET_C,
                    default=current.get(
                        CONF_LEAF_TEMP_OFFSET_C, DEFAULT_LEAF_TEMP_OFFSET_C
                    ),
                ): vol.All(vol.Coerce(float), vol.Range(min=-10.0, max=5.0)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
