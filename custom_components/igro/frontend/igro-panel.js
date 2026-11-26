/**
 * iGro Home Assistant Custom Sidebar Panel (<igro-panel>).
 * Grow with Jane-inspired plant lifecycle, environment, journal & photo manager.
 */

import {
  IGroApi,
  LOG_TYPE_META,
  NUTRIENT_UNITS,
  PHENO_STATUS_META,
  POLLEN_DONOR_META,
  REMINDER_ACTION_META,
  STAGE_META,
  downloadTextFile,
  escapeHtml,
  formatDate,
  formatDateTime,
  formatRelative,
  formatTemp,
  fromLocalDatetimeInput,
  scaleNutrientsForVolume,
  stageBadgeHtml,
  vpdBadgeHtml,
} from "./api.js?v=0.6.0";
import {
  renderConfirmModal,
  renderCrossModal,
  renderCuringLogModal,
  renderEnvironmentModal,
  renderGrowCycleModal,
  renderHarvestModal,
  renderHarvestSeedsModal,
  renderLightboxModal,
  renderLogModal,
  renderPedigreeModal,
  renderPhenoHuntModal,
  renderPhenoScoreModal,
  renderPhotoModal,
  renderPlantModal,
  renderPollenModal,
  renderPresetModal,
  renderReminderModal,
  renderScaledMixHtml,
  renderStageHistoryModal,
  renderStageModal,
} from "./modals.js?v=0.6.0";
import { PANEL_STYLES } from "./styles.js?v=0.6.0";

class IGroPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._api = null;
    this._narrow = false;
    this._initialized = false;

    this._tab = "overview"; // overview | plants | environments | journal | gallery | breeding | archive
    this._selectedPlantId = null;
    this._plantSubTab = "journal"; // journal | photos | history | harvest
    this._journalSubTab = "logs"; // logs | reminders | presets
    this._breedingSubTab = "crosses"; // crosses | phenos | pollen | seeds
    this._selectedPhenoHuntId = null;
    this._filters = {
      plantSearch: "",
      plantStage: "",
      plantEnv: "",
      logPlant: "",
      logType: "",
      logStatus: "",
      photoPlant: "",
      photoStage: "",
      archiveSearch: "",
      archiveCycle: "",
      archiveKeepersOnly: false,
      archiveSort: "newest",
    };

    this._state = {
      environments: [],
      plants: [],
      recent_logs: [],
      planned_logs: [],
      scheduled_stage_changes: [],
      recent_photos: [],
      nutrient_presets: [],
      grow_cycles: [],
      harvests: [],
      reminders: [],
      pollen_batches: [],
      breeding_crosses: [],
      seed_batches: [],
      pheno_hunts: [],
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
      status: this._filters.logStatus || null,
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
    } else if (this._tab === "breeding") {
      mainHtml = this._renderBreeding();
    } else if (this._tab === "archive") {
      mainHtml = this._renderArchive();
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
      } else if (this._modal.type === "stage_history") {
        modalHtml = renderStageHistoryModal(this._modal.data, this._state);
      } else if (this._modal.type === "harvest") {
        modalHtml = renderHarvestModal(this._modal.data, this._state);
      } else if (this._modal.type === "curing") {
        modalHtml = renderCuringLogModal(this._modal.data);
      } else if (this._modal.type === "cycle") {
        modalHtml = renderGrowCycleModal(this._modal.data);
      } else if (this._modal.type === "reminder") {
        modalHtml = renderReminderModal(this._modal.data, this._state);
      } else if (this._modal.type === "pollen") {
        modalHtml = renderPollenModal(this._modal.data, this._state);
      } else if (this._modal.type === "cross") {
        modalHtml = renderCrossModal(this._modal.data, this._state);
      } else if (this._modal.type === "harvest_seeds") {
        modalHtml = renderHarvestSeedsModal(this._modal.data);
      } else if (this._modal.type === "pedigree") {
        modalHtml = renderPedigreeModal(this._modal.data);
      } else if (this._modal.type === "pheno_hunt") {
        modalHtml = renderPhenoHuntModal(this._modal.data, this._state);
      } else if (this._modal.type === "pheno_score") {
        modalHtml = renderPhenoScoreModal(this._modal.data, this._state);
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
            <button class="nav-tab ${this._tab === "breeding" ? "active" : ""}" data-tab="breeding">🧬 Breeding</button>
            <button class="nav-tab ${this._tab === "archive" ? "active" : ""}" data-tab="archive">🏆 Archive</button>
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
    const activeReminders = (this._state.reminders || []).filter((r) => r.status === "active");
    const prioritizedReminders = [...activeReminders]
      .sort((a, b) => Number(Boolean(b.is_due)) - Number(Boolean(a.is_due)))
      .slice(0, 5);
    const dueCount = s.due_reminders ?? activeReminders.filter((r) => r.is_due).length;

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
            <div class="kpi-label">Due Tasks</div>
            <div class="kpi-value" style="color:${dueCount > 0 ? "var(--igro-warn)" : "var(--igro-accent)"}">${dueCount} <span style="font-size:14px;color:var(--igro-text-muted);font-weight:500;">/ ${activeReminders.length} active</span></div>
          </div>
          <span class="kpi-emoji">⏰</span>
        </div>
      </div>

      <div class="section-header">
        <h2 class="section-title">⏰ Due Today & Upcoming Tasks${dueCount > 0 ? ` <span class="badge badge-warn" style="margin-left:6px;">${dueCount} due</span>` : ""}</h2>
        <div style="display:flex;gap:8px;">
          <button class="btn btn-sm" id="btn-add-reminder-overview">+ Reminder</button>
          <button class="btn btn-sm" data-open-reminders-tab="1">All Reminders (${activeReminders.length}) →</button>
        </div>
      </div>
      ${
        prioritizedReminders.length
          ? `<div class="timeline">${prioritizedReminders.map((r) => this._renderReminderItem(r, true)).join("")}</div>`
          : `<div class="empty-state" style="padding:20px;">
              <p style="margin:0;">No upcoming tasks scheduled. Click <strong>+ Reminder</strong> to set watering, feeding, or curing schedules synced to HA Calendar & To-Do.</p>
            </div>`
      }

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
      subHtml = `
        <div style="display:flex;justify-content:flex-end;margin-bottom:12px;">
          <button class="btn btn-sm btn-primary" id="btn-add-stage-history">+ Add Past Stage</button>
        </div>
        ${
          hist.length
            ? `<div class="timeline">${hist
                .map(
                  (h) => `
              <div class="log-item">
                <div class="log-icon" style="background:var(--igro-accent-soft);">${STAGE_META[h.stage]?.icon || "🌱"}</div>
                <div class="log-body">
                  <div class="log-header">
                    <span class="log-title">${STAGE_META[h.stage]?.label || h.stage}</span>
                    <div style="display:flex;align-items:center;gap:6px;">
                      <span class="log-time">${formatDate(h.started_at)} → ${h.ended_at ? formatDate(h.ended_at) : "Current"}</span>
                      <button class="btn btn-sm btn-icon" data-edit-stage-history="${escapeHtml(h.id)}" title="Edit stage date/notes">✏️</button>
                      ${hist.length > 1 ? `<button class="btn btn-sm btn-icon btn-danger" data-delete-stage-history="${escapeHtml(h.id)}" title="Delete stage entry">✕</button>` : ""}
                    </div>
                  </div>
                  ${h.notes ? `<p class="log-notes">${escapeHtml(h.notes)}</p>` : ""}
                </div>
              </div>
            `
                )
                .join("")}</div>`
            : `<div class="empty-state"><p>No stage history recorded.</p></div>`
        }
      `;
    } else if (this._plantSubTab === "harvest") {
      const h = plant.harvest;
      if (!h) {
        subHtml = `
          <div class="empty-state">
            <div class="empty-state-emoji">🌾</div>
            <h3>No harvest recorded yet</h3>
            <p>Record wet weight, dry flower weight, trim, drying days, curing RH, and tasting notes once this plant finishes.</p>
            <button class="btn btn-primary" data-record-harvest="${escapeHtml(plant.id)}">🌾 Record Harvest</button>
          </div>
        `;
      } else {
        const curingLogs = h.curing_logs || [];
        subHtml = `
          <div class="card" style="margin-bottom:16px;">
            <div class="card-body">
              <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
                <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                  <h3 style="margin:0;">🌾 Harvest Summary</h3>
                  <span class="badge badge-muted">📅 ${formatDate(h.harvested_at)}</span>
                  ${h.rating ? `<span class="badge badge-warn">${"★".repeat(h.rating)}</span>` : ""}
                  ${h.is_keeper ? `<span class="badge badge-ok">🏆 Keeper</span>` : ""}
                </div>
                <div style="display:flex;gap:6px;flex-wrap:wrap;">
                  <button class="btn btn-sm" data-export-report-md="${escapeHtml(plant.id)}">📄 Export MD</button>
                  <button class="btn btn-sm" data-export-report-json="${escapeHtml(plant.id)}">📦 Export JSON</button>
                  <button class="btn btn-sm" data-record-harvest="${escapeHtml(plant.id)}">✏️ Edit</button>
                  <button class="btn btn-sm btn-danger" data-delete-harvest="${escapeHtml(h.id)}">🗑</button>
                </div>
              </div>

              <div class="stat-chips" style="grid-template-columns:repeat(auto-fit, minmax(115px, 1fr));margin-top:14px;">
                <div class="stat-chip">
                  <div class="stat-chip-label">Wet Weight</div>
                  <div class="stat-chip-val">${h.wet_weight_g !== null && h.wet_weight_g !== undefined ? `${h.wet_weight_g} g` : "—"}</div>
                </div>
                <div class="stat-chip">
                  <div class="stat-chip-label">Dry Flower</div>
                  <div class="stat-chip-val" style="color:var(--igro-accent);">${h.dry_weight_g !== null && h.dry_weight_g !== undefined ? `${h.dry_weight_g} g` : "—"}${h.dry_weight_oz ? ` (${h.dry_weight_oz} oz)` : ""}</div>
                </div>
                <div class="stat-chip">
                  <div class="stat-chip-label">Retention</div>
                  <div class="stat-chip-val">${h.retention_pct !== null && h.retention_pct !== undefined ? `${h.retention_pct}%` : "—"}</div>
                </div>
                <div class="stat-chip">
                  <div class="stat-chip-label">Trim / Larf</div>
                  <div class="stat-chip-val">${h.trim_weight_g !== null && h.trim_weight_g !== undefined ? `${h.trim_weight_g} g` : "—"}</div>
                </div>
                <div class="stat-chip">
                  <div class="stat-chip-label">Efficiency</div>
                  <div class="stat-chip-val">${h.grams_per_watt !== null && h.grams_per_watt !== undefined ? `${h.grams_per_watt} g/W` : "—"}</div>
                </div>
                <div class="stat-chip">
                  <div class="stat-chip-label">Cure / Jar RH</div>
                  <div class="stat-chip-val">${h.cure_rh_pct !== null && h.cure_rh_pct !== undefined ? `${h.cure_rh_pct}%` : "—"}${h.curing_days !== null && h.curing_days !== undefined ? ` · D${h.curing_days}` : ""}</div>
                </div>
              </div>

              ${
                h.aroma_notes || h.effect_notes
                  ? `<div class="log-chips" style="margin-top:12px;">
                      ${h.aroma_notes ? `<span class="log-chip">👃 Aroma: ${escapeHtml(h.aroma_notes)}</span>` : ""}
                      ${h.effect_notes ? `<span class="log-chip">✨ Effects: ${escapeHtml(h.effect_notes)}</span>` : ""}
                      ${h.dry_days ? `<span class="log-chip">🍂 Dried ${h.dry_days} days</span>` : ""}
                    </div>`
                  : ""
              }
              ${h.notes ? `<p class="log-notes">${escapeHtml(h.notes)}</p>` : ""}
            </div>
          </div>

          <div class="section-header" style="margin-top:8px;">
            <h3 class="section-title">🫙 Curing & Burping Log (${curingLogs.length})</h3>
            <button class="btn btn-primary btn-sm" data-add-curing="${escapeHtml(h.id)}" data-plant-name="${escapeHtml(plant.name)}">+ Log Jar Check / Burp</button>
          </div>
          ${
            curingLogs.length
              ? `<div class="timeline">${curingLogs
                  .map(
                    (cl) => `
                  <div class="log-item">
                    <div class="log-icon" style="background:rgba(2,132,199,0.16);color:#0284c7;">🫙</div>
                    <div class="log-body">
                      <div class="log-header">
                        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
                          <span class="log-title">${cl.burped ? "Jar Burped" : "Jar Checked"}</span>
                          ${cl.jar_rh_pct !== null && cl.jar_rh_pct !== undefined ? `<span class="badge ${cl.jar_rh_pct >= 58 && cl.jar_rh_pct <= 65 ? "badge-ok" : "badge-warn"}">RH ${cl.jar_rh_pct}%</span>` : ""}
                          ${cl.jar_temp_c !== null && cl.jar_temp_c !== undefined ? `<span class="badge badge-muted">${formatTemp(cl.jar_temp_c, unit)}</span>` : ""}
                        </div>
                        <div style="display:flex;align-items:center;gap:6px;">
                          <span class="log-time" title="${escapeHtml(formatDateTime(cl.logged_at))}">${formatRelative(cl.logged_at)}</span>
                          <button class="btn btn-sm btn-icon btn-danger" data-delete-curing="${escapeHtml(cl.id)}" title="Delete curing entry">✕</button>
                        </div>
                      </div>
                      ${cl.notes ? `<p class="log-notes">${escapeHtml(cl.notes)}</p>` : ""}
                    </div>
                  </div>
                `
                  )
                  .join("")}</div>`
              : `<div class="empty-state"><p>No jar checks logged yet. Click <strong>+ Log Jar Check / Burp</strong> to track curing humidity.</p></div>`
          }
        `;
      }
    }

    const schedStages = plant.scheduled_stage_changes || [];
    const schedBannerHtml = schedStages.length
      ? `
        <div style="margin-bottom:16px;display:flex;flex-direction:column;gap:8px;">
          ${schedStages
            .map(
              (sc) => `
            <div class="log-item" style="border-style:dashed;border-color:var(--igro-info);">
              <div class="log-icon" style="background:rgba(14,165,233,0.16);color:var(--igro-info);">📅</div>
              <div class="log-body">
                <div class="log-header">
                  <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                    <span class="log-title">Scheduled Stage Transition</span>
                    ${stageBadgeHtml(sc.target_stage)}
                    <span class="badge badge-info">${formatDate(sc.scheduled_for)} (${formatRelative(sc.scheduled_for)})</span>
                    ${sc.auto_apply ? `<span class="badge badge-ok">Auto-apply</span>` : `<span class="badge badge-muted">Manual</span>`}
                  </div>
                  <div style="display:flex;gap:6px;">
                    <button class="btn btn-sm btn-primary" data-apply-sched-stage="${escapeHtml(sc.id)}">▶ Apply Now</button>
                    <button class="btn btn-sm btn-danger" data-cancel-sched-stage="${escapeHtml(sc.id)}">✕</button>
                  </div>
                </div>
                ${sc.notes ? `<p class="log-notes">${escapeHtml(sc.notes)}</p>` : ""}
              </div>
            </div>
          `
            )
            .join("")}
        </div>
      `
      : "";

    return `
      <div style="margin-bottom:14px;display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
        <button class="btn" id="btn-back-plants">← Back to Plants</button>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <button class="btn" data-export-report-md="${escapeHtml(plant.id)}">📄 Export Report</button>
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
            ${plant.grow_cycle_name ? `<span>🗓 ${escapeHtml(plant.grow_cycle_name)}</span>` : ""}
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
            <button class="btn btn-sm" data-plant-reminder="${escapeHtml(plant.id)}">⏰ + Reminder</button>
            <button class="btn btn-sm" data-record-harvest="${escapeHtml(plant.id)}">🌾 ${plant.harvest ? "Edit Harvest" : "Record Harvest"}</button>
          </div>
          ${plant.notes ? `<p class="log-notes" style="margin-top:12px;">${escapeHtml(plant.notes)}</p>` : ""}
        </div>
      </div>

      ${schedBannerHtml}
      <div class="nav-tabs" style="margin-bottom:14px;">
        <button class="nav-tab ${this._plantSubTab === "journal" ? "active" : ""}" data-plant-subtab="journal">📓 Journal (${this._plantLogs.length})</button>
        <button class="nav-tab ${this._plantSubTab === "photos" ? "active" : ""}" data-plant-subtab="photos">📷 Photos (${this._plantPhotos.length})</button>
        <button class="nav-tab ${this._plantSubTab === "history" ? "active" : ""}" data-plant-subtab="history">📅 Stage History</button>
        <button class="nav-tab ${this._plantSubTab === "harvest" ? "active" : ""}" data-plant-subtab="harvest">🌾 Harvest & Cure${plant.harvest?.dry_weight_g ? ` (${plant.harvest.dry_weight_g}g)` : ""}</button>
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

    const isPlanned = log.status === "planned";
    return `
      <div class="log-item" style="${isPlanned ? "border-style:dashed;border-color:var(--igro-info);" : ""}">
        <div class="log-icon" style="background:${meta.color}22;color:${meta.color};">${meta.icon}</div>
        <div class="log-body">
          <div class="log-header">
            <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
              <span class="log-title">${escapeHtml(log.title || meta.label)}</span>
              ${isPlanned ? `<span class="badge badge-info">📅 Planned</span>` : ""}
              ${log.plant_name ? `<span class="badge badge-muted">🪴 ${escapeHtml(log.plant_name)}</span>` : ""}
            </div>
            <div style="display:flex;align-items:center;gap:6px;">
              <span class="log-time" title="${escapeHtml(formatDateTime(log.logged_at))}">${formatRelative(log.logged_at)}</span>
              ${isPlanned ? `<button class="btn btn-sm btn-primary" data-complete-log="${escapeHtml(log.id)}" title="Mark completed">✅ Done</button>` : ""}
              ${showDelete ? `<button class="btn btn-sm btn-icon" data-edit-log="${escapeHtml(log.id)}" title="Edit entry">✏️</button>` : ""}
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

  _renderReminderItem(rem, compact = false) {
    const meta = REMINDER_ACTION_META[rem.action_type] || REMINDER_ACTION_META.note;
    const isCompleted = rem.status === "completed";
    const isPaused = rem.status === "paused";
    const borderStyle = rem.is_overdue
      ? "border-color:var(--igro-danger);"
      : rem.is_moisture_triggered || rem.is_due_today
      ? "border-color:var(--igro-warn);"
      : isCompleted
      ? "opacity:0.72;"
      : "";

    const chips = [];
    if (rem.recurrence_days) chips.push(`🔁 Every ${rem.recurrence_days}d`);
    if (rem.moisture_threshold !== null && rem.moisture_threshold !== undefined) {
      chips.push(`💧 Moisture < ${rem.moisture_threshold}%`);
    }
    if (rem.preset_name) chips.push(`🧪 ${rem.preset_name}`);
    if (rem.auto_log_on_complete) chips.push("📓 Auto-logs");
    if (rem.environment_name && !rem.plant_name) chips.push(`⛺ ${rem.environment_name}`);

    return `
      <div class="log-item" style="${borderStyle}">
        <div class="log-icon" style="background:${meta.color}22;color:${meta.color};">${meta.icon}</div>
        <div class="log-body">
          <div class="log-header">
            <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
              <span class="log-title">${escapeHtml(rem.title)}</span>
              ${rem.is_overdue ? `<span class="badge badge-danger">Overdue</span>` : ""}
              ${!rem.is_overdue && rem.is_due_today ? `<span class="badge badge-warn">Due Today</span>` : ""}
              ${rem.is_moisture_triggered ? `<span class="badge badge-danger">💧 Dry Soil</span>` : ""}
              ${isPaused ? `<span class="badge badge-muted">Paused</span>` : ""}
              ${isCompleted ? `<span class="badge badge-ok">Completed</span>` : ""}
              ${rem.plant_name ? `<span class="badge badge-muted">🪴 ${escapeHtml(rem.plant_name)}</span>` : ""}
            </div>
            <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
              <span class="log-time" title="${escapeHtml(formatDateTime(rem.due_at))}">${formatRelative(rem.due_at)}</span>
              ${!isCompleted ? `<button class="btn btn-sm btn-primary" data-complete-reminder="${escapeHtml(rem.id)}" title="Mark completed">✅ Done</button>` : ""}
              ${!compact ? `<button class="btn btn-sm btn-icon" data-edit-reminder="${escapeHtml(rem.id)}" title="Edit reminder">✏️</button>` : ""}
              ${!compact ? `<button class="btn btn-sm btn-icon btn-danger" data-delete-reminder="${escapeHtml(rem.id)}" title="Delete reminder">✕</button>` : ""}
            </div>
          </div>
          ${chips.length ? `<div class="log-chips">${chips.map((c) => `<span class="log-chip">${escapeHtml(c)}</span>`).join("")}</div>` : ""}
          ${rem.notes ? `<p class="log-notes">${escapeHtml(rem.notes)}</p>` : ""}
        </div>
      </div>
    `;
  }

  _renderJournal(unit) {
    const f = this._filters;
    const presets = this._state.nutrient_presets || [];
    const reminders = this._state.reminders || [];
    const activeRemCount = reminders.filter((r) => r.status === "active").length;

    const headerAction =
      this._journalSubTab === "presets"
        ? `<button class="btn btn-primary" id="btn-add-preset">+ New Preset</button>`
        : this._journalSubTab === "reminders"
        ? `<button class="btn btn-primary" id="btn-add-reminder">+ New Reminder</button>`
        : `<button class="btn btn-primary" id="btn-add-log-2">+ New Entry</button>`;

    let bodyHtml = "";
    if (this._journalSubTab === "presets") {
      bodyHtml = presets.length
        ? `<div class="grid-cards">${presets.map((pr) => this._renderPresetCard(pr)).join("")}</div>`
        : `<div class="empty-state">
            <div class="empty-state-emoji">🧪</div>
            <h3>No nutrient presets saved yet</h3>
            <p>Save reusable nutrient recipes (e.g. Veg Week 2–4 Base) with target pH/EC and auto-scale dosages for any bucket volume.</p>
            <button class="btn btn-primary" id="btn-empty-preset">+ Create First Preset</button>
          </div>`;
    } else if (this._journalSubTab === "reminders") {
      bodyHtml = reminders.length
        ? `<div class="timeline">${reminders.map((r) => this._renderReminderItem(r, false)).join("")}</div>`
        : `<div class="empty-state">
            <div class="empty-state-emoji">⏰</div>
            <h3>No grow reminders yet</h3>
            <p>Create recurring watering, feeding, or curing jar burp schedules. Active reminders sync automatically with Home Assistant Calendar &amp; To-Do lists.</p>
            <button class="btn btn-primary" id="btn-empty-reminder">+ Create First Reminder</button>
          </div>`;
    } else {
      bodyHtml = `
        <div class="filter-bar">
          <select class="select" id="filter-log-plant">
            <option value="">All Plants</option>
            ${(this._state.plants || []).map((p) => `<option value="${escapeHtml(p.id)}" ${f.logPlant === p.id ? "selected" : ""}>${escapeHtml(p.name)}</option>`).join("")}
          </select>
          <select class="select" id="filter-log-type">
            <option value="">All Action Types</option>
            ${Object.entries(LOG_TYPE_META).map(([k, v]) => `<option value="${k}" ${f.logType === k ? "selected" : ""}>${v.icon} ${v.label}</option>`).join("")}
          </select>
          <select class="select" id="filter-log-status">
            <option value="">All Statuses</option>
            <option value="completed" ${f.logStatus === "completed" ? "selected" : ""}>✅ Completed</option>
            <option value="planned" ${f.logStatus === "planned" ? "selected" : ""}>📅 Planned</option>
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
    }

    return `
      <div class="section-header" style="margin-top:0;">
        <div class="nav-tabs">
          <button class="nav-tab ${this._journalSubTab === "logs" ? "active" : ""}" data-journal-subtab="logs">📓 Activity Log</button>
          <button class="nav-tab ${this._journalSubTab === "reminders" ? "active" : ""}" data-journal-subtab="reminders">⏰ Reminders (${activeRemCount})</button>
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

  _renderBreeding() {
    const crosses = this._state.breeding_crosses || [];
    const hunts = this._state.pheno_hunts || [];
    const pollen = this._state.pollen_batches || [];
    const seeds = this._state.seed_batches || [];

    const headerAction =
      this._breedingSubTab === "pollen"
        ? `<button class="btn btn-primary" id="btn-add-pollen">+ Store Pollen</button>`
        : this._breedingSubTab === "phenos"
        ? `<button class="btn btn-primary" id="btn-add-pheno-hunt">+ New Pheno Hunt</button>`
        : this._breedingSubTab === "seeds"
        ? `<button class="btn" data-breeding-subtab="crosses">🧬 Harvest from Crosses</button>`
        : `<button class="btn btn-primary" id="btn-add-cross">+ New Cross</button>`;

    let bodyHtml = "";
    if (this._breedingSubTab === "crosses") {
      bodyHtml = crosses.length
        ? `<div class="grid-cards">${crosses
            .map((c) => {
              const statusCls =
                c.status === "harvested"
                  ? "badge-ok"
                  : c.status === "failed"
                  ? "badge-danger"
                  : c.status === "planned"
                  ? "badge-muted"
                  : "badge-info";
              const matLabel =
                c.status === "harvested"
                  ? `Harvested ${formatDate(c.seed_harvested_at)}`
                  : c.days_to_maturity !== null && c.days_to_maturity !== undefined
                  ? c.days_to_maturity <= 0
                    ? "Mature / Ready!"
                    : `In ${c.days_to_maturity}d (${formatDate(c.expected_maturity_date)})`
                  : formatDate(c.expected_maturity_date);

              return `
                <div class="card">
                  <div class="card-body">
                    <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;">
                      <div>
                        <h3 class="plant-title" style="margin:0;">🧬 ${escapeHtml(c.name)}</h3>
                        <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:6px;">
                          <span class="badge badge-info">${escapeHtml(c.generation)}</span>
                          <span class="badge ${statusCls}">${escapeHtml(c.status)}</span>
                          ${c.minted_seed_batch ? `<span class="badge badge-ok">🌰 ${c.seed_count ?? c.minted_seed_batch.seed_count} seeds</span>` : ""}
                        </div>
                      </div>
                      <div style="display:flex;gap:6px;">
                        <button class="btn btn-sm" data-edit-cross="${escapeHtml(c.id)}" title="Edit cross">✏️</button>
                        <button class="btn btn-sm btn-danger" data-delete-cross="${escapeHtml(c.id)}" title="Delete cross">🗑</button>
                      </div>
                    </div>

                    <div class="log-chips" style="margin-top:12px;">
                      <span class="log-chip">♀️ <strong>${escapeHtml(c.mother_display)}</strong></span>
                      <span class="log-chip">×</span>
                      <span class="log-chip">♂️ <strong>${escapeHtml(c.father_display)}</strong></span>
                    </div>

                    <div class="stat-chips" style="margin-top:10px;">
                      <div class="stat-chip">
                        <div class="stat-chip-label">Pollinated</div>
                        <div class="stat-chip-val">${formatDate(c.pollination_date)}</div>
                      </div>
                      <div class="stat-chip">
                        <div class="stat-chip-label">Scope</div>
                        <div class="stat-chip-val">${escapeHtml((c.pollination_scope || "branch").replace("_", " "))}</div>
                      </div>
                      <div class="stat-chip">
                        <div class="stat-chip-label">Maturity</div>
                        <div class="stat-chip-val" style="font-size:12px;">${escapeHtml(matLabel)}</div>
                      </div>
                    </div>

                    ${c.branch_tag ? `<div style="font-size:12px;color:var(--igro-text-muted);margin-top:8px;">🏷 Tag: ${escapeHtml(c.branch_tag)}</div>` : ""}
                    ${c.goals ? `<div style="font-size:12px;color:var(--igro-text-muted);margin-top:4px;">🎯 ${escapeHtml(c.goals)}</div>` : ""}
                    ${c.notes ? `<p class="log-notes">${escapeHtml(c.notes)}</p>` : ""}

                    <div style="margin-top:14px;display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;">
                      <button class="btn btn-sm" data-view-pedigree="${escapeHtml(c.id)}">🌳 Pedigree Tree</button>
                      <button class="btn btn-sm btn-primary" data-harvest-seeds="${escapeHtml(c.id)}">🌰 ${c.minted_seed_batch ? "Update Seeds" : "Harvest & Mint Seeds"}</button>
                    </div>
                  </div>
                </div>
              `;
            })
            .join("")}</div>`
        : `<div class="empty-state">
            <div class="empty-state-emoji">🧬</div>
            <h3>No breeding crosses yet</h3>
            <p>Track F1/F2/S1/BX1 crosses linking Mother × Pollen Donor, estimate 6-week seed maturity, view multi-generation pedigree trees, and mint harvested seeds straight to your Seedbank.</p>
            <button class="btn btn-primary" id="btn-empty-cross">+ Create First Cross</button>
          </div>`;
    } else if (this._breedingSubTab === "phenos") {
      if (!hunts.length) {
        bodyHtml = `<div class="empty-state">
          <div class="empty-state-emoji">🔍</div>
          <h3>No pheno hunts yet</h3>
          <p>Group sibling plants from a cross or seed pack and compare vigor, stretch, resin, terpene profiles, flowering time, and yield side by side to select keepers &amp; breeders.</p>
          <button class="btn btn-primary" id="btn-empty-pheno-hunt">+ Start First Pheno Hunt</button>
        </div>`;
      } else {
        const activeHunt =
          hunts.find((h) => h.id === this._selectedPhenoHuntId) || hunts[0];
        this._selectedPhenoHuntId = activeHunt.id;
        const scores = activeHunt.scores || [];

        bodyHtml = `
          <div class="filter-bar" style="justify-content:space-between;align-items:center;">
            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
              <select class="select" id="select-pheno-hunt" style="min-width:240px;">
                ${hunts
                  .map(
                    (h) =>
                      `<option value="${escapeHtml(h.id)}" ${h.id === activeHunt.id ? "selected" : ""}>🔍 ${escapeHtml(h.name)} (${h.plant_count} phenos)</option>`
                  )
                  .join("")}
              </select>
              <button class="btn btn-sm" data-edit-pheno-hunt="${escapeHtml(activeHunt.id)}">✏️ Edit Hunt</button>
              <button class="btn btn-sm btn-danger" data-delete-pheno-hunt="${escapeHtml(activeHunt.id)}">🗑</button>
            </div>
            <button class="btn btn-sm btn-primary" data-add-pheno-score="${escapeHtml(activeHunt.id)}">+ Score Sibling Plant</button>
          </div>

          <div class="card" style="margin-bottom:14px;">
            <div class="card-body" style="padding:12px 16px;">
              <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
                <div>
                  <strong>${escapeHtml(activeHunt.name)}</strong>
                  <span style="color:var(--igro-text-muted);font-size:12px;margin-left:8px;">
                    ${escapeHtml([activeHunt.strain, activeHunt.breeder, activeHunt.breeding_cross_name ? `Cross: ${activeHunt.breeding_cross_name}` : ""].filter(Boolean).join(" · "))}
                  </span>
                </div>
                <div style="display:flex;gap:6px;flex-wrap:wrap;">
                  <span class="badge badge-ok">🏆 ${activeHunt.keeper_count} Keepers</span>
                  <span class="badge badge-warn">🧬 ${activeHunt.breeder_count} Breeders</span>
                  <span class="badge badge-danger">❌ ${activeHunt.cull_count} Culls</span>
                </div>
              </div>
              ${activeHunt.selection_goals ? `<div style="font-size:12px;color:var(--igro-text-muted);margin-top:6px;">🎯 Goals: ${escapeHtml(activeHunt.selection_goals)}</div>` : ""}
            </div>
          </div>

          ${
            scores.length
              ? `
            <div class="pheno-table-wrap">
              <table class="pheno-table">
                <thead>
                  <tr>
                    <th>Pheno / Plant</th>
                    <th>Status</th>
                    <th>Overall</th>
                    <th>Vigor</th>
                    <th>Stretch</th>
                    <th>Internode</th>
                    <th>Resin</th>
                    <th>Resist</th>
                    <th>Aroma / Terps</th>
                    <th>Flower</th>
                    <th>Yield</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  ${scores
                    .map((sc) => {
                      const sm = PHENO_STATUS_META[sc.status] || PHENO_STATUS_META.evaluating;
                      return `
                        <tr>
                          <td>
                            <div style="font-weight:700;">${escapeHtml(sc.pheno_code || "")} ${escapeHtml(sc.plant_name)}</div>
                            ${sc.plant_stage ? `<div style="font-size:11px;color:var(--igro-text-muted);">${escapeHtml(STAGE_META[sc.plant_stage]?.label || sc.plant_stage)}</div>` : ""}
                          </td>
                          <td><span class="badge ${sm.cls}">${sm.icon} ${sm.label}</span></td>
                          <td><strong>${sc.overall_score !== null && sc.overall_score !== undefined ? `${sc.overall_score}/5` : "—"}</strong></td>
                          <td>${sc.vigor ? `${sc.vigor}/5` : "—"}</td>
                          <td>${sc.stretch_factor ? `${sc.stretch_factor}x` : "—"}</td>
                          <td>${sc.internode_spacing ? escapeHtml(sc.internode_spacing) : "—"}</td>
                          <td>${sc.resin_density ? `${sc.resin_density}/5` : "—"}</td>
                          <td>${sc.pest_mold_resistance ? `${sc.pest_mold_resistance}/5` : "—"}</td>
                          <td style="white-space:normal;min-width:140px;">
                            ${sc.aroma_score ? `<strong>${sc.aroma_score}/5</strong> ` : ""}${escapeHtml(sc.terpene_notes || "—")}
                          </td>
                          <td>${sc.flower_days ? `${sc.flower_days}d` : "—"}</td>
                          <td>${sc.effective_yield_g !== null && sc.effective_yield_g !== undefined ? `${sc.effective_yield_g}g` : "—"}</td>
                          <td>
                            <div style="display:flex;gap:4px;">
                              <button class="btn btn-sm btn-icon" data-edit-pheno-score="${escapeHtml(sc.id)}" data-hunt-id="${escapeHtml(activeHunt.id)}" title="Edit score">✏️</button>
                              <button class="btn btn-sm btn-icon btn-danger" data-delete-pheno-score="${escapeHtml(sc.id)}" title="Remove from hunt">✕</button>
                            </div>
                          </td>
                        </tr>
                      `;
                    })
                    .join("")}
                </tbody>
              </table>
            </div>
          `
              : `<div class="empty-state">
                  <p>No sibling plants scored in <strong>${escapeHtml(activeHunt.name)}</strong> yet. Click <strong>+ Score Sibling Plant</strong> above to start comparing phenotypes!</p>
                </div>`
          }
        `;
      }
    } else if (this._breedingSubTab === "pollen") {
      bodyHtml = pollen.length
        ? `<div class="grid-cards">${pollen
            .map((pb) => {
              const dm = POLLEN_DONOR_META[pb.donor_type] || POLLEN_DONOR_META.other;
              const viabCls =
                pb.viability === "high"
                  ? "badge-ok"
                  : pb.viability === "medium"
                  ? "badge-warn"
                  : pb.viability === "low"
                  ? "badge-danger"
                  : "badge-muted";
              return `
                <div class="card">
                  <div class="card-body">
                    <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;">
                      <div>
                        <h3 class="plant-title" style="margin:0;">🌼 ${escapeHtml(pb.name)}</h3>
                        <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:6px;">
                          <span class="badge ${dm.cls}">${dm.icon} ${dm.label}</span>
                          <span class="badge ${viabCls}">Viability: ${escapeHtml((pb.viability || "high").toUpperCase())}</span>
                        </div>
                      </div>
                      <div style="display:flex;gap:6px;">
                        <button class="btn btn-sm" data-edit-pollen="${escapeHtml(pb.id)}">✏️</button>
                        <button class="btn btn-sm btn-danger" data-delete-pollen="${escapeHtml(pb.id)}">🗑</button>
                      </div>
                    </div>
                    <div class="meta-row" style="margin-top:12px;">
                      ${pb.donor_plant_name ? `<span>🪴 ${escapeHtml(pb.donor_plant_name)}</span>` : ""}
                      ${pb.donor_strain ? `<span>🌱 ${escapeHtml(pb.donor_strain)}</span>` : ""}
                      <span>📅 ${formatDate(pb.collected_at)}</span>
                    </div>
                    ${
                      pb.storage_method || pb.storage_location
                        ? `<div class="log-chips">
                            ${pb.storage_method ? `<span class="log-chip">❄️ ${escapeHtml(pb.storage_method)}</span>` : ""}
                            ${pb.storage_location ? `<span class="log-chip">📍 ${escapeHtml(pb.storage_location)}</span>` : ""}
                          </div>`
                        : ""
                    }
                    ${pb.notes ? `<p class="log-notes">${escapeHtml(pb.notes)}</p>` : ""}
                  </div>
                </div>
              `;
            })
            .join("")}</div>`
        : `<div class="empty-state">
            <div class="empty-state-emoji">🌼</div>
            <h3>Pollen Vault is empty</h3>
            <p>Store male or STS/Colloidal Silver reversed pollen batches with collection dates, freezer locations, and viability status.</p>
            <button class="btn btn-primary" id="btn-empty-pollen">+ Store First Pollen Batch</button>
          </div>`;
    } else if (this._breedingSubTab === "seeds") {
      bodyHtml = seeds.length
        ? `<div class="grid-cards">${seeds
            .map(
              (sb) => `
            <div class="card">
              <div class="card-body">
                <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;">
                  <div>
                    <h3 class="plant-title" style="margin:0;">🌰 ${escapeHtml(sb.name)}</h3>
                    <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:6px;">
                      ${sb.generation ? `<span class="badge badge-info">${escapeHtml(sb.generation)}</span>` : ""}
                      <span class="badge ${sb.seed_type === "feminized" ? "badge-ok" : "badge-muted"}">${escapeHtml(sb.seed_type)}</span>
                      <span class="badge badge-warn">${sb.seed_count} seeds</span>
                    </div>
                  </div>
                  <button class="btn btn-sm btn-danger" data-delete-seed-batch="${escapeHtml(sb.id)}">🗑</button>
                </div>
                ${sb.lineage_summary ? `<div style="font-size:13px;font-weight:600;margin-top:10px;">🧬 ${escapeHtml(sb.lineage_summary)}</div>` : ""}
                <div class="meta-row" style="margin-top:8px;margin-bottom:0;">
                  ${sb.breeder ? `<span>🏷 ${escapeHtml(sb.breeder)}</span>` : ""}
                  ${sb.harvested_at ? `<span>📅 ${formatDate(sb.harvested_at)}</span>` : ""}
                  ${sb.storage_location ? `<span>📍 ${escapeHtml(sb.storage_location)}</span>` : ""}
                </div>
                ${sb.notes ? `<p class="log-notes">${escapeHtml(sb.notes)}</p>` : ""}
              </div>
            </div>
          `
            )
            .join("")}</div>`
        : `<div class="empty-state">
            <div class="empty-state-emoji">🌰</div>
            <h3>No minted seed batches yet</h3>
            <p>Harvest mature seeds from any Breeding Cross to automatically mint a Seedbank batch with full pedigree lineage.</p>
          </div>`;
    }

    return `
      <div class="kpi-grid">
        <div class="kpi-card">
          <div>
            <div class="kpi-label">Breeding Crosses</div>
            <div class="kpi-value">${crosses.length}</div>
          </div>
          <span class="kpi-emoji">🧬</span>
        </div>
        <div class="kpi-card">
          <div>
            <div class="kpi-label">Pheno Hunts</div>
            <div class="kpi-value">${hunts.length}</div>
          </div>
          <span class="kpi-emoji">🔍</span>
        </div>
        <div class="kpi-card">
          <div>
            <div class="kpi-label">Pollen Vault</div>
            <div class="kpi-value">${pollen.length}</div>
          </div>
          <span class="kpi-emoji">🌼</span>
        </div>
        <div class="kpi-card">
          <div>
            <div class="kpi-label">Minted Seed Batches</div>
            <div class="kpi-value">${seeds.length}</div>
          </div>
          <span class="kpi-emoji">🌰</span>
        </div>
      </div>

      <div class="section-header">
        <div class="nav-tabs">
          <button class="nav-tab ${this._breedingSubTab === "crosses" ? "active" : ""}" data-breeding-subtab="crosses">🧬 Crosses (${crosses.length})</button>
          <button class="nav-tab ${this._breedingSubTab === "phenos" ? "active" : ""}" data-breeding-subtab="phenos">🔍 Pheno Hunts (${hunts.length})</button>
          <button class="nav-tab ${this._breedingSubTab === "pollen" ? "active" : ""}" data-breeding-subtab="pollen">🌼 Pollen Vault (${pollen.length})</button>
          <button class="nav-tab ${this._breedingSubTab === "seeds" ? "active" : ""}" data-breeding-subtab="seeds">🌰 Minted Seeds (${seeds.length})</button>
        </div>
        ${headerAction}
      </div>
      ${bodyHtml}
    `;
  }

  _renderArchive() {
    const s = this._state.summary || {};
    const cycles = this._state.grow_cycles || [];
    const f = this._filters;
    const totalDryG = s.total_dry_yield_g || 0;
    const totalDryOz = (totalDryG / 28.349523125).toFixed(2);

    let harvests = [...(this._state.harvests || [])];
    if (f.archiveCycle) {
      harvests = harvests.filter((h) => h.grow_cycle_id === f.archiveCycle);
    }
    if (f.archiveKeepersOnly) {
      harvests = harvests.filter((h) => h.is_keeper);
    }
    if (f.archiveSearch) {
      const q = f.archiveSearch.toLowerCase();
      harvests = harvests.filter((h) =>
        `${h.plant_name || ""} ${h.strain || ""} ${h.breeder || ""} ${h.aroma_notes || ""} ${h.effect_notes || ""}`
          .toLowerCase()
          .includes(q)
      );
    }
    if (f.archiveSort === "yield") {
      harvests.sort((a, b) => (b.dry_weight_g || 0) - (a.dry_weight_g || 0));
    } else if (f.archiveSort === "rating") {
      harvests.sort((a, b) => (b.rating || 0) - (a.rating || 0));
    }

    return `
      <div class="kpi-grid">
        <div class="kpi-card">
          <div>
            <div class="kpi-label">Harvested Plants</div>
            <div class="kpi-value">${s.total_harvests ?? harvests.length}</div>
          </div>
          <span class="kpi-emoji">🌾</span>
        </div>
        <div class="kpi-card">
          <div>
            <div class="kpi-label">Total Dry Yield</div>
            <div class="kpi-value">${totalDryG}g <span style="font-size:14px;color:var(--igro-text-muted);font-weight:500;">(${totalDryOz} oz)</span></div>
          </div>
          <span class="kpi-emoji">⚖️</span>
        </div>
        <div class="kpi-card">
          <div>
            <div class="kpi-label">Avg Dry / Plant</div>
            <div class="kpi-value">${s.avg_dry_yield_g !== null && s.avg_dry_yield_g !== undefined ? `${s.avg_dry_yield_g}g` : "—"}</div>
          </div>
          <span class="kpi-emoji">📈</span>
        </div>
        <div class="kpi-card">
          <div>
            <div class="kpi-label">Keeper Phenos</div>
            <div class="kpi-value">${s.keeper_count ?? 0}</div>
          </div>
          <span class="kpi-emoji">🏆</span>
        </div>
      </div>

      <div class="section-header">
        <h2 class="section-title">🗓 Grow Cycles (${cycles.length})</h2>
        <button class="btn btn-sm btn-primary" id="btn-add-cycle">+ New Grow Cycle</button>
      </div>
      ${
        cycles.length
          ? `<div class="grid-cards" style="margin-bottom:22px;">${cycles
              .map(
                (c) => `
              <div class="card">
                <div class="card-body">
                  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;">
                    <div>
                      <h3 class="plant-title" style="margin:0;">🗓 ${escapeHtml(c.name)}</h3>
                      <div class="plant-subtitle" style="margin:3px 0 0;">
                        ${formatDate(c.started_at)}${c.ended_at ? ` → ${formatDate(c.ended_at)}` : " · Ongoing"}
                      </div>
                    </div>
                    <div style="display:flex;gap:6px;align-items:center;">
                      <span class="badge ${c.status === "active" ? "badge-ok" : "badge-muted"}">${escapeHtml(c.status)}</span>
                      <button class="btn btn-sm" data-edit-cycle="${escapeHtml(c.id)}">✏️</button>
                      <button class="btn btn-sm btn-danger" data-delete-cycle="${escapeHtml(c.id)}">🗑</button>
                    </div>
                  </div>
                  <div class="stat-chips" style="margin-top:12px;">
                    <div class="stat-chip">
                      <div class="stat-chip-label">Plants</div>
                      <div class="stat-chip-val">${c.plant_count ?? 0}</div>
                    </div>
                    <div class="stat-chip">
                      <div class="stat-chip-label">Harvested</div>
                      <div class="stat-chip-val">${c.harvest_count ?? 0}</div>
                    </div>
                    <div class="stat-chip">
                      <div class="stat-chip-label">Dry Yield</div>
                      <div class="stat-chip-val">${c.total_dry_yield_g ?? 0}g</div>
                    </div>
                  </div>
                  ${c.notes ? `<p class="log-notes">${escapeHtml(c.notes)}</p>` : ""}
                </div>
              </div>
            `
              )
              .join("")}</div>`
          : `<div class="empty-state" style="padding:24px;margin-bottom:22px;">
              <p style="margin:0;">Group plants into named runs (e.g., <em>Winter 2026 Run</em>) with <strong>+ New Grow Cycle</strong>.</p>
            </div>`
      }

      <div class="section-header">
        <h2 class="section-title">🏆 Harvest Archive & Strain Comparison (${harvests.length})</h2>
      </div>
      <div class="filter-bar">
        <input class="input" id="filter-archive-search" placeholder="Search strain, breeder, aroma, effects..." value="${escapeHtml(f.archiveSearch)}" style="min-width:230px;" />
        <select class="select" id="filter-archive-cycle">
          <option value="">All Grow Cycles</option>
          ${cycles.map((c) => `<option value="${escapeHtml(c.id)}" ${f.archiveCycle === c.id ? "selected" : ""}>${escapeHtml(c.name)}</option>`).join("")}
        </select>
        <select class="select" id="filter-archive-sort">
          <option value="newest" ${f.archiveSort === "newest" ? "selected" : ""}>Sort: Newest Harvest</option>
          <option value="yield" ${f.archiveSort === "yield" ? "selected" : ""}>Sort: Highest Dry Yield</option>
          <option value="rating" ${f.archiveSort === "rating" ? "selected" : ""}>Sort: Highest Rating</option>
        </select>
        <label style="display:inline-flex;align-items:center;gap:6px;font-size:13px;font-weight:600;cursor:pointer;">
          <input type="checkbox" id="filter-archive-keepers" ${f.archiveKeepersOnly ? "checked" : ""} />
          <span>🏆 Keepers Only</span>
        </label>
      </div>

      ${
        harvests.length
          ? `<div class="grid-cards">${harvests
              .map(
                (h) => `
              <div class="card">
                <div class="plant-cover" style="height:130px;">
                  ${
                    h.cover_photo_url
                      ? `<img src="${escapeHtml(h.cover_photo_url)}" alt="${escapeHtml(h.plant_name || "Harvest")}" loading="lazy" />`
                      : `<span class="plant-cover-placeholder">🌾</span>`
                  }
                  <div class="plant-cover-overlay">
                    <div style="display:flex;gap:6px;flex-wrap:wrap;">
                      ${h.is_keeper ? `<span class="badge badge-ok" style="background:rgba(15,23,42,0.82);color:#4ade80;">🏆 Keeper</span>` : ""}
                      ${h.rating ? `<span class="plant-day-pill">${"★".repeat(h.rating)}</span>` : ""}
                    </div>
                    <span class="plant-day-pill">${formatDate(h.harvested_at)}</span>
                  </div>
                </div>
                <div class="card-body">
                  <h3 class="plant-title">${escapeHtml(h.plant_name || "Plant")}</h3>
                  <div class="plant-subtitle">
                    ${escapeHtml([h.strain, h.breeder, h.grow_cycle_name].filter(Boolean).join(" · ") || (h.medium || "soil"))}
                  </div>
                  <div class="stat-chips">
                    <div class="stat-chip">
                      <div class="stat-chip-label">Dry Yield</div>
                      <div class="stat-chip-val" style="color:var(--igro-accent);">${h.dry_weight_g !== null && h.dry_weight_g !== undefined ? `${h.dry_weight_g}g` : "—"}</div>
                    </div>
                    <div class="stat-chip">
                      <div class="stat-chip-label">Retention</div>
                      <div class="stat-chip-val">${h.retention_pct !== null && h.retention_pct !== undefined ? `${h.retention_pct}%` : "—"}</div>
                    </div>
                    <div class="stat-chip">
                      <div class="stat-chip-label">g / Watt</div>
                      <div class="stat-chip-val">${h.grams_per_watt !== null && h.grams_per_watt !== undefined ? h.grams_per_watt : "—"}</div>
                    </div>
                  </div>
                  ${
                    h.aroma_notes || h.effect_notes
                      ? `<div class="log-chips" style="margin-top:10px;">
                          ${h.aroma_notes ? `<span class="log-chip">👃 ${escapeHtml(h.aroma_notes)}</span>` : ""}
                          ${h.effect_notes ? `<span class="log-chip">✨ ${escapeHtml(h.effect_notes)}</span>` : ""}
                        </div>`
                      : ""
                  }
                  <div style="margin-top:14px;display:flex;justify-content:space-between;gap:6px;flex-wrap:wrap;">
                    <button class="btn btn-sm" data-open-plant="${escapeHtml(h.plant_id)}">🪴 Open Plant</button>
                    <div style="display:flex;gap:6px;">
                      <button class="btn btn-sm" data-export-report-md="${escapeHtml(h.plant_id)}">📄 MD</button>
                      <button class="btn btn-sm" data-record-harvest="${escapeHtml(h.plant_id)}">✏️</button>
                    </div>
                  </div>
                </div>
              </div>
            `
              )
              .join("")}</div>`
          : `<div class="empty-state">
              <div class="empty-state-emoji">🏆</div>
              <h3>No harvested plants yet</h3>
              <p>Open any plant and click <strong>🌾 Record Harvest</strong> to track wet/dry weights, curing jars, and compare strains here.</p>
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

    // Edit / Complete / Delete log
    const findLogById = (logId) =>
      [...this._journalLogs, ...this._plantLogs, ...(this._state.recent_logs || []), ...(this._state.planned_logs || [])].find(
        (l) => l.id === logId
      );

    root.querySelectorAll("[data-edit-log]").forEach((el) => {
      el.addEventListener("click", () => {
        const lg = findLogById(el.dataset.editLog);
        if (lg) {
          this._modal = { type: "log", data: { ...lg } };
          this._render();
        }
      });
    });

    root.querySelectorAll("[data-complete-log]").forEach((el) => {
      el.addEventListener("click", async () => {
        const logId = el.dataset.completeLog;
        try {
          await this._api.completeLog(logId);
          await this._refreshState();
          this._showToast("Marked entry as completed!");
        } catch (err) {
          this._showToast(`Error: ${err.message || err}`, true);
        }
      });
    });

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

    // Retrospective Stage History & Scheduled Stage Transitions
    root.getElementById("btn-add-stage-history")?.addEventListener("click", () => {
      const plant = (this._state.plants || []).find((p) => p.id === this._selectedPlantId);
      if (plant) {
        this._modal = { type: "stage_history", data: { plant, history: null } };
        this._render();
      }
    });

    root.querySelectorAll("[data-edit-stage-history]").forEach((el) => {
      el.addEventListener("click", () => {
        const plant = (this._state.plants || []).find((p) => p.id === this._selectedPlantId);
        const hist = (plant?.stage_history || []).find((h) => h.id === el.dataset.editStageHistory);
        if (plant && hist) {
          this._modal = { type: "stage_history", data: { plant, history: hist } };
          this._render();
        }
      });
    });

    root.querySelectorAll("[data-delete-stage-history]").forEach((el) => {
      el.addEventListener("click", () => {
        const histId = el.dataset.deleteStageHistory;
        this._openConfirm({
          title: "🗑 Delete Stage History Entry",
          message: "Remove this stage entry? Remaining stages will automatically re-chain chronologically.",
          confirmLabel: "Delete Stage Entry",
          onConfirm: async () => {
            await this._api.deleteStageHistory(histId);
            await this._refreshState();
            this._showToast("Stage history updated");
          },
        });
      });
    });

    root.querySelectorAll("[data-apply-sched-stage]").forEach((el) => {
      el.addEventListener("click", async () => {
        try {
          await this._api.applyScheduledStageChange(el.dataset.applySchedStage);
          await this._refreshState();
          this._showToast("Scheduled stage transition applied!");
        } catch (err) {
          this._showToast(`Error: ${err.message || err}`, true);
        }
      });
    });

    root.querySelectorAll("[data-cancel-sched-stage]").forEach((el) => {
      el.addEventListener("click", () => {
        const schedId = el.dataset.cancelSchedStage;
        this._openConfirm({
          title: "Cancel Scheduled Stage Change",
          message: "Cancel this upcoming scheduled stage transition?",
          confirmLabel: "Cancel Transition",
          onConfirm: async () => {
            await this._api.cancelScheduledStageChange(schedId);
            await this._refreshState();
            this._showToast("Scheduled transition cancelled");
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
    root.getElementById("filter-log-status")?.addEventListener("change", async (e) => {
      this._filters.logStatus = e.target.value;
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

    // Archive filters & Grow Cycle / Harvest / Curing / Export actions
    root.getElementById("filter-archive-search")?.addEventListener("input", (e) => {
      this._filters.archiveSearch = e.target.value;
      this._render();
      const inp = this.shadowRoot.getElementById("filter-archive-search");
      if (inp) {
        inp.focus();
        inp.setSelectionRange(inp.value.length, inp.value.length);
      }
    });
    root.getElementById("filter-archive-cycle")?.addEventListener("change", (e) => {
      this._filters.archiveCycle = e.target.value;
      this._render();
    });
    root.getElementById("filter-archive-sort")?.addEventListener("change", (e) => {
      this._filters.archiveSort = e.target.value;
      this._render();
    });
    root.getElementById("filter-archive-keepers")?.addEventListener("change", (e) => {
      this._filters.archiveKeepersOnly = e.target.checked;
      this._render();
    });

    root.getElementById("btn-add-cycle")?.addEventListener("click", () => {
      this._modal = { type: "cycle", data: null };
      this._render();
    });

    root.querySelectorAll("[data-edit-cycle]").forEach((el) => {
      el.addEventListener("click", () => {
        const cyc = (this._state.grow_cycles || []).find((c) => c.id === el.dataset.editCycle);
        if (cyc) {
          this._modal = { type: "cycle", data: cyc };
          this._render();
        }
      });
    });

    root.querySelectorAll("[data-delete-cycle]").forEach((el) => {
      el.addEventListener("click", () => {
        const cyc = (this._state.grow_cycles || []).find((c) => c.id === el.dataset.deleteCycle);
        if (!cyc) return;
        this._openConfirm({
          title: "🗑 Delete Grow Cycle",
          message: `Delete grow cycle "${cyc.name}"? Plants and harvests inside will remain intact.`,
          confirmLabel: "Delete Cycle",
          onConfirm: async () => {
            await this._api.deleteGrowCycle(cyc.id);
            await this._refreshState();
            this._showToast(`Deleted cycle "${cyc.name}"`);
          },
        });
      });
    });

    root.querySelectorAll("[data-record-harvest]").forEach((el) => {
      el.addEventListener("click", () => {
        const plant = (this._state.plants || []).find((p) => p.id === el.dataset.recordHarvest);
        if (plant) {
          this._modal = { type: "harvest", data: { plant, harvest: plant.harvest || null } };
          this._render();
        }
      });
    });

    root.querySelectorAll("[data-delete-harvest]").forEach((el) => {
      el.addEventListener("click", () => {
        const harvestId = el.dataset.deleteHarvest;
        this._openConfirm({
          title: "🗑 Delete Harvest Record",
          message: "Delete this harvest record and its curing jar logs?",
          confirmLabel: "Delete Harvest",
          onConfirm: async () => {
            await this._api.deleteHarvest(harvestId);
            await this._refreshState();
            this._showToast("Harvest record deleted");
          },
        });
      });
    });

    root.querySelectorAll("[data-add-curing]").forEach((el) => {
      el.addEventListener("click", () => {
        const harvestId = el.dataset.addCuring;
        const harvest = (this._state.harvests || []).find((h) => h.id === harvestId);
        this._modal = {
          type: "curing",
          data: { harvest: harvest || { id: harvestId }, plantName: el.dataset.plantName || "" },
        };
        this._render();
      });
    });

    root.querySelectorAll("[data-delete-curing]").forEach((el) => {
      el.addEventListener("click", () => {
        const clogId = el.dataset.deleteCuring;
        this._openConfirm({
          title: "🗑 Delete Curing Entry",
          message: "Delete this jar check / burp log?",
          confirmLabel: "Delete Entry",
          onConfirm: async () => {
            await this._api.deleteCuringLog(clogId);
            await this._refreshState();
            this._showToast("Curing entry deleted");
          },
        });
      });
    });

    root.querySelectorAll("[data-export-report-md]").forEach((el) => {
      el.addEventListener("click", async () => {
        try {
          const res = await this._api.exportPlantReport(el.dataset.exportReportMd);
          downloadTextFile(`${res.filename_base}.md`, res.markdown, "text/markdown;charset=utf-8");
          this._showToast("Downloaded Markdown grow report!");
        } catch (err) {
          this._showToast(`Export error: ${err.message || err}`, true);
        }
      });
    });

    root.querySelectorAll("[data-export-report-json]").forEach((el) => {
      el.addEventListener("click", async () => {
        try {
          const res = await this._api.exportPlantReport(el.dataset.exportReportJson);
          downloadTextFile(
            `${res.filename_base}.json`,
            JSON.stringify(res.json_data, null, 2),
            "application/json;charset=utf-8"
          );
          this._showToast("Downloaded JSON grow report!");
        } catch (err) {
          this._showToast(`Export error: ${err.message || err}`, true);
        }
      });
    });

    // Reminders actions
    const openNewReminder = (defaults = {}) => {
      this._modal = { type: "reminder", data: defaults };
      this._render();
    };
    root.getElementById("btn-add-reminder")?.addEventListener("click", () => openNewReminder());
    root.getElementById("btn-add-reminder-overview")?.addEventListener("click", () => openNewReminder());
    root.getElementById("btn-empty-reminder")?.addEventListener("click", () => openNewReminder());

    root.querySelectorAll("[data-open-reminders-tab]").forEach((el) => {
      el.addEventListener("click", async () => {
        this._journalSubTab = "reminders";
        await this._switchTab("journal");
      });
    });

    root.querySelectorAll("[data-plant-reminder]").forEach((el) => {
      el.addEventListener("click", () => {
        const plant = (this._state.plants || []).find((p) => p.id === el.dataset.plantReminder);
        openNewReminder({
          plant_id: plant?.id || null,
          environment_id: plant?.environment_id || null,
          title: plant ? `Water ${plant.name}` : "",
          action_type: "water",
        });
      });
    });

    root.querySelectorAll("[data-complete-reminder]").forEach((el) => {
      el.addEventListener("click", async () => {
        const remId = el.dataset.completeReminder;
        try {
          const res = await this._api.completeReminder(remId);
          await this._refreshState();
          const msg = res?.created_log
            ? "Task completed & logged to journal!"
            : "Reminder completed!";
          this._showToast(msg);
        } catch (err) {
          this._showToast(`Error: ${err.message || err}`, true);
        }
      });
    });

    root.querySelectorAll("[data-edit-reminder]").forEach((el) => {
      el.addEventListener("click", () => {
        const rem = (this._state.reminders || []).find((r) => r.id === el.dataset.editReminder);
        if (rem) {
          this._modal = { type: "reminder", data: rem };
          this._render();
        }
      });
    });

    root.querySelectorAll("[data-delete-reminder]").forEach((el) => {
      el.addEventListener("click", () => {
        const rem = (this._state.reminders || []).find((r) => r.id === el.dataset.deleteReminder);
        if (!rem) return;
        this._openConfirm({
          title: "🗑 Delete Reminder",
          message: `Delete reminder "${rem.title}" permanently?`,
          confirmLabel: "Delete Reminder",
          onConfirm: async () => {
            await this._api.deleteReminder(rem.id);
            await this._refreshState();
            this._showToast(`Deleted "${rem.title}"`);
          },
        });
      });
    });

    // Breeding Program, Pollen Vault & Pheno-Hunt actions
    root.querySelectorAll("[data-breeding-subtab]").forEach((el) => {
      el.addEventListener("click", () => {
        this._breedingSubTab = el.dataset.breedingSubtab;
        this._render();
      });
    });

    const openNewPollen = () => {
      this._modal = { type: "pollen", data: null };
      this._render();
    };
    const openNewCross = () => {
      this._modal = { type: "cross", data: null };
      this._render();
    };
    const openNewPhenoHunt = () => {
      this._modal = { type: "pheno_hunt", data: null };
      this._render();
    };
    root.getElementById("btn-add-pollen")?.addEventListener("click", openNewPollen);
    root.getElementById("btn-empty-pollen")?.addEventListener("click", openNewPollen);
    root.getElementById("btn-add-cross")?.addEventListener("click", openNewCross);
    root.getElementById("btn-empty-cross")?.addEventListener("click", openNewCross);
    root.getElementById("btn-add-pheno-hunt")?.addEventListener("click", openNewPhenoHunt);
    root.getElementById("btn-empty-pheno-hunt")?.addEventListener("click", openNewPhenoHunt);

    root.querySelectorAll("[data-edit-pollen]").forEach((el) => {
      el.addEventListener("click", () => {
        const pb = (this._state.pollen_batches || []).find((p) => p.id === el.dataset.editPollen);
        if (pb) {
          this._modal = { type: "pollen", data: pb };
          this._render();
        }
      });
    });

    root.querySelectorAll("[data-delete-pollen]").forEach((el) => {
      el.addEventListener("click", () => {
        const pb = (this._state.pollen_batches || []).find((p) => p.id === el.dataset.deletePollen);
        if (!pb) return;
        this._openConfirm({
          title: "🗑 Delete Pollen Batch",
          message: `Delete pollen batch "${pb.name}" from the vault?`,
          confirmLabel: "Delete Pollen",
          onConfirm: async () => {
            await this._api.deletePollenBatch(pb.id);
            await this._refreshState();
            this._showToast(`Deleted "${pb.name}"`);
          },
        });
      });
    });

    root.querySelectorAll("[data-edit-cross]").forEach((el) => {
      el.addEventListener("click", () => {
        const cr = (this._state.breeding_crosses || []).find((c) => c.id === el.dataset.editCross);
        if (cr) {
          this._modal = { type: "cross", data: cr };
          this._render();
        }
      });
    });

    root.querySelectorAll("[data-delete-cross]").forEach((el) => {
      el.addEventListener("click", () => {
        const cr = (this._state.breeding_crosses || []).find((c) => c.id === el.dataset.deleteCross);
        if (!cr) return;
        this._openConfirm({
          title: "🗑 Delete Breeding Cross",
          message: `Delete breeding cross "${cr.name}"?`,
          confirmLabel: "Delete Cross",
          onConfirm: async () => {
            await this._api.deleteBreedingCross(cr.id);
            await this._refreshState();
            this._showToast(`Deleted "${cr.name}"`);
          },
        });
      });
    });

    root.querySelectorAll("[data-harvest-seeds]").forEach((el) => {
      el.addEventListener("click", () => {
        const cr = (this._state.breeding_crosses || []).find((c) => c.id === el.dataset.harvestSeeds);
        if (cr) {
          this._modal = { type: "harvest_seeds", data: cr };
          this._render();
        }
      });
    });

    root.querySelectorAll("[data-view-pedigree]").forEach((el) => {
      el.addEventListener("click", () => {
        const cr = (this._state.breeding_crosses || []).find((c) => c.id === el.dataset.viewPedigree);
        if (cr) {
          this._modal = { type: "pedigree", data: cr };
          this._render();
        }
      });
    });

    root.querySelectorAll("[data-delete-seed-batch]").forEach((el) => {
      el.addEventListener("click", () => {
        const sb = (this._state.seed_batches || []).find((s) => s.id === el.dataset.deleteSeedBatch);
        if (!sb) return;
        this._openConfirm({
          title: "🗑 Delete Seed Batch",
          message: `Delete minted seed batch "${sb.name}"?`,
          confirmLabel: "Delete Seeds",
          onConfirm: async () => {
            await this._api.deleteSeedBatch(sb.id);
            await this._refreshState();
            this._showToast(`Deleted "${sb.name}"`);
          },
        });
      });
    });

    root.getElementById("select-pheno-hunt")?.addEventListener("change", (e) => {
      this._selectedPhenoHuntId = e.target.value;
      this._render();
    });

    root.querySelectorAll("[data-edit-pheno-hunt]").forEach((el) => {
      el.addEventListener("click", () => {
        const hunt = (this._state.pheno_hunts || []).find((h) => h.id === el.dataset.editPhenoHunt);
        if (hunt) {
          this._modal = { type: "pheno_hunt", data: hunt };
          this._render();
        }
      });
    });

    root.querySelectorAll("[data-delete-pheno-hunt]").forEach((el) => {
      el.addEventListener("click", () => {
        const hunt = (this._state.pheno_hunts || []).find((h) => h.id === el.dataset.deletePhenoHunt);
        if (!hunt) return;
        this._openConfirm({
          title: "🗑 Delete Pheno Hunt",
          message: `Delete pheno hunt "${hunt.name}" and all of its trait scorecards?`,
          confirmLabel: "Delete Hunt",
          onConfirm: async () => {
            await this._api.deletePhenoHunt(hunt.id);
            this._selectedPhenoHuntId = null;
            await this._refreshState();
            this._showToast(`Deleted "${hunt.name}"`);
          },
        });
      });
    });

    root.querySelectorAll("[data-add-pheno-score]").forEach((el) => {
      el.addEventListener("click", () => {
        const hunt = (this._state.pheno_hunts || []).find((h) => h.id === el.dataset.addPhenoScore);
        if (hunt) {
          this._modal = { type: "pheno_score", data: { hunt, score: null } };
          this._render();
        }
      });
    });

    root.querySelectorAll("[data-edit-pheno-score]").forEach((el) => {
      el.addEventListener("click", () => {
        const hunt = (this._state.pheno_hunts || []).find((h) => h.id === el.dataset.huntId);
        const score = (hunt?.scores || []).find((s) => s.id === el.dataset.editPhenoScore);
        if (hunt && score) {
          this._modal = { type: "pheno_score", data: { hunt, score } };
          this._render();
        }
      });
    });

    root.querySelectorAll("[data-delete-pheno-score]").forEach((el) => {
      el.addEventListener("click", () => {
        const scoreId = el.dataset.deletePhenoScore;
        this._openConfirm({
          title: "Remove Plant from Pheno Hunt",
          message: "Remove this plant's phenotype scorecard from the hunt?",
          confirmLabel: "Remove Scorecard",
          onConfirm: async () => {
            await this._api.deletePhenoScore(scoreId);
            await this._refreshState();
            this._showToast("Phenotype scorecard removed");
          },
        });
      });
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
        "light_wattage",
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

    // Live auto-scaling mix preview & future-date status sync inside #log-form
    const logFormEl = root.getElementById("log-form");
    if (logFormEl) {
      logFormEl.addEventListener("input", updateScaledMixPreview);
      logFormEl.addEventListener("change", (e) => {
        if (e.target.id === "log-datetime-input") {
          const picked = new Date(e.target.value);
          const statusSel = root.getElementById("log-status-select");
          if (statusSel && !Number.isNaN(picked.getTime())) {
            statusSel.value = picked.getTime() - Date.now() > 300000 ? "planned" : "completed";
          }
        } else if (e.target.name === "plant_id") {
          const volVal = logFormEl.querySelector("[name='water_volume_ml']")?.value || "";
          const dtVal = logFormEl.querySelector("[name='logged_at']")?.value || "";
          const stVal = logFormEl.querySelector("[name='status']")?.value || "completed";
          this._modal.data = {
            ...this._modal.data,
            plant_id: e.target.value,
            logged_at_local: dtVal,
            status: stVal,
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
      const loggedAtIso = fromLocalDatetimeInput(fd.get("logged_at"));
      const data = {
        log_type: fd.get("log_type"),
        plant_id: fd.get("plant_id") || null,
        title: fd.get("title") || null,
        notes: fd.get("notes") || null,
        training_method: fd.get("training_method") || null,
        status: fd.get("status") || "completed",
      };
      if (loggedAtIso) data.logged_at = loggedAtIso;
      for (const nf of ["water_volume_ml", "ph", "ec", "ppm", "runoff_ph", "runoff_ec", "height_cm"]) {
        const val = fd.get(nf);
        if (val !== null && val !== "") {
          data[nf] = parseFloat(val);
        } else if (this._modal.data?.id) {
          data[nf] = null;
        }
      }
      const rawNutrients = collectNutrientRows(form);
      if (rawNutrients.length) {
        data.nutrients = scaleNutrientsForVolume(rawNutrients, data.water_volume_ml);
      } else if (this._modal.data?.id) {
        data.nutrients = [];
      }

      try {
        if (this._modal.data?.id) {
          await this._api.updateLog(this._modal.data.id, data);
          this._showToast("Journal entry updated!");
        } else {
          await this._api.createLog(data);
          this._showToast(data.status === "planned" ? "Planned entry scheduled!" : "Journal entry saved!");
        }
        this._modal = null;
        await this._refreshState();
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
      if (mode === "upload") {
        const rawTaken = fd.get("taken_at");
        if (rawTaken) {
          const iso = fromLocalDatetimeInput(rawTaken);
          if (iso) fd.set("taken_at", iso);
        } else {
          fd.delete("taken_at");
        }
      }
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

    // Stage transition modal (past/now/future scheduling)
    const stageDateInp = root.getElementById("stage-date-input");
    if (stageDateInp) {
      const updateStageModeUi = () => {
        const todayDefault = root.querySelector("#stage-form [name='today_default']")?.value || "";
        const isFuture = Boolean(stageDateInp.value && todayDefault && stageDateInp.value > todayDefault);
        const schedBox = root.getElementById("stage-schedule-options");
        const submitBtn = root.getElementById("stage-submit-btn");
        if (schedBox) schedBox.style.display = isFuture ? "block" : "none";
        if (submitBtn) {
          const lbl = submitBtn.dataset.targetLabel || "Stage";
          submitBtn.textContent = isFuture ? `📅 Schedule Move to ${lbl}` : `Move to ${lbl}`;
        }
      };
      stageDateInp.addEventListener("change", updateStageModeUi);
      updateStageModeUi();
    }

    root.getElementById("stage-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const notes = (fd.get("notes") || "").trim() || null;
      const pickedDate = (fd.get("changed_at") || "").trim();
      const todayDefault = fd.get("today_default") || "";
      const isFuture = Boolean(pickedDate && todayDefault && pickedDate > todayDefault);
      const { plant, targetStage } = this._modal.data;
      try {
        if (isFuture) {
          const autoApply = fd.get("auto_apply") !== null;
          await this._api.scheduleStageChange(plant.id, targetStage, pickedDate, autoApply, notes);
          this._modal = null;
          await this._refreshState();
          this._showToast(`Scheduled ${plant.name} → ${STAGE_META[targetStage]?.label || targetStage} on ${formatDate(pickedDate)}`);
        } else {
          const changedAt = pickedDate && pickedDate !== todayDefault ? pickedDate : null;
          await this._api.setPlantStage(plant.id, targetStage, notes, changedAt);
          this._modal = null;
          await this._refreshState();
          this._showToast(`Moved ${plant.name} to ${STAGE_META[targetStage]?.label || targetStage}`);
        }
      } catch (err) {
        this._showToast(`Error: ${err.message || err}`, true);
      }
    });

    // Stage History add/edit form submit
    root.getElementById("stage-history-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const stage = fd.get("stage");
      const startedAt = fd.get("started_at");
      const notes = (fd.get("notes") || "").trim() || null;
      const { plant, history } = this._modal.data;
      try {
        if (history?.id) {
          await this._api.updateStageHistory(history.id, { stage, started_at: startedAt, notes });
          this._showToast("Stage history updated!");
        } else {
          await this._api.addStageHistory(plant.id, stage, startedAt, notes);
          this._showToast("Past stage added!");
        }
        this._modal = null;
        await this._refreshState();
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

    // Harvest form submit
    root.getElementById("harvest-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const { plant } = this._modal.data;
      const data = {
        harvested_at: fd.get("harvested_at") || null,
        grow_cycle_id: fd.get("grow_cycle_id") || null,
        cure_start_at: fd.get("cure_start_at") || null,
        aroma_notes: fd.get("aroma_notes") || null,
        effect_notes: fd.get("effect_notes") || null,
        notes: fd.get("notes") || null,
        set_plant_stage: fd.get("set_plant_stage") || null,
        is_keeper: fd.get("is_keeper") !== null,
      };
      for (const ff of ["wet_weight_g", "dry_weight_g", "trim_weight_g", "cure_rh_pct", "light_wattage_override"]) {
        const v = fd.get(ff);
        data[ff] = v !== null && v !== "" ? parseFloat(v) : null;
      }
      for (const intF of ["dry_days", "rating"]) {
        const v = fd.get(intF);
        data[intF] = v !== null && v !== "" ? parseInt(v, 10) : null;
      }
      try {
        await this._api.upsertHarvest(plant.id, data);
        this._modal = null;
        if (this._tab === "plants" && this._selectedPlantId === plant.id) {
          this._plantSubTab = "harvest";
        }
        await this._refreshState();
        this._showToast(`Saved harvest for ${plant.name}!`);
      } catch (err) {
        this._showToast(`Error: ${err.message || err}`, true);
      }
    });

    // Curing jar check form submit
    root.getElementById("curing-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const { harvest } = this._modal.data;
      const data = {
        logged_at: fromLocalDatetimeInput(fd.get("logged_at")),
        burped: fd.get("burped") !== null,
        notes: fd.get("notes") || null,
      };
      for (const ff of ["jar_rh_pct", "jar_temp_c"]) {
        const v = fd.get(ff);
        data[ff] = v !== null && v !== "" ? parseFloat(v) : null;
      }
      try {
        await this._api.addCuringLog(harvest.id, data);
        this._modal = null;
        await this._refreshState();
        this._showToast("Jar check logged!");
      } catch (err) {
        this._showToast(`Error: ${err.message || err}`, true);
      }
    });

    // Grow Cycle form submit
    root.getElementById("cycle-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const data = {
        name: (fd.get("name") || "").trim(),
        started_at: fd.get("started_at") || null,
        ended_at: fd.get("ended_at") || null,
        status: fd.get("status") || "active",
        notes: fd.get("notes") || null,
      };
      try {
        if (this._modal.data?.id) {
          await this._api.updateGrowCycle(this._modal.data.id, data);
          this._showToast("Grow cycle updated!");
        } else {
          await this._api.createGrowCycle(data);
          this._showToast("Grow cycle created!");
        }
        this._modal = null;
        await this._refreshState();
      } catch (err) {
        this._showToast(`Error: ${err.message || err}`, true);
      }
    });

    // Reminder form submit
    root.getElementById("reminder-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const dueIso = fromLocalDatetimeInput(fd.get("due_at"));
      const recRaw = fd.get("recurrence_days");
      const moistRaw = fd.get("moisture_threshold");
      const data = {
        title: (fd.get("title") || "").trim(),
        action_type: fd.get("action_type") || "water",
        due_at: dueIso,
        plant_id: fd.get("plant_id") || null,
        environment_id: fd.get("environment_id") || null,
        preset_id: fd.get("preset_id") || null,
        recurrence_days: recRaw !== null && recRaw !== "" ? parseInt(recRaw, 10) : null,
        moisture_threshold: moistRaw !== null && moistRaw !== "" ? parseFloat(moistRaw) : null,
        auto_log_on_complete: fd.get("auto_log_on_complete") !== null,
        notes: fd.get("notes") || null,
      };
      const statusVal = fd.get("status");
      if (statusVal) data.status = statusVal;
      try {
        if (this._modal.data?.id) {
          await this._api.updateReminder(this._modal.data.id, data);
          this._showToast("Reminder updated!");
        } else {
          await this._api.createReminder(data);
          this._showToast("Reminder scheduled!");
        }
        this._modal = null;
        await this._refreshState();
      } catch (err) {
        this._showToast(`Error: ${err.message || err}`, true);
      }
    });

    // Pollen Vault form submit
    root.getElementById("pollen-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const data = Object.fromEntries(fd.entries());
      for (const k of Object.keys(data)) {
        if (data[k] === "") data[k] = null;
      }
      try {
        if (this._modal.data?.id) {
          await this._api.updatePollenBatch(this._modal.data.id, data);
          this._showToast("Pollen batch updated!");
        } else {
          await this._api.createPollenBatch(data);
          this._showToast("Pollen stored in vault!");
        }
        this._modal = null;
        await this._refreshState();
      } catch (err) {
        this._showToast(`Error: ${err.message || err}`, true);
      }
    });

    // Breeding Cross form submit
    root.getElementById("cross-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const data = Object.fromEntries(fd.entries());
      for (const k of Object.keys(data)) {
        if (data[k] === "") data[k] = null;
      }
      try {
        if (this._modal.data?.id) {
          await this._api.updateBreedingCross(this._modal.data.id, data);
          this._showToast("Breeding cross updated!");
        } else {
          await this._api.createBreedingCross(data);
          this._showToast("Breeding cross created!");
        }
        this._modal = null;
        await this._refreshState();
      } catch (err) {
        this._showToast(`Error: ${err.message || err}`, true);
      }
    });

    // Harvest Seeds & Auto-Mint form submit
    root.getElementById("harvest-seeds-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const cross = this._modal.data;
      const countRaw = fd.get("seed_count");
      const data = {
        harvested_at: fd.get("harvested_at") || null,
        seed_count: countRaw !== null && countRaw !== "" ? parseInt(countRaw, 10) : 0,
        batch_name: (fd.get("batch_name") || "").trim() || cross.name,
        seed_type: fd.get("seed_type") || "regular",
        breeder: fd.get("breeder") || null,
        storage_location: fd.get("storage_location") || null,
        mint_seedbank: fd.get("mint_seedbank") !== null,
        notes: fd.get("notes") || null,
      };
      try {
        const res = await this._api.harvestCrossSeeds(cross.id, data);
        this._modal = null;
        await this._refreshState();
        this._showToast(
          res?.seed_batch
            ? `Harvested ${data.seed_count} seeds & minted Seedbank batch!`
            : "Seed harvest recorded!"
        );
      } catch (err) {
        this._showToast(`Error: ${err.message || err}`, true);
      }
    });

    // Pheno Hunt form submit
    root.getElementById("pheno-hunt-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const data = Object.fromEntries(fd.entries());
      for (const k of Object.keys(data)) {
        if (data[k] === "") data[k] = null;
      }
      try {
        if (this._modal.data?.id) {
          await this._api.updatePhenoHunt(this._modal.data.id, data);
          this._showToast("Pheno hunt updated!");
        } else {
          const res = await this._api.createPhenoHunt(data);
          if (res?.pheno_hunt?.id) this._selectedPhenoHuntId = res.pheno_hunt.id;
          this._showToast("Pheno hunt created!");
        }
        this._modal = null;
        await this._refreshState();
      } catch (err) {
        this._showToast(`Error: ${err.message || err}`, true);
      }
    });

    // Pheno Score form submit
    root.getElementById("pheno-score-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const { hunt } = this._modal.data;
      const plantId = fd.get("plant_id");
      if (!plantId) {
        this._showToast("Please select a plant first", true);
        return;
      }
      const data = {
        pheno_code: (fd.get("pheno_code") || "").trim() || null,
        status: fd.get("status") || "evaluating",
        internode_spacing: fd.get("internode_spacing") || null,
        terpene_notes: fd.get("terpene_notes") || null,
        notes: fd.get("notes") || null,
      };
      for (const intF of ["vigor", "resin_density", "pest_mold_resistance", "aroma_score", "flower_days"]) {
        const v = fd.get(intF);
        data[intF] = v !== null && v !== "" ? parseInt(v, 10) : null;
      }
      for (const flF of ["stretch_factor", "yield_g"]) {
        const v = fd.get(flF);
        data[flF] = v !== null && v !== "" ? parseFloat(v) : null;
      }
      try {
        await this._api.upsertPhenoScore(hunt.id, plantId, data);
        this._modal = null;
        await this._refreshState();
        this._showToast("Phenotype scorecard saved!");
      } catch (err) {
        this._showToast(`Error: ${err.message || err}`, true);
      }
    });
  }
}

if (!customElements.get("igro-panel")) {
  customElements.define("igro-panel", IGroPanel);
}
