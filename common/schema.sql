-- Smart Bird Feeder — shared SQLite schema.
-- Two writers touch this file: puller (clips) and classifier (detections).
-- WAL mode lets them coexist without stepping on each other.

PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;   -- safe under WAL; cuts fsync latency/SD wear on the Pi

-- One row per motion clip pulled from Blink.
CREATE TABLE IF NOT EXISTS clips (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    filename     TEXT    NOT NULL UNIQUE,   -- basename on the clips volume
    camera       TEXT,
    captured_at  TEXT    NOT NULL,          -- ISO8601, when Blink recorded it
    pulled_at    TEXT    NOT NULL,          -- ISO8601, when we downloaded it
    status       TEXT    NOT NULL DEFAULT 'pending',  -- pending | processing | done | error | skipped
    note         TEXT,                       -- error text or reason skipped
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,                    -- ISO8601; NULL means ready now
    processing_started_at TEXT               -- ISO8601; set only while claimed
);

CREATE INDEX IF NOT EXISTS idx_clips_status ON clips(status);

-- One row per confident identification. A clip may yield zero or one.
CREATE TABLE IF NOT EXISTS detections (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    clip_id       INTEGER NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
    common_name   TEXT    NOT NULL,
    scientific    TEXT,
    confidence    REAL    NOT NULL,
    captured_at   TEXT    NOT NULL,         -- copied from the clip for easy sorting
    thumbnail     TEXT    NOT NULL,         -- basename under web/thumbs
    display_image TEXT,
    created_at    TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_det_captured ON detections(captured_at);
CREATE INDEX IF NOT EXISTS idx_det_species  ON detections(common_name);
-- Enforce one detection per clip so a crash between insert and status-update
-- can't leave a duplicate when the clip is reprocessed. Enables the upsert in
-- db.add_detection(). (If an existing DB already has duplicate clip_ids, dedupe
-- them once before this index will build.)
CREATE UNIQUE INDEX IF NOT EXISTS idx_det_clip ON detections(clip_id);

CREATE TABLE IF NOT EXISTS detection_annotations (
    detection_id INTEGER PRIMARY KEY REFERENCES detections(id) ON DELETE CASCADE,
    favorite INTEGER NOT NULL DEFAULT 0 CHECK (favorite IN (0, 1)),
    corrected_common_name TEXT,
    corrected_scientific TEXT,
    excluded INTEGER NOT NULL DEFAULT 0 CHECK (excluded IN (0, 1)),
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_annotations_favorite ON detection_annotations(favorite);

CREATE TABLE IF NOT EXISTS species_journal_state (
    species_key TEXT PRIMARY KEY,
    opened_at TEXT NOT NULL
);

-- Tiny key/value store for cursors (e.g. last 'since' timestamp for the puller).
CREATE TABLE IF NOT EXISTS state (
    key   TEXT PRIMARY KEY,
    value TEXT
);
