# Cached Species Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich My Birds profiles with locally cached iNaturalist taxonomy, Wikimedia introductions, and attributed reference images while keeping the journal fully useful offline from providers.

**Architecture:** The single Gunicorn worker owns one bounded in-process queue. Species requests always return local history immediately and enqueue missing/stale profiles. A provider client rate-limits outbound calls, validates exact species-rank Aves matches, downloads only allowlisted image hosts, re-encodes images locally, and stores sanitized metadata in SQLite.

**Tech Stack:** Python 3.11.15, SQLite, Requests 2, Pillow, `queue.Queue`, `threading`, iNaturalist public API, Wikimedia Page Content Service, `unittest.mock`

## Global Constraints

- Requires the Family Journal Foundation and Daily Postcard Interface plans.
- Public read-only provider endpoints only; no OAuth token, API secret, or user account.
- Use a descriptive `Perch/1.0 (self-hosted bird journal; contact configured by operator)` User-Agent.
- Allow at most one outbound provider request per second; no bulk fetching.
- Use connect timeout 3 seconds and read timeout 10 seconds.
- Accept only exact scientific-name, species-rank, Aves matches.
- Cache profiles for 90 days; display stale content while refresh is queued.
- Never expose provider bodies, stack traces, or sensitive headers in API/log output.
- Download reference images only from configured iNaturalist media hosts, including redirects.
- Enforce a 5 MiB response limit, decode with Pillow, resize to maximum width 960, re-encode, and publish atomically under `data/web/enrichment`.
- Serve reference images only with creator, license, and source link; browser never contacts third-party image hosts.
- Provider failure must never block local browsing, favorites, or corrections.

## File map

- `common/schema.sql`, `common/db.py`: `species_profiles` cache and migration.
- `journal/providers.py`: bounded HTTP, iNaturalist matching, Wikimedia summary, image validation.
- `journal/enrichment.py`: cache repository, freshness policy, queue, and worker lifecycle.
- `journal/app.py`, `journal/queries.py`: schedule/serialize enrichment without delaying local profile queries.
- `journal/requirements.txt`, `journal/Dockerfile`, `docker-compose.yml`: dependencies, writable enrichment mount, and worker environment.
- `web/Caddyfile`: authenticated local enrichment image serving.
- `web/site/views/species.js`: pending refresh and attributed secondary reference image.
- `tests/test_species_profiles.py`, `tests/test_enrichment.py`, `tests/test_enrichment_api.py`, `tests/test_journal_installation.py`: cache/provider/security contracts.

---

### Task 1: Add the repeatable species-profile cache

**Files:**
- Modify: `common/schema.sql`
- Modify: `common/db.py`
- Create: `tests/test_species_profiles.py`

**Interfaces:**
- Produces: `species_profiles` keyed by normalized `sci:`/`common:` key.

- [ ] **Step 1: Write failing schema and key tests**

```python
def test_species_profile_schema_is_repeatable(tmp_path):
    conn = db.connect(tmp_path / "feeder.sqlite")
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(species_profiles)")}
    assert {"species_key","inat_taxon_id","introduction","reference_image","image_creator","image_license","fetched_at","error_category"} <= columns
    conn.close(); db.connect(tmp_path / "feeder.sqlite").close()

def test_species_key_normalizes_whitespace_and_case():
    assert queries.species_key("Blue Jay", "  Cyanocitta   CRISTATA ") == "sci:cyanocitta cristata"
    assert queries.species_key("  Blue   Jay ", None) == "common:blue jay"
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m unittest tests.test_species_profiles -v`

Expected: FAIL because `species_profiles` is absent.

- [ ] **Step 3: Add the cache table**

```sql
CREATE TABLE IF NOT EXISTS species_profiles (
    species_key TEXT PRIMARY KEY,
    inat_taxon_id INTEGER,
    introduction TEXT,
    inat_url TEXT,
    wikipedia_url TEXT,
    reference_image TEXT,
    image_source_url TEXT,
    image_creator TEXT,
    image_license TEXT,
    fetched_at TEXT,
    retry_after TEXT,
    error_category TEXT,
    updated_at TEXT NOT NULL
);
```

No destructive migration is needed; `CREATE TABLE IF NOT EXISTS` runs from `db.connect`.

- [ ] **Step 4: Verify and commit**

Run: `python -m unittest tests.test_species_profiles tests.test_journal_schema -v`

Expected: PASS.

```bash
git add common/schema.sql common/db.py tests/test_species_profiles.py
git commit -m "feat: add species enrichment cache"
```

### Task 2: Build strict provider clients and image ingestion

**Files:**
- Create: `journal/providers.py`
- Modify: `journal/requirements.txt`
- Create: `tests/test_enrichment.py`

**Interfaces:**
- Produces: `ProviderClient.match_species(scientific_name) -> TaxonMatch | None`, `fetch_summary(wikipedia_url) -> PageSummary | None`, and `download_reference_image(photo, destination) -> ReferenceImage | None`.

- [ ] **Step 1: Write mocked failing provider tests**

Test exact Aves/species acceptance; rejection of fuzzy, genus, and non-bird results; URL encoding; User-Agent; one-second spacing via injected clock/sleeper; 3/10 timeouts; Wikimedia plain-text extraction; missing attribution rejection; five-megabyte cutoff; disallowed initial/redirect host rejection; malformed image rejection; 960px resize; and atomic publication. No test performs network I/O.

Representative exact-match fixture:

```python
INAT_MATCH = {"results":[{"id":123,"name":"Cyanocitta cristata","rank":"species","iconic_taxon_name":"Aves","wikipedia_url":"https://en.wikipedia.org/wiki/Blue_jay","default_photo":{"medium_url":"https://inaturalist-open-data.s3.amazonaws.com/photos/1/medium.jpg","attribution":"(c) Jane Birder, CC BY 4.0","license_code":"cc-by"}}]}
assert client.match_species("Cyanocitta cristata").taxon_id == 123
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m unittest tests.test_enrichment -v`

Expected: FAIL because `journal.providers` does not exist.

- [ ] **Step 3: Implement bounded requests and exact matching**

Use one `requests.Session`, injected `clock=time.monotonic` and `sleep=time.sleep`, `timeout=(3, 10)`, `stream=True` for images, and a `RateGate.wait()` that maintains one second between provider calls. Query `GET https://api.inaturalist.org/v2/taxa` with `q={scientific_name}`, `rank=species`, and an explicit `fields` selection for `id,name,rank,iconic_taxon_name,wikipedia_url,default_photo`. Match case-folded scientific names exactly and require `rank == "species"` and `iconic_taxon_name == "Aves"`. When a Wikipedia URL is present, extract its page title and query `GET https://en.wikipedia.org/api/rest_v1/page/summary/{url_encoded_title}`; retain only plain-text `extract`, canonical page URL, and image metadata already validated through iNaturalist.

Allow image hosts exactly:

```python
ALLOWED_IMAGE_HOSTS = {
    "inaturalist-open-data.s3.amazonaws.com",
    "static.inaturalist.org",
}
MAX_IMAGE_BYTES = 5 * 1024 * 1024
```

Disable automatic redirects and manually follow at most three redirects, validating every `Location` host. Stream in 64 KiB chunks and stop before exceeding the limit. Decode, convert to RGB, resize to 960px maximum, save as JPEG to `.tmp`, then `replace` the final path.

- [ ] **Step 4: Pin dependencies and verify**

Append:

```text
requests>=2.32.4,<3
Pillow==11.3.0
```

Run: `python -m unittest tests.test_enrichment -v`

Expected: PASS with zero live network calls.

- [ ] **Step 5: Commit**

```bash
git add journal/providers.py journal/requirements.txt tests/test_enrichment.py
git commit -m "feat: add bounded species providers"
```

### Task 3: Add cache freshness, failure categories, and the worker queue

**Files:**
- Create: `journal/enrichment.py`
- Modify: `journal/app.py`
- Create: `tests/test_enrichment_queue.py`

**Interfaces:**
- Produces: `EnrichmentService.get(species_key) -> dict | None`, `schedule(species_key, common, scientific) -> bool`, `start()`, and `stop()`.

- [ ] **Step 1: Write failing service tests**

Cover fresh rows not queued, stale rows returned and queued, missing rows pending, duplicate queue collapse, restart-safe requeue, successful provider/cache/image flow, and categorized `not_found`, `throttled`, `timeout`, `malformed`, and `unavailable` failures. Assert retry-after durations: not-found 24 hours, throttled 1 hour, timeout/unavailable 15 minutes, malformed 6 hours.

- [ ] **Step 2: Run and confirm failure**

Run: `python -m unittest tests.test_enrichment_queue -v`

Expected: FAIL because `EnrichmentService` does not exist.

- [ ] **Step 3: Implement one bounded queue and freshness policy**

Use `Queue(maxsize=100)`, a locked `set[str]` for queued keys, one daemon thread, and sentinel shutdown. `get` returns `status: ready` for rows under 90 days, `status: stale` plus content for older rows, `status: pending` for missing rows with no active retry delay, and `status: failed` with only `error_category` and `retry_after` during a cached failure delay.

On success, upsert all sanitized metadata and clear error fields. On failure, retain existing introduction/reference data, update only category/retry timestamp/updated timestamp, and never persist response bodies or exception strings.

- [ ] **Step 4: Start exactly one service with the app**

In `create_app`, construct one service, save it under `app.extensions["enrichment"]`, and call `start()` unless `TESTING` and `ENRICHMENT_AUTOSTART` is false. Tests inject a fake provider and deterministic clock. Gunicorn remains one worker.

- [ ] **Step 5: Verify and commit**

Run: `python -m unittest tests.test_enrichment_queue tests.test_journal_api -v`

Expected: PASS.

```bash
git add journal/enrichment.py journal/app.py tests/test_enrichment_queue.py
git commit -m "feat: queue cached species enrichment"
```

### Task 4: Integrate enrichment with the species API without blocking local data

**Files:**
- Modify: `journal/queries.py`
- Modify: `journal/app.py`
- Create: `tests/test_enrichment_api.py`

**Interfaces:**
- Consumes: `EnrichmentService`.
- Produces: `/api/species/{species_key}` with `enrichment: {status, introduction, sources, reference_image}`.

- [ ] **Step 1: Write failing API integration tests**

```python
response = client.get("/api/species/sci%3Acyanocitta%20cristata")
assert response.status_code == 200
assert response.json["visits"] == 2
assert response.json["enrichment"]["status"] == "pending"
fake_service.schedule.assert_called_once()
```

Add cases where the fake provider raises on scheduling and where cached stale content exists. Expected: local stats/gallery remain 200; stale introduction remains present; response never contains `provider_body`, `exception`, or a third-party image URL.

- [ ] **Step 2: Run and confirm failure**

Run: `python -m unittest tests.test_enrichment_api -v`

Expected: FAIL because species detail lacks enrichment.

- [ ] **Step 3: Add non-blocking serialization**

After the local query completes, call `service.get(key)`, call `service.schedule(...)` for `pending` or `stale`, and serialize only:

```python
{
  "status": profile["status"],
  "introduction": profile.get("introduction"),
  "sources": {"inaturalist": profile.get("inat_url"), "wikipedia": profile.get("wikipedia_url")},
  "reference_image": None if not fully_attributed else {
      "src": "/enrichment/" + profile["reference_image"],
      "creator": profile["image_creator"],
      "license": profile["image_license"],
      "source": profile["image_source_url"],
  },
}
```

Catch queue-full/provider scheduling errors, log only category/species key, and return local content.

- [ ] **Step 4: Verify and commit**

Run: `python -m unittest tests.test_enrichment_api tests.test_journal_api -v`

Expected: PASS.

```bash
git add journal/queries.py journal/app.py tests/test_enrichment_api.py
git commit -m "feat: expose cached species profiles"
```

### Task 5: Mount and serve the local reference-image cache securely

**Files:**
- Modify: `docker-compose.yml`
- Modify: `web/Caddyfile`
- Modify: `tests/test_journal_installation.py`

**Interfaces:**
- Produces: journal RW `/data/web/enrichment`; web RO `/data/web`; authenticated `/enrichment/*` local file serving.

- [ ] **Step 1: Add failing boundary tests**

Require journal volume source `./data/web/enrichment` targeting `/data/web/enrichment` with write access, require no broad `./data/web:/data/web` journal mount, and require Caddy `@dynamic` to include `/enrichment/*`. Assert no provider hostname appears in frontend JavaScript.

- [ ] **Step 2: Run and confirm failure**

Run: `python -m unittest tests.test_journal_installation -v`

Expected: FAIL because journal lacks the cache mount and Caddy route.

- [ ] **Step 3: Add the narrow mount and local route**

Add:

```yaml
- ./data/web/enrichment:/data/web/enrichment
```

to `journal.volumes`, and change Caddy matcher to:

```caddyfile
@dynamic path /thumbs/* /images/* /enrichment/* /data/*
```

All remain below the existing Basic Auth directive and use `Cache-Control "no-store"`.

- [ ] **Step 4: Verify and commit**

Run: `python -m unittest tests.test_journal_installation tests.test_installation -v`

Expected: PASS.

```bash
git add docker-compose.yml web/Caddyfile tests/test_journal_installation.py
git commit -m "feat: serve local enrichment images"
```

### Task 6: Render attributed enrichment as a secondary profile element

**Files:**
- Modify: `web/site/views/species.js`
- Modify: `web/site/styles.css`
- Modify: `tests/test_web_contract.py`

**Interfaces:**
- Consumes: serialized enrichment from Task 4.
- Produces: local-first profile with one pending refresh and attributed reference image.

- [ ] **Step 1: Add failing frontend contracts**

Require introduction via `textContent`, source links with `rel="noopener noreferrer"`, reference image only when creator/license/source are all present, Perch cover before external image, pending refresh limited to one attempt, and local-only messages for missing/failed enrichment.

- [ ] **Step 2: Run and confirm failure**

Run: `python -m unittest tests.test_web_contract.WebContractTests.test_species_enrichment_contract -v`

Expected: FAIL because the profile does not render the approved metadata.

- [ ] **Step 3: Implement safe profile enrichment rendering**

Keep the Perch photograph as the cover. Append a “About this bird” section only after local statistics. For `pending`, show `We’re gathering a little more about this bird.` and schedule one 2-second refresh tied to the current species route; cancel it on navigation. For `failed` or absent content, show `Your sightings are still complete; extra species notes are unavailable right now.`

Reference image caption format: `Reference photo by {creator} · {license} · View source`. Set introduction using `.textContent` and link only the API-returned canonical source URLs.

- [ ] **Step 4: Verify and commit**

Run: `python -m unittest tests.test_web_contract tests.test_enrichment_api -v`

Expected: PASS.

```bash
git add web/site/views/species.js web/site/styles.css tests/test_web_contract.py
git commit -m "feat: show attributed bird profiles"
```

### Task 7: Complete offline-provider and security acceptance

**Files:**
- Modify: enrichment files only if acceptance exposes a defect.

**Interfaces:**
- Consumes: all enrichment tasks.
- Produces: provider-independent, auditable profile behavior.

- [ ] **Step 1: Run all tests with network disabled**

Run: `python -m unittest discover -s tests -v`

Expected: all tests PASS without provider access.

- [ ] **Step 2: Build and inspect the runtime boundary**

Run: `docker compose build journal web && docker compose config --format json | python -c 'import json,sys; s=json.load(sys.stdin)["services"]["journal"]; print(s.get("ports"), [v["target"] for v in s["volumes"]])'`

Expected: `None` for ports; targets include `/data/db`, `/data/web/enrichment`, and the exact labels target, but not `/data/blink`, `/data/clips`, `/data/web/images`, or `/data/web/thumbs`.

- [ ] **Step 3: Exercise provider failure manually**

Start the stack with journal egress temporarily unavailable, open a species profile, favorite a visit, and correct a visit. Expected: local cover, history, gallery, favorites, and correction work; enrichment shows the local-only message; no third-party request appears in browser network logs.

- [ ] **Step 4: Exercise cached success and attribution**

Restore egress, open one uncached species, wait for pending refresh, and reopen it. Expected: exact matching species introduction and secondary reference image appear with creator, license, and source; image URL is on the Perch origin under `/enrichment/`.

- [ ] **Step 5: Inspect logs for leakage**

Run: `docker compose logs journal --no-color`

Expected: no Basic Auth value, cookie, environment secret, raw provider body, redirect body, or Python stack trace for categorized provider failures.

- [ ] **Step 6: Leave a clean acceptance commit**

If fixes were necessary, rerun the full suite and commit only those files with `git commit -m "fix: close enrichment acceptance gaps"`. Otherwise `git status --short` must produce no output.
