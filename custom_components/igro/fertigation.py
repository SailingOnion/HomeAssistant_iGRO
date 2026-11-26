"""Fertigation scheduling, ordered batch-mixing, and safety interlock controller."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, time, timedelta
import logging
from typing import TYPE_CHECKING, Any

from .calculations import parse_iso_datetime, scale_nutrients_for_volume
from .const import (
    DOSING_ROLE_DEFAULT_ORDER,
    EVENT_DOSING_RUN_COMPLETED,
    EVENT_DOSING_SAFETY_ABORT,
    EVENT_FERTIGATION_EMERGENCY_STOP,
    EVENT_FERTIGATION_SHOT,
    EVENT_LOG_CREATED,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .coordinator import IGroCoordinator

_LOGGER = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Pure calculation, scheduling & safety validation helpers
# ------------------------------------------------------------------
def _parse_hhmm(raw: str | None, default: time) -> time:
    if not raw:
        return default
    try:
        parts = raw.strip().split(":")
        return time(hour=int(parts[0]) % 24, minute=int(parts[1]) % 60)
    except (ValueError, IndexError):
        return default


def compute_high_frequency_shot_times(
    window_start: str | None,
    window_end: str | None,
    feeds_per_day: int,
    p1_ramp_shots: int = 2,
    p1_interval_min: int = 30,
    p3_dryback_cutoff_min: int = 120,
) -> list[str]:
    """Compute daily HH:MM shot times supporting P1 ramp, P2 maintenance & P3 cutoff.

    Returns sorted unique `"HH:MM"` strings inside `[window_start, effective_end]`.
    """
    n = max(1, min(int(feeds_per_day or 1), 24))
    start_t = _parse_hhmm(window_start, time(8, 0))
    end_t = _parse_hhmm(window_end, time(20, 0))

    start_min = start_t.hour * 60 + start_t.minute
    end_min = end_t.hour * 60 + end_t.minute
    if end_min <= start_min:
        end_min += 24 * 60

    cutoff = max(0, int(p3_dryback_cutoff_min or 0))
    effective_end = max(start_min + 15, end_min - cutoff)
    total_span = effective_end - start_min

    if n == 1:
        m = start_min % (24 * 60)
        return [f"{m // 60:02d}:{m % 60:02d}"]

    minutes_list: list[int] = []
    ramp_count = max(0, min(int(p1_ramp_shots or 0), n))
    ramp_step = max(5, int(p1_interval_min or 30))

    # P1 ramp shots at the start of the active window
    if ramp_count > 0 and ramp_count < n and (ramp_count * ramp_step) < total_span:
        for i in range(ramp_count):
            minutes_list.append(start_min + i * ramp_step)
        p2_remaining = n - ramp_count
        p2_start = minutes_list[-1] + ramp_step
        p2_span = max(0, effective_end - p2_start)
        if p2_remaining == 1:
            minutes_list.append(effective_end)
        else:
            step = p2_span / (p2_remaining - 1) if p2_remaining > 1 else 0
            for j in range(p2_remaining):
                minutes_list.append(round(p2_start + j * step))
    else:
        step = total_span / (n - 1)
        for i in range(n):
            minutes_list.append(round(start_min + i * step))

    formatted: list[str] = []
    seen: set[str] = set()
    for raw_m in minutes_list:
        m = raw_m % (24 * 60)
        label = f"{m // 60:02d}:{m % 60:02d}"
        if label not in seen:
            seen.add(label)
            formatted.append(label)
    return formatted


def compute_next_fertigation_time(
    schedule: dict[str, Any], now: datetime | None = None
) -> str | None:
    """Compute the next scheduled fertigation timestamp (UTC ISO-8601)."""
    if schedule.get("mode") != "scheduled":
        return None
    ref = (now or datetime.now(UTC)).astimezone(UTC)
    sched_type = schedule.get("schedule_type") or "high_frequency"

    if sched_type == "interval":
        hours = float(schedule.get("interval_hours") or 6.0)
        last_dt = parse_iso_datetime(schedule.get("last_fed_at"))
        if last_dt is None:
            return ref.replace(microsecond=0).isoformat()
        nxt = last_dt + timedelta(hours=max(0.25, hours))
        return nxt.replace(microsecond=0).isoformat()

    if sched_type == "fixed_times":
        times = schedule.get("fixed_times") or []
    else:
        times = compute_high_frequency_shot_times(
            schedule.get("window_start"),
            schedule.get("window_end"),
            int(schedule.get("feeds_per_day") or 4),
            int(schedule.get("p1_ramp_shots") or 2),
            int(schedule.get("p1_interval_min") or 30),
            int(schedule.get("p3_dryback_cutoff_min") or 120),
        )

    if not times:
        return None

    candidates: list[datetime] = []
    for day_offset in (0, 1):
        base_day = (ref + timedelta(days=day_offset)).date()
        for hhmm in times:
            t = _parse_hhmm(hhmm, time(8, 0))
            cand = datetime.combine(base_day, t, tzinfo=UTC)
            if cand >= ref - timedelta(seconds=30):
                candidates.append(cand)
    if not candidates:
        return None
    candidates.sort()
    return candidates[0].replace(microsecond=0).isoformat()


def validate_fertigation_safety(
    schedule: dict[str, Any],
    shot_duration_s: float,
    daily_volume_ml: float,
    *,
    leak_detected: bool = False,
    reservoir_low: bool = False,
) -> tuple[bool, str | None, float]:
    """Validate fertigation shot against safety interlocks & volume caps.

    Returns `(allowed, block_reason, computed_volume_ml)`.
    """
    flow_rate = max(0.1, float(schedule.get("flow_rate_ml_s") or 10.0))
    volume_ml = round(shot_duration_s * flow_rate, 1)

    if leak_detected:
        return False, "Leak detector triggered — emergency stop active", volume_ml
    if reservoir_low:
        return False, "Reservoir low-level interlock triggered (dry-run protection)", volume_ml

    max_shot_s = float(schedule.get("max_shot_duration_s") or 60.0)
    if shot_duration_s <= 0:
        return False, "Shot duration must be greater than 0 seconds", volume_ml
    if shot_duration_s > max_shot_s:
        return (
            False,
            f"Shot duration ({shot_duration_s:.1f}s) exceeds max safety cap ({max_shot_s:.1f}s)",
            volume_ml,
        )

    max_daily_ml = float(schedule.get("max_daily_volume_ml") or 4000.0)
    if (daily_volume_ml + volume_ml) > max_daily_ml:
        return (
            False,
            f"Daily volume cap exceeded ({daily_volume_ml + volume_ml:.0f} mL > {max_daily_ml:.0f} mL)",
            volume_ml,
        )

    return True, None, volume_ml


def evaluate_probe_sanity(
    ph: float | None,
    ec: float | None,
    reservoir: dict[str, Any],
    *,
    require_ph: bool = False,
    require_ec: bool = False,
) -> tuple[bool, str | None]:
    """Check whether pH and EC probe readings are within plausible safe bounds."""
    ph_min = float(reservoir.get("ph_min_bound") or 3.5)
    ph_max = float(reservoir.get("ph_max_bound") or 9.5)
    ec_max = float(reservoir.get("ec_max_bound") or 5.0)

    if require_ph and ph is None:
        return False, "pH sensor reading unavailable"
    if ph is not None and not (ph_min <= ph <= ph_max):
        return (
            False,
            f"pH probe reading ({ph:.2f}) out of safe bounds ({ph_min}–{ph_max})",
        )

    if require_ec and ec is None:
        return False, "EC sensor reading unavailable"
    if ec is not None and not (0.0 <= ec <= ec_max):
        return (
            False,
            f"EC probe reading ({ec:.2f} mS/cm) out of safe bounds (0.0–{ec_max})",
        )

    return True, None


def plan_ordered_batch_mix(
    preset: dict[str, Any],
    target_volume_l: float,
    channels: list[dict[str, Any]],
    daily_dosed_by_channel: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Compute ordered dosing steps for mixing a Nutrient Preset into a reservoir.

    Matches preset nutrients to enabled dosing channels, scales dosages to
    `target_volume_l`, sorts strictly by `mix_order` (Silica -> Cal-Mag -> Base A ->
    Base B -> Bloom -> Additive), and validates per-cycle & daily dose caps.
    """
    daily_map = daily_dosed_by_channel or {}
    water_ml = max(0.0, float(target_volume_l)) * 1000.0
    scaled = scale_nutrients_for_volume(preset.get("nutrients") or [], water_ml)

    enabled_channels = [ch for ch in channels if ch.get("enabled", 1)]
    channel_by_name: dict[str, dict[str, Any]] = {}
    for ch in enabled_channels:
        for key_field in ("nutrient_name", "name"):
            val = (ch.get(key_field) or "").strip().lower()
            if val and val not in channel_by_name:
                channel_by_name[val] = ch

    steps: list[dict[str, Any]] = []
    unmatched: list[str] = []
    errors: list[str] = []
    warnings: list[str] = []

    for item in scaled:
        nut_name = (item.get("name") or "").strip()
        if not nut_name:
            continue
        ch = channel_by_name.get(nut_name.lower())
        if ch is None:
            # Fuzzy substring fallback
            for cand_name, cand_ch in channel_by_name.items():
                if nut_name.lower() in cand_name or cand_name in nut_name.lower():
                    ch = cand_ch
                    break
        if ch is None:
            unmatched.append(nut_name)
            continue

        dose_ml = float(item.get("total_amount") or item.get("amount") or 0.0)
        if dose_ml <= 0:
            continue

        max_cycle = float(ch.get("max_dose_per_cycle_ml") or 50.0)
        max_daily = float(ch.get("max_daily_dose_ml") or 200.0)
        already_today = float(daily_map.get(ch["id"], 0.0))

        if dose_ml > max_cycle:
            errors.append(
                f"{ch['name']}: required {dose_ml:.1f} mL exceeds max cycle cap ({max_cycle:.1f} mL)"
            )
        if already_today + dose_ml > max_daily:
            errors.append(
                f"{ch['name']}: daily total {already_today + dose_ml:.1f} mL exceeds cap ({max_daily:.1f} mL)"
            )
        rem_ml = ch.get("bottle_remaining_ml")
        if rem_ml is not None and float(rem_ml) < dose_ml:
            warnings.append(
                f"{ch['name']}: bottle low ({float(rem_ml):.0f} mL left, needs {dose_ml:.1f} mL)"
            )

        order = int(
            ch.get("mix_order")
            if ch.get("mix_order") is not None
            else DOSING_ROLE_DEFAULT_ORDER.get(ch.get("role") or "additive", 60)
        )
        flow = max(0.05, float(ch.get("flow_rate_ml_s") or 1.0))
        steps.append(
            {
                "channel_id": ch["id"],
                "channel_name": ch["name"],
                "role": ch.get("role") or "additive",
                "nutrient_name": nut_name,
                "mix_order": order,
                "dose_ml": round(dose_ml, 2),
                "duration_s": round(dose_ml / flow, 2),
                "stir_delay_s": int(ch.get("stir_delay_s") or 30),
            }
        )

    steps.sort(key=lambda s: (s["mix_order"], s["channel_name"].lower()))
    return {
        "valid": len(errors) == 0 and len(steps) > 0,
        "steps": steps,
        "unmatched_nutrients": unmatched,
        "errors": errors,
        "warnings": warnings,
        "total_ml": round(sum(s["dose_ml"] for s in steps), 2),
    }


def compute_auto_trim_dose(
    reservoir: dict[str, Any],
    channels: list[dict[str, Any]],
    daily_dosed_by_channel: dict[str, float],
    current_ph: float | None,
    current_ec: float | None,
) -> dict[str, Any] | None:
    """Compute a safe proportional micro-dose step for closed-loop pH/EC trimming.

    Returns a dict `{channel, dose_ml, run_type, reason}` or `None` if no trim needed.
    Raises `ValueError` if a safety guardrail / probe sanity check fails.
    """
    ok, reason = evaluate_probe_sanity(current_ph, current_ec, reservoir)
    if not ok:
        raise ValueError(reason or "Probe sanity check failed")

    volume_l = max(1.0, float(reservoir.get("current_volume_l") or reservoir.get("capacity_l") or 20.0))
    enabled = [ch for ch in channels if ch.get("enabled", 1)]

    # 1. Check pH trim first (small proportional micro-pulses: 0.05 mL/L per 0.5 pH delta)
    target_ph = reservoir.get("target_ph")
    ph_tol = float(reservoir.get("ph_tolerance") or 0.15)
    if current_ph is not None and target_ph is not None:
        delta = current_ph - float(target_ph)
        if abs(delta) > ph_tol:
            needed_role = "ph_down" if delta > 0 else "ph_up"
            ch = next((c for c in enabled if c.get("role") == needed_role), None)
            if ch is not None:
                raw_ml = max(0.5, min(volume_l * 0.08 * abs(delta), float(ch.get("max_dose_per_cycle_ml") or 10.0)))
                dose_ml = round(raw_ml, 2)
                daily = float(daily_dosed_by_channel.get(ch["id"], 0.0))
                max_daily = float(ch.get("max_daily_dose_ml") or 50.0)
                if daily + dose_ml > max_daily:
                    raise ValueError(
                        f"Auto-pH lockout: {ch['name']} daily cap ({max_daily} mL) reached"
                    )
                return {
                    "channel": ch,
                    "dose_ml": dose_ml,
                    "run_type": "auto_ph_trim",
                    "reason": f"pH {current_ph:.2f} vs target {float(target_ph):.2f}",
                }

    # 2. Check EC top-up trim if EC is below target - tolerance
    target_ec = reservoir.get("target_ec")
    ec_tol = float(reservoir.get("ec_tolerance") or 0.1)
    if current_ec is not None and target_ec is not None:
        ec_deficit = float(target_ec) - current_ec
        if ec_deficit > ec_tol:
            base_channels = [
                c
                for c in enabled
                if c.get("role") in ("base_a", "base_b", "bloom_pk")
            ]
            base_channels.sort(key=lambda c: int(c.get("mix_order") or 30))
            if base_channels:
                ch = base_channels[0]
                raw_ml = max(1.0, min(volume_l * 0.4 * ec_deficit, float(ch.get("max_dose_per_cycle_ml") or 20.0)))
                dose_ml = round(raw_ml, 2)
                daily = float(daily_dosed_by_channel.get(ch["id"], 0.0))
                max_daily = float(ch.get("max_daily_dose_ml") or 200.0)
                if daily + dose_ml > max_daily:
                    raise ValueError(
                        f"Auto-EC lockout: {ch['name']} daily cap ({max_daily} mL) reached"
                    )
                return {
                    "channel": ch,
                    "dose_ml": dose_ml,
                    "run_type": "auto_ec_trim",
                    "reason": f"EC {current_ec:.2f} vs target {float(target_ec):.2f}",
                }

    return None


# ------------------------------------------------------------------
# Async Home Assistant Hardware Execution Controller
# ------------------------------------------------------------------
class IGroFertigationController:
    """Executes safe fertigation shots, ordered batch mixes & emergency stops."""

    def __init__(self, hass: HomeAssistant, coordinator: IGroCoordinator) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self._plant_locks: dict[str, asyncio.Lock] = {}
        self._reservoir_locks: dict[str, asyncio.Lock] = {}
        self._active_tasks: set[asyncio.Task[Any]] = set()
        self._last_trim_at: dict[str, datetime] = {}

    def _is_binary_on(self, entity_id: str | None) -> bool:
        if not entity_id:
            return False
        st = self.hass.states.get(entity_id)
        return st is not None and st.state in ("on", "true", "wet", "problem")

    async def _set_switch(self, entity_id: str | None, turn_on: bool) -> None:
        if not entity_id:
            return
        domain = entity_id.split(".", 1)[0]
        service = "turn_on" if turn_on else "turn_off"
        if domain in ("switch", "valve", "light", "fan", "input_boolean"):
            if domain == "valve":
                service = "open_valve" if turn_on else "close_valve"
            await self.hass.services.async_call(
                domain, service, {"entity_id": entity_id}, blocking=True
            )
        else:
            await self.hass.services.async_call(
                "homeassistant", service, {"entity_id": entity_id}, blocking=True
            )

    async def _set_number(self, entity_id: str | None, value: float) -> None:
        if not entity_id:
            return
        domain = entity_id.split(".", 1)[0]
        if domain in ("number", "input_number"):
            await self.hass.services.async_call(
                domain,
                "set_value",
                {"entity_id": entity_id, "value": value},
                blocking=True,
            )

    async def async_emergency_stop(
        self, reason: str = "Manual emergency stop"
    ) -> dict[str, Any]:
        """Immediately halt all pumps, valves, dosers and lock out automation."""
        _LOGGER.error("iGro EMERGENCY STOP triggered: %s", reason)
        data = self.coordinator.data or {}
        stopped_entities: set[str] = set()

        for res in data.get("reservoirs", {}).values():
            for key in ("circ_pump_entity_id", "ro_fill_entity_id", "master_feed_pump_entity_id"):
                eid = res.get(key)
                if eid:
                    stopped_entities.add(eid)
            await self.coordinator.db.async_update_reservoir(
                res["id"], {"status": "emergency_stop", "last_error": reason, "auto_trim_enabled": 0}
            )

        for ch in data.get("dosing_channels", []):
            if ch.get("entity_id") and (ch.get("control_type") or "switch") == "switch":
                stopped_entities.add(ch["entity_id"])

        for sched in data.get("fertigation_schedules", {}).values():
            for key in ("pump_entity_id", "valve_entity_id"):
                eid = sched.get(key)
                if eid:
                    stopped_entities.add(eid)
            if sched.get("mode") != "off":
                await self.coordinator.db.async_upsert_fertigation_schedule(
                    sched["plant_id"], {"mode": "off", "last_error": reason}
                )

        for eid in stopped_entities:
            try:
                await self._set_switch(eid, False)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Failed to turn off %s during emergency stop: %s", eid, err)

        self.hass.bus.async_fire(
            EVENT_FERTIGATION_EMERGENCY_STOP,
            {"reason": reason, "stopped_entities": sorted(stopped_entities)},
        )
        await self.coordinator.async_request_refresh()
        return {"stopped": True, "reason": reason, "stopped_entities": sorted(stopped_entities)}

    async def async_run_fertigation_shot(
        self,
        plant_id: str,
        *,
        trigger_type: str = "manual",
        duration_s: float | None = None,
    ) -> dict[str, Any]:
        """Execute a safe timed fertigation shot for a plant and log to journal."""
        lock = self._plant_locks.setdefault(plant_id, asyncio.Lock())
        async with lock:
            data = self.coordinator.data or {}
            sched = data.get("fertigation_schedules", {}).get(plant_id)
            if not sched:
                raise ValueError(f"No fertigation schedule configured for plant {plant_id}")

            res = (
                data.get("reservoirs", {}).get(sched["reservoir_id"])
                if sched.get("reservoir_id")
                else None
            )
            leak_detected = self._is_binary_on(sched.get("leak_entity_id")) or (
                res is not None and self._is_binary_on(res.get("leak_entity_id"))
            )
            reservoir_low = res is not None and self._is_binary_on(
                res.get("low_level_entity_id")
            )

            flow_rate = max(0.1, float(sched.get("flow_rate_ml_s") or 10.0))
            if duration_s is not None:
                shot_s = float(duration_s)
            elif sched.get("target_shot_ml"):
                shot_s = round(float(sched["target_shot_ml"]) / flow_rate, 2)
            else:
                shot_s = float(sched.get("shot_duration_s") or 15.0)

            daily_ml = await self.coordinator.db.async_get_daily_fertigation_volume(plant_id)
            allowed, block_reason, volume_ml = validate_fertigation_safety(
                sched,
                shot_s,
                daily_ml,
                leak_detected=leak_detected,
                reservoir_low=reservoir_low,
            )

            res_ph = res.get("ph") if res else None
            res_ec = res.get("ec") if res else None

            if not allowed:
                event = await self.coordinator.db.async_record_fertigation_event(
                    {
                        "plant_id": plant_id,
                        "schedule_id": sched["id"],
                        "reservoir_id": sched.get("reservoir_id"),
                        "trigger_type": trigger_type,
                        "duration_s": shot_s,
                        "volume_ml": 0.0,
                        "status": "blocked",
                        "block_reason": block_reason,
                        "reservoir_ph": res_ph,
                        "reservoir_ec": res_ec,
                    }
                )
                await self.coordinator.db.async_upsert_fertigation_schedule(
                    plant_id, {"last_error": block_reason}
                )
                if leak_detected:
                    await self.async_emergency_stop(block_reason or "Leak detected")
                else:
                    await self.coordinator.async_request_refresh()
                return {"event": event, "blocked": True, "reason": block_reason}

            # Optional ESPHome hardware watchdog sync
            watchdog_eid = sched.get("esphome_watchdog_entity_id")
            if watchdog_eid:
                try:
                    await self._set_number(
                        watchdog_eid,
                        min(float(sched.get("max_shot_duration_s") or 60.0), shot_s + 5.0),
                    )
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Watchdog sync failed on %s: %s", watchdog_eid, err)

            use_shared = bool(sched.get("use_shared_pump")) and bool(
                res and res.get("master_feed_pump_entity_id")
            )
            valve_eid = sched.get("valve_entity_id") or (
                sched.get("pump_entity_id") if use_shared else None
            )
            pump_eid = (
                res["master_feed_pump_entity_id"]
                if use_shared and res
                else sched.get("pump_entity_id")
            )

            # Safe valve-before-pump / pump-off-before-valve-close sequencing
            try:
                if valve_eid:
                    await self._set_switch(valve_eid, True)
                    await asyncio.sleep(0.5)
                if pump_eid:
                    await self._set_switch(pump_eid, True)
                await asyncio.sleep(shot_s)
            finally:
                if pump_eid:
                    try:
                        await self._set_switch(pump_eid, False)
                    except Exception as err:  # noqa: BLE001
                        _LOGGER.error("CRITICAL: failed to turn off pump %s: %s", pump_eid, err)
                if valve_eid:
                    await asyncio.sleep(0.5)
                    try:
                        await self._set_switch(valve_eid, False)
                    except Exception as err:  # noqa: BLE001
                        _LOGGER.error("CRITICAL: failed to close valve %s: %s", valve_eid, err)

            event = await self.coordinator.db.async_record_fertigation_event(
                {
                    "plant_id": plant_id,
                    "schedule_id": sched["id"],
                    "reservoir_id": sched.get("reservoir_id"),
                    "trigger_type": trigger_type,
                    "duration_s": shot_s,
                    "volume_ml": volume_ml,
                    "status": "completed",
                    "reservoir_ph": res_ph,
                    "reservoir_ec": res_ec,
                }
            )
            await self.coordinator.db.async_upsert_fertigation_schedule(
                plant_id,
                {"last_fed_at": event["logged_at"], "last_error": None},
            )

            # Auto-log to Grow Journal
            log_type = sched.get("auto_log_action") or "feed"
            env_readings = self.coordinator.get_environment_readings_for_plant(plant_id)
            created_log = await self.coordinator.db.async_create_log(
                {
                    "plant_id": plant_id,
                    "log_type": log_type,
                    "title": f"Auto Fertigation ({trigger_type.title()})",
                    "water_volume_ml": volume_ml,
                    "ph": res_ph,
                    "ec": res_ec,
                    "notes": f"{shot_s:.1f}s shot ({volume_ml:.0f} mL)"
                    + (f" from {res['name']}" if res else ""),
                    **{k: v for k, v in env_readings.items() if v is not None},
                }
            )
            self.hass.bus.async_fire(
                EVENT_LOG_CREATED,
                {
                    "log_id": created_log["id"],
                    "plant_id": plant_id,
                    "log_type": log_type,
                    "status": "completed",
                },
            )
            self.hass.bus.async_fire(
                EVENT_FERTIGATION_SHOT,
                {
                    "plant_id": plant_id,
                    "trigger_type": trigger_type,
                    "duration_s": shot_s,
                    "volume_ml": volume_ml,
                    "reservoir_id": sched.get("reservoir_id"),
                },
            )
            await self.coordinator.async_request_refresh()
            return {"event": event, "created_log": created_log, "blocked": False}

    async def _actuate_dosing_channel(
        self, channel: dict[str, Any], dose_ml: float
    ) -> float:
        """Drive a single peristaltic channel and return elapsed seconds."""
        flow = max(0.05, float(channel.get("flow_rate_ml_s") or 1.0))
        duration_s = round(dose_ml / flow, 2)
        ctrl = channel.get("control_type") or "switch"
        eid = channel.get("entity_id")

        if ctrl == "number_ml" and eid:
            await self._set_number(eid, dose_ml)
        elif ctrl == "esphome_service" and channel.get("esphome_service"):
            svc = channel["esphome_service"].strip()
            if "." in svc:
                dom, srv = svc.split(".", 1)
                await self.hass.services.async_call(
                    dom, srv, {"ml": dose_ml, "duration_s": duration_s}, blocking=True
                )
        elif eid:
            try:
                await self._set_switch(eid, True)
                await asyncio.sleep(duration_s)
            finally:
                await self._set_switch(eid, False)
        return duration_s

    async def async_dose_channel(
        self,
        channel_id: str,
        dose_ml: float,
        *,
        run_type: str = "manual_dose",
        check_caps: bool = True,
    ) -> dict[str, Any]:
        """Dose a specific mL amount on one dosing channel with safety caps."""
        data = self.coordinator.data or {}
        ch = next((c for c in data.get("dosing_channels", []) if c["id"] == channel_id), None)
        if not ch:
            raise ValueError(f"Dosing channel {channel_id} not found")
        res = data.get("reservoirs", {}).get(ch["reservoir_id"])
        if not res:
            raise ValueError("Parent reservoir not found")

        lock = self._reservoir_locks.setdefault(res["id"], asyncio.Lock())
        async with lock:
            if self._is_binary_on(res.get("leak_entity_id")):
                await self.async_emergency_stop("Leak detected during dosing")
                raise ValueError("Leak detected — dosing aborted")
            if check_caps:
                max_cycle = float(ch.get("max_dose_per_cycle_ml") or 50.0)
                if dose_ml > max_cycle:
                    raise ValueError(
                        f"Dose {dose_ml:.1f} mL exceeds per-cycle cap ({max_cycle:.1f} mL)"
                    )
                daily = await self.coordinator.db.async_get_daily_channel_dose(channel_id)
                max_daily = float(ch.get("max_daily_dose_ml") or 200.0)
                if daily + dose_ml > max_daily:
                    raise ValueError(
                        f"Daily dose cap ({max_daily:.1f} mL) exceeded for {ch['name']}"
                    )

            duration_s = await self._actuate_dosing_channel(ch, dose_ml)
            await self.coordinator.db.async_consume_channel_bottle(channel_id, dose_ml)
            run = await self.coordinator.db.async_record_dosing_run(
                {
                    "reservoir_id": res["id"],
                    "channel_id": channel_id,
                    "run_type": run_type,
                    "status": "completed",
                    "dosed_ml": round(dose_ml, 2),
                    "steps": [
                        {
                            "channel_id": channel_id,
                            "channel_name": ch["name"],
                            "dose_ml": round(dose_ml, 2),
                            "duration_s": duration_s,
                        }
                    ],
                    "start_ph": res.get("ph"),
                    "start_ec": res.get("ec"),
                    "end_ph": res.get("ph"),
                    "end_ec": res.get("ec"),
                }
            )
            await self.coordinator.async_request_refresh()
            return {"run": run}

    async def async_run_batch_mix(
        self,
        reservoir_id: str,
        preset_id: str,
        target_volume_l: float,
    ) -> dict[str, Any]:
        """Run ordered nutrient batch-mixing state machine with stir delays."""
        lock = self._reservoir_locks.setdefault(reservoir_id, asyncio.Lock())
        async with lock:
            data = self.coordinator.data or {}
            res = data.get("reservoirs", {}).get(reservoir_id)
            if not res:
                raise ValueError(f"Reservoir {reservoir_id} not found")
            preset = next(
                (p for p in data.get("nutrient_presets", []) if p["id"] == preset_id),
                None,
            )
            if not preset:
                raise ValueError(f"Nutrient preset {preset_id} not found")

            channels = [
                c
                for c in data.get("dosing_channels", [])
                if c["reservoir_id"] == reservoir_id
            ]
            daily_map = {
                ch["id"]: await self.coordinator.db.async_get_daily_channel_dose(ch["id"])
                for ch in channels
            }
            plan = plan_ordered_batch_mix(preset, target_volume_l, channels, daily_map)

            if self._is_binary_on(res.get("leak_entity_id")):
                await self.async_emergency_stop("Leak detected before batch mix")
                raise ValueError("Leak detected — batch mix aborted")
            if self._is_binary_on(res.get("low_level_entity_id")):
                raise ValueError("Reservoir low-level interlock active — refill before mixing")
            if not plan["valid"]:
                reason = "; ".join(plan["errors"]) or "No matching enabled dosing channels"
                await self.coordinator.db.async_record_dosing_run(
                    {
                        "reservoir_id": reservoir_id,
                        "preset_id": preset_id,
                        "run_type": "batch_mix",
                        "status": "aborted",
                        "target_volume_l": target_volume_l,
                        "dosed_ml": 0.0,
                        "steps": plan["steps"],
                        "abort_reason": reason,
                        "start_ph": res.get("ph"),
                        "start_ec": res.get("ec"),
                    }
                )
                self.hass.bus.async_fire(
                    EVENT_DOSING_SAFETY_ABORT,
                    {"reservoir_id": reservoir_id, "reason": reason},
                )
                await self.coordinator.async_request_refresh()
                raise ValueError(reason)

            await self.coordinator.db.async_update_reservoir(
                reservoir_id, {"status": "mixing", "last_error": None}
            )
            circ_eid = res.get("circ_pump_entity_id")
            executed_steps: list[dict[str, Any]] = []
            total_dosed = 0.0
            ch_lookup = {c["id"]: c for c in channels}

            try:
                if circ_eid:
                    await self._set_switch(circ_eid, True)
                for idx, step in enumerate(plan["steps"]):
                    if self._is_binary_on(res.get("leak_entity_id")):
                        raise RuntimeError("Leak detected mid-mix")
                    ch = ch_lookup[step["channel_id"]]
                    dur = await self._actuate_dosing_channel(ch, step["dose_ml"])
                    await self.coordinator.db.async_consume_channel_bottle(
                        ch["id"], step["dose_ml"]
                    )
                    total_dosed += step["dose_ml"]
                    executed_steps.append({**step, "actual_duration_s": dur})
                    stir = int(step.get("stir_delay_s") or 0)
                    if stir > 0 and idx < len(plan["steps"]) - 1:
                        await asyncio.sleep(min(stir, 120))
            except Exception as err:
                await self.coordinator.db.async_update_reservoir(
                    reservoir_id, {"status": "locked_out", "last_error": str(err)}
                )
                await self.coordinator.db.async_record_dosing_run(
                    {
                        "reservoir_id": reservoir_id,
                        "preset_id": preset_id,
                        "run_type": "batch_mix",
                        "status": "aborted",
                        "target_volume_l": target_volume_l,
                        "dosed_ml": round(total_dosed, 2),
                        "steps": executed_steps,
                        "abort_reason": str(err),
                        "start_ph": res.get("ph"),
                        "start_ec": res.get("ec"),
                    }
                )
                self.hass.bus.async_fire(
                    EVENT_DOSING_SAFETY_ABORT,
                    {"reservoir_id": reservoir_id, "reason": str(err)},
                )
                await self.coordinator.async_request_refresh()
                raise
            finally:
                if circ_eid:
                    try:
                        await self._set_switch(circ_eid, False)
                    except Exception:  # noqa: BLE001
                        pass

            now_iso = datetime.now(UTC).replace(microsecond=0).isoformat()
            await self.coordinator.db.async_update_reservoir(
                reservoir_id,
                {"status": "idle", "last_mixed_at": now_iso, "last_error": None},
            )
            run = await self.coordinator.db.async_record_dosing_run(
                {
                    "reservoir_id": reservoir_id,
                    "preset_id": preset_id,
                    "run_type": "batch_mix",
                    "status": "completed",
                    "target_volume_l": target_volume_l,
                    "dosed_ml": round(total_dosed, 2),
                    "steps": executed_steps,
                    "start_ph": res.get("ph"),
                    "start_ec": res.get("ec"),
                    "end_ph": res.get("ph"),
                    "end_ec": res.get("ec"),
                }
            )
            self.hass.bus.async_fire(
                EVENT_DOSING_RUN_COMPLETED,
                {
                    "reservoir_id": reservoir_id,
                    "preset_id": preset_id,
                    "total_ml": round(total_dosed, 2),
                },
            )
            await self.coordinator.async_request_refresh()
            return {"run": run, "plan": plan}

    async def async_run_auto_trim(self, reservoir_id: str) -> dict[str, Any]:
        """Run one closed-loop pH/EC micro-dose trim cycle if needed."""
        data = self.coordinator.data or {}
        res = data.get("reservoirs", {}).get(reservoir_id)
        if not res:
            raise ValueError(f"Reservoir {reservoir_id} not found")
        channels = [
            c for c in data.get("dosing_channels", []) if c["reservoir_id"] == reservoir_id
        ]
        daily_map = {
            ch["id"]: await self.coordinator.db.async_get_daily_channel_dose(ch["id"])
            for ch in channels
        }
        try:
            action = compute_auto_trim_dose(
                res, channels, daily_map, res.get("ph"), res.get("ec")
            )
        except ValueError as err:
            await self.coordinator.db.async_update_reservoir(
                reservoir_id, {"status": "locked_out", "last_error": str(err)}
            )
            self.hass.bus.async_fire(
                EVENT_DOSING_SAFETY_ABORT,
                {"reservoir_id": reservoir_id, "reason": str(err)},
            )
            await self.coordinator.async_request_refresh()
            raise

        if action is None:
            return {"trimmed": False, "reason": "Within target pH & EC tolerances"}

        self._last_trim_at[reservoir_id] = datetime.now(UTC)
        result = await self.async_dose_channel(
            action["channel"]["id"],
            action["dose_ml"],
            run_type=action["run_type"],
            check_caps=True,
        )
        return {"trimmed": True, "action": action["reason"], **result}

    def schedule_background_check(self, data: dict[str, Any]) -> None:
        """Non-blocking scheduler tick invoked after coordinator data refreshes."""
        now = datetime.now(UTC)

        # 1. Leak detection kill-switch takes top priority
        for res in data.get("reservoirs", {}).values():
            if res.get("leak_detected") and res.get("status") != "emergency_stop":
                self._spawn(
                    self.async_emergency_stop(f"Leak sensor triggered on {res['name']}")
                )
                return

        # 2. Evaluate active plant fertigation schedules
        for pid, sched in data.get("fertigation_schedules", {}).items():
            mode = sched.get("mode")
            if mode == "off" or self._plant_locks.get(pid, asyncio.Lock()).locked():
                continue

            if mode == "scheduled":
                nxt = parse_iso_datetime(sched.get("next_fertigation_at"))
                last_dt = parse_iso_datetime(sched.get("last_fed_at"))
                if (
                    nxt is not None
                    and nxt <= now
                    and (last_dt is None or (now - last_dt).total_seconds() >= 90)
                ):
                    self._spawn(
                        self.async_run_fertigation_shot(pid, trigger_type="scheduled")
                    )
            elif mode == "moisture_triggered":
                plant = data.get("plants", {}).get(pid) or {}
                moist = plant.get("soil_moisture")
                thresh = sched.get("moisture_threshold_pct")
                cooldown_min = int(sched.get("moisture_cooldown_min") or 90)
                last_dt = parse_iso_datetime(sched.get("last_fed_at"))
                cooled = (
                    last_dt is None
                    or (now - last_dt).total_seconds() >= cooldown_min * 60
                )
                if (
                    moist is not None
                    and thresh is not None
                    and float(moist) <= float(thresh)
                    and cooled
                ):
                    self._spawn(
                        self.async_run_fertigation_shot(pid, trigger_type="moisture")
                    )

        # 3. Evaluate auto-trim reservoirs respecting settle_delay_s
        for rid, res in data.get("reservoirs", {}).items():
            if not res.get("auto_trim_enabled") or res.get("status") != "idle":
                continue
            settle_s = int(res.get("settle_delay_s") or 180)
            last_trim = self._last_trim_at.get(rid)
            if last_trim is None or (now - last_trim).total_seconds() >= settle_s:
                self._spawn(self._safe_auto_trim(rid))

    async def _safe_auto_trim(self, reservoir_id: str) -> None:
        try:
            await self.async_run_auto_trim(reservoir_id)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Auto-trim skipped/aborted on %s: %s", reservoir_id, err)

    def _spawn(self, coro: Any) -> None:
        task = self.hass.async_create_task(coro)
        self._active_tasks.add(task)
        task.add_done_callback(self._active_tasks.discard)
