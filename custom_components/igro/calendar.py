"""Calendar platform exposing iGro reminders, planned logs, and stage milestones."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .calculations import parse_iso_datetime
from .const import DOMAIN, STAGE_LABELS
from .coordinator import IGroCoordinator
from .entity import IGroSummaryEntity


def build_calendar_events_in_window(
    data: dict[str, Any],
    start_date: datetime,
    end_date: datetime,
) -> list[CalendarEvent]:
    """Build all iGro CalendarEvent items overlapping [start_date, end_date]."""
    start_utc = (
        start_date.astimezone(UTC)
        if start_date.tzinfo
        else start_date.replace(tzinfo=UTC)
    )
    end_utc = (
        end_date.astimezone(UTC) if end_date.tzinfo else end_date.replace(tzinfo=UTC)
    )

    events: list[CalendarEvent] = []

    # 1. Active reminders (including projected recurring instances within window)
    for rem in data.get("reminders", []):
        if rem.get("status") != "active":
            continue
        due_dt = parse_iso_datetime(rem.get("due_at"))
        if due_dt is None:
            continue
        rec_days = rem.get("recurrence_days")
        prefix = f"[{rem['plant_name']}] " if rem.get("plant_name") else ""
        summary = f"{prefix}{rem['title']}"
        desc_parts = [f"Action: {rem.get('action_type', 'task')}"]
        if rem.get("notes"):
            desc_parts.append(rem["notes"])
        description = "\n".join(desc_parts)

        occurrences: list[datetime] = []
        if rec_days and int(rec_days) > 0:
            step = timedelta(days=int(rec_days))
            cur = due_dt
            # Advance to window start if due_dt is far in the past
            if cur < start_utc:
                delta_days = (start_utc - cur).days
                skips = max(0, delta_days // int(rec_days))
                cur = cur + timedelta(days=skips * int(rec_days))
                if cur < start_utc:
                    cur += step
            # Cap iterations to avoid runaway loops on tiny intervals
            count = 0
            while cur <= end_utc and count < 120:
                occurrences.append(cur)
                cur += step
                count += 1
        elif start_utc <= due_dt <= end_utc:
            occurrences.append(due_dt)

        for occ in occurrences:
            events.append(
                CalendarEvent(
                    start=occ,
                    end=occ + timedelta(minutes=30),
                    summary=summary,
                    description=description,
                    uid=f"igro_rem_{rem['id']}_{occ.strftime('%Y%m%d')}",
                )
            )

    # 2. Pending scheduled stage transitions
    for sc in data.get("scheduled_stage_changes", []):
        sched_dt = parse_iso_datetime(sc.get("scheduled_for"))
        if sched_dt is None or not (start_utc <= sched_dt <= end_utc):
            continue
        stage_label = STAGE_LABELS.get(sc["target_stage"], sc["target_stage"])
        prefix = f"[{sc['plant_name']}] " if sc.get("plant_name") else ""
        events.append(
            CalendarEvent(
                start=sched_dt,
                end=sched_dt + timedelta(hours=1),
                summary=f"{prefix}Stage -> {stage_label}",
                description=sc.get("notes") or "Scheduled grow stage transition",
                uid=f"igro_stage_{sc['id']}",
            )
        )

    # 3. Planned future journal logs
    for lg in data.get("planned_logs", []):
        log_dt = parse_iso_datetime(lg.get("logged_at"))
        if log_dt is None or not (start_utc <= log_dt <= end_utc):
            continue
        prefix = f"[{lg['plant_name']}] " if lg.get("plant_name") else ""
        title = lg.get("title") or lg.get("log_type", "task").replace("_", " ").title()
        events.append(
            CalendarEvent(
                start=log_dt,
                end=log_dt + timedelta(minutes=30),
                summary=f"{prefix}Planned: {title}",
                description=lg.get("notes") or "",
                uid=f"igro_log_{lg['id']}",
            )
        )

    events.sort(key=lambda ev: ev.start)
    return events


class IGroScheduleCalendar(IGroSummaryEntity, CalendarEntity):
    """Home Assistant Calendar entity for all iGro schedules & milestones."""

    _attr_name = "Grow Schedule"
    _attr_icon = "mdi:calendar-month"

    def __init__(self, coordinator: IGroCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_schedule_calendar"

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next upcoming grow event."""
        now = datetime.now(UTC)
        events = build_calendar_events_in_window(
            self.coordinator.data or {},
            now - timedelta(days=1),
            now + timedelta(days=90),
        )
        for ev in events:
            if ev.end >= now:
                return ev
        return None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return calendar events within the requested date range."""
        return build_calendar_events_in_window(
            self.coordinator.data or {}, start_date, end_date
        )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the iGro calendar platform."""
    coordinator: IGroCoordinator = hass.data[DOMAIN]["coordinator"]
    async_add_entities([IGroScheduleCalendar(coordinator)])
