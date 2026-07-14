import assert from "node:assert/strict";
import test from "node:test";

import {detection, installDom} from "./web_test_dom.mjs";

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
