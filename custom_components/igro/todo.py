"""To-Do list platform exposing iGro reminders as actionable HA tasks."""

from __future__ import annotations

from datetime import date, datetime

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .calculations import parse_iso_datetime
from .const import DOMAIN
from .coordinator import IGroCoordinator
from .entity import IGroSummaryEntity


def _to_todo_due(iso_ts: str | None) -> date | datetime | None:
    dt = parse_iso_datetime(iso_ts)
    return dt


class IGroTasksTodoList(IGroSummaryEntity, TodoListEntity):
    """Home Assistant To-Do list backed by iGro reminders."""

    _attr_name = "Grow Tasks"
    _attr_icon = "mdi:clipboard-check-outline"
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        | TodoListEntityFeature.SET_DUE_DATE_ON_ITEM
        | TodoListEntityFeature.SET_DUE_DATETIME_ON_ITEM
        | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
    )

    def __init__(self, coordinator: IGroCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_tasks_todo"

    @property
    def todo_items(self) -> list[TodoItem]:
        """Return active and completed iGro reminders as TodoItems."""
        reminders = (self.coordinator.data or {}).get("reminders", [])
        items: list[TodoItem] = []
        for rem in reminders:
            if rem.get("status") == "paused":
                continue
            prefix = f"[{rem['plant_name']}] " if rem.get("plant_name") else ""
            status = (
                TodoItemStatus.COMPLETED
                if rem.get("status") == "completed"
                else TodoItemStatus.NEEDS_ACTION
            )
            desc_lines = []
            if rem.get("recurrence_days"):
                desc_lines.append(f"Repeats every {rem['recurrence_days']} days")
            if rem.get("moisture_threshold") is not None:
                desc_lines.append(f"Moisture trigger < {rem['moisture_threshold']}%")
            if rem.get("notes"):
                desc_lines.append(rem["notes"])
            items.append(
                TodoItem(
                    uid=rem["id"],
                    summary=f"{prefix}{rem['title']}",
                    status=status,
                    due=_to_todo_due(rem.get("due_at")),
                    description="\n".join(desc_lines) or None,
                )
            )
        return items

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Create a new reminder from Home Assistant's To-Do UI."""
        due_iso = item.due.isoformat() if item.due else None
        await self.coordinator.db.async_create_reminder(
            {
                "title": item.summary or "Grow Task",
                "action_type": "note",
                "due_at": due_iso,
                "notes": item.description,
                "auto_log_on_complete": False,
            }
        )
        await self.coordinator.async_request_refresh()

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Update or complete an iGro reminder from Home Assistant's To-Do UI."""
        if not item.uid:
            return
        if item.status == TodoItemStatus.COMPLETED:
            await self.coordinator.db.async_complete_reminder(item.uid)
        else:
            updates: dict[str, object] = {"status": "active"}
            if item.summary:
                updates["title"] = item.summary
            if item.due is not None:
                updates["due_at"] = item.due.isoformat()
            if item.description is not None:
                updates["notes"] = item.description
            await self.coordinator.db.async_update_reminder(item.uid, updates)
        await self.coordinator.async_request_refresh()

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Delete reminders removed from the HA To-Do list."""
        for uid in uids:
            await self.coordinator.db.async_delete_reminder(uid)
        await self.coordinator.async_request_refresh()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the iGro todo platform."""
    coordinator: IGroCoordinator = hass.data[DOMAIN]["coordinator"]
    async_add_entities([IGroTasksTodoList(coordinator)])
