/**
 * Shared styles for the iGro Home Assistant custom panel.
 * Integrates seamlessly with Home Assistant light & dark themes.
 */

export const PANEL_STYLES = `
:host {
  --igro-accent: #16a34a;
  --igro-accent-hover: #15803d;
  --igro-accent-soft: rgba(22, 163, 74, 0.14);
  --igro-bg: var(--primary-background-color, #111618);
  --igro-surface: var(--card-background-color, #1c2226);
  --igro-surface-2: var(--secondary-background-color, #252c31);
  --igro-border: var(--divider-color, rgba(148, 163, 184, 0.18));
  --igro-text: var(--primary-text-color, #f1f5f9);
  --igro-text-muted: var(--secondary-text-color, #94a3b8);
  --igro-danger: #ef4444;
  --igro-warn: #f59e0b;
  --igro-info: #0ea5e9;
  --igro-radius: 14px;
  --igro-shadow: 0 2px 10px rgba(0, 0, 0, 0.14);
  display: block;
  min-height: 100vh;
  background: var(--igro-bg);
  color: var(--igro-text);
  font-family: var(--paper-font-body1_-_font-family, Roboto, system-ui, -apple-system, sans-serif);
  box-sizing: border-box;
}

*, *::before, *::after {
  box-sizing: border-box;
}

/* Topbar */
.topbar {
  position: sticky;
  top: 0;
  z-index: 20;
  background: var(--igro-surface);
  border-bottom: 1px solid var(--igro-border);
  padding: 12px 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.topbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.menu-btn {
  display: none;
  background: transparent;
  border: 1px solid var(--igro-border);
  color: var(--igro-text);
  border-radius: 10px;
  width: 38px;
  height: 38px;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  cursor: pointer;
}

.menu-btn.visible {
  display: inline-flex;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 20px;
  font-weight: 700;
  letter-spacing: -0.02em;
  cursor: pointer;
}

.brand-icon {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: linear-gradient(135deg, #16a34a, #059669);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  box-shadow: 0 4px 12px rgba(22, 163, 74, 0.35);
}

.nav-tabs {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.nav-tab {
  border: none;
  background: transparent;
  color: var(--igro-text-muted);
  padding: 8px 14px;
  border-radius: 10px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.nav-tab:hover {
  background: var(--igro-surface-2);
  color: var(--igro-text);
}

.nav-tab.active {
  background: var(--igro-accent-soft);
  color: var(--igro-accent);
}

.topbar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* Main content */
.container {
  max-width: 1360px;
  margin: 0 auto;
  padding: 20px;
}

/* Buttons */
.btn {
  border: 1px solid var(--igro-border);
  background: var(--igro-surface);
  color: var(--igro-text);
  padding: 8px 14px;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  transition: all 0.15s ease;
}

.btn:hover {
  background: var(--igro-surface-2);
}

.btn-primary {
  background: var(--igro-accent);
  border-color: var(--igro-accent);
  color: #fff;
}

.btn-primary:hover {
  background: var(--igro-accent-hover);
  border-color: var(--igro-accent-hover);
}

.btn-danger {
  color: var(--igro-danger);
  border-color: rgba(239, 68, 68, 0.35);
}

.btn-danger:hover {
  background: rgba(239, 68, 68, 0.12);
}

.btn-sm {
  padding: 5px 10px;
  font-size: 12px;
  border-radius: 8px;
}

.btn-icon {
  padding: 6px 8px;
}

/* Cards & Grids */
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 14px;
  margin-bottom: 22px;
}

.kpi-card {
  background: var(--igro-surface);
  border: 1px solid var(--igro-border);
  border-radius: var(--igro-radius);
  padding: 16px 18px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  box-shadow: var(--igro-shadow);
}

.kpi-label {
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--igro-text-muted);
  margin-bottom: 4px;
}

.kpi-value {
  font-size: 28px;
  font-weight: 700;
  line-height: 1.1;
}

.kpi-emoji {
  font-size: 28px;
  opacity: 0.9;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 22px 0 12px;
  gap: 12px;
  flex-wrap: wrap;
}

.section-title {
  font-size: 17px;
  font-weight: 700;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}

.grid-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
}

.card {
  background: var(--igro-surface);
  border: 1px solid var(--igro-border);
  border-radius: var(--igro-radius);
  overflow: hidden;
  box-shadow: var(--igro-shadow);
  transition: transform 0.15s ease, border-color 0.15s ease;
}

.card.clickable {
  cursor: pointer;
}

.card.clickable:hover {
  transform: translateY(-2px);
  border-color: var(--igro-accent);
}

.card-body {
  padding: 16px;
}

/* Badges */
.badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 9px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  border: 1px solid transparent;
  white-space: nowrap;
}

.badge-ok {
  color: #16a34a;
  background: rgba(22, 163, 74, 0.15);
  border-color: rgba(22, 163, 74, 0.3);
}

.badge-info {
  color: #0ea5e9;
  background: rgba(14, 165, 233, 0.15);
  border-color: rgba(14, 165, 233, 0.3);
}

.badge-warn {
  color: #d97706;
  background: rgba(217, 119, 6, 0.15);
  border-color: rgba(217, 119, 6, 0.3);
}

.badge-danger {
  color: #ef4444;
  background: rgba(239, 68, 68, 0.15);
  border-color: rgba(239, 68, 68, 0.3);
}

.badge-muted {
  color: var(--igro-text-muted);
  background: var(--igro-surface-2);
  border-color: var(--igro-border);
}

/* Plant Cards */
.plant-cover {
  height: 155px;
  background: linear-gradient(135deg, rgba(22, 163, 74, 0.22), rgba(5, 150, 105, 0.08));
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.plant-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.plant-cover-placeholder {
  font-size: 48px;
  opacity: 0.7;
}

.plant-cover-overlay {
  position: absolute;
  top: 10px;
  left: 10px;
  right: 10px;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 6px;
}

.plant-day-pill {
  background: rgba(15, 23, 42, 0.78);
  color: #fff;
  padding: 3px 9px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  backdrop-filter: blur(6px);
}

.plant-title {
  font-size: 16px;
  font-weight: 700;
  margin: 0 0 2px;
}

.plant-subtitle {
  font-size: 13px;
  color: var(--igro-text-muted);
  margin: 0 0 12px;
}

.meta-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 12px;
  color: var(--igro-text-muted);
  margin-bottom: 12px;
}

.stat-chips {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-top: 10px;
}

.stat-chip {
  background: var(--igro-surface-2);
  border-radius: 10px;
  padding: 8px 10px;
  text-align: center;
}

.stat-chip-label {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--igro-text-muted);
}

.stat-chip-val {
  font-size: 14px;
  font-weight: 700;
  margin-top: 2px;
}

/* Environment Cards */
.env-metrics {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  margin: 14px 0;
}

.env-metric {
  background: var(--igro-surface-2);
  border-radius: 12px;
  padding: 12px 10px;
  text-align: center;
}

.env-metric-label {
  font-size: 11px;
  color: var(--igro-text-muted);
  margin-bottom: 4px;
}

.env-metric-val {
  font-size: 19px;
  font-weight: 700;
}

.env-metric-sub {
  font-size: 11px;
  color: var(--igro-text-muted);
  margin-top: 2px;
}

.vpd-bar-wrap {
  margin: 10px 0 14px;
}

.vpd-bar-label {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: var(--igro-text-muted);
  margin-bottom: 4px;
}

.vpd-bar-track {
  height: 8px;
  border-radius: 999px;
  background: linear-gradient(90deg, #0ea5e9 0%, #16a34a 35%, #16a34a 65%, #f59e0b 82%, #ef4444 100%);
  position: relative;
}

.vpd-bar-marker {
  position: absolute;
  top: -4px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #fff;
  border: 3px solid var(--igro-accent);
  transform: translateX(-50%);
  box-shadow: 0 2px 6px rgba(0,0,0,0.4);
}

/* Plant Detail View */
.detail-hero {
  background: var(--igro-surface);
  border: 1px solid var(--igro-border);
  border-radius: var(--igro-radius);
  padding: 20px;
  display: flex;
  gap: 20px;
  flex-wrap: wrap;
  margin-bottom: 18px;
  box-shadow: var(--igro-shadow);
}

.detail-photo {
  width: 220px;
  height: 220px;
  border-radius: 12px;
  overflow: hidden;
  background: linear-gradient(135deg, rgba(22, 163, 74, 0.2), rgba(5, 150, 105, 0.08));
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.detail-photo img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.detail-info {
  flex: 1;
  min-width: 260px;
}

.stage-stepper {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin: 14px 0;
}

.stage-step {
  border: 1px solid var(--igro-border);
  background: var(--igro-surface-2);
  color: var(--igro-text-muted);
  padding: 6px 12px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
}

.stage-step:hover {
  border-color: var(--igro-accent);
  color: var(--igro-text);
}

.stage-step.completed {
  background: rgba(22, 163, 74, 0.12);
  border-color: rgba(22, 163, 74, 0.35);
  color: var(--igro-accent);
}

.stage-step.current {
  background: var(--igro-accent);
  border-color: var(--igro-accent);
  color: #fff;
  box-shadow: 0 2px 10px rgba(22, 163, 74, 0.35);
}

.quick-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 14px;
}

/* Journal Timeline */
.timeline {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.log-item {
  background: var(--igro-surface);
  border: 1px solid var(--igro-border);
  border-radius: 12px;
  padding: 14px 16px;
  display: flex;
  gap: 14px;
  align-items: flex-start;
}

.log-icon {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
}

.log-body {
  flex: 1;
  min-width: 0;
}

.log-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.log-title {
  font-weight: 700;
  font-size: 14px;
}

.log-time {
  font-size: 12px;
  color: var(--igro-text-muted);
}

.log-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.log-chip {
  font-size: 12px;
  background: var(--igro-surface-2);
  border: 1px solid var(--igro-border);
  padding: 2px 8px;
  border-radius: 6px;
}

.log-notes {
  margin: 8px 0 0;
  font-size: 13px;
  color: var(--igro-text-muted);
  white-space: pre-wrap;
}

/* Gallery */
.photo-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
  gap: 14px;
}

.photo-card {
  background: var(--igro-surface);
  border: 1px solid var(--igro-border);
  border-radius: 12px;
  overflow: hidden;
  cursor: pointer;
  transition: transform 0.15s ease;
}

.photo-card:hover {
  transform: translateY(-2px);
}

.photo-thumb {
  aspect-ratio: 4 / 3;
  width: 100%;
  object-fit: cover;
  display: block;
  background: var(--igro-surface-2);
}

.photo-meta {
  padding: 10px 12px;
  font-size: 12px;
}

/* Filter Bar */
.filter-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 16px;
  align-items: center;
}

.input, .select, .textarea {
  background: var(--igro-surface);
  color: var(--igro-text);
  border: 1px solid var(--igro-border);
  border-radius: 10px;
  padding: 8px 12px;
  font-size: 13px;
  font-family: inherit;
  outline: none;
}

.input:focus, .select:focus, .textarea:focus {
  border-color: var(--igro-accent);
}

.textarea {
  width: 100%;
  min-height: 74px;
  resize: vertical;
}

/* Empty State */
.empty-state {
  background: var(--igro-surface);
  border: 1px dashed var(--igro-border);
  border-radius: var(--igro-radius);
  padding: 40px 20px;
  text-align: center;
  color: var(--igro-text-muted);
}

.empty-state-emoji {
  font-size: 42px;
  margin-bottom: 10px;
}

.empty-state h3 {
  margin: 0 0 6px;
  color: var(--igro-text);
}

/* Modals */
.modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 100;
  background: rgba(0, 0, 0, 0.65);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
}

.modal {
  background: var(--igro-surface);
  border: 1px solid var(--igro-border);
  border-radius: 16px;
  width: 100%;
  max-width: 580px;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.45);
  overflow: hidden;
}

.modal-header {
  padding: 16px 20px;
  border-bottom: 1px solid var(--igro-border);
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-shrink: 0;
}

.modal > form {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.modal-title {
  font-size: 17px;
  font-weight: 700;
  margin: 0;
}

.modal-body {
  flex: 1 1 auto;
  min-height: 0;
  padding: 18px 20px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.modal-footer {
  padding: 14px 20px;
  border-top: 1px solid var(--igro-border);
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  flex-shrink: 0;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.form-field.full {
  grid-column: 1 / -1;
}

.form-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--igro-text-muted);
}

.form-field .input, .form-field .select {
  width: 100%;
}

.chip-selector {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.chip-opt {
  border: 1px solid var(--igro-border);
  background: var(--igro-surface-2);
  color: var(--igro-text);
  padding: 6px 11px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.chip-opt.selected {
  background: var(--igro-accent);
  border-color: var(--igro-accent);
  color: #fff;
}

.nutrient-row {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr auto;
  gap: 8px;
  align-items: center;
}

/* Lightbox */
.lightbox-img {
  max-width: 100%;
  max-height: 68vh;
  border-radius: 10px;
  object-fit: contain;
  margin: 0 auto;
  display: block;
}

/* Toast */
.toast {
  position: fixed;
  bottom: 24px;
  right: 24px;
  z-index: 200;
  background: #1e293b;
  color: #fff;
  padding: 12px 18px;
  border-radius: 12px;
  font-size: 13px;
  font-weight: 600;
  box-shadow: 0 10px 30px rgba(0,0,0,0.4);
  border-left: 4px solid var(--igro-accent);
}

.toast.error {
  border-left-color: var(--igro-danger);
}

/* Pedigree Tree Diagram */
.pedigree-scroll {
  overflow-x: auto;
  padding: 10px 4px;
}

.pedigree-branch {
  display: flex;
  align-items: center;
  gap: 16px;
}

.pedigree-node {
  min-width: 175px;
  max-width: 220px;
  background: var(--igro-surface-2);
  border: 1px solid var(--igro-border);
  border-radius: 12px;
  padding: 10px 12px;
  flex-shrink: 0;
}

.pedigree-node.cross {
  border-color: var(--igro-accent);
  background: rgba(22, 163, 74, 0.08);
}

.pedigree-node.pollen {
  border-color: #eab308;
}

.pedigree-parents {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-left: 16px;
  border-left: 2px solid var(--igro-border);
  position: relative;
}

.pedigree-role {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.pedigree-role.mother { color: #ec4899; }
.pedigree-role.father { color: #0ea5e9; }
.pedigree-role.root { color: var(--igro-accent); }

/* Pheno Comparison Matrix Table */
.pheno-table-wrap {
  overflow-x: auto;
  border: 1px solid var(--igro-border);
  border-radius: var(--igro-radius);
  background: var(--igro-surface);
}

.pheno-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.pheno-table th,
.pheno-table td {
  padding: 10px 12px;
  text-align: left;
  border-bottom: 1px solid var(--igro-border);
  white-space: nowrap;
}

.pheno-table th {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--igro-text-muted);
  background: var(--igro-surface-2);
}

.pheno-table tr:last-child td {
  border-bottom: none;
}

@media (max-width: 680px) {
  .container { padding: 14px; }
  .form-grid { grid-template-columns: 1fr; }
  .detail-photo { width: 100%; height: 210px; }
  .topbar { padding: 10px 14px; }
}
`;
