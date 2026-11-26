# 🌱 iGro — Plant Grow Cycle Manager for Home Assistant

**iGro** brings a complete **Grow with Jane**-inspired plant lifecycle, breeding, and automated fertigation manager directly into Home Assistant — combining a dedicated zero-build sidebar web app with native Home Assistant devices, real-time VPD calculations from your existing sensors, reusable nutrient presets, harvest & curing archives, HA Calendar & To-Do reminders, breeding/pheno-hunt tracking, and high-frequency fertigation & peristaltic reservoir dosing.

---

## ✨ Features (`v0.7.0`)

### 🪴 Plant & Lifecycle Tracking
- Track plants from **Germination → Seedling → Vegetative → Flowering → Drying → Curing → Harvested → Archived**.
- Store strain, breeder/source, plant type (photoperiod, autoflower, clone, vegetable, herb, houseplant, etc.), grow medium, pot size, grow cycle, and notes.
- Automatic **Total Grow Days**, **Stage Days**, **Stage Week**, and editable chronological **Stage History** timeline.
- **Retrospective & Ahead-of-Time Stage Scheduling**: Backdate past stage transitions (auto re-chains stage history) or schedule future transitions (e.g., flip to Flowering next Monday) with optional automatic application.
- Interactive stage progress stepper with themed native iGro modals (`Escape` to close, zero browser popups) + native Home Assistant `select` entity and automation services.

### ⛺ Environments & Live VPD Monitoring
- Create grow tents, rooms, cabinets, greenhouses, or drying tents with optional **Light Wattage (W)** for automatic **g/W** yield efficiency calculations.
- Bind **existing Home Assistant sensors & devices**:
  - Temperature & Humidity sensors (°C or °F auto-converted)
  - CO₂ sensors & plant-level Soil Moisture sensors
  - Grow Lights, Exhaust Fans, Humidifiers, and Cameras
- Real-time **Leaf VPD (kPa)** & **Dew Point** calculations with configurable leaf temperature offset (default `-2.0 °C` for LED canopies).
- **Stage-aware VPD targets** (or custom per-tent min/max overrides for VPD, Temp, and Humidity) with native `binary_sensor` alert entities for instant HA notifications or climate automations.

### 📓 Grow Journal, Nutrient Presets & Auto-Scaling
- Log **Watering**, **Feeding (Nutrients)**, **Training (LST, Topping, FIM, SCROG, Mainlining, etc.)**, **Defoliation**, **Measurements (Height)**, **Transplant**, **Flush**, **Pest/Issue**, **Pollination**, **Reversal (STS/CS)**, and **Notes**.
- **Backdated & Planned Entries**: Log retrospective entries with custom timestamps or schedule upcoming planned actions with one-tap **Done** completion.
- **Nutrient Preset Recipes & Multi-Week Schedules**: Save reusable feeding recipes scoped by stage & week range (with target pH/EC/PPM and mixing notes), get stage/week-matched preset recommendations per plant, and auto-scale dosages (`mL/L`, `mL/gal`, `g/L`, `g/gal`, `tsp/gal`) live for any bucket volume.
- Automatically snapshots the tent's live Temperature, Humidity, and VPD onto current journal entries.

### ⏰ Reminders & Schedules (HA Calendar & To-Do Integration)
- Schedule one-time or recurring tasks (watering, feeding, defoliation, flushing, curing jar burps, etc.) with optional **linked Nutrient Preset** auto-logging on completion.
- **Soil Moisture Early Trigger**: Mark a plant's watering reminder due early whenever its linked soil moisture sensor drops below a configured threshold.
- Native **Home Assistant Calendar** (`calendar.igro_grow_schedule`) exposing active reminders (with projected recurring occurrences), scheduled stage transitions, and planned journal entries.
- Native **Home Assistant To-Do List** (`todo.igro_grow_tasks`) with bidirectional create, edit, delete, and check-off sync from HA dashboards and voice assistants.
- Fires `igro_reminder_due` events once per due cycle for mobile push or TTS automations, alongside an Overview **Due Today & Upcoming Tasks** widget.

### 💧 High-Frequency Fertigation & Automated Reservoir Dosing
- **Managed Nutrient Reservoirs**:
  - Bind live HA sensors & safety hardware: **pH**, **EC**, **Water Temp**, **Water Level (%)**, **Low-Level Float Interlock**, **Leak Detector Kill-Switch**, **RO Top-Off Valve**, **Circulation Pump**, and **Shared Master Feed Pump**.
  - **Peristaltic Dosing Pump Bank**: Map 4–8+ channels (`switch.*`, ESPHome `number.*` mL, or custom ESPHome service) to *Silica*, *Cal-Mag*, *Base A*, *Base B*, *Bloom/PK*, *Additives*, *pH Down*, and *pH Up* with a **Calibration & Prime Wizard** (`mL/s`) and **bottle level gauges** with low-bottle alerts.
  - **Ordered Batch Mixing**: Select any saved Nutrient Preset + target volume (L) to dose channels strictly in chemical mix order (`Silica → Cal-Mag → Base A → Base B → Bloom/PK → Additives`) with circulation pump control and stir delays to prevent nutrient precipitation/lockout.
  - **Closed-Loop Auto-pH & Auto-EC Trimming**: Proportional micro-dosing with mandatory settle delays, probe sanity bounds checks, and strict per-cycle & daily dose caps.
- **Per-Plant High-Frequency Fertigation**:
  - Supports **Dedicated Per-Plant Pumps**, **Shared Master Pump + Per-Plant Solenoid Valves** (safe valve-open-before-pump / pump-off-before-valve-close sequencing), and **ESPHome max-on hardware watchdog** sync.
  - **Crop Steering (P1 / P2 / P3)** high-frequency scheduling (P1 morning ramp shots, P2 daytime maintenance spacing, P3 overnight dryback cutoff), **Interval**, **Fixed Clock Times**, and **Soil Moisture Trigger** (with cooldown).
  - **Flood & Hardware Safety Interlocks**: Max single-shot duration cap, max daily total volume cap, low-level dry-run protection, leak-detector kill-switch, and global **🛑 Emergency Stop** button & service.
  - Automatically logs every completed automated feed shot to the plant's Grow Journal with calculated mL and live reservoir pH/EC.

### 🧬 Breeding Program, Pollen Vault, Pedigree Tree & Pheno-Hunts
- **Pollen Vault**: Track stored male and STS/Colloidal Silver reversed pollen batches with donor plant/strain, collection date, freezer storage method & location, and viability status.
- **Breeding Crosses & Auto-Mint Seeds**: Link **Mother × Pollen Donor / Parent Cross** with generation notation (`F1`, `F2`, `F3`, `S1`, `BX1`, `IX`, `Polyhybrid`, etc.), pollination scope & branch tag, and automatic 6-week seed maturity countdown. Harvest mature seeds in one click to **auto-mint a Seedbank batch** with full pedigree lineage and inferred feminized/regular type.
- **Interactive Multi-Generation Pedigree Tree**: Cycle-safe visual ancestor diagram tracing crosses across multiple generations plus clickable descendant navigation.
- **Pheno-Hunt Comparison Matrix**: Group sibling plants into a Pheno Hunt and compare **Vigor**, **Stretch Factor**, **Internode Spacing**, **Resin Density**, **Pest/Mold Resistance**, **Aroma/Terpene Notes**, **Flowering Time**, **Dry Yield**, **Overall Score**, and status (`Evaluating`, `🏆 Keeper`, `🧬 Breeder`, `❌ Cull`) side by side.

### 🌾 Harvest, Curing & Historical Grow Archive
- Record **Wet Weight**, **Dry Flower Weight**, **Trim/Larf Weight**, drying days, curing start date, jar RH %, 1–5★ rating, aroma & smoke/effect notes, and **🏆 Keeper Phenotype** flags.
- Automatic **Wet → Dry Retention %**, **Dry Yield (oz)**, **Grams per Watt (g/W)**, and **Curing Days** calculations.
- Dedicated **Curing & Burping Log** per harvest tracking jar humidity, temperature, and burp checks.
- Group runs into named **Grow Cycles**, search/filter/sort past harvests in the **🏆 Archive** tab, and export complete plant grow reports in **Markdown (`.md`)** or **JSON (`.json`)**.

### 📷 Photo Journal & Camera Integration
- Upload progress photos (with optional custom backdated timestamp) from your phone or computer via the Home Assistant app/browser.
- **One-click camera capture** from any Home Assistant `camera.*` entity (ESP32-CAM, Reolink, UniFi, Wyze, Frigate, etc.) — manually or on a daily automation schedule.
- Filter gallery by plant or grow stage, set cover photos, and inspect in a full-screen lightbox.

### 💾 SQLite Persistence (Zero Extra Dependencies)
- Uses Python's built-in `sqlite3` in WAL mode, stored as a dedicated `igro.db` inside your Home Assistant `/config/` folder alongside `home-assistant_v2.db` (keeping HA's recorder lock-free and safe from schema/purge conflicts).
- Photos are stored safely in `/config/igro_media/` with per-photo access tokens.

---

## 📦 Installation

### Option 1: Home Assistant Marketplace (HA 2026.11+, Recommended)
*(Make sure the GitHub repository is **Public** — Marketplace custom repositories require public repos.)*
1. In Home Assistant, go to **Settings → Marketplace** (accept the community notice if opening for the first time).
2. Click the three-dot menu (`⋮`) in the top right → **Custom repositories**.
3. Sign in with GitHub if prompted.
4. Add `https://github.com/SailingOnion/HomeAssistant_iGRO` with type **Integration**.
5. Search for **iGro** in Marketplace and click **Install**.
6. Restart Home Assistant.
7. Go to **Settings → Devices & Services → + Add Integration** and search for **iGro**.

*(On Home Assistant 2026.10 or earlier, use **HACS → ⋮ → Custom repositories** with the same URL and category **Integration**.)*

### Option 2: Manual Installation
1. Copy `custom_components/igro` into your Home Assistant `/config/custom_components/igro` directory.
   > **Note:** `local_apps` is for containerized **Apps** (formerly Add-ons). Custom Python integrations like iGro still go inside `/config/custom_components/`.
2. Restart Home Assistant.
3. Go to **Settings → Devices & Services → + Add Integration → iGro**.

After setup, **iGro** appears directly in your Home Assistant sidebar (`mdi:sprout`).

---

## 🏠 Home Assistant Entities Created

Each **Environment**, **Plant**, and **Reservoir** is dynamically registered as its own Home Assistant Device (no restart needed when adding or removing items):

| Scope | Platform | Entities |
| --- | --- | --- |
| **Global Hub** | `sensor` | Active Plants, Environments, Active Alerts, Total Dry Yield, Due Reminders |
| **Global Hub** | `calendar` | Grow Schedule (active reminders, recurring projections, scheduled stage transitions, planned logs) |
| **Global Hub** | `todo` | Grow Tasks (bidirectional HA To-Do list synced with iGro reminders) |
| **Environment** | `sensor` | Temperature, Humidity, VPD (kPa), VPD Status, Active Plants |
| **Environment** | `binary_sensor` | VPD Alert, Temperature Alert, Humidity Alert |
| **Plant** | `sensor` | Grow Stage, Total Grow Days, Stage Days, Days Since Watered, Last pH, Last EC, Soil Moisture, Height, Harvest Dry Yield, Next Feed, Daily Fertigation Volume |
| **Plant** | `select` | Stage, Fertigation Mode (`off` / `scheduled` / `moisture_triggered`) |
| **Plant** | `number` | Feeds Per Day (`1–24`), Feed Shot Duration (`1–300 s`) |
| **Plant** | `button` | Log Watering, Capture Photo, Manual Pulse Feed |
| **Reservoir** | `sensor` | pH, EC (`mS/cm`), Water Temperature, Water Level (`%`), Status |
| **Reservoir** | `binary_sensor` | Safety Interlock (leak, low-level, probe fault, or lockout) |
| **Reservoir** | `button` | Emergency Stop |

---

## 🛠️ Services & Events

### Services
- `igro.log_action` — Record or schedule a Grow Journal entry (with optional Nutrient Preset auto-scaling)
- `igro.set_stage` / `igro.advance_stage` — Move a plant's growth stage (now, backdated, or scheduled ahead)
- `igro.capture_photo` — Capture a snapshot from a Home Assistant camera into the Photo Journal
- `igro.create_plant` — Create a new plant programmatically
- `igro.record_harvest` — Record wet/dry/trim weights, rating, keeper status, and tasting notes
- `igro.create_reminder` / `igro.complete_reminder` — Schedule or complete recurring/one-time grow reminders
- `igro.fertigate_plant` — Trigger a safety-interlocked manual fertigation pulse shot
- `igro.mix_reservoir_batch` — Execute an ordered dosing batch mix from a saved Nutrient Preset
- `igro.dose_channel` — Dispense a calibrated mL volume on a single peristaltic channel
- `igro.emergency_stop` — Immediately shut off all pumps, valves, and dosing relays and pause automated fertigation

### Home Assistant Events
`igro_log_created`, `igro_stage_changed`, `igro_photo_added`, `igro_harvest_recorded`, `igro_reminder_due`, `igro_fertigation_shot`, `igro_fertigation_emergency_stop`, `igro_dosing_run_completed`, `igro_dosing_safety_abort`.

---

## 🤖 Automation Examples

### Notify on Due Grow Reminders
```yaml
alias: "iGro - Reminder Due Notification"
trigger:
  - platform: event
    event_type: igro_reminder_due
action:
  - service: notify.mobile_app_phone
    data:
      title: "⏰ iGro Task Due"
      message: "{{ trigger.event.data.title }}"
```

### Daily Timelapse Photo from Tent Camera
```yaml
alias: "iGro - Daily Noon Tent Photo"
trigger:
  - platform: time
    at: "12:00:00"
action:
  - service: igro.capture_photo
    data:
      plant: "Northern Lights #1"
      caption: "Daily noon check-in"
```

### Alert When VPD Leaves Optimal Range
```yaml
alias: "iGro - Flower Tent VPD Alert"
trigger:
  - platform: state
    entity_id: binary_sensor.4x4_flower_tent_vpd_alert
    to: "on"
    for:
      minutes: 15
action:
  - service: notify.mobile_app_phone
    data:
      title: "⚠️ Flower Tent VPD Alert"
      message: >
        VPD is {{ states('sensor.4x4_flower_tent_vpd') }} kPa
        ({{ state_attr('sensor.4x4_flower_tent_vpd', 'status') }}).
```

### Critical Push Alert on Fertigation Emergency Stop
```yaml
alias: "iGro - Emergency Stop Alert"
trigger:
  - platform: event
    event_type: igro_fertigation_emergency_stop
action:
  - service: notify.mobile_app_phone
    data:
      title: "🚨 iGro EMERGENCY STOP"
      message: "All pumps & dosers halted: {{ trigger.event.data.reason }}"
```

---

## 🗺️ Upcoming Roadmap
- **Seedbank / Genetics Vault & Clone Lineage Tree (#13)**: Full seed pack inventory, germination rate tracking, and mother → clone lineage trees (extends the minted `seed_batches` from Breeding).
- **Charts & Analytics (#8)**: Interactive height, pH/EC, runoff, and VPD trend graphs.
- **Batch Actions (#9)**: Multi-plant and whole-tent bulk watering/feeding/training logging.
- **Lighting & DLI / PPFD Tracking (#4)**: Photoperiod schedules, canopy PPFD sensors, and daily light integral targets.
- **Closed-Loop Climate Control & ESPHome MIMO Sync (#5, #6)**: Stage-aware climate setpoints driving exhaust, humidifiers, heaters, and light dimming.
- **Grow Energy & Cost-Per-Gram Tracking (#12)**: Track kWh power usage, utility cost, and total cost per dry gram harvested.
- **Timelapse Video/GIF Generator (#3)**: Export MP4/GIF timelapses directly from your plant Photo Journal.
