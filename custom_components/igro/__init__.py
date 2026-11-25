"""The iGro Home Assistant custom integration."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_DB_PATH,
    CONF_MEDIA_PATH,
    CONF_PANEL_ICON,
    CONF_PANEL_TITLE,
    DEFAULT_DB_FILENAME,
    DEFAULT_MEDIA_DIRNAME,
    DEFAULT_PANEL_ICON,
    DEFAULT_PANEL_TITLE,
    DOMAIN,
    PANEL_URL_PATH,
    PLATFORMS,
    STATIC_URL_PATH,
)
from .coordinator import IGroCoordinator
from .database import IGroDatabase
from .http_api import IGroPhotoServeView, IGroPhotoUploadView
from .services import async_register_services, async_unregister_services
from .websocket_api import async_register_websocket_api

_LOGGER = logging.getLogger(__name__)


def _resolve_config_path(hass: HomeAssistant, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return Path(hass.config.path(raw_path))


async def _async_register_static_frontend(hass: HomeAssistant) -> None:
    """Serve the frontend ES modules from /igro_static."""
    frontend_dir = str(Path(__file__).parent / "frontend")
    try:
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL_PATH, frontend_dir, cache_headers=False)]
        )
    except (ImportError, AttributeError):
        # Fallback for older HA versions
        hass.http.register_static_path(STATIC_URL_PATH, frontend_dir, False)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up iGro from a config entry."""
    cfg = {**entry.data, **entry.options}
    db_path = _resolve_config_path(hass, cfg.get(CONF_DB_PATH, DEFAULT_DB_FILENAME))
    media_dir = _resolve_config_path(
        hass, cfg.get(CONF_MEDIA_PATH, DEFAULT_MEDIA_DIRNAME)
    )
    media_dir.mkdir(parents=True, exist_ok=True)

    db = IGroDatabase(db_path)
    await db.async_initialize()

    coordinator = IGroCoordinator(hass, entry, db, media_dir)
    await coordinator.async_config_entry_first_refresh()

    domain_data = hass.data.setdefault(DOMAIN, {})
    domain_data["coordinator"] = coordinator
    domain_data["db"] = db
    domain_data["entry_id"] = entry.entry_id

    if not domain_data.get("apis_registered"):
        hass.http.register_view(IGroPhotoUploadView())
        hass.http.register_view(IGroPhotoServeView())
        async_register_websocket_api(hass)
        await _async_register_static_frontend(hass)
        domain_data["apis_registered"] = True

    await async_register_services(hass)

    panel_title = cfg.get(CONF_PANEL_TITLE, DEFAULT_PANEL_TITLE)
    panel_icon = cfg.get(CONF_PANEL_ICON, DEFAULT_PANEL_ICON)

    # Register sidebar panel
    try:
        frontend.async_remove_panel(hass, PANEL_URL_PATH)
    except Exception:  # noqa: BLE001
        pass

    await panel_custom.async_register_panel(
        hass,
        webcomponent_name="igro-panel",
        frontend_url_path=PANEL_URL_PATH,
        sidebar_title=panel_title,
        sidebar_icon=panel_icon,
        module_url=f"{STATIC_URL_PATH}/igro-panel.js?v=0.1.1",
        config={"entry_id": entry.entry_id},
        require_admin=False,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    _LOGGER.info("iGro initialized (SQLite DB: %s, media: %s)", db_path, media_dir)
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload iGro when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an iGro config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        domain_data = hass.data.get(DOMAIN, {})
        coordinator: IGroCoordinator | None = domain_data.pop("coordinator", None)
        if coordinator:
            coordinator.async_shutdown_listeners()
        domain_data.pop("db", None)
        domain_data.pop("entry_id", None)

        await async_unregister_services(hass)
        try:
            frontend.async_remove_panel(hass, PANEL_URL_PATH)
        except Exception:  # noqa: BLE001
            pass

    return unload_ok
