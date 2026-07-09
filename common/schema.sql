-- Smart Bird Feeder — shared SQLite schema.
-- Two writers touch this file: puller (clips) and classifier (detections).
-- WAL mode lets them coexist without stepping on each other.

PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
PRAGMA synchronous = NORMAL;   -- safe under WAL; cuts fsync latency/SD wear on the Pi

-- One row per motion clip pulled from Blink.
CREATE TABLE IF NOT EXISTS clips (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    filename     TEXT    NOT NULL UNIQUE,   -- basename on the clips volume
    camera       TEXT,
    captured_at  TEXT    NOT NULL,          -- ISO8601, when Blink recorded it
    pulled_at    TEXT    NOT NULL,          -- ISO8601, when we downloaded it
    status       TEXT    NOT NULL DEFAULT 'pending',  -- pending | done | error | skipped
    note         TEXT                        -- error text or reason skipped
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
    created_at    TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_det_captured ON detections(captured_at);
CREATE INDEX IF NOT EXISTS idx_det_species  ON detections(common_name);
-- Enforce one detection per clip so a crash between insert and status-update
-- can't leave a duplicate when the clip is reprocessed. Enables the upsert in
-- db.add_detection(). (If an existing DB already has duplicate clip_ids, dedupe
-- them once before this index will build.)
CREATE UNIQUE INDEX IF NOT EXISTS idx_det_clip ON detections(clip_id);

-- Tiny key/value store for cursors (e.g. last 'since' timestamp for the puller).
CREATE TABLE IF NOT EXISTS state (
    key   TEXT PRIMARY KEY,
    value TEXT
);
