# Daily Postcard Interface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the read-only Field Log dashboard with the approved photo-first Perch journal, including shared favorites/corrections and reliable iOS/Android home-screen branding.

**Architecture:** Keep the frontend framework-free and split it into a small API client, hash router, pure presentation helpers, reusable DOM components, and one module per view. The service worker caches only the static shell. All journal data and images remain network-only behind the existing authentication layers.

**Tech Stack:** Semantic HTML, modern CSS, ES modules, Fetch API, Web App Manifest, Service Worker, Python `unittest` contract tests

## Global Constraints

- Requires the completed Family Journal Foundation plan and its eight API routes.
- Primary navigation copy is exactly **Today**, **My Birds**, and **Favorites**.
- Header brand is **Perch · Sara's Feeder**; installed short name is **Perch** and full name is **Perch · Sara's Feeder**.
- Use the existing stylized Perch bird mark as the canonical logo.
- Provide normal 192×192, normal 512×512, dedicated maskable 512×512, Apple 180×180, and favicon assets.
- Do not use the same file for normal and maskable purposes.
- Cache only the application shell; never cache `/api/`, `/images/`, `/thumbs/`, or `/enrichment/` responses.
- Remove browser-loaded Google Fonts and use local system font stacks so the shell makes no unauthenticated third-party font requests.
- Render provider and API text with `textContent`; never inject returned HTML.
- Use semantic links/buttons, visible focus states, descriptive accessible names, and non-color status cues.
- Respect `prefers-reduced-motion`; lazy-load below-fold gallery images.
- Optimistically update favorite/correction state and visibly roll back on failure.
- Preserve current route and filters during refreshes.

## File map

- `web/site/index.html`: semantic shell, header, navigation, live status, and view outlet.
- `web/site/app.js`: bootstrap, router hookup, refresh lifecycle, and service-worker registration.
- `web/site/api.js`: fetch wrapper and API methods.
- `web/site/router.js`: hash parsing and route dispatch.
- `web/site/format.js`: pure local-time, confidence, and greeting formatting.
- `web/site/components.js`: image, favorite, visit card, error, and pagination elements.
- `web/site/views/today.js`, `history.js`, `birds.js`, `favorites.js`, `species.js`, `visit.js`: view-specific rendering and interactions.
- `web/site/styles.css`: Daily Postcard responsive system.
- `web/site/manifest.json`, `web/site/sw.js`, `web/site/icons/*`: Perch PWA identity.
- `scripts/build-perch-icons.py`: deterministic checked-in icon generation from the canonical mark geometry.
- `tests/test_web_contract.py`, `tests/test_pwa_contract.py`: static and generated-asset contracts.

---

### Task 1: Establish the Perch shell, API client, and router

**Files:**
- Modify: `web/site/index.html`
- Replace: `web/site/app.js`
- Create: `web/site/api.js`
- Create: `web/site/router.js`
- Create: `web/site/format.js`
- Create: `tests/test_web_contract.py`

**Interfaces:**
- Produces: `api.getToday()`, `getDetections(params)`, `getDetection(id)`, `patchDetection(id, patch)`, `getSpecies(params)`, `getSpeciesDetail(key, params)`, `searchTaxa(query)`.
- Produces: `parseRoute(hash) -> {name, params}` and `startRouter(render) -> cleanup`.

- [ ] **Step 1: Write failing shell and module contract tests**

```python
def test_shell_uses_perch_identity_and_semantic_navigation():
    html = read("web/site/index.html")
    assert "Perch · Sara's Feeder" in html
    assert 'href="#/today"' in html
    assert 'href="#/birds"' in html
    assert 'href="#/favorites"' in html
    assert 'id="view"' in html and 'aria-live="polite"' in html
    assert '<script type="module" src="app.js"></script>' in html

def test_frontend_never_reads_legacy_static_json():
    scripts = "\n".join(path.read_text() for path in (ROOT / "web/site").rglob("*.js"))
    assert "detections.json" not in scripts
    assert '"/api/today"' in scripts
```

- [ ] **Step 2: Run and confirm failure**

Run: `python -m unittest tests.test_web_contract -v`

Expected: FAIL on Field Log identity and legacy JSON usage.

- [ ] **Step 3: Create the semantic shell**

Use this structure in `index.html`:

```html
<header class="app-header">
  <a class="brand" href="#/today" aria-label="Perch, Sara's Feeder home">
    <img src="icons/perch-mark.svg" alt="" width="40" height="40">
    <span>Perch <small>Sara's Feeder</small></span>
  </a>
  <nav class="top-nav" aria-label="Journal">
    <a href="#/today">Today</a><a href="#/birds">My Birds</a><a href="#/favorites">Favorites</a>
  </nav>
</header>
<main id="view" tabindex="-1"></main>
<p id="connection-status" class="status" role="status" aria-live="polite"></p>
<nav class="bottom-nav" aria-label="Journal">
  <a href="#/today">Today</a><a href="#/birds">My Birds</a><a href="#/favorites">Favorites</a>
</nav>
<script type="module" src="app.js"></script>
```

- [ ] **Step 4: Implement API client and hash router**

`api.js` must use one wrapper:

```javascript
async function request(path, options = {}) {
  const response = await fetch(path, {cache: "no-store", headers: {"Content-Type": "application/json"}, ...options});
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw Object.assign(new Error(body.message || "The feeder could not be reached."), {status: response.status, body});
  return body;
}
export const getToday = () => request("/api/today");
export const patchDetection = (id, patch) => request(`/api/detections/${id}`, {method: "PATCH", body: JSON.stringify(patch)});
```

`router.js` recognizes `/today`, `/history`, `/birds`, `/favorites`, `/species/:key`, `/visits/:id`, and redirects empty/unknown hashes to `#/today`. Query parameters are returned as `URLSearchParams`. Remove the Google Fonts `<link>` and preconnect elements from `index.html`.

- [ ] **Step 5: Verify and commit**

Run: `python -m unittest tests.test_web_contract -v`

Expected: PASS.

```bash
git add web/site/index.html web/site/app.js web/site/api.js web/site/router.js web/site/format.js tests/test_web_contract.py
git commit -m "feat: add Perch journal shell"
```

### Task 2: Build the photo-first Today view

**Files:**
- Create: `web/site/components.js`
- Create: `web/site/views/today.js`
- Modify: `web/site/app.js`
- Modify: `web/site/styles.css`
- Modify: `tests/test_web_contract.py`

**Interfaces:**
- Produces: `renderToday(outlet, data, actions)` and reusable `favoriteButton`, `visitCard`, `missingImage`, `inlineError`.

- [ ] **Step 1: Add failing Today contracts**

Assert source-level presence of the response fields `greeting`, `latest`, `visits_today`, `species_today`, `busiest_hour`, `hourly_activity`, and `recent`; accessible favorite labels; “Wrong bird?”; empty copy; retry control; and image `onerror` fallback.

- [ ] **Step 2: Run and confirm failure**

Run: `python -m unittest tests.test_web_contract.WebContractTests.test_today_view_contract -v`

Expected: FAIL because `views/today.js` does not exist.

- [ ] **Step 3: Implement safe DOM components**

Create elements with `document.createElement`; set all API strings with `.textContent`. `favoriteButton(detection, onToggle)` must set `aria-pressed`, use label `Add {species} visit to favorites` or `Remove {species} visit from favorites`, optimistically flip state, disable during the request, and restore the prior state plus call `showStatus("Favorite was not saved. Try again.")` on rejection.

- [ ] **Step 4: Render the approved Today hierarchy**

`renderToday` must create, in order: local greeting; large hero using `display_image`; returning/new text; three stat cards; a semantic 24-bar activity chart with each bar labeled `{hour}: {count} visits`; recent cards using thumbnails; and complete-history link. If no latest visit exists, render: `The first identified visitor will appear here automatically.` If loading fails, leave the last successful DOM intact and append a retryable inline status.

- [ ] **Step 5: Add Daily Postcard responsive styling**

Use CSS custom properties based on the approved pale green, charcoal, warm amber, cream, and muted sage palette. Hero aspect ratio is `4 / 3`, page max width `72rem`, phone bottom navigation appears below `48rem`, desktop top navigation appears at/above `48rem`, all focusable controls use a 3px visible outline, and motion transitions are disabled inside:

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { scroll-behavior: auto !important; transition: none !important; animation: none !important; }
}
```

- [ ] **Step 6: Verify and commit**

Run: `python -m unittest tests.test_web_contract -v`

Expected: PASS.

```bash
git add web/site/components.js web/site/views/today.js web/site/app.js web/site/styles.css tests/test_web_contract.py
git commit -m "feat: build Daily Postcard landing page"
```

### Task 3: Add complete history, My Birds, Favorites, and paginated profiles

**Files:**
- Create: `web/site/views/history.js`
- Create: `web/site/views/birds.js`
- Create: `web/site/views/favorites.js`
- Create: `web/site/views/species.js`
- Modify: `web/site/app.js`
- Modify: `web/site/styles.css`
- Modify: `tests/test_web_contract.py`

**Interfaces:**
- Produces: `renderBirds`, `renderFavorites`, `renderSpecies`; all accept `(outlet, data, actions)`.

- [ ] **Step 1: Add failing collection/profile contracts**

Assert cursor-paginated complete history with species/favorite/date filters; exact sort values `newest`, `visits`, `recent`, `alphabetical`; search input; “New” text; first/last seen and count fields; favorite album; species cover; busiest hours; gallery cursor; enrichment status slots; and `loading="lazy"` on gallery images.

- [ ] **Step 2: Run and confirm failure**

Run: `python -m unittest tests.test_web_contract -v`

Expected: FAIL because the three views are absent.

- [ ] **Step 3: Implement complete history and My Birds with URL-preserved filters**

History reads `#/history?species={key}&favorite={boolean}&date={YYYY-MM-DD}`, calls cursor-paginated `/api/detections`, appends older results, and keeps filter values in the URL. Search and sort update `#/birds?q={encoded}&sort={value}` with `history.replaceState`, call `/api/species`, and retain the URL during automatic refresh. Species tiles link with `encodeURIComponent(species_key)`, show a Perch thumbnail, visits, first seen, last seen, and textual “New”. Opening a species profile causes the server response to clear its shared `is_new` state; returning to My Birds must refetch the collection rather than preserving a stale badge.

- [ ] **Step 4: Implement shared Favorites and species profiles**

Favorites calls `/api/detections?favorite=true` and uses shared optimistic controls. Species profile uses a favorite Perch image or most recent Perch image as cover, renders local history before enrichment, shows a local-only message for `missing`, `pending`, or `failed`, and appends cursor pages without replacing existing gallery nodes.

- [ ] **Step 5: Verify and commit**

Run: `python -m unittest tests.test_web_contract -v`

Expected: PASS.

```bash
git add web/site/views/history.js web/site/views/birds.js web/site/views/favorites.js web/site/views/species.js web/site/app.js web/site/styles.css tests/test_web_contract.py
git commit -m "feat: add shared bird collection"
```

### Task 4: Add visit detail and controlled corrections

**Files:**
- Create: `web/site/views/visit.js`
- Modify: `web/site/components.js`
- Modify: `web/site/app.js`
- Modify: `web/site/styles.css`
- Modify: `tests/test_web_contract.py`

**Interfaces:**
- Produces: `renderVisit(outlet, detection, actions)` and `openCorrectionPicker(detection, actions)`.

- [ ] **Step 1: Add failing correction interaction contracts**

Require larger image, effective and original species, scientific name, local time, confidence, favorite, correction state, searchable taxa results, and distinct “Not a bird”. Require no free-text PATCH value: the selected catalog item supplies both the UI label and API correction common name.

- [ ] **Step 2: Run and confirm failure**

Run: `python -m unittest tests.test_web_contract.WebContractTests.test_visit_correction_contract -v`

Expected: FAIL because `views/visit.js` is absent.

- [ ] **Step 3: Implement accessible visit detail and picker**

Use a native `<dialog>` when supported and an in-page section fallback. Debounce `/api/taxa?q=` by 200ms, cap rendered results at 20, provide keyboard focus, and include buttons for catalog choices, `Not a bird`, and `Restore original identification`. PATCH shapes are exactly:

```javascript
{correction: selected.common_name, excluded: false}
{excluded: true}
{correction: null, excluded: false}
```

Update the current visit optimistically; on failure restore its complete prior object, keep the dialog open, and announce `That correction was not saved. Try again.`

- [ ] **Step 4: Verify and commit**

Run: `python -m unittest tests.test_web_contract -v`

Expected: PASS.

```bash
git add web/site/views/visit.js web/site/components.js web/site/app.js web/site/styles.css tests/test_web_contract.py
git commit -m "feat: add visit corrections"
```

### Task 5: Install the canonical Perch PWA identity

**Files:**
- Create: `web/site/icons/perch-mark.svg`
- Create: `scripts/build-perch-icons.py`
- Regenerate: `web/site/icons/icon-192.png`
- Regenerate: `web/site/icons/icon-512.png`
- Create: `web/site/icons/icon-maskable-512.png`
- Regenerate: `web/site/icons/apple-touch-icon.png`
- Create: `web/site/icons/favicon-32.png`
- Create: `web/site/favicon.ico`
- Modify: `web/site/manifest.json`
- Modify: `web/site/index.html`
- Modify: `web/site/sw.js`
- Create: `tests/test_pwa_contract.py`

**Interfaces:**
- Produces: deterministic icon assets and shell cache `perch-shell-v2`.

- [ ] **Step 1: Write failing PWA asset tests**

```python
def test_manifest_has_distinct_normal_and_maskable_icons():
    manifest = json.loads(read("web/site/manifest.json"))
    assert manifest["name"] == "Perch · Sara's Feeder"
    assert manifest["short_name"] == "Perch"
    assert manifest["start_url"] == "/"
    assert manifest["display"] == "standalone"
    icons = {(i["sizes"], i.get("purpose", "any")): i["src"] for i in manifest["icons"]}
    assert icons[("512x512", "any")] != icons[("512x512", "maskable")]

def test_icon_dimensions_and_maskable_safe_zone():
    expected = {"icon-192.png": (192,192), "icon-512.png": (512,512), "icon-maskable-512.png": (512,512), "apple-touch-icon.png": (180,180)}
    for name, size in expected.items():
        with Image.open(ROOT / "web/site/icons" / name) as image: assert image.size == size
    normal = (ROOT / "web/site/icons/icon-512.png").read_bytes()
    maskable = (ROOT / "web/site/icons/icon-maskable-512.png").read_bytes()
    assert normal != maskable
```

Also assert HTML links the manifest, Apple icon, PNG favicon, `.ico` favicon, theme color, and `sw.js` contains `perch-shell-v2` plus explicit exclusions for `/api/`, `/images/`, `/thumbs/`, and `/enrichment/`.

- [ ] **Step 2: Run and confirm failure**

Run: `python -m unittest tests.test_pwa_contract -v`

Expected: FAIL on Field Log names, shared maskable asset, and stale cache version.

- [ ] **Step 3: Create canonical vector mark and deterministic generator**

Trace the existing approved dark-bird/amber-wing mark in `perch-mark.svg`. `build-perch-icons.py` must render the same geometry with Pillow polygons/ellipses, center normal artwork in a pale-green square, center maskable artwork within the central 66% safe zone on a full-bleed pale-green background, and write all PNGs plus `favicon.ico`. Check generated binaries into Git so the Pi does not need to generate them.

- [ ] **Step 4: Update manifest, HTML, and shell caching**

Manifest identity:

```json
{
  "name": "Perch · Sara's Feeder",
  "short_name": "Perch",
  "start_url": "/",
  "scope": "/",
  "display": "standalone",
  "background_color": "#E9EDE4",
  "theme_color": "#E9EDE4",
  "icons": [
    {"src":"icons/icon-192.png","sizes":"192x192","type":"image/png","purpose":"any"},
    {"src":"icons/icon-512.png","sizes":"512x512","type":"image/png","purpose":"any"},
    {"src":"icons/icon-maskable-512.png","sizes":"512x512","type":"image/png","purpose":"maskable"}
  ]
}
```

Set `CACHE = "perch-shell-v2"`; shell-cache every static module and icon; return without `respondWith` for API/image paths so the browser performs a normal network request.

- [ ] **Step 5: Generate, verify, and commit**

Run: `python scripts/build-perch-icons.py`

Expected: prints each generated filename and size; exit 0.

Run: `python -m unittest tests.test_pwa_contract tests.test_web_contract -v`

Expected: PASS.

```bash
git add scripts/build-perch-icons.py web/site/icons web/site/favicon.ico web/site/manifest.json web/site/index.html web/site/sw.js tests/test_pwa_contract.py
git commit -m "feat: install Perch PWA branding"
```

### Task 6: Complete browser, accessibility, and home-screen acceptance

**Files:**
- Modify: frontend files only when an acceptance check demonstrates a defect.

**Interfaces:**
- Consumes: all interface tasks.
- Produces: tested desktop, phone, iOS, and Android behavior.

- [ ] **Step 1: Run automated tests and build**

Run: `python -m unittest discover -s tests -v && docker compose build web journal`

Expected: all tests PASS and both images build.

- [ ] **Step 2: Test desktop and phone layouts**

Open a populated test instance at 390×844, 768×1024, and 1440×900. Verify Today hierarchy, long scientific names, empty state, missing image, inline API failure with retry, My Birds sorts/search, Favorites, species pagination, visit detail, and correction rollback. Expected: no horizontal scroll, clipped controls, overlapping bottom navigation, or full-page error replacement.

- [ ] **Step 3: Test keyboard and accessibility behavior**

Using only Tab, Shift+Tab, Enter, Space, Escape, and arrow keys, traverse navigation, favorites, cards, dialog, correction choices, and pagination. Enable reduced motion. Expected: visible focus on every control, meaningful accessible names, dialog focus returns to “Wrong bird?”, status changes are announced, and no color-only state.

- [ ] **Step 4: Test iOS home-screen installation**

On current iOS Safari, visit the authenticated Perch URL, choose Share → Add to Home Screen, confirm preview name `Perch` and bird mark, install, launch, and authenticate. Expected: standalone launch at journal root with the Perch icon, no browser-generated initial tile, and working Today navigation.

- [ ] **Step 5: Test Android home-screen installation**

On current Android Chrome, choose Install app/Add to Home screen, confirm name and bird mark, install, and launch. Expected: maskable icon is not clipped in the launcher and the app opens standalone at journal root.

- [ ] **Step 6: Verify offline shell behavior**

Load once, disconnect network, relaunch. Expected: branded shell loads and explains that journal data requires a connection; no stale counts, API payloads, or bird photographs appear.

- [ ] **Step 7: Leave a clean acceptance commit**

If acceptance required code changes, rerun `python -m unittest discover -s tests -v`, then:

```bash
git add web/site tests
git commit -m "fix: close journal interface acceptance gaps"
```

Otherwise `git status --short` must produce no output.
