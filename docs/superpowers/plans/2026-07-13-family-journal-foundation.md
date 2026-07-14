# Family Journal Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add permanent detection images, shared annotations, and a private journal API without disrupting the working Blink-to-classifier pipeline or current static dashboard.

**Architecture:** SQLite remains the source of truth. A new non-root Flask/Gunicorn `journal` container owns read/write journal behavior, while Caddy proxies authenticated `/api/*` requests to it over an internal Compose network. The classifier atomically publishes a 1280px display image and 480px thumbnail for every accepted detection and never prunes either.

**Tech Stack:** Python 3.11.15, SQLite/WAL, Flask 3, Gunicorn 23, Pillow, Docker Compose, Caddy 2.11.4, `unittest`

## Global Constraints

- Preserve the existing Blink ingestion, classifier, Raspberry Pi deployment, and Basic Auth boundary.
- Do not publish a host port for `journal`; only Caddy may reach `journal:8000`.
- Run `journal` as `${PUID:-1000}:${PGID:-1000}` with a read-only root filesystem, all capabilities dropped, no-new-privileges, bounded processes/logs, and `/tmp` tmpfs.
- Mount `data/db` read-write, `classifier/model/current/labels.txt` read-only, and no Blink credentials or raw clips into `journal`.
- Keep original classifier names immutable; store favorites, corrections, and exclusions in `detection_annotations`.
- Validate corrections against the installed label bundle; arbitrary species text is forbidden.
- Use `TZ`, default `America/New_York`, for local-day grouping and daylight-saving behavior.
- Enforce cursor pagination and a maximum page size of 100.
- Store display images at maximum width 1280 and thumbnails at maximum width 480 using atomic replacement.
- Retain every identified display image and thumbnail indefinitely; raw clip retention remains unchanged.
- Existing detections use their current thumbnail as both display and thumbnail image.

## File map

- `common/schema.sql`: additive annotations/shared species-open state and detection display-image column.
- `common/db.py`: repeatable migration and atomic detection upsert with both image paths.
- `classifier/watcher.py`: image sizing, atomic publication, and removal of thumbnail pruning.
- `journal/app.py`: Flask app factory, error mapping, and route registration.
- `journal/queries.py`: journal SQL, local-day summaries, cursors, species aggregation, and annotation writes.
- `journal/labels.py`: installed-label parsing and bounded correction search.
- `journal/Dockerfile`, `journal/requirements.txt`: pinned runtime.
- `docker-compose.yml`, `web/Caddyfile`, `scripts/prepare-data.sh`: secure service wiring and data directory ordering.
- `tests/test_journal_schema.py`, `tests/test_journal_queries.py`, `tests/test_journal_api.py`, `tests/test_journal_installation.py`, `tests/test_watcher.py`: executable contracts.

---

### Task 1: Add repeatable journal schema migrations

**Files:**
- Modify: `common/schema.sql`
- Modify: `common/db.py`
- Create: `tests/test_journal_schema.py`

**Interfaces:**
- Produces: `detections.display_image: TEXT`, `detection_annotations`, and `db.connect(path) -> sqlite3.Connection` that migrates old databases idempotently.

- [ ] **Step 1: Write failing migration tests**

```python
def test_old_detection_database_migrates_without_rewriting_prediction(tmp_path):
    path = tmp_path / "old.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript(OLD_SCHEMA)
    conn.execute(
        "INSERT INTO clips(id, filename, captured_at, pulled_at) VALUES(1,'one.mp4','2026-07-13T12:00:00Z','2026-07-13T12:01:00Z')"
    )
    conn.execute(
        "INSERT INTO detections(clip_id,common_name,scientific,confidence,captured_at,thumbnail,created_at) VALUES(1,'Blue Jay','Cyanocitta cristata',.91,'2026-07-13T12:00:00Z','thumbs/1.jpg','2026-07-13T12:02:00Z')"
    )
    conn.commit(); conn.close()

    migrated = db.connect(path)
    row = migrated.execute("SELECT * FROM detections").fetchone()
    assert row["common_name"] == "Blue Jay"
    assert row["display_image"] == "thumbs/1.jpg"
    assert migrated.execute("SELECT COUNT(*) n FROM detection_annotations").fetchone()["n"] == 0

def test_migration_is_repeatable(tmp_path):
    first = db.connect(tmp_path / "feeder.sqlite"); first.close()
    second = db.connect(tmp_path / "feeder.sqlite")
    assert second.execute("PRAGMA foreign_key_check").fetchall() == []
```

- [ ] **Step 2: Run the tests and confirm failure**

Run: `python -m unittest tests.test_journal_schema -v`

Expected: FAIL because `display_image` and `detection_annotations` do not exist.

- [ ] **Step 3: Add the schema and migration**

Add to `common/schema.sql`:

```sql
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
```

Call `_migrate_detections(conn)` after `_migrate_clips(conn)` and implement:

```python
def _migrate_detections(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(detections)")}
    with conn:
        if "display_image" not in columns:
            conn.execute("ALTER TABLE detections ADD COLUMN display_image TEXT")
        conn.execute(
            "UPDATE detections SET display_image = thumbnail "
            "WHERE display_image IS NULL OR display_image = ''"
        )
```

Also add nullable `display_image TEXT` to the fresh `detections` definition before `created_at`.

- [ ] **Step 4: Run schema and existing tests**

Run: `python -m unittest tests.test_journal_schema tests.test_clip_recovery tests.test_watcher -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add common/schema.sql common/db.py tests/test_journal_schema.py
git commit -m "feat: add shared journal annotations"
```

### Task 2: Publish permanent display images and thumbnails atomically

**Files:**
- Modify: `common/db.py`
- Modify: `classifier/watcher.py`
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `tests/test_watcher.py`

**Interfaces:**
- Produces: `publish_detection_images(frame: Path, clip_id: int) -> tuple[str, str]` returning `(display_image, thumbnail)` relative to `/data/web`.
- Produces: `finish_clip_with_detection(..., thumbnail: str, display_image: str) -> None`.

- [ ] **Step 1: Add failing image-publication tests**

```python
def test_publish_detection_images_creates_two_atomic_sizes(self):
    frame = self.root / "source.jpg"
    Image.new("RGB", (2000, 1200), "#67805a").save(frame)
    with mock.patch.object(watcher, "IMAGES_DIR", self.root / "images"), mock.patch.object(
        watcher, "THUMBS_DIR", self.root / "thumbs"
    ):
        display, thumb = watcher.publish_detection_images(frame, 42)
    with Image.open(self.root / display) as large, Image.open(self.root / thumb) as small:
        self.assertLessEqual(large.width, 1280)
        self.assertLessEqual(small.width, 480)
    self.assertEqual(list(self.root.rglob("*.tmp")), [])

def test_regenerate_json_does_not_delete_old_images(self):
    old = self.root / "thumbs" / "old.jpg"
    old.parent.mkdir(); old.write_bytes(b"kept")
    with mock.patch.object(watcher, "WEB_DIR", self.root), mock.patch.object(
        watcher, "DATA_DIR", self.root / "data"
    ), mock.patch.object(watcher, "THUMBS_DIR", old.parent):
        watcher.regenerate_json(self.conn)
    self.assertTrue(old.exists())
```

- [ ] **Step 2: Run the targeted tests and confirm failure**

Run: `python -m unittest tests.test_watcher.WatcherRecoveryTests.test_publish_detection_images_creates_two_atomic_sizes tests.test_watcher.WatcherRecoveryTests.test_regenerate_json_does_not_delete_old_images -v`

Expected: FAIL because the publisher does not exist and regeneration prunes images.

- [ ] **Step 3: Implement atomic dual-image publication**

Replace `save_thumbnail` with:

```python
DISPLAY_WIDTH = int(os.getenv("DISPLAY_WIDTH", "1280"))
IMAGES_DIR = WEB_DIR / "images"

def _atomic_jpeg(source: Image.Image, target: Path, max_width: int, quality: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    image = source.copy()
    if image.width > max_width:
        height = round(image.height * max_width / image.width)
        image = image.resize((max_width, height), Image.Resampling.LANCZOS)
    temporary = target.with_suffix(target.suffix + ".tmp")
    image.save(temporary, "JPEG", quality=quality, optimize=True)
    temporary.replace(target)

def publish_detection_images(frame: Path, clip_id: int) -> tuple[str, str]:
    from PIL import Image
    name = f"{clip_id}.jpg"
    with Image.open(frame) as opened:
        rgb = opened.convert("RGB")
        _atomic_jpeg(rgb, IMAGES_DIR / name, DISPLAY_WIDTH, 88)
        _atomic_jpeg(rgb, THUMBS_DIR / name, THUMB_WIDTH, 82)
    return f"images/{name}", f"thumbs/{name}"
```

Call it from `process_clip`, pass both paths to `db.finish_clip_with_detection`, extend both detection upserts to persist `display_image`, and delete the pruning block from `regenerate_json`.

- [ ] **Step 4: Add the runtime setting and verify**

Add `DISPLAY_WIDTH: ${DISPLAY_WIDTH:-1280}` to the classifier environment and `DISPLAY_WIDTH=1280` to `.env.example`.

Run: `python -m unittest tests.test_watcher tests.test_clip_recovery -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add common/db.py classifier/watcher.py docker-compose.yml .env.example tests/test_watcher.py
git commit -m "feat: retain permanent detection photos"
```

### Task 3: Build journal query and correction-label modules

**Files:**
- Create: `journal/__init__.py`
- Create: `journal/labels.py`
- Create: `journal/queries.py`
- Create: `tests/test_journal_queries.py`

**Interfaces:**
- Produces: `LabelCatalog.from_file(path)`, `LabelCatalog.search(query, limit=20)`, `LabelCatalog.resolve(common_name) -> Taxon | None`.
- Produces: `today(conn, tz_name, recent_limit=12)`, `detections(conn, *, cursor, limit, species_key, favorite, local_date, tz_name)`, `detection(conn, id)`, `patch_detection(conn, id, patch, catalog)`, `species(conn, *, query, sort)`, `species_detail(conn, species_key, *, cursor, limit)`, and `mark_species_opened(conn, species_key)` returning JSON-safe dictionaries or `None`.

- [ ] **Step 1: Write failing domain tests**

Cover idempotent favorites, preserved original predictions, correction-driven species counts, exclusion/restoration, cursor stability after a newer insert, maximum limits, local midnight, and the 2026-11-01 New York daylight-saving fallback. Representative assertions:

```python
updated = queries.patch_detection(conn, detection_id, {"favorite": True}, catalog)
assert updated["favorite"] is True
assert queries.patch_detection(conn, detection_id, {"favorite": True}, catalog) == updated

corrected = queries.patch_detection(conn, detection_id, {"correction": "Northern Cardinal"}, catalog)
assert corrected["original_species"]["common_name"] == "Blue Jay"
assert corrected["effective_species"]["common_name"] == "Northern Cardinal"

queries.patch_detection(conn, detection_id, {"excluded": True}, catalog)
assert queries.today(conn, "America/New_York")["visits_today"] == 0
queries.patch_detection(conn, detection_id, {"excluded": False}, catalog)
assert queries.today(conn, "America/New_York")["visits_today"] == 1

collection = queries.species(conn, query="", sort="newest")
assert collection["species"][0]["is_new"] is True
queries.mark_species_opened(conn, collection["species"][0]["species_key"])
assert queries.species(conn, query="", sort="newest")["species"][0]["is_new"] is False
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m unittest tests.test_journal_queries -v`

Expected: FAIL because `journal.labels` and `journal.queries` do not exist.

- [ ] **Step 3: Implement labels and a single effective-detection SQL projection**

Use one reusable SQL projection in `queries.py` so every aggregate obeys corrections and exclusions:

```python
EFFECTIVE_SQL = """
SELECT d.*, COALESCE(NULLIF(a.corrected_common_name,''), d.common_name) AS effective_common,
       COALESCE(NULLIF(a.corrected_scientific,''), d.scientific) AS effective_scientific,
       COALESCE(a.favorite, 0) AS favorite, COALESCE(a.excluded, 0) AS excluded,
       a.corrected_common_name IS NOT NULL AS corrected
FROM detections d LEFT JOIN detection_annotations a ON a.detection_id = d.id
"""

def species_key(common: str, scientific: str | None) -> str:
    value = " ".join((scientific or common).strip().casefold().split())
    return ("sci:" if scientific else "common:") + value
```

`patch_detection` must use `INSERT ... ON CONFLICT(detection_id) DO UPDATE`, retain an existing favorite during exclusion, reject an unknown correction with `InvalidCorrection`, and map `correction: null` to clearing both corrected columns. Encode cursors as URL-safe base64 JSON containing `captured_at` and `id`; query older rows with `(captured_at < ?) OR (captured_at = ? AND id < ?)`.

`species` must left-join `species_journal_state` and return `is_new: true` until the shared profile has been opened. `mark_species_opened` validates that the effective, non-excluded species exists, then upserts its normalized key and `opened_at`; corrections can therefore create a new unopened album.

- [ ] **Step 4: Run domain and concurrency tests**

Run: `python -m unittest tests.test_journal_queries tests.test_clip_recovery -v`

Expected: PASS, including one test that writes a new clip through a second WAL connection while a journal read connection is open.

- [ ] **Step 5: Commit**

```bash
git add journal/__init__.py journal/labels.py journal/queries.py tests/test_journal_queries.py
git commit -m "feat: add journal domain queries"
```

### Task 4: Expose the private journal API

**Files:**
- Create: `journal/app.py`
- Create: `journal/requirements.txt`
- Create: `tests/test_journal_api.py`

**Interfaces:**
- Consumes: query functions and `LabelCatalog` from Task 3.
- Produces: `create_app(config: dict | None = None) -> flask.Flask` and the approved eight routes.
- Produces: `with_db_retry(operation, attempts=3, delay_seconds=0.05)` for short SQLite lock recovery.

- [ ] **Step 1: Add failing API tests**

Create a temporary SQLite fixture and test:

```python
app = create_app({"TESTING": True, "DB_PATH": str(db_path), "LABELS_PATH": str(labels), "TZ": "America/New_York"})
client = app.test_client()
assert client.get("/api/health").json == {"status": "ok"}
assert client.get("/api/today").status_code == 200
assert client.get("/api/detections?limit=101").status_code == 400
assert client.get("/api/detections/not-an-id").status_code == 404
assert client.patch(f"/api/detections/{detection_id}", json={"favorite": True}).json["favorite"] is True
assert client.patch(f"/api/detections/{detection_id}", json={"correction": "Invented Finch"}).status_code == 422
assert client.get("/api/taxa?q=card").json["taxa"][0]["common_name"] == "Northern Cardinal"
```

Exercise Today, history filters, stable cursors, detection detail, PATCH, species search/sorts, species detail/gallery, shared new/opened state, taxa bounds, missing rows, malformed cursors, and a mocked `sqlite3.OperationalError("database is locked")` returning `503` with `{"error":"database_busy","retryable":true}`.

- [ ] **Step 2: Run and confirm failure**

Run: `python -m unittest tests.test_journal_api -v`

Expected: FAIL because `journal.app` does not exist.

- [ ] **Step 3: Implement the Flask app factory and error contract**

Use environment-backed defaults:

```python
DEFAULTS = {
    "DB_PATH": os.getenv("DB_PATH", "/data/db/feeder.sqlite"),
    "LABELS_PATH": os.getenv("LABELS_PATH", "/app/model/labels.txt"),
    "TZ": os.getenv("TZ", "America/New_York"),
    "MAX_PAGE_SIZE": 100,
}

def create_app(config=None):
    app = Flask(__name__)
    app.config.from_mapping(DEFAULTS)
    if config: app.config.update(config)
    catalog = LabelCatalog.from_file(app.config["LABELS_PATH"])
    # Register explicit routes; each opens and closes one db.connect() per request.
    return app
```

Wrap each query operation with:

```python
def with_db_retry(operation, attempts=3, delay_seconds=0.05):
    for attempt in range(attempts):
        try:
            return operation()
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).casefold() or attempt == attempts - 1:
                raise
            time.sleep(delay_seconds * (attempt + 1))
```

When `GET /api/species/{species_key}` successfully finds a profile, call `mark_species_opened` in the same short request transaction before returning it. Return JSON errors with stable codes: `bad_request` (400), `not_found` (404), `invalid_correction` (422), and `database_busy` (503). Never return exception text, SQL, provider bodies, headers, cookies, or environment values.

- [ ] **Step 4: Pin the runtime and run tests**

Create `journal/requirements.txt`:

```text
Flask==3.1.2
gunicorn==23.0.0
```

Run: `python -m unittest tests.test_journal_api tests.test_journal_queries -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add journal/app.py journal/requirements.txt tests/test_journal_api.py
git commit -m "feat: expose private journal API"
```

### Task 5: Wire the secure container, Caddy route, and data ordering

**Files:**
- Create: `journal/Dockerfile`
- Modify: `docker-compose.yml`
- Modify: `web/Caddyfile`
- Modify: `scripts/prepare-data.sh`
- Modify: `tests/test_installation.py`
- Create: `tests/test_journal_installation.py`

**Interfaces:**
- Consumes: `journal.app:create_app` and Gunicorn.
- Produces: authenticated `/api/* -> journal:8000`; no journal host port.

- [ ] **Step 1: Write failing deployment-contract tests**

```python
def test_journal_is_internal_hardened_and_narrowly_mounted():
    config = compose_config()
    journal = config["services"]["journal"]
    assert "ports" not in journal
    assert journal["user"] == "1000:1000"
    assert journal["read_only"] is True
    assert journal["cap_drop"] == ["ALL"]
    volumes = "\n".join(v["source"] + ":" + v["target"] for v in journal["volumes"])
    assert "data/db:/data/db" in volumes
    assert "/data/blink" not in volumes and "/data/clips" not in volumes

def test_caddy_proxies_api_before_static_fallback():
    caddy = read("web/Caddyfile")
    assert caddy.index("handle /api/*") < caddy.index("handle {")
    assert "reverse_proxy journal:8000" in caddy
```

Extend the data-preparation test to require `data/web/images`, `data/web/thumbs`, and `data/web/enrichment`, all created before Blink authentication instructions.

- [ ] **Step 2: Run and confirm failure**

Run: `python -m unittest tests.test_journal_installation tests.test_installation -v`

Expected: FAIL because the service, proxy, and nested directories are absent.

- [ ] **Step 3: Create the hardened image and Compose service**

`journal/Dockerfile`:

```dockerfile
FROM python:3.11.15-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY journal/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && pip check
COPY common/ ./common/
COPY journal/ ./journal/
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", "--timeout", "30", "journal.app:create_app()"]
```

Add `journal` with the shared security anchor, no `ports`, database RW, exact labels file RO, `/tmp` tmpfs, `app-internal` plus `journal-egress` networks, health check calling Python `urllib.request` against `/api/health`, and `depends_on: classifier`. Add `app-internal` to `web` and make `web` depend on a healthy journal.

- [ ] **Step 4: Add Caddy routing and directory preparation**

Inside the existing authenticated site block, before dynamic/static handlers:

```caddyfile
handle /api/* {
    reverse_proxy journal:8000
}
```

Change `scripts/prepare-data.sh` directories to:

```bash
directories=(data/blink data/clips data/db data/web data/web/images data/web/thumbs data/web/enrichment)
```

- [ ] **Step 5: Verify the phase**

Run: `python -m unittest discover -s tests -v`

Expected: all tests PASS.

Run: `docker compose config --quiet`

Expected: exit 0 with no unset-variable warning when a valid `.env` is present.

Run: `docker compose build journal web classifier`

Expected: all three images build successfully.

On the Raspberry Pi, run: `docker compose up -d && docker compose ps`

Expected: `puller`, `classifier`, `journal`, and `web` are running and `journal` reports healthy; an authenticated request to `http://127.0.0.1:8080/api/health` returns `{"status":"ok"}`.

- [ ] **Step 6: Commit**

```bash
git add journal/Dockerfile docker-compose.yml web/Caddyfile scripts/prepare-data.sh tests/test_installation.py tests/test_journal_installation.py
git commit -m "feat: deploy private journal service"
```

### Task 6: Run foundation acceptance and migration checks

**Files:**
- Modify: `tests/test_journal_api.py` only if an acceptance assertion exposes a real contract gap.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: a release gate for the interface phase.

- [ ] **Step 1: Run the full automated suite**

Run: `python -m unittest discover -s tests -v`

Expected: all tests PASS.

- [ ] **Step 2: Exercise an old database copy**

Run: `cp data/db/feeder.sqlite /tmp/perch-foundation.sqlite && DB_PATH=/tmp/perch-foundation.sqlite LABELS_PATH=classifier/model/current/labels.txt python -c 'from journal.app import create_app; app=create_app(); print(app.test_client().get("/api/health").json)'`

Expected: `{'status': 'ok'}` and the original `data/db/feeder.sqlite` is unchanged.

- [ ] **Step 3: Inspect the effective Compose boundary**

Run: `docker compose config --format json | python -c 'import json,sys; s=json.load(sys.stdin)["services"]["journal"]; print(s.get("ports"), s["read_only"], s["user"])'`

Expected: `None True 1000:1000` with the configured default IDs.

- [ ] **Step 4: Commit any acceptance-only correction, otherwise leave the tree clean**

```bash
git status --short
```

Expected: no output.
