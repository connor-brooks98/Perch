import {startRouter} from "./router.js";
import {getDetection, getDetections, getSpecies, getSpeciesDetail, getToday, patchDetection, searchTaxa} from "./api.js";
import {inlineError, showStatus} from "./components.js";
import {renderBirds} from "./views/birds.js";
import {renderFavorites} from "./views/favorites.js";
import {appendHistoryVisits, renderHistory} from "./views/history.js";
import {appendSpeciesGallery, renderSpecies} from "./views/species.js";
import {renderToday} from "./views/today.js";
import {renderVisit} from "./views/visit.js";

const view = document.querySelector("#view");
let renderVersion = 0;

function removeInlineError() {
  view.querySelector("[data-inline-error]")?.remove();
}

async function loadToday(version) {
  removeInlineError();
  try {
    const data = await getToday();
    if (version !== renderVersion) return;
    renderToday(view, data, {
      onToggleFavorite: (detection, favorite) => patchDetection(detection.id, {favorite}),
      onCorrect: (detection) => {
        window.location.hash = `#/visits/${encodeURIComponent(detection.id)}`;
      },
    });
    showStatus("");
  } catch (_error) {
    if (version !== renderVersion) return;
    const retry = () => loadToday(version);
    view.append(inlineError("The feeder could not be refreshed.", retry));
  }
}

const visitActions = {
  onToggleFavorite: (detection, favorite) => patchDetection(detection.id, {favorite}),
  onCorrect: (detection) => {
    window.location.hash = `#/visits/${encodeURIComponent(detection.id)}`;
  },
};

function replaceHash(path, params) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== "" && value !== false && value !== null && value !== undefined) query.set(key, value);
  }
  const suffix = query.toString();
  const hash = `#/${path}${suffix ? `?${suffix}` : ""}`;
  window.history.replaceState(null, "", hash);
  return hash;
}

function showLoadError(message, retry) {
  removeInlineError();
  view.append(inlineError(message, retry));
}

async function loadHistory(version, params) {
  const filters = {
    species: params.get("species") || "",
    favorite: params.get("favorite") === "true",
    date: params.get("date") || "",
  };
  try {
    const data = await getDetections({...filters, favorite: filters.favorite || ""});
    if (version !== renderVersion) return;
    renderHistory(view, {...data, filters}, {
      ...visitActions,
      onFiltersChange: (next) => {
        replaceHash("history", next);
        loadHistory(++renderVersion, new URLSearchParams(window.location.hash.split("?", 2)[1] || ""));
      },
      onLoadMore: async (cursor, grid, button) => {
        button.disabled = true;
        try {
          const page = await getDetections({...filters, favorite: filters.favorite || "", cursor});
          appendHistoryVisits(grid, page.detections || [], visitActions);
          if (page.next_cursor) {
            button.dataset.cursor = page.next_cursor;
            button.disabled = false;
          } else button.remove();
        } catch (_error) {
          button.disabled = false;
          showStatus("Older visits could not be loaded. Try again.");
        }
      },
    });
  } catch (_error) {
    if (version !== renderVersion) return;
    showLoadError("Visit history could not be loaded.", () => loadHistory(version, params));
  }
}

async function loadBirds(version, params) {
  const q = params.get("q") || "";
  const sort = params.get("sort") || "newest";
  try {
    const data = await getSpecies({q, sort});
    if (version !== renderVersion) return;
    renderBirds(view, {...data, q, sort}, {
      onQueryChange: (nextQ, nextSort) => {
        replaceHash("birds", {q: nextQ, sort: nextSort === "newest" ? "" : nextSort});
        loadBirds(++renderVersion, new URLSearchParams({q: nextQ, sort: nextSort}));
      },
    });
  } catch (_error) {
    if (version !== renderVersion) return;
    showLoadError("My Birds could not be loaded.", () => loadBirds(version, params));
  }
}

async function loadFavorites(version) {
  try {
    const data = await getDetections({favorite: true});
    if (version !== renderVersion) return;
    renderFavorites(view, data, visitActions);
  } catch (_error) {
    if (version !== renderVersion) return;
    showLoadError("Favorites could not be loaded.", () => loadFavorites(version));
  }
}

async function loadSpecies(version, key) {
  try {
    const data = await getSpeciesDetail(key);
    if (version !== renderVersion) return;
    renderSpecies(view, {...data, enrichment: data.enrichment || {status: "missing"}}, {
      ...visitActions,
      pendingRefreshKey: version,
      onRefresh: async () => {
        if (version !== renderVersion) return null;
        try {
          const refreshed = await getSpeciesDetail(key);
          if (version !== renderVersion) return null;
          return refreshed.enrichment || {status: "missing"};
        } catch (_error) {
          return version === renderVersion ? {status: "failed"} : null;
        }
      },
      onLoadMore: async (cursor, grid, button) => {
        button.disabled = true;
        try {
          const page = await getSpeciesDetail(key, {cursor});
          appendSpeciesGallery(grid, page.gallery || [], visitActions);
          if (page.next_cursor) {
            button.dataset.cursor = page.next_cursor;
            button.disabled = false;
          } else button.remove();
        } catch (_error) {
          button.disabled = false;
          showStatus("Older species visits could not be loaded. Try again.");
        }
      },
    });
  } catch (_error) {
    if (version !== renderVersion) return;
    showLoadError("This bird profile could not be loaded.", () => loadSpecies(version, key));
  }
}

async function loadVisit(version, id) {
  try {
    const detection = await getDetection(id);
    if (version !== renderVersion) return;
    const actions = {
      onToggleFavorite: (visit, favorite) => patchDetection(visit.id, {favorite}),
      searchTaxa,
      onSaveCorrection: (visit, patch) => patchDetection(visit.id, patch),
      onDetectionChange: () => renderVisit(view, detection, actions),
    };
    renderVisit(view, detection, actions);
    showStatus("");
  } catch (_error) {
    if (version !== renderVersion) return;
    showLoadError("This visit could not be loaded.", () => loadVisit(version, id));
  }
}

function render(route) {
  const version = ++renderVersion;
  view.dataset.route = route.name;
  if (route.name === "today") {
    loadToday(version);
    return;
  }
  removeInlineError();
  if (route.name === "history") loadHistory(version, route.params);
  else if (route.name === "birds") loadBirds(version, route.params);
  else if (route.name === "favorites") loadFavorites(version);
  else if (route.name === "species") loadSpecies(version, route.params.get("key"));
  else if (route.name === "visit") loadVisit(version, route.params.get("id"));
  else view.replaceChildren();
}

startRouter(render);

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}
