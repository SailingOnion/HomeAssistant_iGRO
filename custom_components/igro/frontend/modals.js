/**
 * Modal builders for iGro (Plant, Environment, Journal Log, Photo Upload / Camera Snap, Lightbox).
 */

import {
  LOG_TYPE_META,
  NUTRIENT_UNITS,
  STAGE_META,
  TRAINING_METHODS,
  escapeHtml,
  formatDateTime,
  scaleNutrientsForVolume,
  stageBadgeHtml,
  toLocalDatetimeInput,
} from "./api.js?v=0.3.0";

function entityOptionsHtml(entities = [], selected = "", placeholder = "None") {
  const opts = [`<option value="">${escapeHtml(placeholder)}</option>`];
  const seen = new Set();
  for (const e of entities) {
    seen.add(e.entity_id);
    const sel = e.entity_id === selected ? "selected" : "";
    opts.push(
      `<option value="${escapeHtml(e.entity_id)}" ${sel}>${escapeHtml(e.name)} (${escapeHtml(e.entity_id)})</option>`
    );
  }
  if (selected && !seen.has(selected)) {
    opts.push(`<option value="${escapeHtml(selected)}" selected>${escapeHtml(selected)}</option>`);
  }
  return opts.join("");
}

export function renderPlantModal(plant, state, haEntities) {
  const isEdit = Boolean(plant?.id);
  const meta = state.meta || {};
  const stages = meta.stages || Object.keys(STAGE_META);
  const plantTypes = meta.plant_types || ["photoperiod", "autoflower", "clone", "vegetable", "herb", "houseplant", "other"];
  const mediums = meta.mediums || ["soil", "coco", "hydroponic", "dwc", "living_soil", "rockwool", "other"];
  const startDate = (plant?.started_at || new Date().toISOString()).slice(0, 10);

  return `
    <div class="modal-backdrop" data-close-modal="1">
      <div class="modal" role="dialog" aria-modal="true">
        <div class="modal-header">
          <h3 class="modal-title">${isEdit ? "Edit Plant" : "🌱 Add New Plant"}</h3>
          <button class="btn btn-icon btn-sm" data-close-modal="1">✕</button>
        </div>
        <form id="plant-form">
          <div class="modal-body">
            <div class="form-grid">
              <div class="form-field full">
                <label class="form-label">Plant Name *</label>
                <input class="input" name="name" required placeholder="e.g. Northern Lights #1" value="${escapeHtml(plant?.name || "")}" />
              </div>
              <div class="form-field">
                <label class="form-label">Strain / Cultivar</label>
                <input class="input" name="strain" placeholder="e.g. Northern Lights" value="${escapeHtml(plant?.strain || "")}" />
              </div>
              <div class="form-field">
                <label class="form-label">Breeder / Source</label>
                <input class="input" name="breeder" placeholder="e.g. Sensi Seeds" value="${escapeHtml(plant?.breeder || "")}" />
              </div>
              <div class="form-field">
                <label class="form-label">Plant Type</label>
                <select class="select" name="plant_type">
                  ${plantTypes.map((t) => `<option value="${t}" ${plant?.plant_type === t ? "selected" : ""}>${t.replace("_", " ")}</option>`).join("")}
                </select>
              </div>
              <div class="form-field">
                <label class="form-label">Grow Stage</label>
                <select class="select" name="stage">
                  ${stages.map((s) => `<option value="${s}" ${(plant?.stage || "germination") === s ? "selected" : ""}>${STAGE_META[s]?.label || s}</option>`).join("")}
                </select>
              </div>
              <div class="form-field">
                <label class="form-label">Environment / Tent</label>
                <select class="select" name="environment_id">
                  <option value="">Unassigned</option>
                  ${(state.environments || []).map((e) => `<option value="${escapeHtml(e.id)}" ${plant?.environment_id === e.id ? "selected" : ""}>${escapeHtml(e.name)}</option>`).join("")}
                </select>
              </div>
              <div class="form-field">
                <label class="form-label">Start Date</label>
                <input class="input" type="date" name="started_at" value="${escapeHtml(startDate)}" />
              </div>
              <div class="form-field">
                <label class="form-label">Grow Medium</label>
                <select class="select" name="medium">
                  ${mediums.map((m) => `<option value="${m}" ${(plant?.medium || "soil") === m ? "selected" : ""}>${m.replace("_", " ")}</option>`).join("")}
                </select>
              </div>
              <div class="form-field">
                <label class="form-label">Pot Size</label>
                <input class="input" name="pot_size" placeholder="e.g. 5 gal fabric" value="${escapeHtml(plant?.pot_size || "")}" />
              </div>
              <div class="form-field">
                <label class="form-label">Soil Moisture Sensor (HA)</label>
                <select class="select" name="soil_moisture_entity_id">
                  ${entityOptionsHtml(haEntities.moisture, plant?.soil_moisture_entity_id, "None")}
                </select>
              </div>
              <div class="form-field">
                <label class="form-label">Dedicated Camera (HA)</label>
                <select class="select" name="camera_entity_id">
                  ${entityOptionsHtml(haEntities.cameras, plant?.camera_entity_id, "Inherit from environment")}
                </select>
              </div>
              <div class="form-field full">
                <label class="form-label">Notes</label>
                <textarea class="textarea" name="notes" placeholder="Phenotype notes, germination method, goals...">${escapeHtml(plant?.notes || "")}</textarea>
              </div>
            </div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn" data-close-modal="1">Cancel</button>
            <button type="submit" class="btn btn-primary">${isEdit ? "Save Changes" : "Create Plant"}</button>
          </div>
        </form>
      </div>
    </div>
  `;
}

export function renderEnvironmentModal(env, state, haEntities) {
  const isEdit = Boolean(env?.id);
  const envTypes = state.meta?.environment_types || ["tent", "room", "cabinet", "greenhouse", "outdoor", "drying_tent", "other"];

  return `
    <div class="modal-backdrop" data-close-modal="1">
      <div class="modal" role="dialog" aria-modal="true">
        <div class="modal-header">
          <h3 class="modal-title">${isEdit ? "Edit Environment" : "⛺ Add Grow Environment"}</h3>
          <button class="btn btn-icon btn-sm" data-close-modal="1">✕</button>
        </div>
        <form id="env-form">
          <div class="modal-body">
            <div class="form-grid">
              <div class="form-field full">
                <label class="form-label">Name *</label>
                <input class="input" name="name" required placeholder="e.g. 4x4 Flower Tent" value="${escapeHtml(env?.name || "")}" />
              </div>
              <div class="form-field">
                <label class="form-label">Type</label>
                <select class="select" name="env_type">
                  ${envTypes.map((t) => `<option value="${t}" ${(env?.env_type || "tent") === t ? "selected" : ""}>${t.replace("_", " ")}</option>`).join("")}
                </select>
              </div>
              <div class="form-field">
                <label class="form-label">Dimensions</label>
                <input class="input" name="dimensions" placeholder="e.g. 4x4x6.5 ft" value="${escapeHtml(env?.dimensions || "")}" />
              </div>
              <div class="form-field">
                <label class="form-label">Light Schedule</label>
                <input class="input" name="light_schedule" placeholder="18/6 or 12/12" value="${escapeHtml(env?.light_schedule || "18/6")}" />
              </div>
              <div class="form-field">
                <label class="form-label">Leaf Temp Offset (°C for VPD)</label>
                <input class="input" type="number" step="0.5" name="leaf_temp_offset_c" value="${env?.leaf_temp_offset_c ?? -2.0}" />
              </div>

              <div class="form-field full" style="margin-top:4px;font-weight:700;font-size:13px;">🔗 Link Home Assistant Sensors & Devices</div>

              <div class="form-field">
                <label class="form-label">Temperature Sensor</label>
                <select class="select" name="temp_entity_id">
                  ${entityOptionsHtml(haEntities.temperature, env?.temp_entity_id, "None")}
                </select>
              </div>
              <div class="form-field">
                <label class="form-label">Humidity Sensor</label>
                <select class="select" name="humidity_entity_id">
                  ${entityOptionsHtml(haEntities.humidity, env?.humidity_entity_id, "None")}
                </select>
              </div>
              <div class="form-field">
                <label class="form-label">CO₂ Sensor</label>
                <select class="select" name="co2_entity_id">
                  ${entityOptionsHtml(haEntities.co2, env?.co2_entity_id, "None")}
                </select>
              </div>
              <div class="form-field">
                <label class="form-label">Tent Camera</label>
                <select class="select" name="camera_entity_id">
                  ${entityOptionsHtml(haEntities.cameras, env?.camera_entity_id, "None")}
                </select>
              </div>
              <div class="form-field">
                <label class="form-label">Grow Light Entity</label>
                <select class="select" name="light_entity_id">
                  ${entityOptionsHtml(haEntities.controls, env?.light_entity_id, "None")}
                </select>
              </div>
              <div class="form-field">
                <label class="form-label">Exhaust / Fan Entity</label>
                <select class="select" name="exhaust_entity_id">
                  ${entityOptionsHtml(haEntities.controls, env?.exhaust_entity_id, "None")}
                </select>
              </div>
              <div class="form-field full">
                <label class="form-label">Humidifier / Dehumidifier Entity</label>
                <select class="select" name="humidifier_entity_id">
                  ${entityOptionsHtml(haEntities.controls, env?.humidifier_entity_id, "None")}
                </select>
              </div>

              <div class="form-field full" style="margin-top:4px;font-weight:700;font-size:13px;">🎯 Target Alert Ranges (optional — VPD auto-adapts to plant stage if blank)</div>

              <div class="form-field">
                <label class="form-label">Min VPD (kPa)</label>
                <input class="input" type="number" step="0.05" name="target_vpd_min" placeholder="Auto" value="${env?.target_vpd_min ?? ""}" />
              </div>
              <div class="form-field">
                <label class="form-label">Max VPD (kPa)</label>
                <input class="input" type="number" step="0.05" name="target_vpd_max" placeholder="Auto" value="${env?.target_vpd_max ?? ""}" />
              </div>
              <div class="form-field">
                <label class="form-label">Min Temp (°C)</label>
                <input class="input" type="number" step="0.5" name="target_temp_min_c" placeholder="e.g. 20" value="${env?.target_temp_min_c ?? ""}" />
              </div>
              <div class="form-field">
                <label class="form-label">Max Temp (°C)</label>
                <input class="input" type="number" step="0.5" name="target_temp_max_c" placeholder="e.g. 28" value="${env?.target_temp_max_c ?? ""}" />
              </div>
              <div class="form-field">
                <label class="form-label">Min Humidity (%)</label>
                <input class="input" type="number" step="1" name="target_humidity_min" placeholder="e.g. 45" value="${env?.target_humidity_min ?? ""}" />
              </div>
              <div class="form-field">
                <label class="form-label">Max Humidity (%)</label>
                <input class="input" type="number" step="1" name="target_humidity_max" placeholder="e.g. 65" value="${env?.target_humidity_max ?? ""}" />
              </div>
              <div class="form-field full">
                <label class="form-label">Notes</label>
                <textarea class="textarea" name="notes" placeholder="Light model, exhaust CFM, ducting notes...">${escapeHtml(env?.notes || "")}</textarea>
              </div>
            </div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn" data-close-modal="1">Cancel</button>
            <button type="submit" class="btn btn-primary">${isEdit ? "Save Environment" : "Create Environment"}</button>
          </div>
        </form>
      </div>
    </div>
  `;
}

export function renderScaledMixHtml(nutrients, waterVolumeMl) {
  const vol = parseFloat(waterVolumeMl);
  if (!Number.isFinite(vol) || vol <= 0) {
    return `<span style="color:var(--igro-text-muted);">Enter a Water Volume (mL) above to auto-calculate exact total mix dosages.</span>`;
  }
  const scaled = scaleNutrientsForVolume(
    (nutrients || []).filter((n) => n?.name && n?.amount !== "" && n?.amount !== null && n?.amount !== undefined),
    vol
  );
  if (!scaled.length) {
    return `<span style="color:var(--igro-text-muted);">Add nutrients with amounts above to preview scaled totals for ${(vol / 1000).toFixed(2)} L.</span>`;
  }
  const liters = (vol / 1000).toFixed(2);
  const gal = (vol / 3785.411784).toFixed(2);
  return `
    <div style="font-weight:600;margin-bottom:6px;">🧮 Total Mix for ${vol} mL (${liters} L / ${gal} gal):</div>
    <div class="log-chips" style="margin-top:0;">
      ${scaled
        .map(
          (n) =>
            `<span class="log-chip" style="border-color:var(--igro-accent);color:var(--igro-text);"><strong>${escapeHtml(n.name)}</strong>: ${n.total_amount ?? n.amount} ${escapeHtml(n.total_unit || n.unit || "")}</span>`
        )
        .join("")}
    </div>
  `;
}

function nutrientUnitSelectHtml(selected = "mL/L") {
  const units = NUTRIENT_UNITS.includes(selected) ? NUTRIENT_UNITS : [selected, ...NUTRIENT_UNITS];
  return `<select class="select" name="nut_unit">${units
    .map((u) => `<option value="${escapeHtml(u)}" ${u === selected ? "selected" : ""}>${escapeHtml(u)}</option>`)
    .join("")}</select>`;
}

export function renderLogModal(defaults, state) {
  const isEdit = Boolean(defaults.id);
  const selectedType = defaults.log_type || "water";
  const selectedPlantId =
    defaults.plant_id !== undefined ? defaults.plant_id || "" : state.plants?.[0]?.id ?? "";
  const selectedPlant = (state.plants || []).find((p) => p.id === selectedPlantId);
  const selectableTypes = ["water", "feed", "training", "defoliation", "measurement", "transplant", "flush", "pest_issue", "note"];
  const showWaterFields = ["water", "feed", "flush"].includes(selectedType);
  const showFeedFields = selectedType === "feed";
  const showTrainingFields = selectedType === "training";
  const showMeasureFields = selectedType === "measurement";
  const nutrients = defaults.nutrients?.length
    ? defaults.nutrients
    : showFeedFields
    ? [{ name: "", amount: "", unit: "mL/L" }]
    : [];
  const loggedAtLocal = defaults.logged_at_local ?? toLocalDatetimeInput(defaults.logged_at);
  const selectedStatus = defaults.status || "completed";

  const allPresets = state.nutrient_presets || [];
  const suggestedIds = new Set(selectedPlant?.suggested_preset_ids || []);
  const suggestedPresets = allPresets.filter((pr) => suggestedIds.has(pr.id));
  const otherPresets = allPresets.filter((pr) => !suggestedIds.has(pr.id));

  return `
    <div class="modal-backdrop" data-close-modal="1">
      <div class="modal" role="dialog" aria-modal="true">
        <div class="modal-header">
          <h3 class="modal-title">${isEdit ? "✏️ Edit Journal Entry" : "📓 Log Grow Action"}</h3>
          <button class="btn btn-icon btn-sm" data-close-modal="1">✕</button>
        </div>
        <form id="log-form">
          <div class="modal-body">
            <div class="form-field">
              <label class="form-label">Action Type</label>
              <input type="hidden" name="log_type" value="${escapeHtml(selectedType)}" />
              <div class="chip-selector">
                ${selectableTypes
                  .map((t) => {
                    const m = LOG_TYPE_META[t];
                    return `<button type="button" class="chip-opt ${selectedType === t ? "selected" : ""}" data-log-type="${t}">${m.icon} ${m.label}</button>`;
                  })
                  .join("")}
              </div>
            </div>

            <div class="form-grid">
              <div class="form-field">
                <label class="form-label">Plant</label>
                <select class="select" name="plant_id">
                  <option value="">General / All Plants</option>
                  ${(state.plants || []).map((p) => `<option value="${escapeHtml(p.id)}" ${selectedPlantId === p.id ? "selected" : ""}>${escapeHtml(p.name)}</option>`).join("")}
                </select>
              </div>
              <div class="form-field">
                <label class="form-label">Title (optional)</label>
                <input class="input" name="title" placeholder="${escapeHtml(LOG_TYPE_META[selectedType]?.label || "Summary")}" value="${escapeHtml(defaults.title || "")}" />
              </div>
              <div class="form-field">
                <label class="form-label">Date & Time (past or future)</label>
                <input class="input" type="datetime-local" id="log-datetime-input" name="logged_at" value="${escapeHtml(loggedAtLocal)}" />
              </div>
              <div class="form-field">
                <label class="form-label">Status</label>
                <select class="select" id="log-status-select" name="status">
                  <option value="completed" ${selectedStatus === "completed" ? "selected" : ""}>✅ Completed</option>
                  <option value="planned" ${selectedStatus === "planned" ? "selected" : ""}>📅 Planned / Scheduled</option>
                </select>
              </div>

              ${
                showFeedFields && allPresets.length
                  ? `
                <div class="form-field full">
                  <label class="form-label">🧪 Apply Nutrient Preset</label>
                  <select class="select" id="log-preset-select">
                    <option value="">— Choose a saved recipe to auto-fill —</option>
                    ${
                      suggestedPresets.length
                        ? `<optgroup label="⭐ Recommended for ${escapeHtml(selectedPlant?.name || "Plant")} (${escapeHtml(STAGE_META[selectedPlant?.stage]?.label || "")} Wk ${selectedPlant?.stage_week ?? 1})">
                            ${suggestedPresets.map((pr) => `<option value="${escapeHtml(pr.id)}" ${defaults.preset_id === pr.id ? "selected" : ""}>⭐ ${escapeHtml(pr.name)}</option>`).join("")}
                          </optgroup>`
                        : ""
                    }
                    ${
                      otherPresets.length
                        ? `<optgroup label="${suggestedPresets.length ? "Other Presets" : "Saved Presets"}">
                            ${otherPresets.map((pr) => `<option value="${escapeHtml(pr.id)}" ${defaults.preset_id === pr.id ? "selected" : ""}>${escapeHtml(pr.name)}</option>`).join("")}
                          </optgroup>`
                        : ""
                    }
                  </select>
                </div>
              `
                  : ""
              }

              ${
                showWaterFields
                  ? `
                <div class="form-field">
                  <label class="form-label">Water Volume (mL)</label>
                  <input class="input" type="number" step="50" name="water_volume_ml" placeholder="e.g. 2000" value="${defaults.water_volume_ml ?? ""}" />
                </div>
                <div class="form-field">
                  <label class="form-label">Input pH</label>
                  <input class="input" type="number" step="0.1" min="0" max="14" name="ph" placeholder="e.g. 6.3" value="${defaults.ph ?? ""}" />
                </div>
                <div class="form-field">
                  <label class="form-label">Input EC (mS/cm)</label>
                  <input class="input" type="number" step="0.1" name="ec" placeholder="e.g. 1.4" value="${defaults.ec ?? ""}" />
                </div>
                <div class="form-field">
                  <label class="form-label">Input PPM</label>
                  <input class="input" type="number" step="10" name="ppm" placeholder="e.g. 700" value="${defaults.ppm ?? ""}" />
                </div>
                <div class="form-field">
                  <label class="form-label">Runoff pH</label>
                  <input class="input" type="number" step="0.1" min="0" max="14" name="runoff_ph" placeholder="optional" value="${defaults.runoff_ph ?? ""}" />
                </div>
                <div class="form-field">
                  <label class="form-label">Runoff EC</label>
                  <input class="input" type="number" step="0.1" name="runoff_ec" placeholder="optional" value="${defaults.runoff_ec ?? ""}" />
                </div>
              `
                  : ""
              }

              ${
                showFeedFields
                  ? `
                <div class="form-field full">
                  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                    <label class="form-label">Nutrients / Additives</label>
                    <button type="button" class="btn btn-sm" data-add-nutrient="1">+ Add Nutrient</button>
                  </div>
                  <div id="nutrients-list" style="display:flex;flex-direction:column;gap:8px;">
                    ${nutrients
                      .map(
                        (n, idx) => `
                      <div class="nutrient-row" data-nutrient-row="${idx}">
                        <input class="input" name="nut_name" placeholder="Nutrient (e.g. Cal-Mag)" value="${escapeHtml(n.name || "")}" />
                        <input class="input" type="number" step="0.1" name="nut_amount" placeholder="Qty (e.g. 2)" value="${escapeHtml(n.amount ?? "")}" />
                        ${nutrientUnitSelectHtml(n.unit || "mL/L")}
                        <button type="button" class="btn btn-sm btn-danger" data-remove-nutrient="${idx}">✕</button>
                      </div>
                    `
                      )
                      .join("")}
                  </div>
                  <div id="scaled-mix-preview" style="margin-top:10px;padding:10px 12px;border-radius:10px;background:var(--igro-surface-2);border:1px solid var(--igro-border);font-size:12px;">
                    ${renderScaledMixHtml(nutrients, defaults.water_volume_ml)}
                  </div>
                </div>
              `
                  : ""
              }

              ${
                showTrainingFields
                  ? `
                <div class="form-field full">
                  <label class="form-label">Training Method</label>
                  <select class="select" name="training_method">
                    ${TRAINING_METHODS.map((m) => `<option value="${escapeHtml(m)}" ${defaults.training_method === m ? "selected" : ""}>${escapeHtml(m)}</option>`).join("")}
                  </select>
                </div>
              `
                  : ""
              }

              ${
                showMeasureFields
                  ? `
                <div class="form-field full">
                  <label class="form-label">Plant Height (cm)</label>
                  <input class="input" type="number" step="0.5" name="height_cm" placeholder="e.g. 42.5" value="${defaults.height_cm ?? ""}" />
                </div>
              `
                  : ""
              }

              <div class="form-field full">
                <label class="form-label">Notes</label>
                <textarea class="textarea" name="notes" placeholder="Leaf color, vigor, runoff observations, adjustments...">${escapeHtml(defaults.notes || "")}</textarea>
              </div>
            </div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn" data-close-modal="1">Cancel</button>
            <button type="submit" class="btn btn-primary">${isEdit ? "Save Changes" : "Save Entry"}</button>
          </div>
        </form>
      </div>
    </div>
  `;
}

export function renderPresetModal(preset, state) {
  const isEdit = Boolean(preset?.id);
  const stages = state.meta?.stages || Object.keys(STAGE_META);
  const nutrients = preset?.nutrients?.length
    ? preset.nutrients
    : [{ name: "", amount: "", unit: "mL/L" }];

  return `
    <div class="modal-backdrop" data-close-modal="1">
      <div class="modal" role="dialog" aria-modal="true">
        <div class="modal-header">
          <h3 class="modal-title">${isEdit ? "✏️ Edit Nutrient Preset" : "🧪 New Nutrient Preset"}</h3>
          <button class="btn btn-icon btn-sm" data-close-modal="1">✕</button>
        </div>
        <form id="preset-form">
          <div class="modal-body">
            <div class="form-grid">
              <div class="form-field full">
                <label class="form-label">Preset Name *</label>
                <input class="input" name="name" required placeholder="e.g. Veg Week 2–4 Base" value="${escapeHtml(preset?.name || "")}" />
              </div>
              <div class="form-field">
                <label class="form-label">Target Stage (optional)</label>
                <select class="select" name="stage">
                  <option value="">Any Stage</option>
                  ${stages.map((s) => `<option value="${s}" ${preset?.stage === s ? "selected" : ""}>${STAGE_META[s]?.label || s}</option>`).join("")}
                </select>
              </div>
              <div class="form-field">
                <label class="form-label">Stage Week Range (optional)</label>
                <div style="display:grid;grid-template-columns:1fr auto 1fr;gap:6px;align-items:center;">
                  <input class="input" type="number" min="1" max="52" name="week_start" placeholder="From wk" value="${preset?.week_start ?? ""}" />
                  <span style="color:var(--igro-text-muted);">–</span>
                  <input class="input" type="number" min="1" max="52" name="week_end" placeholder="To wk" value="${preset?.week_end ?? ""}" />
                </div>
              </div>
              <div class="form-field">
                <label class="form-label">Target pH</label>
                <input class="input" type="number" step="0.1" min="0" max="14" name="target_ph" placeholder="e.g. 6.0" value="${preset?.target_ph ?? ""}" />
              </div>
              <div class="form-field">
                <label class="form-label">Target EC (mS/cm)</label>
                <input class="input" type="number" step="0.1" name="target_ec" placeholder="e.g. 1.4" value="${preset?.target_ec ?? ""}" />
              </div>
              <div class="form-field full">
                <label class="form-label">Target PPM (optional)</label>
                <input class="input" type="number" step="10" name="target_ppm" placeholder="e.g. 700" value="${preset?.target_ppm ?? ""}" />
              </div>

              <div class="form-field full">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                  <label class="form-label">Nutrients & Dosages</label>
                  <button type="button" class="btn btn-sm" data-add-nutrient="1">+ Add Nutrient</button>
                </div>
                <div id="nutrients-list" style="display:flex;flex-direction:column;gap:8px;">
                  ${nutrients
                    .map(
                      (n, idx) => `
                    <div class="nutrient-row" data-nutrient-row="${idx}">
                      <input class="input" name="nut_name" placeholder="Nutrient (e.g. Grow A)" value="${escapeHtml(n.name || "")}" />
                      <input class="input" type="number" step="0.1" name="nut_amount" placeholder="Qty" value="${escapeHtml(n.amount ?? "")}" />
                      ${nutrientUnitSelectHtml(n.unit || "mL/L")}
                      <button type="button" class="btn btn-sm btn-danger" data-remove-nutrient="${idx}">✕</button>
                    </div>
                  `
                    )
                    .join("")}
                </div>
              </div>

              <div class="form-field full">
                <label class="form-label">Mixing Order / Notes</label>
                <textarea class="textarea" name="notes" placeholder="e.g. Mix Silica first, wait 10 min, then Cal-Mag, A, B, pH last...">${escapeHtml(preset?.notes || "")}</textarea>
              </div>
            </div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn" data-close-modal="1">Cancel</button>
            <button type="submit" class="btn btn-primary">${isEdit ? "Save Preset" : "Create Preset"}</button>
          </div>
        </form>
      </div>
    </div>
  `;
}

export function renderPhotoModal(defaults, state, haEntities) {
  const mode = defaults.mode || "upload";
  const selectedPlantId = defaults.plant_id || (state.plants?.[0]?.id ?? "");
  const plant = (state.plants || []).find((p) => p.id === selectedPlantId);
  const defaultCamera = defaults.camera_entity_id || plant?.effective_camera_entity_id || haEntities.cameras?.[0]?.entity_id || "";

  return `
    <div class="modal-backdrop" data-close-modal="1">
      <div class="modal" role="dialog" aria-modal="true">
        <div class="modal-header">
          <h3 class="modal-title">📷 Add Grow Photo</h3>
          <button class="btn btn-icon btn-sm" data-close-modal="1">✕</button>
        </div>
        <form id="photo-form">
          <div class="modal-body">
            <div class="chip-selector">
              <button type="button" class="chip-opt ${mode === "upload" ? "selected" : ""}" data-photo-mode="upload">⬆️ Upload from Device</button>
              <button type="button" class="chip-opt ${mode === "camera" ? "selected" : ""}" data-photo-mode="camera">🎥 Snap from HA Camera</button>
            </div>
            <input type="hidden" name="mode" value="${mode}" />

            <div class="form-grid">
              <div class="form-field">
                <label class="form-label">Plant</label>
                <select class="select" name="plant_id">
                  <option value="">General / Tent</option>
                  ${(state.plants || []).map((p) => `<option value="${escapeHtml(p.id)}" ${selectedPlantId === p.id ? "selected" : ""}>${escapeHtml(p.name)}</option>`).join("")}
                </select>
              </div>
              <div class="form-field">
                <label class="form-label">Grow Stage</label>
                <select class="select" name="stage">
                  <option value="">Auto (plant's current stage)</option>
                  ${Object.entries(STAGE_META).map(([k, v]) => `<option value="${k}" ${defaults.stage === k ? "selected" : ""}>${v.label}</option>`).join("")}
                </select>
              </div>

              ${
                mode === "upload"
                  ? `
                <div class="form-field full">
                  <label class="form-label">Image File *</label>
                  <input class="input" type="file" name="file" accept="image/*" required />
                </div>
                <div class="form-field full">
                  <label class="form-label">Date Taken (optional — leave blank for now)</label>
                  <input class="input" type="datetime-local" name="taken_at" />
                </div>
              `
                  : `
                <div class="form-field full">
                  <label class="form-label">Home Assistant Camera *</label>
                  <select class="select" name="camera_entity_id" required>
                    ${entityOptionsHtml(haEntities.cameras, defaultCamera, "Select a camera...")}
                  </select>
                </div>
              `
              }

              <div class="form-field full">
                <label class="form-label">Caption</label>
                <input class="input" name="caption" placeholder="e.g. Day 21 Flower — trichomes stacking!" />
              </div>
            </div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn" data-close-modal="1">Cancel</button>
            <button type="submit" class="btn btn-primary">${mode === "upload" ? "Upload Photo" : "Capture Snapshot"}</button>
          </div>
        </form>
      </div>
    </div>
  `;
}

export function renderLightboxModal(photo) {
  return `
    <div class="modal-backdrop" data-close-modal="1">
      <div class="modal" style="max-width:820px;" role="dialog" aria-modal="true">
        <div class="modal-header">
          <h3 class="modal-title">${escapeHtml(photo.plant_name || photo.environment_name || "Grow Photo")}</h3>
          <button class="btn btn-icon btn-sm" data-close-modal="1">✕</button>
        </div>
        <div class="modal-body">
          <img class="lightbox-img" src="${escapeHtml(photo.url)}" alt="${escapeHtml(photo.caption || "Grow photo")}" />
          <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;">
            <div>
              ${photo.stage ? stageBadgeHtml(photo.stage) : ""}
              <span style="margin-left:8px;font-size:13px;color:var(--igro-text-muted);">${formatDateTime(photo.taken_at)}</span>
              ${photo.caption ? `<p style="margin:8px 0 0;font-size:14px;">${escapeHtml(photo.caption)}</p>` : ""}
            </div>
            <div style="display:flex;gap:8px;">
              ${photo.plant_id ? `<button class="btn btn-sm" data-set-cover="${escapeHtml(photo.id)}" data-plant-id="${escapeHtml(photo.plant_id)}">⭐ Set Cover</button>` : ""}
              <button class="btn btn-sm btn-danger" data-delete-photo="${escapeHtml(photo.id)}">🗑 Delete</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  `;
}

export function renderStageModal({ plant, targetStage }) {
  const todayLocal = new Date(Date.now() - new Date().getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 10);
  const targetLabel = STAGE_META[targetStage]?.label || targetStage;

  return `
    <div class="modal-backdrop" data-close-modal="1">
      <div class="modal" style="max-width:480px;" role="dialog" aria-modal="true">
        <div class="modal-header">
          <h3 class="modal-title">🔄 Change Growth Stage</h3>
          <button class="btn btn-icon btn-sm" data-close-modal="1">✕</button>
        </div>
        <form id="stage-form">
          <div class="modal-body">
            <div style="font-size:14px;font-weight:600;">${escapeHtml(plant.name)}</div>
            <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:12px;border-radius:12px;background:var(--igro-surface-2);border:1px solid var(--igro-border);">
              ${stageBadgeHtml(plant.stage)}
              <span style="color:var(--igro-text-muted);font-weight:700;">→</span>
              ${stageBadgeHtml(targetStage)}
            </div>
            <input type="hidden" name="today_default" value="${todayLocal}" />
            <div class="form-field">
              <label class="form-label">Transition Date (past to backdate, future to schedule)</label>
              <input class="input" type="date" id="stage-date-input" name="changed_at" value="${todayLocal}" />
            </div>
            <div id="stage-schedule-options" style="display:none;padding:10px 12px;border-radius:10px;background:rgba(14, 165, 233, 0.12);border:1px solid rgba(14, 165, 233, 0.35);font-size:13px;">
              <label style="display:flex;align-items:center;gap:8px;cursor:pointer;">
                <input type="checkbox" name="auto_apply" checked />
                <span>Auto-apply stage transition automatically on this date</span>
              </label>
            </div>
            <div class="form-field">
              <label class="form-label">Note (optional)</label>
              <textarea class="textarea" id="stage-note-input" name="notes" placeholder="e.g. Flipped light schedule to 12/12, transplanted to 5 gal fabric pot..."></textarea>
            </div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn" data-close-modal="1">Cancel</button>
            <button type="submit" class="btn btn-primary" id="stage-submit-btn" data-target-label="${escapeHtml(targetLabel)}">Move to ${escapeHtml(targetLabel)}</button>
          </div>
        </form>
      </div>
    </div>
  `;
}

export function renderStageHistoryModal({ plant, history }, state) {
  const isEdit = Boolean(history?.id);
  const stages = state.meta?.stages || Object.keys(STAGE_META);
  const dateVal = (history?.started_at || new Date().toISOString()).slice(0, 10);

  return `
    <div class="modal-backdrop" data-close-modal="1">
      <div class="modal" style="max-width:460px;" role="dialog" aria-modal="true">
        <div class="modal-header">
          <h3 class="modal-title">${isEdit ? "✏️ Edit Stage History" : "📅 Add Past Stage"}</h3>
          <button class="btn btn-icon btn-sm" data-close-modal="1">✕</button>
        </div>
        <form id="stage-history-form">
          <div class="modal-body">
            <div style="font-size:13px;color:var(--igro-text-muted);">Plant: <strong>${escapeHtml(plant.name)}</strong> — dates automatically re-chain chronologically.</div>
            <div class="form-field">
              <label class="form-label">Stage</label>
              <select class="select" name="stage">
                ${stages.map((s) => `<option value="${s}" ${(history?.stage || "germination") === s ? "selected" : ""}>${STAGE_META[s]?.label || s}</option>`).join("")}
              </select>
            </div>
            <div class="form-field">
              <label class="form-label">Start Date *</label>
              <input class="input" type="date" name="started_at" required value="${escapeHtml(dateVal)}" />
            </div>
            <div class="form-field">
              <label class="form-label">Notes (optional)</label>
              <textarea class="textarea" name="notes" placeholder="Notes about this stage...">${escapeHtml(history?.notes || "")}</textarea>
            </div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn" data-close-modal="1">Cancel</button>
            <button type="submit" class="btn btn-primary">${isEdit ? "Save Changes" : "Add Stage"}</button>
          </div>
        </form>
      </div>
    </div>
  `;
}

export function renderConfirmModal({ title, message, confirmLabel = "Delete", danger = true }) {
  return `
    <div class="modal-backdrop" data-close-modal="1">
      <div class="modal" style="max-width:440px;" role="dialog" aria-modal="true">
        <div class="modal-header">
          <h3 class="modal-title">${escapeHtml(title || "Confirm Action")}</h3>
          <button class="btn btn-icon btn-sm" data-close-modal="1">✕</button>
        </div>
        <div class="modal-body">
          <p style="margin:0;font-size:14px;line-height:1.5;color:var(--igro-text);">${escapeHtml(message || "Are you sure?")}</p>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn" data-close-modal="1">Cancel</button>
          <button type="button" class="btn ${danger ? "btn-danger" : "btn-primary"}" id="confirm-modal-ok">${escapeHtml(confirmLabel)}</button>
        </div>
      </div>
    </div>
  `;
}
