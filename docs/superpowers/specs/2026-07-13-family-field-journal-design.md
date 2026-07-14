# Family Field Journal Design

## Status

Approved for implementation planning on 2026-07-13.

## Goal

Turn Perch's current read-only detection dashboard into a warm, photo-first family field journal for one feeder. Every authenticated family member sees the same journal, favorites, corrections, species collection, and history. The experience should feel personal and delightful on a phone while remaining useful on desktop.

The release must preserve Perch's self-hosted character, current Blink ingestion and local classification pipeline, Raspberry Pi deployment, and defense-in-depth web boundary. It must not introduce another host-facing port or make the journal unavailable when an enrichment provider is down.

## Product decisions

- The visual direction is **Daily Postcard**: a prominent latest-visitor photograph followed by a concise daily story, useful statistics, and recent visits.
- The primary navigation is **Today**, **My Birds**, and **Favorites**.
- The journal is shared. It does not maintain per-person favorites, preferences, or edit history.
- The release is photo-first. Raw Blink video playback and live streaming are postponed.
- Every identified display image and thumbnail is retained indefinitely.
- Favorites and species corrections are included in the first release.
- Species profiles combine Perch's own history with locally cached public enrichment.
- Home Assistant is out of scope.

## User experience

### Today

Today is the landing page and emotional center of the application. It contains, in order:

1. A local-date greeting such as “Good morning from the feeder.”
2. A large latest-visitor image with common name, scientific name, local capture time, confidence, returning/new status, and a favorite control.
3. Compact cards for visits today, species today, and busiest local hour.
4. A small hourly activity chart for the current local day.
5. Recent visit cards with image, effective species, time, confidence, favorite control, and “Wrong bird?” action.
6. A path into complete history when more visits exist than the landing page shows.

An empty journal uses friendly copy and explains that the first identified visitor will appear automatically. An API failure keeps the static shell available, shows a compact retryable status, and never replaces the whole page with an error screen.

### My Birds

My Birds is the permanent species collection. Its collection view supports text search and sorting by newest discovery, most visits, most recent visit, and alphabetical name. Each species tile uses a Perch photograph and shows visit count, first seen, and last seen. A newly observed species receives a temporary “New” marker until its profile has been opened.

Each species profile contains:

- A Perch photograph as the cover image, preferring a shared favorite and otherwise using the most recent detection.
- Effective common and scientific names.
- First seen, last seen, total visits, and busiest observed hours.
- A paginated gallery of every non-excluded detection assigned to that species.
- A cached external introduction, reference link, and properly attributed reference image when available.
- A local-only fallback when enrichment has not completed or failed.

### Favorites

Favorites is one shared family album ordered newest first. Favoriting and unfavoriting are idempotent. The state is visible on the landing page, visit detail, species gallery, and favorites album without a page reload.

### Visit details and corrections

Opening a visit shows the larger image, effective species, original AI prediction, scientific name, local capture time, confidence, favorite state, and correction state.

“Wrong bird?” opens a searchable list derived from the installed model labels plus a distinct “Not a bird” choice. The journal does not accept arbitrary species text. This avoids spelling variants and preserves a consistent species collection.

A correction changes the effective species used by Today, My Birds, Favorites, search, and all statistics. It does not modify the original AI prediction. “Not a bird” excludes the detection from visitor totals, activity charts, species albums, and normal history, while leaving the underlying detection and image available in the database for audit and possible restoration.

## Architecture

### Chosen approach

Add a small `journal` Python service and retain the existing static frontend. This was selected over embedding HTTP behavior in the classifier or rebuilding Perch as a full web framework application.

The request flow is:

```text
browser -> Caddy -> static site
                -> /api/* -> journal service -> SQLite

Blink -> puller -> clips -> classifier -> SQLite + permanent images
```

The journal service is independently restartable and has one purpose: present and mutate journal state. It does not download Blink clips, load the bird model, extract frames, or serve public files.

### Container boundaries

- `journal` runs as the configured non-root `PUID:PGID`, with a read-only root filesystem, dropped capabilities, no-new-privileges, bounded processes, bounded logs, and a tmpfs for temporary files.
- It mounts `data/db` read-write, `data/web/enrichment` read-write, and the current classifier label bundle read-only. It cannot write classifier snapshots or read raw clips.
- It joins the internal application network used by Caddy and has outbound HTTPS access for enrichment.
- It declares no `ports` entry. Only Caddy can reach `journal:8000` through Compose networking.
- The web container remains unable to read Blink credentials or raw clips.
- Caddy's existing authentication rule covers `/api/*` as well as static and image content.
- The optional remote-access deployment remains unchanged and is not part of this feature's repository documentation.

### HTTP service

Use a small Flask application served by Gunicorn with one worker and a small thread pool. The expected traffic is a handful of authenticated family members, so predictable resource use and simple operational behavior are more important than horizontal scale.

The API surface is:

- `GET /api/today` — local-day summary, latest detection, recent detections, and hourly activity.
- `GET /api/detections` — cursor-paginated history with optional species, favorite, and date filters.
- `GET /api/detections/{id}` — one visit with original and effective identification.
- `PATCH /api/detections/{id}` — idempotently update favorite, correction, or excluded state.
- `GET /api/species` — effective species collection with search and supported sort modes.
- `GET /api/species/{species_key}` — local statistics, gallery page, enrichment, and enrichment status.
- `GET /api/taxa?q=...` — bounded search across the installed model's known bird labels for the correction picker.
- `GET /api/health` — database readiness for container health checks.

All list endpoints enforce a maximum page size. Cursor pagination is preferred over offset pagination so new detections do not cause duplicates while a user browses older history.

## Data model

### Immutable detections

The existing `detections` row remains the immutable classifier output. New detections continue storing the original common name, scientific name, confidence, capture time, and image paths. Existing rows migrate without rewriting their prediction.

### Shared annotations

Add one optional annotation row per detection:

```sql
CREATE TABLE detection_annotations (
    detection_id          INTEGER PRIMARY KEY REFERENCES detections(id) ON DELETE CASCADE,
    favorite              INTEGER NOT NULL DEFAULT 0 CHECK (favorite IN (0, 1)),
    corrected_common_name TEXT,
    corrected_scientific  TEXT,
    excluded              INTEGER NOT NULL DEFAULT 0 CHECK (excluded IN (0, 1)),
    updated_at            TEXT NOT NULL
);
```

The effective name is the corrected value when present and otherwise the original classifier value. An excluded row is omitted from all normal journal queries. Updates use `INSERT ... ON CONFLICT DO UPDATE` inside short transactions.

Corrections are validated against the currently installed label bundle before being stored. The correction stores both common and scientific names rather than a model output index because model indices are bundle-specific and may change in a future model.

### Enrichment cache

Add a `species_profiles` cache keyed by normalized scientific name, falling back to normalized common name only when the model has no scientific name. A species key is `sci:` plus the trimmed, whitespace-collapsed, case-folded scientific name, or `common:` plus the equivalently normalized common name. The key is URL-encoded when used in an API path. The cache stores the matched iNaturalist taxon identifier, introduction, source URLs, local reference-image path, image creator, image license, fetch timestamps, and the last non-sensitive error category.

Cached content is considered fresh for 90 days. Stale content remains displayable while refresh is attempted. Provider response bodies and stack traces are never written into the public API response.

### Query rules

- Species counts and activity use effective, non-excluded detections.
- Favorites may be corrected but may not remain visible when excluded as “Not a bird.” Restoring the detection restores its existing favorite flag.
- First-seen and new-species calculations use effective assignments, so a correction can create or remove a species album.
- Capture times remain stored in their existing canonical form. Grouping, greetings, and formatting use the configured `TZ`, defaulting to `America/New_York`.
- The database remains in WAL mode with the existing busy timeout so puller, classifier, and journal writes can coexist.

## Permanent image handling

The current classifier produces one 480-pixel-wide image and removes images outside the recent JSON window. That behavior is incompatible with a permanent photo journal.

For every new confident detection, the classifier will atomically publish:

- A display image with a maximum width of 1280 pixels, JPEG quality appropriate for the hero and detail views.
- A thumbnail with a maximum width of 480 pixels for grids and lists.

Both paths are stored with the detection and are never removed by routine dashboard regeneration. Files are written to temporary names and atomically renamed so Caddy never serves a partial image.

Existing 480-pixel images remain supported as both display image and thumbnail after migration. The migration does not attempt to reconstruct higher-resolution files from already-pruned raw clips. Raw Blink clips continue obeying `RETAIN_DAYS` and are not required after images are published.

The static `detections.json` file may remain temporarily for migration compatibility, but the redesigned interface reads the journal API. Its former 300-row limit no longer defines retention or gallery history.

Externally sourced reference images use a separate `data/web/enrichment` directory. The journal downloads only image URLs returned by the validated iNaturalist species match, rejects redirects outside the expected iNaturalist media hosts, enforces a five-megabyte response limit, decodes and resizes the image to a maximum 960-pixel width, re-encodes it, and publishes it atomically. The browser never contacts a third-party image host directly. A reference image is served only alongside its creator, license, and source link.

## External enrichment

The journal matches a species using its scientific name against the supported iNaturalist API. It accepts only an exact species-rank bird match. The iNaturalist result provides stable taxon metadata, an optional default-photo attribution and license, and an optional Wikipedia link.

When a Wikipedia link is available, the service retrieves the Wikimedia page summary for a concise readable introduction and canonical source link. Every profile displays source attribution. A Perch photograph remains the profile cover; an external reference image is secondary and is shown only when its license and creator metadata are present.

Enrichment behavior follows these rules:

- Public read-only endpoints only; no iNaturalist or Wikimedia user account, OAuth token, or API secret.
- A descriptive Perch user agent.
- At most one outbound provider request per second and no bulk downloads.
- Strict connect/read timeouts and bounded response sizes.
- One in-process enrichment queue in the single Gunicorn worker.
- A profile request returns local data immediately and schedules missing or stale enrichment. The frontend may refresh the profile once when the API reports `pending`.
- Restarts are safe: a missing or stale row is queued again on a later request.
- Provider failure never blocks local journal browsing or corrections.

This approach follows iNaturalist's recommendation to use its newer API, identify the application, keep requests near one per second, and avoid bulk access. Wikimedia's page-summary service supplies the introduction and basic page metadata.

References:

- [iNaturalist API recommended practices](https://www.inaturalist.org/pages/api%2Brecommended%2Bpractices)
- [Wikimedia Page Content Service](https://www.mediawiki.org/wiki/Page_Content_Service)

## Frontend design

The frontend remains framework-free HTML, CSS, and JavaScript. It gains client-side view routing for Today, My Birds, Favorites, species detail, and visit detail while preserving installable-PWA behavior.

Desktop uses a compact top navigation. Phone layouts use a fixed bottom navigation for Today, My Birds, and Favorites. The content hierarchy is the same at every breakpoint.

Interaction requirements:

- Use semantic links and buttons with visible focus states and descriptive accessible names.
- Do not communicate confidence, favorite state, new status, or failures through color alone.
- Respect reduced-motion preferences.
- Lazy-load gallery images below the fold and use thumbnails in grids.
- Use optimistic favorite and correction updates, but roll back visibly when the request fails.
- Preserve the user's current page and filters during automatic refreshes.
- Never inject provider HTML; render returned text through `textContent`.

The service worker caches the application shell, not authenticated API responses or journal images. A stale shell may open offline and explain that journal data requires a connection to the feeder rather than displaying misleading cached counts.

## Error handling and operations

- SQLite busy errors receive a short bounded retry in the journal service and otherwise return a retryable response.
- Invalid IDs, unknown correction taxa, malformed cursors, and unsupported filters return clear 4xx responses without internal details.
- Missing image files render a neutral placeholder while retaining the journal record.
- Enrichment timeouts, not-found results, throttling, and malformed provider responses are categorized and cached briefly to prevent request loops.
- API failures show an inline status with a retry action; the last successful view remains visible where safe.
- Journal startup runs idempotent migrations before reporting healthy.
- Container logs exclude authentication headers, Basic Auth values, cookies, provider response bodies, and environment secrets.
- Database backup remains sufficient for annotations and cached metadata. Permanent images remain covered by the existing `data/web` backup requirement.

## Migration and compatibility

1. Apply idempotent schema migrations for annotations, image-path evolution, and species profiles.
2. Treat each existing detection's current thumbnail as both its display and thumbnail image.
3. Stop pruning identified images during dashboard regeneration.
4. Add the journal service and Caddy `/api/*` proxy before switching the frontend to API reads.
5. Keep old detection rows and raw-clip retention settings unchanged.
6. Verify that current empty and populated installations both start without manual database work.

Rollback may return to the old static frontend without losing original detections. New annotation and enrichment tables are additive and can remain unused. Newly generated larger images are also harmless to the older frontend.

## Testing

### Database and domain tests

- Clean and existing-database migrations are repeatable.
- Favorite updates are idempotent.
- Corrections preserve original classifier values.
- “Not a bird” removes and restoration returns a detection to every relevant aggregate.
- Corrected assignments update species counts, first/last seen, new-species state, and activity.
- Concurrent classifier and journal writes respect WAL and busy-timeout behavior.
- Local-day grouping is correct across midnight and daylight-saving transitions.

### API tests

- Today, history, species, detail, search, sort, pagination, and health responses.
- Cursor stability while new detections arrive.
- Validation and bounded page sizes.
- Missing rows and missing image behavior.
- Favorite/correction update success, rollback cases, and retryable busy responses.
- API routes are reachable through authenticated Caddy and the journal port is not published to the host.

### Image and enrichment tests

- Display and thumbnail dimensions, atomic publication, and permanent retention.
- Existing one-size images remain renderable.
- Exact bird-species matching and rejection of ambiguous/non-bird taxa.
- Attribution and licensing fields survive caching.
- Fresh, stale, missing, throttled, timed-out, and malformed enrichment responses.
- Local species profiles remain complete when all outbound access is unavailable.

### Frontend tests

- Today, My Birds, Favorites, species detail, visit detail, corrections, empty journal, offline API, and missing-image states.
- Desktop and phone breakpoints using realistic long names and large histories.
- Keyboard-only navigation, focus visibility, accessible names, contrast, and reduced motion.
- Optimistic interaction success and visible rollback on failure.
- PWA shell update and offline explanation behavior.

The complete existing test suite must continue to pass. Deployment verification must include a Raspberry Pi build, health checks, an authenticated local browser session, and a phone-sized remote session through the existing private access path.

## Out of scope

- Raw-video playback and live streaming
- Per-family-member favorites, corrections, settings, or audit identity
- Home Assistant
- Audio recognition or BirdNET correlation
- Public feeds, community sharing, or public guest mode
- Individual-bird naming, sex recognition, or behavior recognition
- AI chat or generated naturalist commentary
- Configurable notification controls, daily push recaps, or monthly generated recaps
- Changes to the separately managed remote-access configuration

These can be evaluated after the shared photo journal is stable and has accumulated enough real household use to justify further complexity.
