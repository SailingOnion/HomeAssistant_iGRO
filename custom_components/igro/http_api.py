"""HTTP views and media helpers for iGro photo journal."""

from __future__ import annotations

import asyncio
import hmac
import logging
import mimetypes
from pathlib import Path
from typing import Any
import uuid

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import (
    ALLOWED_IMAGE_EXTENSIONS,
    DOMAIN,
    EVENT_PHOTO_ADDED,
    MAX_PHOTO_SIZE_BYTES,
)
from .coordinator import IGroCoordinator, photo_url

_LOGGER = logging.getLogger(__name__)


def _get_coordinator(hass: HomeAssistant) -> IGroCoordinator | None:
    domain_data = hass.data.get(DOMAIN)
    if not domain_data:
        return None
    return domain_data.get("coordinator")


def _write_bytes_sync(target_path: Path, data: bytes) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(data)


def _remove_file_sync(target_path: Path) -> None:
    try:
        if target_path.is_file():
            target_path.unlink()
    except OSError as err:
        _LOGGER.warning("Failed to delete iGro photo file %s: %s", target_path, err)


async def async_remove_photo_file(media_dir: Path, filename: str) -> None:
    """Safely remove a photo file inside media_dir."""
    safe_name = Path(filename).name
    target = (media_dir / safe_name).resolve()
    try:
        target.relative_to(media_dir.resolve())
    except ValueError:
        return
    await asyncio.to_thread(_remove_file_sync, target)


async def async_save_photo_bytes(
    hass: HomeAssistant,
    coordinator: IGroCoordinator,
    data: bytes,
    ext: str,
    mime_type: str,
    *,
    plant_id: str | None = None,
    environment_id: str | None = None,
    log_id: str | None = None,
    stage: str | None = None,
    caption: str | None = None,
    source: str = "upload",
    taken_at: str | None = None,
) -> dict[str, Any]:
    """Persist photo bytes to disk and create a SQLite photo record."""
    if len(data) > MAX_PHOTO_SIZE_BYTES:
        raise ValueError(f"Photo exceeds maximum size of {MAX_PHOTO_SIZE_BYTES // (1024 * 1024)} MB")
    if len(data) == 0:
        raise ValueError("Photo file is empty")

    clean_ext = ext.lower()
    if not clean_ext.startswith("."):
        clean_ext = f".{clean_ext}"
    if clean_ext not in ALLOWED_IMAGE_EXTENSIONS:
        clean_ext = ".jpg"

    filename = f"{uuid.uuid4().hex}{clean_ext}"
    target_path = coordinator.media_dir / filename
    await asyncio.to_thread(_write_bytes_sync, target_path, data)

    record = await coordinator.db.async_create_photo(
        {
            "plant_id": plant_id,
            "environment_id": environment_id,
            "log_id": log_id,
            "stage": stage,
            "filename": filename,
            "mime_type": mime_type or "image/jpeg",
            "caption": caption,
            "source": source,
            "taken_at": taken_at,
        }
    )
    record["url"] = photo_url(record["id"], record["access_token"])

    hass.bus.async_fire(
        EVENT_PHOTO_ADDED,
        {
            "photo_id": record["id"],
            "plant_id": record.get("plant_id"),
            "environment_id": record.get("environment_id"),
            "stage": record.get("stage"),
            "source": source,
        },
    )
    await coordinator.async_request_refresh()
    return record


async def async_capture_camera_photo(
    hass: HomeAssistant,
    coordinator: IGroCoordinator,
    camera_entity_id: str,
    *,
    plant_id: str | None = None,
    environment_id: str | None = None,
    stage: str | None = None,
    caption: str | None = None,
) -> dict[str, Any]:
    """Capture a live snapshot from an HA camera entity and save it to iGro."""
    from homeassistant.components import camera

    image = await camera.async_get_image(hass, camera_entity_id)
    content_type = image.content_type or "image/jpeg"
    ext = mimetypes.guess_extension(content_type) or ".jpg"
    if ext == ".jpe":
        ext = ".jpg"

    return await async_save_photo_bytes(
        hass,
        coordinator,
        image.content,
        ext,
        content_type,
        plant_id=plant_id,
        environment_id=environment_id,
        stage=stage,
        caption=caption,
        source="camera",
    )


class IGroPhotoUploadView(HomeAssistantView):
    """Authenticated endpoint to upload photos via multipart/form-data."""

    url = f"/api/{DOMAIN}/photos/upload"
    name = f"api:{DOMAIN}:photos:upload"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Handle multipart photo upload."""
        hass: HomeAssistant = request.app["hass"]
        coordinator = _get_coordinator(hass)
        if coordinator is None:
            return web.json_response({"error": "iGro not initialized"}, status=503)

        try:
            reader = await request.multipart()
        except Exception as err:
            return web.json_response({"error": f"Invalid multipart payload: {err}"}, status=400)

        file_bytes: bytes | None = None
        orig_filename = "upload.jpg"
        mime_type = "image/jpeg"
        fields: dict[str, str] = {}

        while True:
            part = await reader.next()
            if part is None:
                break
            if part.name == "file":
                orig_filename = part.filename or "upload.jpg"
                mime_type = part.headers.get("Content-Type", "image/jpeg")
                chunks = bytearray()
                while True:
                    chunk = await part.read_chunk(65536)
                    if not chunk:
                        break
                    chunks.extend(chunk)
                    if len(chunks) > MAX_PHOTO_SIZE_BYTES:
                        return web.json_response(
                            {"error": "File exceeds 15 MB limit"}, status=413
                        )
                file_bytes = bytes(chunks)
            elif part.name:
                fields[part.name] = (await part.text()).strip()

        if file_bytes is None:
            return web.json_response({"error": "Missing 'file' field"}, status=400)

        ext = Path(orig_filename).suffix.lower()
        if not ext or ext not in ALLOWED_IMAGE_EXTENSIONS:
            guessed = mimetypes.guess_extension(mime_type) or ".jpg"
            ext = ".jpg" if guessed == ".jpe" else guessed

        try:
            record = await async_save_photo_bytes(
                hass,
                coordinator,
                file_bytes,
                ext,
                mime_type,
                plant_id=fields.get("plant_id") or None,
                environment_id=fields.get("environment_id") or None,
                log_id=fields.get("log_id") or None,
                stage=fields.get("stage") or None,
                caption=fields.get("caption") or None,
                source="upload",
                taken_at=fields.get("taken_at") or None,
            )
        except ValueError as err:
            return web.json_response({"error": str(err)}, status=400)

        return web.json_response({"photo": record}, status=201)


class IGroPhotoServeView(HomeAssistantView):
    """Serve stored photos via unguessable per-photo token or authenticated session."""

    url = f"/api/{DOMAIN}/photos/{{photo_id}}"
    name = f"api:{DOMAIN}:photos:serve"
    requires_auth = False

    async def get(self, request: web.Request, photo_id: str) -> web.StreamResponse:
        """Serve a stored photo file."""
        hass: HomeAssistant = request.app["hass"]
        coordinator = _get_coordinator(hass)
        if coordinator is None:
            return web.Response(status=503, text="iGro not initialized")

        record = await coordinator.db.async_get_photo(photo_id)
        if record is None:
            return web.Response(status=404, text="Photo not found")

        is_authenticated = bool(request.get("hass_user"))
        provided_token = request.query.get("token", "")
        expected_token = record.get("access_token", "")
        token_valid = bool(
            provided_token
            and expected_token
            and hmac.compare_digest(provided_token, expected_token)
        )

        if not (is_authenticated or token_valid):
            return web.Response(status=401, text="Unauthorized")

        safe_name = Path(record["filename"]).name
        file_path = (coordinator.media_dir / safe_name).resolve()
        try:
            file_path.relative_to(coordinator.media_dir.resolve())
        except ValueError:
            return web.Response(status=403, text="Forbidden")

        if not file_path.is_file():
            return web.Response(status=404, text="Photo file missing")

        return web.FileResponse(
            path=file_path,
            headers={
                "Content-Type": record.get("mime_type") or "image/jpeg",
                "Cache-Control": "private, max-age=3600",
            },
        )
