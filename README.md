# 🌱 iGro — Plant Grow Cycle Manager for Home Assistant

**iGro** brings a complete **Grow with Jane**-style plant lifecycle manager directly into Home Assistant — combining a dedicated sidebar web app with native Home Assistant devices, real-time VPD calculations from your existing sensors, a grow journal, and a photo gallery powered by device uploads and Home Assistant cameras.

---

## ✨ Features (v1)

### 🪴 Plant & Lifecycle Tracking
- Track plants from **Germination → Seedling → Vegetative → Flowering → Drying → Curing → Harvested → Archived**.
- Store strain, breeder/source, plant type (photoperiod, autoflower, clone, vegetable, herb, etc.), grow medium, pot size, and notes.
- Automatic **Total Grow Days**, **Stage Days**, **Stage Week**, and **Stage History** timeline.
- Interactive stage progress stepper in the UI + native Home Assistant `select` entity and automation services.

### ⛺ Environments & Live VPD Monitoring
- Create grow tents, rooms, cabinets, greenhouses, or drying tents.
- Bind **existing Home Assistant sensors & devices**:
  - Temperature & Humidity sensors (°C or °F auto-converted)
  - CO₂ sensors & plant-level Soil Moisture sensors
  - Grow Lights, Exhaust Fans, Humidifiers, and Cameras
- Real-time **Leaf VPD (kPa)** & **Dew Point** calculations with configurable leaf temperature offset (default `-2.0 °C` for LED canopies).
- **Stage-aware VPD targets** (or custom per-tent min/max overrides for VPD, Temp, and Humidity) with native `binary_sensor` alert entities for instant HA notifications or climate automations.

### 📓 Grow Journal & Action Logging
- Log **Watering**, **Feeding (Nutrients)**, **Training (LST, Topping, FIM, SCROG, etc.)**, **Defoliation**, **Measurements (Height)**, **Transplant**, **Flush**, **Pest/Issue**, and **Notes**.
- Track water volume (mL), input pH / EC / PPM, runoff pH / EC, and multi-line nutrient recipes.
- Automatically snapshots the tent's live Temperature, Humidity, and VPD onto every journal entry.

### 📷 Photo Journal & Camera Integration
- Upload progress photos directly from your phone or computer via the Home Assistant app/browser.
- **One-click camera capture** from any Home Assistant `camera.*` entity (ESP32-CAM, Reolink, UniFi, Wyze, Frigate, etc.) — manually or on a daily automation schedule!
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

Each **Environment** and each **Plant** is dynamically registered as its own Home Assistant Device (no restart needed when adding or removing items):

| Scope | Platform | Entities |
| --- | --- | --- |
| **Global Hub** | `sensor` | Active Plants, Environments, Active Alerts |
| **Environment** | `sensor` | Temperature, Humidity, VPD (kPa), VPD Status, Active Plants |
| **Environment** | `binary_sensor` | VPD Alert, Temperature Alert, Humidity Alert |
| **Plant** | `sensor` | Grow Stage, Total Grow Days, Stage Days, Days Since Watered, Last pH, Last EC, Soil Moisture, Height |
| **Plant** | `select` | Stage (change lifecycle stage from dashboards/automations) |
| **Plant** | `button` | Log Watering, Capture Photo |

---

## 🤖 Automation Examples

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

### Auto-Log Watering When Smart Irrigation Runs
```yaml
alias: "iGro - Log Auto Irrigation"
trigger:
  - platform: state
    entity_id: switch.tent_drip_pump
    from: "on"
    to: "off"
action:
  - service: igro.log_action
    data:
      plant: "Northern Lights #1"
      log_type: water
      water_volume_ml: 1500
      notes: "Automated drip cycle"
```

---

## 🗺️ Roadmap (v2)
- **Reminders & Schedules**: Native Home Assistant `calendar` / `todo` integration for watering intervals, feeding schedules, and light-flip reminders.
- **Harvest & Yield Tracking**: Wet weight, dry weight, trim weight, curing RH logs, smoke/tasting notes, and historical grow archives.
- **Timelapse Export & Growth Charts**: Visual height, pH/EC, and VPD history charts right inside the plant profile.
