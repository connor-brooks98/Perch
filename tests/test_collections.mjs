import assert from "node:assert/strict";
import test from "node:test";

import {detection, installDom} from "./web_test_dom.mjs";

function controlledBrowser(hash = "#/species/sci%3Ablue%20jay") {
  const originalWindow = globalThis.window;
  const originalSetTimeout = globalThis.setTimeout;
  const originalClearTimeout = globalThis.clearTimeout;
  const listeners = new Map();
  const timers = new Map();
  const delays = [];
  let nextTimer = 1;
  globalThis.window = {
    location: {hash},
    addEventListener(name, callback) {
      const callbacks = listeners.get(name) || [];
      callbacks.push(callback);
      listeners.set(name, callbacks);
    },
    removeEventListener(name, callback) {
      listeners.set(name, (listeners.get(name) || []).filter((item) => item !== callback));
    },
  };
  globalThis.setTimeout = (callback, delay) => {
    const id = nextTimer++;
    delays.push(delay);
    timers.set(id, callback);
    return id;
  };
  globalThis.clearTimeout = (id) => timers.delete(id);
  return {
    delays,
    activeTimers: () => [...timers.keys()],
    fire: async (id) => {
      const callback = timers.get(id);
      timers.delete(id);
      return callback?.();
    },
    navigate(nextHash) {
      window.location.hash = nextHash;
      for (const callback of listeners.get("hashchange") || []) callback();
    },
    restore() {
      globalThis.setTimeout = originalSetTimeout;
      globalThis.clearTimeout = originalClearTimeout;
      if (originalWindow === undefined) delete globalThis.window;
      else globalThis.window = originalWindow;
    },
  };
}

test("history requests filter updates and appends older visits", async () => {
  const {view} = installDom();
  const {renderHistory} = await import("../web/site/views/history.js");
  const changes = [];
  const cursors = [];
  renderHistory(view, {
    detections: [detection({id: 1})],
    next_cursor: "older-page",
    filters: {species: "sci:blue jay", favorite: true, date: "2026-07-13"},
  }, {
    onFiltersChange: (filters) => changes.push(filters),
    onLoadMore: (cursor, grid, button) => cursors.push([cursor, grid, button]),
  });

  const favorite = view.querySelector("[data-history-favorite]");
  assert.equal(favorite.checked, true);
  favorite.checked = false;
  await favorite.dispatch("change");
  assert.equal(changes[0].favorite, false);

  const button = view.querySelector("[data-load-more]");
  await button.dispatch("click");
  assert.equal(cursors[0][0], "older-page");
  assert.equal(cursors[0][1].children.length, 1);
});

test("My Birds renders server new state and encoded profile links", async () => {
  const {view} = installDom();
  const {renderBirds} = await import("../web/site/views/birds.js");
  renderBirds(view, {
    q: "blue",
    sort: "visits",
    species: [{
      species_key: "sci:blue jay",
      common_name: "Blue Jay",
      scientific: "Cyanocitta cristata",
      visits: 3,
      first_seen: "2026-07-10T10:00:00Z",
      last_seen: "2026-07-13T10:00:00Z",
      thumbnail: "thumbs/1.jpg",
      is_new: true,
    }],
  });

  assert.equal(view.querySelector("[data-new-bird]").textContent, "New");
  assert.equal(view.querySelector("a").href, "#/species/sci%3Ablue%20jay");
  assert.match(view.textContent, /3 visits/);
  assert.match(view.textContent, /First seen/);
  assert.match(view.textContent, /Last seen/);
});

test("species gallery appends cursor pages without replacing existing nodes", async () => {
  const {view} = installDom();
  const {renderSpecies, appendSpeciesGallery} = await import("../web/site/views/species.js");
  renderSpecies(view, {
    species_key: "sci:blue jay", common_name: "Blue Jay", scientific: "Cyanocitta cristata",
    visits: 2, first_seen: "2026-07-10T10:00:00Z", last_seen: "2026-07-13T10:00:00Z",
    busiest_hours: [10], cover: detection({id: 2, favorite: true}),
    gallery: [detection({id: 2})], next_cursor: "page-2", enrichment: {status: "missing"},
  });
  const grid = view.querySelector("[data-species-gallery]");
  const first = grid.children[0];
  appendSpeciesGallery(grid, [detection({id: 1})]);
  assert.equal(grid.children.length, 2);
  assert.equal(grid.children[0], first);
  assert.equal(grid.querySelectorAll("img").every((image) => image.loading === "lazy"), true);
  assert.match(view.textContent, /Your sightings are still complete/);
  const intro = view.querySelector(".species-intro");
  assert.ok(
    intro.children.indexOf(view.querySelector(".album-date")) <
      intro.children.indexOf(view.querySelector(".enrichment-slot")),
    "local species statistics must render before enrichment",
  );
});

test("pending enrichment refreshes once without replacing local visit state", async () => {
  const browser = controlledBrowser();
  const originalFetch = globalThis.fetch;
  let fetchCalls = 0;
  let saveFavorite;
  const favoriteSaved = new Promise((resolve) => { saveFavorite = resolve; });
  globalThis.fetch = async () => {
    fetchCalls += 1;
    return {
      ok: true,
      json: async () => ({
        enrichment: {
          status: "ready",
          introduction: "Blue jays are clever family visitors.",
          sources: {inaturalist: "https://www.inaturalist.org/taxa/8229", wikipedia: null},
          reference_image: null,
        },
      }),
    };
  };
  try {
    const {getSpeciesDetail} = await import("../web/site/api.js");
    const {renderSpecies, appendSpeciesGallery} = await import("../web/site/views/species.js");
    const {view} = installDom();
    renderSpecies(view, {
      species_key: "sci:blue jay", common_name: "Blue Jay", scientific: "Cyanocitta cristata",
      visits: 2, first_seen: "2026-07-10T10:00:00Z", last_seen: "2026-07-13T10:00:00Z",
      busiest_hours: [10], cover: detection({id: 2}), gallery: [detection({id: 2})],
      enrichment: {status: "pending"},
    }, {
      pendingRefreshKey: "preserve-local-state",
      onRefresh: async () => (await getSpeciesDetail("sci:blue jay")).enrichment,
      onToggleFavorite: () => favoriteSaved,
    });
    const grid = view.querySelector("[data-species-gallery]");
    const originalCard = grid.children[0];
    appendSpeciesGallery(grid, [detection({id: 1})]);
    const appendedCard = grid.children[1];
    const favorite = originalCard.querySelector(".favorite-button");
    const favoriteClick = favorite.dispatch("click");
    assert.equal(favorite.textContent, "★");
    assert.equal(favorite.disabled, true);
    assert.deepEqual(browser.delays, [2000]);

    await browser.fire(browser.activeTimers()[0]);

    assert.equal(fetchCalls, 1);
    assert.equal(grid.children[0], originalCard);
    assert.equal(grid.children[1], appendedCard);
    assert.equal(originalCard.querySelector(".favorite-button"), favorite);
    assert.equal(favorite.textContent, "★");
    assert.match(view.querySelector(".enrichment-slot").textContent, /clever family visitors/);
    assert.equal(browser.activeTimers().length, 0);
    assert.equal(fetchCalls, 1);
    saveFavorite({favorite: true});
    await favoriteClick;

    renderSpecies(view, {
      species_key: "sci:blue jay", common_name: "Blue Jay", visits: 2,
      busiest_hours: [], cover: detection({id: 2}), gallery: [], enrichment: {status: "pending"},
    }, {
      pendingRefreshKey: "still-pending-once",
      onRefresh: async () => {
        fetchCalls += 1;
        return {status: "pending"};
      },
    });
    await browser.fire(browser.activeTimers()[0]);
    assert.equal(fetchCalls, 2);
    assert.equal(browser.activeTimers().length, 0, "a pending response must not schedule a second attempt");
  } finally {
    globalThis.fetch = originalFetch;
    browser.restore();
  }
});

test("pending enrichment cancels before navigation and ignores an in-flight response", async () => {
  const browser = controlledBrowser();
  try {
    const {renderSpecies} = await import("../web/site/views/species.js");
    const {view} = installDom();
    let refreshCalls = 0;
    const data = {
      common_name: "Blue Jay", visits: 1, busiest_hours: [], cover: detection(), gallery: [],
      enrichment: {status: "pending"},
    };
    renderSpecies(view, data, {pendingRefreshKey: "cancel-before", onRefresh: async () => { refreshCalls += 1; }});
    browser.navigate("#/birds");
    assert.equal(browser.activeTimers().length, 0);
    assert.equal(refreshCalls, 0);

    let releaseResponse;
    browser.navigate("#/species/sci%3Ablue%20jay");
    renderSpecies(view, data, {
      pendingRefreshKey: "ignore-in-flight",
      onRefresh: () => new Promise((resolve) => { releaseResponse = resolve; }),
    });
    const attempt = browser.fire(browser.activeTimers()[0]);
    browser.navigate("#/favorites");
    releaseResponse({
      status: "ready", introduction: "Must be ignored after navigation.",
      sources: {}, reference_image: null,
    });
    await attempt;
    assert.doesNotMatch(view.querySelector(".enrichment-slot").textContent, /Must be ignored/);
  } finally {
    browser.restore();
  }
});

test("species enrichment renders complete safe attribution and rejects malicious URLs", async () => {
  const {renderSpecies} = await import("../web/site/views/species.js");
  const generated = "/enrichment/1234567890abcdef12345678-1234567890abcdef1234567890abcdef.jpg";
  const base = {
    common_name: "Blue Jay", visits: 1, busiest_hours: [], cover: detection(), gallery: [],
  };
  const {view} = installDom();
  renderSpecies(view, {...base, enrichment: {
    status: "ready",
    introduction: "A safely attributed visitor.",
    sources: {
      inaturalist: "https://www.inaturalist.org/taxa/8229",
      wikipedia: "https://en.wikipedia.org/wiki/Blue_jay",
    },
    reference_image: {
      src: generated, creator: "Jane Birder", license: "CC BY 4.0",
      source: "https://static.inaturalist.org/photos/1.jpg",
    },
  }});
  const links = view.querySelectorAll(".enrichment-source");
  assert.equal(links.length, 3);
  assert.equal(links.every((link) => link.rel === "noopener noreferrer"), true);
  assert.match(view.querySelector(".reference-image").textContent, /Reference photo by Jane Birder · CC BY 4.0 · View source/);
  assert.equal(view.querySelector(".reference-image").querySelector("img").src, generated);

  const unsafeCases = [
    ["javascript:alert(1)", "javascript:alert(1)", "javascript:alert(1)"],
    [
      "http://www.inaturalist.org/taxa/8229",
      "http://en.wikipedia.org/wiki/Blue_jay",
      "http://static.inaturalist.org/photos/1.jpg",
    ],
    [
      "https://user:secret@www.inaturalist.org/taxa/8229",
      "https://user:secret@en.wikipedia.org/wiki/Blue_jay",
      "https://user:secret@static.inaturalist.org/photos/1.jpg",
    ],
    [
      "https://www.inaturalist.org:444/taxa/8229",
      "https://en.wikipedia.org:444/wiki/Blue_jay",
      "https://static.inaturalist.org:444/photos/1.jpg",
    ],
    [
      "https://www.inaturalist.org.evil.example/taxa/8229",
      "https://en.wikipedia.org.evil.example/wiki/Blue_jay",
      "https://static.inaturalist.org.evil.example/photos/1.jpg",
    ],
    [
      "https://unrelated.example/taxa/8229",
      "https://unrelated.example/wiki/Blue_jay",
      "https://unrelated.example/photos/1.jpg",
    ],
  ];
  for (const [unsafeInaturalist, unsafeWikipedia, unsafePhoto] of unsafeCases) {
    const next = installDom().view;
    renderSpecies(next, {...base, enrichment: {
      status: "ready", introduction: "Local-safe text.",
      sources: {inaturalist: unsafeInaturalist, wikipedia: unsafeWikipedia},
      reference_image: {
        src: generated, creator: "Jane Birder", license: "CC BY 4.0", source: unsafePhoto,
      },
    }});
    assert.equal(next.querySelectorAll(".enrichment-source").length, 0, unsafeInaturalist);
    assert.equal(next.querySelector(".reference-image"), null, unsafePhoto);
  }

  for (const incomplete of [
    {src: generated, creator: "", license: "CC BY 4.0", source: "https://static.inaturalist.org/photos/1.jpg"},
    {src: generated, creator: "Jane", license: "", source: "https://static.inaturalist.org/photos/1.jpg"},
    {src: "/enrichment/../bird.jpg", creator: "Jane", license: "CC BY 4.0", source: "https://static.inaturalist.org/photos/1.jpg"},
  ]) {
    const next = installDom().view;
    renderSpecies(next, {...base, enrichment: {
      status: "ready", introduction: "Local-safe text.", sources: {}, reference_image: incomplete,
    }});
    assert.equal(next.querySelector(".reference-image"), null);
  }
});
