"""Constants for the iGro Home Assistant integration."""

from __future__ import annotations

DOMAIN = "igro"
PLATFORMS = ["sensor", "binary_sensor", "select", "button", "calendar", "todo"]

# Configuration keys
CONF_DB_PATH = "db_path"
CONF_MEDIA_PATH = "media_path"
CONF_PANEL_TITLE = "panel_title"
CONF_PANEL_ICON = "panel_icon"
CONF_LEAF_TEMP_OFFSET_C = "leaf_temp_offset_c"

DEFAULT_DB_FILENAME = "igro.db"
DEFAULT_MEDIA_DIRNAME = "igro_media"
DEFAULT_PANEL_TITLE = "iGro"
DEFAULT_PANEL_ICON = "mdi:sprout"
DEFAULT_LEAF_TEMP_OFFSET_C = -2.0

STATIC_URL_PATH = "/igro_static"
PANEL_URL_PATH = "igro"

# Dispatcher signals for dynamic entity updates
SIGNAL_ENTITIES_CHANGED = f"{DOMAIN}_entities_changed"

# Grow stages in lifecycle order
STAGE_GERMINATION = "germination"
STAGE_SEEDLING = "seedling"
STAGE_VEGETATIVE = "vegetative"
STAGE_FLOWERING = "flowering"
STAGE_DRYING = "drying"
STAGE_CURING = "curing"
STAGE_HARVESTED = "harvested"
STAGE_ARCHIVED = "archived"

GROW_STAGES: list[str] = [
    STAGE_GERMINATION,
    STAGE_SEEDLING,
    STAGE_VEGETATIVE,
    STAGE_FLOWERING,
    STAGE_DRYING,
    STAGE_CURING,
    STAGE_HARVESTED,
    STAGE_ARCHIVED,
]

ACTIVE_STAGES: set[str] = {
    STAGE_GERMINATION,
    STAGE_SEEDLING,
    STAGE_VEGETATIVE,
    STAGE_FLOWERING,
    STAGE_DRYING,
    STAGE_CURING,
}

STAGE_LABELS: dict[str, str] = {
    STAGE_GERMINATION: "Germination",
    STAGE_SEEDLING: "Seedling",
    STAGE_VEGETATIVE: "Vegetative",
    STAGE_FLOWERING: "Flowering",
    STAGE_DRYING: "Drying",
    STAGE_CURING: "Curing",
    STAGE_HARVESTED: "Harvested",
    STAGE_ARCHIVED: "Archived",
}

# Recommended VPD ranges in kPa per stage: (min_kpa, max_kpa)
STAGE_VPD_TARGETS: dict[str, tuple[float, float]] = {
    STAGE_GERMINATION: (0.4, 0.8),
    STAGE_SEEDLING: (0.4, 0.8),
    STAGE_VEGETATIVE: (0.8, 1.2),
    STAGE_FLOWERING: (1.2, 1.6),
    STAGE_DRYING: (0.7, 1.0),
    STAGE_CURING: (0.6, 0.9),
}

# Plant types & grow mediums
PLANT_TYPES: list[str] = [
    "photoperiod",
    "autoflower",
    "clone",
    "vegetable",
    "herb",
    "houseplant",
    "other",
]

GROW_MEDIUMS: list[str] = [
    "soil",
    "coco",
    "hydroponic",
    "dwc",
    "aeroponic",
    "living_soil",
    "rockwool",
    "other",
]

ENVIRONMENT_TYPES: list[str] = [
    "tent",
    "room",
    "cabinet",
    "greenhouse",
    "outdoor",
    "drying_tent",
    "other",
]

# Journal / log entry types
LOG_TYPE_WATER = "water"
LOG_TYPE_FEED = "feed"
LOG_TYPE_TRAINING = "training"
LOG_TYPE_MEASUREMENT = "measurement"
LOG_TYPE_STAGE_CHANGE = "stage_change"
LOG_TYPE_PEST_ISSUE = "pest_issue"
LOG_TYPE_FLUSH = "flush"
LOG_TYPE_DEFOLIATION = "defoliation"
LOG_TYPE_TRANSPLANT = "transplant"
LOG_TYPE_NOTE = "note"

LOG_TYPES: list[str] = [
    LOG_TYPE_WATER,
    LOG_TYPE_FEED,
    LOG_TYPE_TRAINING,
    LOG_TYPE_DEFOLIATION,
    LOG_TYPE_MEASUREMENT,
    LOG_TYPE_TRANSPLANT,
    LOG_TYPE_FLUSH,
    LOG_TYPE_PEST_ISSUE,
    LOG_TYPE_STAGE_CHANGE,
    LOG_TYPE_NOTE,
]

# VPD status values
VPD_STATUS_OPTIMAL = "optimal"
VPD_STATUS_LOW = "low"
VPD_STATUS_HIGH = "high"
VPD_STATUS_UNKNOWN = "unknown"

# HA Events
EVENT_LOG_CREATED = f"{DOMAIN}_log_created"
EVENT_STAGE_CHANGED = f"{DOMAIN}_stage_changed"
EVENT_PHOTO_ADDED = f"{DOMAIN}_photo_added"
EVENT_HARVEST_RECORDED = f"{DOMAIN}_harvest_recorded"
EVENT_REMINDER_DUE = f"{DOMAIN}_reminder_due"

# Services
SERVICE_LOG_ACTION = "log_action"
SERVICE_ADVANCE_STAGE = "advance_stage"
SERVICE_SET_STAGE = "set_stage"
SERVICE_CAPTURE_PHOTO = "capture_photo"
SERVICE_CREATE_PLANT = "create_plant"
SERVICE_RECORD_HARVEST = "record_harvest"
SERVICE_CREATE_REMINDER = "create_reminder"
SERVICE_COMPLETE_REMINDER = "complete_reminder"

# Allowed photo MIME types / extensions
ALLOWED_IMAGE_EXTENSIONS: set[str] = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_PHOTO_SIZE_BYTES = 15 * 1024 * 1024  # 15 MB
