/**
 * API client and formatting helpers for the iGro Home Assistant panel.
 */

export const STAGE_META = {
  germination: { label: "Germination", color: "#a16207", bg: "rgba(161, 98, 7, 0.16)", icon: "🌱" },
  seedling:    { label: "Seedling",    color: "#65a30d", bg: "rgba(101, 163, 13, 0.16)", icon: "🌿" },
  vegetative:  { label: "Vegetative",  color: "#16a34a", bg: "rgba(22, 163, 74, 0.16)", icon: "🪴" },
  flowering:   { label: "Flowering",   color: "#9333ea", bg: "rgba(147, 51, 234, 0.16)", icon: "🌸" },
  drying:      { label: "Drying",      color: "#d97706", bg: "rgba(217, 119, 6, 0.16)", icon: "🍂" },
  curing:      { label: "Curing",      color: "#0284c7", bg: "rgba(2, 132, 199, 0.16)", icon: "🫙" },
  harvested:   { label: "Harvested",   color: "#059669", bg: "rgba(5, 150, 105, 0.16)", icon: "✨" },
  archived:    { label: "Archived",    color: "#64748b", bg: "rgba(100, 116, 139, 0.16)", icon: "📦" },
};

export const LOG_TYPE_META = {
  water:        { label: "Water",        icon: "💧", color: "#0ea5e9" },
  feed:         { label: "Feed",         icon: "🧪", color: "#10b981" },
  training:     { label: "Training",     icon: "✂️", color: "#f59e0b" },
  defoliation:  { label: "Defoliation",  icon: "🍃", color: "#84cc16" },
  measurement:  { label: "Measurement",  icon: "📏", color: "#8b5cf6" },
  transplant:   { label: "Transplant",   icon: "🪴", color: "#a16207" },
  flush:        { label: "Flush",        icon: "🚿", color: "#06b6d4" },
  pest_issue:   { label: "Pest / Issue", icon: "🪲", color: "#ef4444" },
  stage_change: { label: "Stage Change", icon: "🔄", color: "#a855f7" },
  note:         { label: "Note",         icon: "📝", color: "#64748b" },
};

export const TRAINING_METHODS = [
  "LST (Low Stress Training)",
  "Topping",
  "FIM",
  "SCROG",
  "SOG",
  "Mainlining / Manifold",
  "Supercropping",
  "Lollipopping",
  "HST",
  "Other",
];

export function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function formatTemp(tempC, targetUnit = "°C") {
  if (tempC === null || tempC === undefined) return "—";
  if (targetUnit && targetUnit.toUpperCase().includes("F")) {
    const f = (tempC * 9) / 5 + 32;
    return `${f.toFixed(1)}°F`;
  }
  return `${Number(tempC).toFixed(1)}°C`;
}

export function formatDate(iso) {
  if (!iso) return "—";
  const normalized = /^\d{4}-\d{2}-\d{2}$/.test(iso) ? `${iso}T12:00:00` : iso;
  const d = new Date(normalized);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function formatDateTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function formatRelative(iso) {
  if (!iso) return "Never";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const diffMs = Date.now() - d.getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days === 1) return "Yesterday";
  if (days < 30) return `${days}d ago`;
  return formatDate(iso);
}

export function stageBadgeHtml(stage) {
  const meta = STAGE_META[stage] || { label: stage || "Unknown", color: "#64748b", bg: "rgba(100,116,139,0.16)", icon: "🌱" };
  return `<span class="badge" style="color:${meta.color};background:${meta.bg};border-color:${meta.color}40">${meta.icon} ${escapeHtml(meta.label)}</span>`;
}

export function vpdBadgeHtml(env) {
  if (env.vpd_kpa === null || env.vpd_kpa === undefined) {
    return `<span class="badge badge-muted">VPD —</span>`;
  }
  const st = env.vpd_status || "unknown";
  const cls =
    st === "optimal"
      ? "badge-ok"
      : st === "low"
      ? "badge-info"
      : st === "high"
      ? "badge-danger"
      : "badge-muted";
  return `<span class="badge ${cls}">VPD ${env.vpd_kpa.toFixed(2)} kPa</span>`;
}

export class IGroApi {
  constructor(hass) {
    this.hass = hass;
  }

  async getState() {
    return this.hass.callWS({ type: "igro/get_state" });
  }

  async listHaEntities() {
    return this.hass.callWS({ type: "igro/list_ha_entities" });
  }

  async createEnvironment(data) {
    return this.hass.callWS({ type: "igro/environments/create", data });
  }

  async updateEnvironment(environment_id, data) {
    return this.hass.callWS({ type: "igro/environments/update", environment_id, data });
  }

  async deleteEnvironment(environment_id) {
    return this.hass.callWS({ type: "igro/environments/delete", environment_id });
  }

  async createPlant(data) {
    return this.hass.callWS({ type: "igro/plants/create", data });
  }

  async updatePlant(plant_id, data) {
    return this.hass.callWS({ type: "igro/plants/update", plant_id, data });
  }

  async setPlantStage(plant_id, stage, notes = null) {
    return this.hass.callWS({ type: "igro/plants/set_stage", plant_id, stage, notes });
  }

  async deletePlant(plant_id) {
    return this.hass.callWS({ type: "igro/plants/delete", plant_id });
  }

  async listLogs(filters = {}) {
    return this.hass.callWS({ type: "igro/logs/list", ...filters });
  }

  async createLog(data) {
    return this.hass.callWS({ type: "igro/logs/create", data });
  }

  async deleteLog(log_id) {
    return this.hass.callWS({ type: "igro/logs/delete", log_id });
  }

  async listPhotos(filters = {}) {
    return this.hass.callWS({ type: "igro/photos/list", ...filters });
  }

  async captureCameraPhoto({ camera_entity_id, plant_id = null, environment_id = null, stage = null, caption = null }) {
    return this.hass.callWS({
      type: "igro/photos/capture_camera",
      camera_entity_id,
      plant_id,
      environment_id,
      stage,
      caption,
    });
  }

  async deletePhoto(photo_id) {
    return this.hass.callWS({ type: "igro/photos/delete", photo_id });
  }

  async setCoverPhoto(plant_id, photo_id) {
    return this.hass.callWS({ type: "igro/photos/set_cover", plant_id, photo_id });
  }

  async uploadPhoto(formData) {
    const url = "/api/igro/photos/upload";
    let resp;
    if (typeof this.hass.fetchWithAuth === "function") {
      resp = await this.hass.fetchWithAuth(url, { method: "POST", body: formData });
    } else {
      const token = this.hass.auth?.data?.access_token;
      resp = await fetch(url, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: formData,
      });
    }
    const json = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      throw new Error(json.error || `Upload failed (${resp.status})`);
    }
    return json;
  }
}
