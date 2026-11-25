"""Unit tests for reminders, recurring schedules, and calendar event projection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from custom_components.igro.calendar import build_calendar_events_in_window
from custom_components.igro.database import IGroDatabase


@pytest.mark.asyncio
async def test_reminder_crud_and_recurring_completion_with_preset(
    tmp_path: Path,
) -> None:
    """Completing a recurring reminder advances due_at and auto-logs preset nutrients."""
    db = IGroDatabase(tmp_path / "igro_reminders.db")
    await db.async_initialize()

    env = await db.async_create_environment({"name": "4x4 Tent"})
    plant = await db.async_create_plant(
        {"name": "Blue Dream #1", "environment_id": env["id"], "stage": "vegetative"}
    )
    preset = await db.async_create_nutrient_preset(
        {
            "name": "Veg Base",
            "stage": "vegetative",
            "target_ph": 6.1,
            "target_ec": 1.4,
            "target_ppm": 700,
            "nutrients": [{"name": "Grow A", "amount": "2", "unit": "mL/L"}],
        }
    )

    due_start = "2026-04-01T09:00:00+00:00"
    rem = await db.async_create_reminder(
        {
            "title": "Feed Veg Base",
            "action_type": "feed",
            "plant_id": plant["id"],
            "due_at": due_start,
            "recurrence_days": 3,
            "moisture_threshold": 30,
            "preset_id": preset["id"],
            "auto_log_on_complete": True,
            "notes": "Water until 15% runoff",
        }
    )
    assert rem["environment_id"] == env["id"]
    assert rem["recurrence_days"] == 3
    assert rem["moisture_threshold"] == 30.0
    assert rem["status"] == "active"

    # Mark notified and ensure timestamp persists
    await db.async_mark_reminders_notified([rem["id"]], now_iso="2026-04-01T09:05:00+00:00")
    listed = await db.async_list_reminders(plant_id=plant["id"])
    assert len(listed) == 1
    assert listed[0]["last_notified_at"] == "2026-04-01T09:05:00+00:00"

    # Complete recurring reminder -> advances due_at +3 days, clears last_notified_at, creates log
    res = await db.async_complete_reminder(
        rem["id"], now_iso="2026-04-01T10:00:00+00:00"
    )
    assert res is not None
    updated = res["reminder"]
    assert updated["status"] == "active"
    assert updated["due_at"] == "2026-04-04T10:00:00+00:00"
    assert updated["last_completed_at"] == "2026-04-01T10:00:00+00:00"
    assert updated["last_notified_at"] is None

    created_log = res["created_log"]
    assert created_log is not None
    assert created_log["log_type"] == "feed"
    assert created_log["plant_id"] == plant["id"]
    assert created_log["ph"] == 6.1
    assert created_log["ec"] == 1.4
    assert created_log["ppm"] == 700
    assert created_log["nutrients"] == [{"name": "Grow A", "amount": "2", "unit": "mL/L"}]

    # Update & delete
    edited = await db.async_update_reminder(
        rem["id"], {"title": "Feed Veg Base v2", "recurrence_days": 4, "status": "paused"}
    )
    assert edited is not None
    assert edited["title"] == "Feed Veg Base v2"
    assert edited["recurrence_days"] == 4
    assert edited["status"] == "paused"

    deleted = await db.async_delete_reminder(rem["id"])
    assert deleted is True
    assert await db.async_list_reminders() == []


@pytest.mark.asyncio
async def test_one_time_reminder_completion_without_auto_log(tmp_path: Path) -> None:
    """One-time reminder marks itself completed and respects create_log=False."""
    db = IGroDatabase(tmp_path / "igro_onetime.db")
    await db.async_initialize()

    rem = await db.async_create_reminder(
        {
            "title": "Burp Cure Jars",
            "action_type": "burp_jars",
            "due_at": "2026-05-10T18:00:00+00:00",
            "auto_log_on_complete": False,
        }
    )
    res = await db.async_complete_reminder(
        rem["id"], now_iso="2026-05-10T18:15:00+00:00"
    )
    assert res is not None
    assert res["reminder"]["status"] == "completed"
    assert res["created_log"] is None


def test_build_calendar_events_in_window_projects_recurring_and_milestones() -> None:
    """Calendar builder projects recurring reminders, stage transitions, and planned logs."""
    window_start = datetime(2026, 6, 1, 0, 0, tzinfo=UTC)
    window_end = datetime(2026, 6, 10, 23, 59, tzinfo=UTC)

    data = {
        "reminders": [
            {
                "id": "r1",
                "title": "Water Tent",
                "action_type": "water",
                "plant_name": "Northern Lights",
                "due_at": "2026-06-02T09:00:00+00:00",
                "recurrence_days": 3,
                "status": "active",
                "notes": "2L pH 6.2",
            },
            {
                "id": "r2",
                "title": "Paused Task",
                "action_type": "note",
                "due_at": "2026-06-03T09:00:00+00:00",
                "status": "paused",
            },
        ],
        "scheduled_stage_changes": [
            {
                "id": "sc1",
                "plant_name": "Northern Lights",
                "target_stage": "flowering",
                "scheduled_for": "2026-06-06T12:00:00+00:00",
                "notes": "Flip 12/12",
            }
        ],
        "planned_logs": [
            {
                "id": "l1",
                "plant_name": "Northern Lights",
                "log_type": "defoliation",
                "title": "Lollipopping",
                "logged_at": "2026-06-07T15:00:00+00:00",
                "notes": "Clean lower canopy",
            },
            {
                "id": "l2",
                "plant_name": "Northern Lights",
                "log_type": "flush",
                "title": "Out of Window",
                "logged_at": "2026-07-01T15:00:00+00:00",
            },
        ],
    }

    events = build_calendar_events_in_window(data, window_start, window_end)
    # Recurring r1 hits June 2, 5, 8 (3 occurrences) + sc1 (June 6) + l1 (June 7) = 5 events
    assert len(events) == 5
    summaries = [ev.summary for ev in events]
    assert summaries.count("[Northern Lights] Water Tent") == 3
    assert "[Northern Lights] Stage -> Flowering" in summaries
    assert "[Northern Lights] Planned: Lollipopping" in summaries
    # Sorted chronologically
    assert all(events[i].start <= events[i + 1].start for i in range(len(events) - 1))
    # Each event has positive duration
    assert all(ev.end > ev.start for ev in events)
    assert events[0].start == datetime(2026, 6, 2, 9, 0, tzinfo=UTC)
    assert events[0].end == datetime(2026, 6, 2, 9, 0, tzinfo=UTC) + timedelta(minutes=30)
