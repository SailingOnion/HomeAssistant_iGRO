/**
 * iGro Home Assistant Custom Sidebar Panel (<igro-panel>).
 * Grow with Jane-inspired plant lifecycle, environment, journal & photo manager.
 */

import {
  IGroApi,
  LOG_TYPE_META,
  NUTRIENT_UNITS,
  STAGE_META,
  escapeHtml,
  formatDate,
  formatDateTime,
  formatRelative,
  formatTemp,
  scaleNutrientsForVolume,
  stageBadgeHtml,
  vpdBadgeHtml,
} from "./api.js?v=0.2.1";
import {
  renderConfirmModal,
  renderEnvironmentModal,
  renderLightboxModal,
  renderLogModal,
  renderPhotoModal,
  renderPlantModal,
  renderPresetModal,
  renderScaledMixHtml,
  renderStageModal,
} from "./modals.js?v=0.2.1";
import { PANEL_STYLES } from "./styles.js?v=0.2.1";

class IGroPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._api = null;
    this._narrow = false;
    this._initialized = false;

    this._tab = "overview"; // overview | plants | environments | journal | gallery
    this._selectedPlantId = null;
    this._plantSubTab = "journal"; // journal | photos | history
    this._journalSubTab = "logs"; // logs | presets
    this._filters = {
      plantSearch: "",
      plantStage: "",
      plantEnv: "",
      logPlant: "",
      logType: "",
      photoPlant: "",
      photoStage: "",
    };

    this._state = {
      environments: [],
      plants: [],
      recent_logs: [],
      recent_photos: [],
      nutrient_presets: [],
      summary: {},
      meta: { temperature_unit: "°C" },
    };
    this._haEntities = {
      temperature: [],
      humidity: [],
      moisture: [],
      co2: [],
      controls: [],
      cameras: [],
    };
    this._journalLogs = [];
    this._galleryPhotos = [];
    this._plantLogs = [];
    this._plantPhotos = [];

    this._modal = null; // { type: 'plant'|'env'|'log'|'photo'|'lightbox', data: ... }
    this._toast = null;
    this._toastTimer = null;
    this._pollTimer = null;
  }

  set hass(hass) {
    this._hass = hass;
    this._api = new IGroApi(hass);
    if (!this._initialized) {
      this._initialized = true;
      this._loadAll();
    }
  }

  set narrow(narrow) {
    if (this._narrow !== narrow) {
      this._narrow = narrow;
      this._render();
    }
  }

  connectedCallback() {
    this._onKeyDown = (e) => {
      if (e.key === "Escape" && this._modal) {
        this._modal = null;
        this._render();
      }
    };
    window.addEventListener("keydown", this._onKeyDown);
    this._pollTimer = setInterval(() => {
      if (this._api && !this._modal) {
        this._refreshState(false);
      }
    }, 30000);
  }

  disconnectedCallback() {
    if (this._onKeyDown) {
      window.removeEventListener("keydown", this._onKeyDown);
      this._onKeyDown = null;
    }
    if (this._pollTimer) {
      clearInterval(this._pollTimer);
      this._pollTimer = null;
    }
  }

  _openConfirm({ title, message, confirmLabel = "Delete", danger = true, onConfirm }) {
    this._modal = {
      type: "confirm",
      data: { title, message, confirmLabel, danger, onConfirm },
    };
    this._render();
  }

  _showToast(message, isError = false) {
    this._toast = { message, isError };
    this._render();
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => {
      this._toast = null;
      this._render();
    }, 3200);
  }

  async _loadAll() {
    await Promise.all([this._refreshState(false), this._refreshHaEntities()]);
    this._render();
  }

  async _refreshHaEntities() {
    try {
      this._haEntities = await this._api.listHaEntities();
    } catch (err) {
      console.warn("iGro: failed to list HA entities", err);
    }
  }

  async _refreshState(shouldRender = true) {
    if (!this._api) return;
    try {
      this._state = await this._api.getState();
      if (this._tab === "journal") {
        await this._loadJournal();
      } else if (this._tab === "gallery") {
        await this._loadGallery();
      }
      if (this._selectedPlantId) {
        const exists = (this._state.plants || []).some((p) => p.id === this._selectedPlantId);
        if (!exists) {
          this._selectedPlantId = null;
        } else {
          await this._loadPlantDetails(this._selectedPlantId);
        }
      }
      if (shouldRender) this._render();
    } catch (err) {
      this._showToast(`Failed to load iGro data: ${err.message || err}`, true);
    }
  }

  async _loadJournal() {
    const res = await this._api.listLogs({
      plant_id: this._filters.logPlant || null,
      log_type: this._filters.logType || null,
      limit: 150,
    });
    this._journalLogs = res.logs || [];
  }

  async _loadGallery() {
    const res = await this._api.listPhotos({
      plant_id: this._filters.photoPlant || null,
      stage: this._filters.photoStage || null,
      limit: 150,
    });
    this._galleryPhotos = res.photos || [];
  }

  async _loadPlantDetails(plantId) {
    const [logsRes, photosRes] = await Promise.all([
      this._api.listLogs({ plant_id: plantId, limit: 150 }),
      this._api.listPhotos({ plant_id: plantId, limit: 150 }),
    ]);
    this._plantLogs = logsRes.logs || [];
    this._plantPhotos = photosRes.photos || [];
  }

  async _openPlantDetail(plantId) {
    this._tab = "plants";
    this._selectedPlantId = plantId;
    this._plantSubTab = "journal";
    await this._loadPlantDetails(plantId);
    this._render();
  }

  async _switchTab(tab) {
    this._tab = tab;
    this._selectedPlantId = null;
    if (tab === "journal") await this._loadJournal();
    if (tab === "gallery") await this._loadGallery();
    this._render();
  }

  // ------------------------------------------------------------------
  // Rendering
  // ------------------------------------------------------------------
  _render() {
    const unit = this._state.meta?.temperature_unit || "°C";
    let mainHtml = "";

    if (this._tab === "overview") {
      mainHtml = this._renderOverview(unit);
    } else if (this._tab === "plants") {
      mainHtml = this._selectedPlantId
        ? this._renderPlantDetail(unit)
        : this._renderPlantsList();
    } else if (this._tab === "environments") {
      mainHtml = this._renderEnvironments(unit);
    } else if (this._tab === "journal") {
      mainHtml = this._renderJournal(unit);
    } else if (this._tab === "gallery") {
      mainHtml = this._renderGallery();
    }

    let modalHtml = "";
    if (this._modal) {
      if (this._modal.type === "plant") {
        modalHtml = renderPlantModal(this._modal.data, this._state, this._haEntities);
      } else if (this._modal.type === "env") {
        modalHtml = renderEnvironmentModal(this._modal.data, this._state, this._haEntities);
      } else if (this._modal.type === "log") {
        modalHtml = renderLogModal(this._modal.data || {}, this._state);
      } else if (this._modal.type === "preset") {
        modalHtml = renderPresetModal(this._modal.data, this._state);
      } else if (this._modal.type === "photo") {
        modalHtml = renderPhotoModal(this._modal.data || {}, this._state, this._haEntities);
      } else if (this._modal.type === "lightbox") {
        modalHtml = renderLightboxModal(this._modal.data);
      } else if (this._modal.type === "stage") {
        modalHtml = renderStageModal(this._modal.data);
      } else if (this._modal.type === "confirm") {
        modalHtml = renderConfirmModal(this._modal.data);
      }
    }

    this.shadowRoot.innerHTML = `
      <style>${PANEL_STYLES}</style>
      <header class="topbar">
        <div class="topbar-left">
          <button class="menu-btn ${this._narrow ? "visible" : ""}" id="ha-menu-toggle" title="Toggle Home Assistant Menu">☰</button>
          <div class="brand" data-tab="overview">
            <span class="brand-icon">🌱</span>
            <span>iGro</span>
          </div>
          <nav class="nav-tabs">
            <button class="nav-tab ${this._tab === "overview" ? "active" : ""}" data-tab="overview">📊 Overview</button>
            <button class="nav-tab ${this._tab === "plants" ? "active" : ""}" data-tab="plants">🪴 Plants</button>
            <button class="nav-tab ${this._tab === "environments" ? "active" : ""}" data-tab="environments">⛺ Environments</button>
            <button class="nav-tab ${this._tab === "journal" ? "active" : ""}" data-tab="journal">📓 Journal</button>
            <button class="nav-tab ${this._tab === "gallery" ? "active" : ""}" data-tab="gallery">📷 Gallery</button>
          </nav>
        </div>
        <div class="topbar-actions">
          <button class="btn" id="btn-refresh" title="Refresh live sensors">↻</button>
          <button class="btn" id="btn-quick-log">+ Log</button>
          <button class="btn btn-primary" id="btn-add-plant">+ Plant</button>
        </div>
      </header>
      <main class="container">
        ${mainHtml}
      </main>
      ${modalHtml}
      ${this._toast ? `<div class="toast ${this._toast.isError ? "error" : ""}">${escapeHtml(this._toast.message)}</div>` : ""}
    `;

    this._bindEvents();
  }

  _renderOverview(unit) {
    const s = this._state.summary || {};
    const envs = this._state.environments || [];
    const activePlants = (this._state.plants || []).filter(
      (p) => !["harvested", "archived"].includes(p.stage)
    );
    const recentLogs = (this._state.recent_logs || []).slice(0, 8);

    return `
      <div class="kpi-grid">
        <div class="kpi-card">
          <div>
            <div class="kpi-label">Active Plants</div>
            <div class="kpi-value">${s.active_plants ?? activePlants.length}</div>
          </div>
          <span class="kpi-emoji">🪴</span>
        </div>
        <div class="kpi-card">
          <div>
            <div class="kpi-label">Environments</div>
            <div class="kpi-value">${s.total_environments ?? envs.length}</div>
          </div>
          <span class="kpi-emoji">⛺</span>
        </div>
        <div class="kpi-card">
          <div>
            <div class="kpi-label">Climate Alerts</div>
            <div class="kpi-value" style="color:${(s.alerts_count || 0) > 0 ? "var(--igro-danger)" : "var(--igro-accent)"}">${s.alerts_count ?? 0}</div>
          </div>
          <span class="kpi-emoji">${(s.alerts_count || 0) > 0 ? "⚠️" : "✅"}</span>
        </div>
        <div class="kpi-card">
          <div>
            <div class="kpi-label">Journal & Photos</div>
            <div class="kpi-value">${s.total_logs ?? 0} <span style="font-size:15px;color:var(--igro-text-muted);font-weight:500;">/ ${s.total_photos ?? 0} 📷</span></div>
          </div>
          <span class="kpi-emoji">📓</span>
        </div>
      </div>

      <div class="section-header">
        <h2 class="section-title">⛺ Live Environments</h2>
        <button class="btn btn-sm" id="btn-add-env">+ Add Environment</button>
      </div>
      ${
        envs.length
          ? `<div class="grid-cards">${envs.map((e) => this._renderEnvCard(e, unit, true)).join("")}</div>`
          : `<div class="empty-state">
              <div class="empty-state-emoji">⛺</div>
              <h3>No grow tents or rooms yet</h3>
              <p>Create an environment and link your Home Assistant temperature, humidity & camera sensors for live VPD tracking.</p>
              <button class="btn btn-primary" id="btn-empty-env">+ Create First Environment</button>
            </div>`
      }

      <div class="section-header">
        <h2 class="section-title">🪴 Active Plants</h2>
        <button class="btn btn-sm" data-tab="plants">View All (${(this._state.plants || []).length}) →</button>
      </div>
      ${
        activePlants.length
          ? `<div class="grid-cards">${activePlants.map((p) => this._renderPlantCard(p)).join("")}</div>`
          : `<div class="empty-state">
              <div class="empty-state-emoji">🌱</div>
              <h3>Start your first grow</h3>
              <p>Add a plant to track stages from germination through curing, log feedings, and snap progress photos.</p>
              <button class="btn btn-primary" id="btn-empty-plant">+ Add First Plant</button>
            </div>`
      }

      <div class="section-header">
        <h2 class="section-title">📓 Recent Activity</h2>
        <button class="btn btn-sm" data-tab="journal">Full Journal →</button>
      </div>
      ${
        recentLogs.length
          ? `<div class="timeline">${recentLogs.map((l) => this._renderLogItem(l, unit, false)).join("")}</div>`
          : `<div class="empty-state"><p>No journal entries logged yet. Click <strong>+ Log</strong> above to record your first watering or note.</p></div>`
      }
    `;
  }

  _renderPlantCard(p) {
    return `
      <div class="card clickable" data-open-plant="${escapeHtml(p.id)}">
        <div class="plant-cover">
          ${
            p.cover_photo_url
              ? `<img src="${escapeHtml(p.cover_photo_url)}" alt="${escapeHtml(p.name)}" loading="lazy" />`
              : `<span class="plant-cover-placeholder">${STAGE_META[p.stage]?.icon || "🌱"}</span>`
          }
          <div class="plant-cover-overlay">
            ${stageBadgeHtml(p.stage)}
            <span class="plant-day-pill">Day ${p.total_days ?? 0} · Wk ${p.stage_week ?? 1}</span>
          </div>
        </div>
        <div class="card-body">
          <h3 class="plant-title">${escapeHtml(p.name)}</h3>
          <div class="plant-subtitle">
            ${escapeHtml([p.strain, p.breeder].filter(Boolean).join(" · ") || (p.plant_type || "Plant"))}
          </div>
          <div class="meta-row">
            ${p.environment_name ? `<span>⛺ ${escapeHtml(p.environment_name)}</span>` : ""}
            <span>🪨 ${escapeHtml((p.medium || "soil").replace("_", " "))}</span>
            ${p.pot_size ? `<span>🏺 ${escapeHtml(p.pot_size)}</span>` : ""}
          </div>
          <div class="stat-chips">
            <div class="stat-chip">
              <div class="stat-chip-label">Watered</div>
              <div class="stat-chip-val">${p.days_since_watered !== null && p.days_since_watered !== undefined ? `${p.days_since_watered}d ago` : "—"}</div>
            </div>
            <div class="stat-chip">
              <div class="stat-chip-label">${p.soil_moisture !== null && p.soil_moisture !== undefined ? "Moisture" : "Last pH"}</div>
              <div class="stat-chip-val">${p.soil_moisture !== null && p.soil_moisture !== undefined ? `${p.soil_moisture}%` : p.last_ph ?? "—"}</div>
            </div>
            <div class="stat-chip">
              <div class="stat-chip-label">Stage Day</div>
              <div class="stat-chip-val">D${p.stage_days ?? 0}</div>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  _renderPlantsList() {
    const f = this._filters;
    const plants = (this._state.plants || []).filter((p) => {
      if (f.plantStage && p.stage !== f.plantStage) return false;
      if (f.plantEnv && p.environment_id !== f.plantEnv) return false;
      if (f.plantSearch) {
        const q = f.plantSearch.toLowerCase();
        const hay = `${p.name} ${p.strain || ""} ${p.breeder || ""}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });

    return `
      <div class="section-header" style="margin-top:0;">
        <h2 class="section-title">🪴 Plants (${plants.length})</h2>
        <button class="btn btn-primary" id="btn-add-plant-2">+ Add Plant</button>
      </div>
      <div class="filter-bar">
        <input class="input" id="filter-plant-search" placeholder="Search name, strain, breeder..." value="${escapeHtml(f.plantSearch)}" style="min-width:220px;" />
        <select class="select" id="filter-plant-stage">
          <option value="">All Stages</option>
          ${Object.entries(STAGE_META).map(([k, v]) => `<option value="${k}" ${f.plantStage === k ? "selected" : ""}>${v.label}</option>`).join("")}
        </select>
        <select class="select" id="filter-plant-env">
          <option value="">All Environments</option>
          ${(this._state.environments || []).map((e) => `<option value="${escapeHtml(e.id)}" ${f.plantEnv === e.id ? "selected" : ""}>${escapeHtml(e.name)}</option>`).join("")}
        </select>
      </div>
      ${
        plants.length
          ? `<div class="grid-cards">${plants.map((p) => this._renderPlantCard(p)).join("")}</div>`
          : `<div class="empty-state">
              <div class="empty-state-emoji">🌱</div>
              <h3>No matching plants</h3>
              <p>Try clearing filters or add a new plant to start tracking.</p>
            </div>`
      }
    `;
  }

  _renderPlantDetail(unit) {
    const plant = (this._state.plants || []).find((p) => p.id === this._selectedPlantId);
    if (!plant) return "";
    const stages = this._state.meta?.stages || Object.keys(STAGE_META);
    const curIdx = stages.indexOf(plant.stage);

    let subHtml = "";
    if (this._plantSubTab === "journal") {
      subHtml = this._plantLogs.length
        ? `<div class="timeline">${this._plantLogs.map((l) => this._renderLogItem(l, unit, true)).join("")}</div>`
        : `<div class="empty-state"><p>No logs for ${escapeHtml(plant.name)} yet. Use the quick action buttons above!</p></div>`;
    } else if (this._plantSubTab === "photos") {
      subHtml = this._plantPhotos.length
        ? `<div class="photo-grid">${this._plantPhotos.map((ph) => this._renderPhotoCard(ph)).join("")}</div>`
        : `<div class="empty-state"><p>No photos yet. Upload one or capture directly from your tent camera!</p></div>`;
    } else if (this._plantSubTab === "history") {
      const hist = plant.stage_history || [];
      subHtml = hist.length
        ? `<div class="timeline">${hist
            .map(
              (h) => `
            <div class="log-item">
              <div class="log-icon" style="background:var(--igro-accent-soft);">${STAGE_META[h.stage]?.icon || "🌱"}</div>
              <div class="log-body">
                <div class="log-header">
                  <span class="log-title">${STAGE_META[h.stage]?.label || h.stage}</span>
                  <span class="log-time">${formatDate(h.started_at)} → ${h.ended_at ? formatDate(h.ended_at) : "Current"}</span>
                </div>
                ${h.notes ? `<p class="log-notes">${escapeHtml(h.notes)}</p>` : ""}
              </div>
            </div>
          `
            )
            .join("")}</div>`
        : `<div class="empty-state"><p>No stage history recorded.</p></div>`;
    }

    return `
      <div style="margin-bottom:14px;display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
        <button class="btn" id="btn-back-plants">← Back to Plants</button>
        <div style="display:flex;gap:8px;">
          <button class="btn" id="btn-edit-plant">✏️ Edit</button>
          <button class="btn btn-danger" id="btn-delete-plant">🗑 Delete</button>
        </div>
      </div>

      <div class="detail-hero">
        <div class="detail-photo">
          ${
            plant.cover_photo_url
              ? `<img src="${escapeHtml(plant.cover_photo_url)}" alt="${escapeHtml(plant.name)}" />`
              : `<span style="font-size:64px;">${STAGE_META[plant.stage]?.icon || "🌱"}</span>`
          }
        </div>
        <div class="detail-info">
          <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
            <h1 style="margin:0;font-size:24px;">${escapeHtml(plant.name)}</h1>
            ${stageBadgeHtml(plant.stage)}
          </div>
          <p style="margin:4px 0 10px;color:var(--igro-text-muted);font-size:14px;">
            ${escapeHtml([plant.strain, plant.breeder, plant.plant_type].filter(Boolean).join(" · "))}
          </p>
          <div class="meta-row">
            ${plant.environment_name ? `<span>⛺ ${escapeHtml(plant.environment_name)}</span>` : "<span>⛺ Unassigned</span>"}
            <span>🪨 ${escapeHtml((plant.medium || "soil").replace("_", " "))}</span>
            ${plant.pot_size ? `<span>🏺 ${escapeHtml(plant.pot_size)}</span>` : ""}
            <span>📅 Started ${formatDate(plant.started_at)}</span>
          </div>

          <div class="stat-chips" style="grid-template-columns:repeat(auto-fit, minmax(110px, 1fr));">
            <div class="stat-chip">
              <div class="stat-chip-label">Total Age</div>
              <div class="stat-chip-val">Day ${plant.total_days ?? 0}</div>
            </div>
            <div class="stat-chip">
              <div class="stat-chip-label">In Stage</div>
              <div class="stat-chip-val">Wk ${plant.stage_week ?? 1} · D${plant.stage_days ?? 0}</div>
            </div>
            <div class="stat-chip">
              <div class="stat-chip-label">Last Watered</div>
              <div class="stat-chip-val">${plant.days_since_watered !== null && plant.days_since_watered !== undefined ? `${plant.days_since_watered}d ago` : "—"}</div>
            </div>
            <div class="stat-chip">
              <div class="stat-chip-label">Last pH / EC</div>
              <div class="stat-chip-val">${plant.last_ph ?? "—"} / ${plant.last_ec ?? "—"}</div>
            </div>
            ${
              plant.soil_moisture !== null && plant.soil_moisture !== undefined
                ? `<div class="stat-chip"><div class="stat-chip-label">Soil Moisture</div><div class="stat-chip-val">${plant.soil_moisture}%</div></div>`
                : ""
            }
            ${
              plant.latest_height_cm !== null && plant.latest_height_cm !== undefined
                ? `<div class="stat-chip"><div class="stat-chip-label">Height</div><div class="stat-chip-val">${plant.latest_height_cm} cm</div></div>`
                : ""
            }
          </div>

          <div style="margin-top:14px;">
            <div class="form-label" style="margin-bottom:4px;">Lifecycle Stage (click to transition)</div>
            <div class="stage-stepper">
              ${stages
                .map((s, idx) => {
                  const cls = idx === curIdx ? "current" : idx < curIdx ? "completed" : "";
                  return `<button class="stage-step ${cls}" data-set-stage="${s}">${STAGE_META[s]?.icon || ""} ${STAGE_META[s]?.label || s}</button>`;
                })
                .join("")}
            </div>
          </div>

          <div class="quick-actions">
            <button class="btn btn-primary btn-sm" data-plant-log="water">💧 Water</button>
            <button class="btn btn-primary btn-sm" data-plant-log="feed">🧪 Feed</button>
            ${(() => {
              const firstId = plant.suggested_preset_ids?.[0];
              const topPreset = firstId
                ? (this._state.nutrient_presets || []).find((pr) => pr.id === firstId)
                : null;
              return topPreset
                ? `<button class="btn btn-sm" style="border-color:var(--igro-accent);color:var(--igro-accent);" data-apply-plant-preset="${escapeHtml(topPreset.id)}">⭐ ${escapeHtml(topPreset.name)}</button>`
                : "";
            })()}
            <button class="btn btn-sm" data-plant-log="training">✂️ Training</button>
            <button class="btn btn-sm" data-plant-log="measurement">📏 Measure</button>
            <button class="btn btn-sm" data-plant-log="note">📝 Note</button>
            <button class="btn btn-sm" id="btn-plant-upload-photo">⬆️ Upload Photo</button>
            ${
              plant.effective_camera_entity_id
                ? `<button class="btn btn-sm" id="btn-plant-snap-cam">🎥 Snap Camera</button>`
                : ""
            }
          </div>
          ${plant.notes ? `<p class="log-notes" style="margin-top:12px;">${escapeHtml(plant.notes)}</p>` : ""}
        </div>
      </div>

      <div class="nav-tabs" style="margin-bottom:14px;">
        <button class="nav-tab ${this._plantSubTab === "journal" ? "active" : ""}" data-plant-subtab="journal">📓 Journal (${this._plantLogs.length})</button>
        <button class="nav-tab ${this._plantSubTab === "photos" ? "active" : ""}" data-plant-subtab="photos">📷 Photos (${this._plantPhotos.length})</button>
        <button class="nav-tab ${this._plantSubTab === "history" ? "active" : ""}" data-plant-subtab="history">📅 Stage History</button>
      </div>
      ${subHtml}
    `;
  }

  _renderEnvCard(env, unit, compact = false) {
    const vpd = env.vpd_kpa;
    const vpdPct = vpd !== null && vpd !== undefined ? Math.max(2, Math.min(98, (vpd / 2.2) * 100)) : null;

    return `
      <div class="card">
        <div class="card-body">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;">
            <div>
              <h3 class="plant-title" style="margin:0;">⛺ ${escapeHtml(env.name)}</h3>
              <div class="plant-subtitle" style="margin:2px 0 0;">
                ${escapeHtml([(env.env_type || "tent").replace("_", " "), env.dimensions, env.light_schedule ? `☀️ ${env.light_schedule}` : ""].filter(Boolean).join(" · "))}
              </div>
            </div>
            <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;justify-content:flex-end;">
              ${vpdBadgeHtml(env)}
              <button class="btn btn-sm" data-edit-env="${escapeHtml(env.id)}" title="Edit environment">✏️ Edit</button>
              ${!compact ? `<button class="btn btn-sm btn-danger" data-delete-env="${escapeHtml(env.id)}" title="Delete environment">🗑</button>` : ""}
            </div>
          </div>

          <div class="env-metrics">
            <div class="env-metric">
              <div class="env-metric-label">Temp</div>
              <div class="env-metric-val" style="color:${env.temp_alert ? "var(--igro-danger)" : "inherit"}">${formatTemp(env.temperature_c, unit)}</div>
              <div class="env-metric-sub">${env.dew_point_c !== null && env.dew_point_c !== undefined ? `DP ${formatTemp(env.dew_point_c, unit)}` : "Not linked"}</div>
            </div>
            <div class="env-metric">
              <div class="env-metric-label">Humidity</div>
              <div class="env-metric-val" style="color:${env.humidity_alert ? "var(--igro-danger)" : "inherit"}">${env.humidity !== null && env.humidity !== undefined ? `${env.humidity}%` : "—"}</div>
              <div class="env-metric-sub">${env.co2 !== null && env.co2 !== undefined ? `CO₂ ${Math.round(env.co2)} ppm` : "RH %"}</div>
            </div>
            <div class="env-metric">
              <div class="env-metric-label">Plants</div>
              <div class="env-metric-val">${env.plant_count ?? 0}</div>
              <div class="env-metric-sub">active</div>
            </div>
          </div>

          <div class="vpd-bar-wrap">
            <div class="vpd-bar-label">
              <span>Leaf VPD (${env.leaf_temp_offset_c ?? -2}°C offset)</span>
              <span>Target: ${env.effective_vpd_min ?? "—"}–${env.effective_vpd_max ?? "—"} kPa</span>
            </div>
            <div class="vpd-bar-track">
              ${vpdPct !== null ? `<div class="vpd-bar-marker" style="left:${vpdPct}%;"></div>` : ""}
            </div>
          </div>

          <div class="meta-row" style="margin-bottom:0;">
            ${env.light_entity_id ? `<span class="badge ${env.light_state === "on" ? "badge-warn" : "badge-muted"}">💡 Light: ${escapeHtml(env.light_state || "—")}</span>` : ""}
            ${env.exhaust_entity_id ? `<span class="badge ${env.exhaust_state === "on" ? "badge-ok" : "badge-muted"}">💨 Exhaust: ${escapeHtml(env.exhaust_state || "—")}</span>` : ""}
            ${env.humidifier_entity_id ? `<span class="badge ${env.humidifier_state === "on" ? "badge-info" : "badge-muted"}">🌫 Humidifier: ${escapeHtml(env.humidifier_state || "—")}</span>` : ""}
            ${env.camera_entity_id ? `<span class="badge badge-muted">🎥 Camera linked</span>` : ""}
          </div>
        </div>
      </div>
    `;
  }

  _renderEnvironments(unit) {
    const envs = this._state.environments || [];
    return `
      <div class="section-header" style="margin-top:0;">
        <h2 class="section-title">⛺ Grow Environments (${envs.length})</h2>
        <button class="btn btn-primary" id="btn-add-env-2">+ Add Environment</button>
      </div>
      ${
        envs.length
          ? `<div class="grid-cards">${envs.map((e) => this._renderEnvCard(e, unit, false)).join("")}</div>`
          : `<div class="empty-state">
              <div class="empty-state-emoji">⛺</div>
              <h3>No environments configured</h3>
              <p>Add your grow tent, room, or drying space and bind Home Assistant sensors for real-time VPD and climate alerts.</p>
              <button class="btn btn-primary" id="btn-empty-env">+ Create Environment</button>
            </div>`
      }
    `;
  }

  _renderLogItem(log, unit, showDelete = true) {
    const meta = LOG_TYPE_META[log.log_type] || LOG_TYPE_META.note;
    const chips = [];
    if (log.water_volume_ml) chips.push(`💧 ${log.water_volume_ml} mL`);
    if (log.ph !== null && log.ph !== undefined) chips.push(`pH ${log.ph}`);
    if (log.ec !== null && log.ec !== undefined) chips.push(`EC ${log.ec}`);
    if (log.ppm !== null && log.ppm !== undefined) chips.push(`${log.ppm} ppm`);
    if (log.runoff_ph !== null && log.runoff_ph !== undefined) chips.push(`Runoff pH ${log.runoff_ph}`);
    if (log.runoff_ec !== null && log.runoff_ec !== undefined) chips.push(`Runoff EC ${log.runoff_ec}`);
    if (log.height_cm !== null && log.height_cm !== undefined) chips.push(`📏 ${log.height_cm} cm`);
    if (log.training_method) chips.push(`✂️ ${log.training_method}`);
    if (Array.isArray(log.nutrients)) {
      for (const n of log.nutrients) {
        if (n?.name) {
          const dose = n.amount ? ` ${n.amount}${n.unit || ""}` : "";
          const total =
            n.total_amount !== null && n.total_amount !== undefined && n.total_unit && n.total_unit !== n.unit
              ? ` (${n.total_amount} ${n.total_unit})`
              : "";
          chips.push(`🧪 ${n.name}${dose}${total}`);
        }
      }
    }
    if (log.vpd_kpa !== null && log.vpd_kpa !== undefined) {
      chips.push(`🌡 ${formatTemp(log.temp_c, unit)} · ${log.humidity ?? "—"}% · ${log.vpd_kpa} kPa`);
    }

    return `
      <div class="log-item">
        <div class="log-icon" style="background:${meta.color}22;color:${meta.color};">${meta.icon}</div>
        <div class="log-body">
          <div class="log-header">
            <div>
              <span class="log-title">${escapeHtml(log.title || meta.label)}</span>
              ${log.plant_name ? `<span class="badge badge-muted" style="margin-left:8px;">🪴 ${escapeHtml(log.plant_name)}</span>` : ""}
            </div>
            <div style="display:flex;align-items:center;gap:8px;">
              <span class="log-time" title="${escapeHtml(formatDateTime(log.logged_at))}">${formatRelative(log.logged_at)}</span>
              ${showDelete ? `<button class="btn btn-sm btn-icon btn-danger" data-delete-log="${escapeHtml(log.id)}" title="Delete log">✕</button>` : ""}
            </div>
          </div>
          ${chips.length ? `<div class="log-chips">${chips.map((c) => `<span class="log-chip">${escapeHtml(c)}</span>`).join("")}</div>` : ""}
          ${log.notes ? `<p class="log-notes">${escapeHtml(log.notes)}</p>` : ""}
        </div>
      </div>
    `;
  }

  _renderPresetCard(pr) {
    const weekLabel =
      pr.week_start || pr.week_end
        ? `Wk ${pr.week_start ?? 1}${pr.week_end && pr.week_end !== pr.week_start ? `–${pr.week_end}` : ""}`
        : null;
    const nutrients = Array.isArray(pr.nutrients) ? pr.nutrients : [];
    return `
      <div class="card">
        <div class="card-body">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;">
            <div>
              <h3 class="plant-title" style="margin:0;">🧪 ${escapeHtml(pr.name)}</h3>
              <div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:6px;">
                ${pr.stage ? stageBadgeHtml(pr.stage) : `<span class="badge badge-muted">Any Stage</span>`}
                ${weekLabel ? `<span class="badge badge-info">📅 ${escapeHtml(weekLabel)}</span>` : ""}
              </div>
            </div>
            <div style="display:flex;gap:6px;">
              <button class="btn btn-sm" data-edit-preset="${escapeHtml(pr.id)}" title="Edit preset">✏️</button>
              <button class="btn btn-sm btn-danger" data-delete-preset="${escapeHtml(pr.id)}" title="Delete preset">🗑</button>
            </div>
          </div>

          <div class="stat-chips" style="margin-top:12px;">
            <div class="stat-chip">
              <div class="stat-chip-label">Target pH</div>
              <div class="stat-chip-val">${pr.target_ph ?? "—"}</div>
            </div>
            <div class="stat-chip">
              <div class="stat-chip-label">Target EC</div>
              <div class="stat-chip-val">${pr.target_ec ?? "—"}</div>
            </div>
            <div class="stat-chip">
              <div class="stat-chip-label">Target PPM</div>
              <div class="stat-chip-val">${pr.target_ppm ?? "—"}</div>
            </div>
          </div>

          ${
            nutrients.length
              ? `<div class="log-chips" style="margin-top:12px;">
                  ${nutrients
                    .map(
                      (n) =>
                        `<span class="log-chip">${escapeHtml(n.name)}${n.amount ? ` · <strong>${escapeHtml(n.amount)} ${escapeHtml(n.unit || "")}</strong>` : ""}</span>`
                    )
                    .join("")}
                </div>`
              : `<p style="font-size:12px;color:var(--igro-text-muted);margin:10px 0 0;">No ingredients listed yet.</p>`
          }
          ${pr.notes ? `<p class="log-notes">${escapeHtml(pr.notes)}</p>` : ""}

          <div style="margin-top:14px;display:flex;justify-content:flex-end;">
            <button class="btn btn-primary btn-sm" data-use-preset="${escapeHtml(pr.id)}">🧪 Use in Feed Log</button>
          </div>
        </div>
      </div>
    `;
  }

  _renderJournal(unit) {
    const f = this._filters;
    const presets = this._state.nutrient_presets || [];

    const headerAction =
      this._journalSubTab === "presets"
        ? `<button class="btn btn-primary" id="btn-add-preset">+ New Preset</button>`
        : `<button class="btn btn-primary" id="btn-add-log-2">+ New Entry</button>`;

    const bodyHtml =
      this._journalSubTab === "presets"
        ? presets.length
          ? `<div class="grid-cards">${presets.map((pr) => this._renderPresetCard(pr)).join("")}</div>`
          : `<div class="empty-state">
              <div class="empty-state-emoji">🧪</div>
              <h3>No nutrient presets saved yet</h3>
              <p>Save reusable nutrient recipes (e.g. Veg Week 2–4 Base) with target pH/EC and auto-scale dosages for any bucket volume.</p>
              <button class="btn btn-primary" id="btn-empty-preset">+ Create First Preset</button>
            </div>`
        : `
          <div class="filter-bar">
            <select class="select" id="filter-log-plant">
              <option value="">All Plants</option>
              ${(this._state.plants || []).map((p) => `<option value="${escapeHtml(p.id)}" ${f.logPlant === p.id ? "selected" : ""}>${escapeHtml(p.name)}</option>`).join("")}
            </select>
            <select class="select" id="filter-log-type">
              <option value="">All Action Types</option>
              ${Object.entries(LOG_TYPE_META).map(([k, v]) => `<option value="${k}" ${f.logType === k ? "selected" : ""}>${v.icon} ${v.label}</option>`).join("")}
            </select>
          </div>
          ${
            this._journalLogs.length
              ? `<div class="timeline">${this._journalLogs.map((l) => this._renderLogItem(l, unit, true)).join("")}</div>`
              : `<div class="empty-state">
                  <div class="empty-state-emoji">📓</div>
                  <h3>No journal entries found</h3>
                  <p>Log waterings, nutrient mixes with pH & EC, LST/topping sessions, or measurements.</p>
                </div>`
          }
        `;

    return `
      <div class="section-header" style="margin-top:0;">
        <div class="nav-tabs">
          <button class="nav-tab ${this._journalSubTab === "logs" ? "active" : ""}" data-journal-subtab="logs">📓 Activity Log</button>
          <button class="nav-tab ${this._journalSubTab === "presets" ? "active" : ""}" data-journal-subtab="presets">🧪 Nutrient Presets (${presets.length})</button>
        </div>
        ${headerAction}
      </div>
      ${bodyHtml}
    `;
  }

  _renderPhotoCard(ph) {
    return `
      <div class="photo-card" data-open-photo="${escapeHtml(ph.id)}">
        <img class="photo-thumb" src="${escapeHtml(ph.url)}" alt="${escapeHtml(ph.caption || "Grow photo")}" loading="lazy" />
        <div class="photo-meta">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:6px;">
            <strong>${escapeHtml(ph.plant_name || ph.environment_name || "Photo")}</strong>
            ${ph.stage ? stageBadgeHtml(ph.stage) : ""}
          </div>
          <div style="color:var(--igro-text-muted);margin-top:4px;">${formatDate(ph.taken_at)} ${ph.source === "camera" ? "· 🎥" : ""}</div>
          ${ph.caption ? `<div style="margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${escapeHtml(ph.caption)}</div>` : ""}
        </div>
      </div>
    `;
  }

  _renderGallery() {
    const f = this._filters;
    return `
      <div class="section-header" style="margin-top:0;">
        <h2 class="section-title">📷 Photo Journal (${this._galleryPhotos.length})</h2>
        <div style="display:flex;gap:8px;">
          <button class="btn" id="btn-snap-photo">🎥 Snap Camera</button>
          <button class="btn btn-primary" id="btn-upload-photo">⬆️ Upload Photo</button>
        </div>
      </div>
      <div class="filter-bar">
        <select class="select" id="filter-photo-plant">
          <option value="">All Plants</option>
          ${(this._state.plants || []).map((p) => `<option value="${escapeHtml(p.id)}" ${f.photoPlant === p.id ? "selected" : ""}>${escapeHtml(p.name)}</option>`).join("")}
        </select>
        <select class="select" id="filter-photo-stage">
          <option value="">All Stages</option>
          ${Object.entries(STAGE_META).map(([k, v]) => `<option value="${k}" ${f.photoStage === k ? "selected" : ""}>${v.label}</option>`).join("")}
        </select>
      </div>
      ${
        this._galleryPhotos.length
          ? `<div class="photo-grid">${this._galleryPhotos.map((ph) => this._renderPhotoCard(ph)).join("")}</div>`
          : `<div class="empty-state">
              <div class="empty-state-emoji">📷</div>
              <h3>No photos yet</h3>
              <p>Upload photos from your phone/desktop or capture snapshots straight from your Home Assistant cameras.</p>
            </div>`
      }
    `;
  }

  // ------------------------------------------------------------------
  // Event Binding & Actions
  // ------------------------------------------------------------------
  _bindEvents() {
    const root = this.shadowRoot;

    // HA mobile sidebar toggle
    root.getElementById("ha-menu-toggle")?.addEventListener("click", () => {
      this.dispatchEvent(new CustomEvent("hass-toggle-menu", { bubbles: true, composed: true }));
    });

    // Topbar tabs & actions
    root.querySelectorAll("[data-tab]").forEach((el) => {
      el.addEventListener("click", () => this._switchTab(el.dataset.tab));
    });

    root.getElementById("btn-refresh")?.addEventListener("click", async () => {
      await this._loadAll();
      this._showToast("Synced with Home Assistant sensors");
    });

    const openNewPlant = async () => {
      await this._refreshHaEntities();
      this._modal = { type: "plant", data: null };
      this._render();
    };
    const openNewEnv = async () => {
      await this._refreshHaEntities();
      this._modal = { type: "env", data: null };
      this._render();
    };
    const openNewLog = (defaults = {}) => {
      this._modal = { type: "log", data: defaults };
      this._render();
    };

    root.getElementById("btn-add-plant")?.addEventListener("click", openNewPlant);
    root.getElementById("btn-add-plant-2")?.addEventListener("click", openNewPlant);
    root.getElementById("btn-empty-plant")?.addEventListener("click", openNewPlant);
    root.getElementById("btn-add-env")?.addEventListener("click", openNewEnv);
    root.getElementById("btn-add-env-2")?.addEventListener("click", openNewEnv);
    root.getElementById("btn-empty-env")?.addEventListener("click", openNewEnv);
    root.getElementById("btn-quick-log")?.addEventListener("click", () => openNewLog({ plant_id: this._selectedPlantId || "" }));
    root.getElementById("btn-add-log-2")?.addEventListener("click", () => openNewLog({ plant_id: this._filters.logPlant || "" }));

    // Plant cards click
    root.querySelectorAll("[data-open-plant]").forEach((el) => {
      el.addEventListener("click", () => this._openPlantDetail(el.dataset.openPlant));
    });

    // Plant detail actions
    root.getElementById("btn-back-plants")?.addEventListener("click", () => {
      this._selectedPlantId = null;
      this._render();
    });

    root.getElementById("btn-edit-plant")?.addEventListener("click", async () => {
      await this._refreshHaEntities();
      const plant = (this._state.plants || []).find((p) => p.id === this._selectedPlantId);
      if (plant) {
        this._modal = { type: "plant", data: plant };
        this._render();
      }
    });

    root.getElementById("btn-delete-plant")?.addEventListener("click", () => {
      const plant = (this._state.plants || []).find((p) => p.id === this._selectedPlantId);
      if (!plant) return;
      this._openConfirm({
        title: "🗑 Delete Plant",
        message: `Delete "${plant.name}" and all of its journal logs and photos? This cannot be undone.`,
        confirmLabel: "Delete Plant",
        onConfirm: async () => {
          await this._api.deletePlant(plant.id);
          this._selectedPlantId = null;
          await this._refreshState();
          this._showToast(`Deleted ${plant.name}`);
        },
      });
    });

    root.querySelectorAll("[data-set-stage]").forEach((el) => {
      el.addEventListener("click", () => {
        const targetStage = el.dataset.setStage;
        const plant = (this._state.plants || []).find((p) => p.id === this._selectedPlantId);
        if (!plant || plant.stage === targetStage) return;
        this._modal = { type: "stage", data: { plant, targetStage } };
        this._render();
        this.shadowRoot.getElementById("stage-note-input")?.focus();
      });
    });

    root.querySelectorAll("[data-plant-log]").forEach((el) => {
      el.addEventListener("click", () => {
        openNewLog({ plant_id: this._selectedPlantId, log_type: el.dataset.plantLog });
      });
    });

    root.querySelectorAll("[data-apply-plant-preset]").forEach((el) => {
      el.addEventListener("click", () => {
        const pr = (this._state.nutrient_presets || []).find((p) => p.id === el.dataset.applyPlantPreset);
        if (!pr) return;
        openNewLog({
          plant_id: this._selectedPlantId,
          log_type: "feed",
          preset_id: pr.id,
          title: pr.name,
          ph: pr.target_ph,
          ec: pr.target_ec,
          ppm: pr.target_ppm,
          nutrients: (pr.nutrients || []).map((n) => ({ ...n })),
          notes: pr.notes || "",
        });
      });
    });

    // Journal sub-tabs & nutrient preset actions
    root.querySelectorAll("[data-journal-subtab]").forEach((el) => {
      el.addEventListener("click", () => {
        this._journalSubTab = el.dataset.journalSubtab;
        this._render();
      });
    });

    const openNewPreset = () => {
      this._modal = { type: "preset", data: null };
      this._render();
    };
    root.getElementById("btn-add-preset")?.addEventListener("click", openNewPreset);
    root.getElementById("btn-empty-preset")?.addEventListener("click", openNewPreset);

    root.querySelectorAll("[data-edit-preset]").forEach((el) => {
      el.addEventListener("click", () => {
        const pr = (this._state.nutrient_presets || []).find((p) => p.id === el.dataset.editPreset);
        if (pr) {
          this._modal = { type: "preset", data: pr };
          this._render();
        }
      });
    });

    root.querySelectorAll("[data-delete-preset]").forEach((el) => {
      el.addEventListener("click", () => {
        const pr = (this._state.nutrient_presets || []).find((p) => p.id === el.dataset.deletePreset);
        if (!pr) return;
        this._openConfirm({
          title: "🗑 Delete Nutrient Preset",
          message: `Delete nutrient preset "${pr.name}"?`,
          confirmLabel: "Delete Preset",
          onConfirm: async () => {
            await this._api.deletePreset(pr.id);
            await this._refreshState();
            this._showToast(`Deleted preset "${pr.name}"`);
          },
        });
      });
    });

    root.querySelectorAll("[data-use-preset]").forEach((el) => {
      el.addEventListener("click", () => {
        const pr = (this._state.nutrient_presets || []).find((p) => p.id === el.dataset.usePreset);
        if (!pr) return;
        openNewLog({
          plant_id: this._filters.logPlant || this._state.plants?.[0]?.id || "",
          log_type: "feed",
          preset_id: pr.id,
          title: pr.name,
          ph: pr.target_ph,
          ec: pr.target_ec,
          ppm: pr.target_ppm,
          nutrients: (pr.nutrients || []).map((n) => ({ ...n })),
          notes: pr.notes || "",
        });
      });
    });

    root.querySelectorAll("[data-plant-subtab]").forEach((el) => {
      el.addEventListener("click", () => {
        this._plantSubTab = el.dataset.plantSubtab;
        this._render();
      });
    });

    root.getElementById("btn-plant-upload-photo")?.addEventListener("click", async () => {
      await this._refreshHaEntities();
      this._modal = { type: "photo", data: { mode: "upload", plant_id: this._selectedPlantId } };
      this._render();
    });

    root.getElementById("btn-plant-snap-cam")?.addEventListener("click", async () => {
      const plant = (this._state.plants || []).find((p) => p.id === this._selectedPlantId);
      if (!plant?.effective_camera_entity_id) return;
      try {
        await this._api.captureCameraPhoto({
          camera_entity_id: plant.effective_camera_entity_id,
          plant_id: plant.id,
          caption: `Day ${plant.total_days ?? 0} (${STAGE_META[plant.stage]?.label || plant.stage})`,
        });
        await this._refreshState();
        this._showToast("Snapshot captured from camera!");
      } catch (err) {
        this._showToast(`Camera capture failed: ${err.message || err}`, true);
      }
    });

    // Environment actions
    root.querySelectorAll("[data-edit-env]").forEach((el) => {
      el.addEventListener("click", async (e) => {
        e.stopPropagation();
        const envId = el.dataset.editEnv;
        await this._refreshHaEntities();
        const env = (this._state.environments || []).find((item) => item.id === envId);
        if (env) {
          this._modal = { type: "env", data: env };
          this._render();
        }
      });
    });

    root.querySelectorAll("[data-delete-env]").forEach((el) => {
      el.addEventListener("click", (e) => {
        e.stopPropagation();
        const envId = el.dataset.deleteEnv;
        const env = (this._state.environments || []).find((item) => item.id === envId);
        if (!env) return;
        this._openConfirm({
          title: "🗑 Delete Environment",
          message: `Delete environment "${env.name}"? Plants inside will stay intact and become unassigned.`,
          confirmLabel: "Delete Environment",
          onConfirm: async () => {
            await this._api.deleteEnvironment(env.id);
            await this._refreshState();
            this._showToast(`Deleted ${env.name}`);
          },
        });
      });
    });

    // Delete log
    root.querySelectorAll("[data-delete-log]").forEach((el) => {
      el.addEventListener("click", () => {
        const logId = el.dataset.deleteLog;
        this._openConfirm({
          title: "🗑 Delete Journal Entry",
          message: "Delete this journal entry permanently?",
          confirmLabel: "Delete Entry",
          onConfirm: async () => {
            await this._api.deleteLog(logId);
            await this._refreshState();
            this._showToast("Entry deleted");
          },
        });
      });
    });

    // Gallery buttons & photo click
    root.getElementById("btn-upload-photo")?.addEventListener("click", async () => {
      await this._refreshHaEntities();
      this._modal = { type: "photo", data: { mode: "upload", plant_id: this._filters.photoPlant || "" } };
      this._render();
    });
    root.getElementById("btn-snap-photo")?.addEventListener("click", async () => {
      await this._refreshHaEntities();
      this._modal = { type: "photo", data: { mode: "camera", plant_id: this._filters.photoPlant || "" } };
      this._render();
    });

    root.querySelectorAll("[data-open-photo]").forEach((el) => {
      el.addEventListener("click", () => {
        const pid = el.dataset.openPhoto;
        const pool = [...this._galleryPhotos, ...this._plantPhotos, ...(this._state.recent_photos || [])];
        const photo = pool.find((p) => p.id === pid);
        if (photo) {
          this._modal = { type: "lightbox", data: photo };
          this._render();
        }
      });
    });

    // Filters
    root.getElementById("filter-plant-search")?.addEventListener("input", (e) => {
      this._filters.plantSearch = e.target.value;
      this._render();
      const inp = this.shadowRoot.getElementById("filter-plant-search");
      if (inp) {
        inp.focus();
        inp.setSelectionRange(inp.value.length, inp.value.length);
      }
    });
    root.getElementById("filter-plant-stage")?.addEventListener("change", (e) => {
      this._filters.plantStage = e.target.value;
      this._render();
    });
    root.getElementById("filter-plant-env")?.addEventListener("change", (e) => {
      this._filters.plantEnv = e.target.value;
      this._render();
    });
    root.getElementById("filter-log-plant")?.addEventListener("change", async (e) => {
      this._filters.logPlant = e.target.value;
      await this._loadJournal();
      this._render();
    });
    root.getElementById("filter-log-type")?.addEventListener("change", async (e) => {
      this._filters.logType = e.target.value;
      await this._loadJournal();
      this._render();
    });
    root.getElementById("filter-photo-plant")?.addEventListener("change", async (e) => {
      this._filters.photoPlant = e.target.value;
      await this._loadGallery();
      this._render();
    });
    root.getElementById("filter-photo-stage")?.addEventListener("change", async (e) => {
      this._filters.photoStage = e.target.value;
      await this._loadGallery();
      this._render();
    });

    // Modal backdrop / close
    root.querySelectorAll("[data-close-modal]").forEach((el) => {
      el.addEventListener("click", (e) => {
        if (e.target === el) {
          this._modal = null;
          this._render();
        }
      });
    });

    // Modal-specific handlers
    this._bindModalForms();
  }

  _bindModalForms() {
    const root = this.shadowRoot;
    if (!this._modal) return;

    // Plant form submit
    root.getElementById("plant-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const data = Object.fromEntries(fd.entries());
      for (const k of Object.keys(data)) {
        if (data[k] === "") data[k] = null;
      }
      try {
        if (this._modal.data?.id) {
          await this._api.updatePlant(this._modal.data.id, data);
          this._showToast("Plant updated");
        } else {
          await this._api.createPlant(data);
          this._showToast("Plant added!");
        }
        this._modal = null;
        await this._refreshState();
      } catch (err) {
        this._showToast(`Error: ${err.message || err}`, true);
      }
    });

    // Environment form submit
    root.getElementById("env-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const data = Object.fromEntries(fd.entries());
      const numFields = [
        "leaf_temp_offset_c",
        "target_vpd_min",
        "target_vpd_max",
        "target_temp_min_c",
        "target_temp_max_c",
        "target_humidity_min",
        "target_humidity_max",
      ];
      for (const k of Object.keys(data)) {
        if (data[k] === "") {
          data[k] = null;
        } else if (numFields.includes(k)) {
          data[k] = parseFloat(data[k]);
        }
      }
      try {
        if (this._modal.data?.id) {
          await this._api.updateEnvironment(this._modal.data.id, data);
          this._showToast("Environment updated");
        } else {
          await this._api.createEnvironment(data);
          this._showToast("Environment created!");
        }
        this._modal = null;
        await this._refreshState();
      } catch (err) {
        this._showToast(`Error: ${err.message || err}`, true);
      }
    });

    // Helper to collect nutrient rows from either #log-form or #preset-form
    const collectNutrientRows = (container) => {
      const nutrients = [];
      container?.querySelectorAll(".nutrient-row").forEach((row) => {
        const name = row.querySelector("[name='nut_name']")?.value?.trim();
        const amount = row.querySelector("[name='nut_amount']")?.value?.trim();
        const unit = row.querySelector("[name='nut_unit']")?.value?.trim() || "mL/L";
        if (name) nutrients.push({ name, amount, unit });
      });
      return nutrients;
    };

    const updateScaledMixPreview = () => {
      const logForm = root.getElementById("log-form");
      const preview = root.getElementById("scaled-mix-preview");
      if (!logForm || !preview) return;
      const vol = logForm.querySelector("[name='water_volume_ml']")?.value;
      const nutrients = collectNutrientRows(logForm);
      preview.innerHTML = renderScaledMixHtml(nutrients, vol);
    };

    // Log form interactive chips, preset picker & nutrient rows
    root.querySelectorAll("[data-log-type]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const plantSel = root.querySelector("#log-form [name='plant_id']")?.value || "";
        this._modal.data = {
          ...this._modal.data,
          plant_id: plantSel,
          log_type: btn.dataset.logType,
        };
        this._render();
      });
    });

    root.getElementById("log-preset-select")?.addEventListener("change", (e) => {
      const presetId = e.target.value;
      if (!presetId) return;
      const pr = (this._state.nutrient_presets || []).find((p) => p.id === presetId);
      if (!pr) return;
      const form = root.getElementById("log-form");
      const volVal = form?.querySelector("[name='water_volume_ml']")?.value || "";
      const plantSel = form?.querySelector("[name='plant_id']")?.value || "";
      this._modal.data = {
        ...this._modal.data,
        plant_id: plantSel,
        log_type: "feed",
        preset_id: pr.id,
        title: pr.name,
        water_volume_ml: volVal !== "" ? parseFloat(volVal) : null,
        ph: pr.target_ph,
        ec: pr.target_ec,
        ppm: pr.target_ppm,
        nutrients: (pr.nutrients || []).map((n) => ({ ...n })),
        notes: pr.notes || "",
      };
      this._render();
    });

    root.querySelector("[data-add-nutrient]")?.addEventListener("click", () => {
      const list = root.getElementById("nutrients-list");
      if (!list) return;
      const row = document.createElement("div");
      row.className = "nutrient-row";
      row.innerHTML = `
        <input class="input" name="nut_name" placeholder="Nutrient name" />
        <input class="input" type="number" step="0.1" name="nut_amount" placeholder="Qty" />
        <select class="select" name="nut_unit">${NUTRIENT_UNITS.map((u) => `<option value="${escapeHtml(u)}">${escapeHtml(u)}</option>`).join("")}</select>
        <button type="button" class="btn btn-sm btn-danger">✕</button>
      `;
      row.querySelector("button").addEventListener("click", () => {
        row.remove();
        updateScaledMixPreview();
      });
      list.appendChild(row);
    });

    root.querySelectorAll("[data-remove-nutrient]").forEach((btn) => {
      btn.addEventListener("click", () => {
        btn.closest(".nutrient-row")?.remove();
        updateScaledMixPreview();
      });
    });

    // Live auto-scaling mix preview inside #log-form
    const logFormEl = root.getElementById("log-form");
    if (logFormEl) {
      logFormEl.addEventListener("input", updateScaledMixPreview);
      logFormEl.addEventListener("change", (e) => {
        if (e.target.name === "plant_id") {
          const volVal = logFormEl.querySelector("[name='water_volume_ml']")?.value || "";
          this._modal.data = {
            ...this._modal.data,
            plant_id: e.target.value,
            water_volume_ml: volVal !== "" ? parseFloat(volVal) : null,
            nutrients: collectNutrientRows(logFormEl),
          };
          this._render();
        } else {
          updateScaledMixPreview();
        }
      });
    }

    root.getElementById("log-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const form = e.target;
      const fd = new FormData(form);
      const data = {
        log_type: fd.get("log_type"),
        plant_id: fd.get("plant_id") || null,
        title: fd.get("title") || null,
        notes: fd.get("notes") || null,
        training_method: fd.get("training_method") || null,
      };
      for (const nf of ["water_volume_ml", "ph", "ec", "ppm", "runoff_ph", "runoff_ec", "height_cm"]) {
        const val = fd.get(nf);
        if (val !== null && val !== "") data[nf] = parseFloat(val);
      }
      const rawNutrients = collectNutrientRows(form);
      if (rawNutrients.length) {
        data.nutrients = scaleNutrientsForVolume(rawNutrients, data.water_volume_ml);
      }

      try {
        await this._api.createLog(data);
        this._modal = null;
        await this._refreshState();
        this._showToast("Journal entry saved!");
      } catch (err) {
        this._showToast(`Error: ${err.message || err}`, true);
      }
    });

    // Nutrient Preset form submit
    root.getElementById("preset-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const form = e.target;
      const fd = new FormData(form);
      const data = {
        name: (fd.get("name") || "").trim(),
        stage: fd.get("stage") || null,
        notes: fd.get("notes") || null,
        nutrients: collectNutrientRows(form),
      };
      for (const intF of ["week_start", "week_end"]) {
        const val = fd.get(intF);
        data[intF] = val !== null && val !== "" ? parseInt(val, 10) : null;
      }
      for (const floatF of ["target_ph", "target_ec", "target_ppm"]) {
        const val = fd.get(floatF);
        data[floatF] = val !== null && val !== "" ? parseFloat(val) : null;
      }

      try {
        if (this._modal.data?.id) {
          await this._api.updatePreset(this._modal.data.id, data);
          this._showToast("Nutrient preset updated!");
        } else {
          await this._api.createPreset(data);
          this._showToast("Nutrient preset created!");
        }
        this._modal = null;
        await this._refreshState();
      } catch (err) {
        this._showToast(`Error: ${err.message || err}`, true);
      }
    });

    // Photo modal mode toggle & submit
    root.querySelectorAll("[data-photo-mode]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const plantSel = root.querySelector("#photo-form [name='plant_id']")?.value || "";
        this._modal.data = {
          ...this._modal.data,
          plant_id: plantSel,
          mode: btn.dataset.photoMode,
        };
        this._render();
      });
    });

    root.getElementById("photo-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const mode = fd.get("mode");
      try {
        if (mode === "upload") {
          await this._api.uploadPhoto(fd);
          this._showToast("Photo uploaded!");
        } else {
          await this._api.captureCameraPhoto({
            camera_entity_id: fd.get("camera_entity_id"),
            plant_id: fd.get("plant_id") || null,
            stage: fd.get("stage") || null,
            caption: fd.get("caption") || null,
          });
          this._showToast("Camera snapshot captured!");
        }
        this._modal = null;
        await this._refreshState();
      } catch (err) {
        this._showToast(`Photo error: ${err.message || err}`, true);
      }
    });

    // Lightbox actions
    root.querySelector("[data-set-cover]")?.addEventListener("click", async (e) => {
      const btn = e.currentTarget;
      await this._api.setCoverPhoto(btn.dataset.plantId, btn.dataset.setCover);
      this._modal = null;
      await this._refreshState();
      this._showToast("Cover photo updated!");
    });

    root.querySelector("[data-delete-photo]")?.addEventListener("click", (e) => {
      const photoId = e.currentTarget.dataset.deletePhoto;
      this._openConfirm({
        title: "🗑 Delete Photo",
        message: "Delete this photo permanently from your grow journal?",
        confirmLabel: "Delete Photo",
        onConfirm: async () => {
          await this._api.deletePhoto(photoId);
          await this._refreshState();
          this._showToast("Photo deleted");
        },
      });
    });

    // Stage transition modal submit
    root.getElementById("stage-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const notes = (fd.get("notes") || "").trim() || null;
      const pickedDate = (fd.get("changed_at") || "").trim();
      const todayDefault = fd.get("today_default") || "";
      const changedAt = pickedDate && pickedDate !== todayDefault ? pickedDate : null;
      const { plant, targetStage } = this._modal.data;
      try {
        await this._api.setPlantStage(plant.id, targetStage, notes, changedAt);
        this._modal = null;
        await this._refreshState();
        this._showToast(`Moved ${plant.name} to ${STAGE_META[targetStage]?.label || targetStage}`);
      } catch (err) {
        this._showToast(`Error: ${err.message || err}`, true);
      }
    });

    // Confirmation modal action
    root.getElementById("confirm-modal-ok")?.addEventListener("click", async () => {
      const fn = this._modal?.data?.onConfirm;
      this._modal = null;
      this._render();
      if (typeof fn === "function") {
        try {
          await fn();
        } catch (err) {
          this._showToast(`Error: ${err.message || err}`, true);
        }
      }
    });
  }
}

if (!customElements.get("igro-panel")) {
  customElements.define("igro-panel", IGroPanel);
}
