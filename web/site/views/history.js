import {visitCard} from "../components.js";

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function field(label, control) {
  const wrapper = element("label", "filter-field");
  wrapper.append(element("span", "filter-label", label), control);
  return wrapper;
}

export function appendHistoryVisits(grid, detections, actions = {}) {
  for (const detection of detections) grid.append(visitCard(detection, actions));
}

export function renderHistory(outlet, data, actions = {}) {
  const page = element("div", "collection-page");
  page.append(element("p", "section-kicker", "The complete feeder record"));
  page.append(element("h1", "page-title", "Visit history"));

  const filters = element("form", "collection-filters");
  filters.addEventListener("submit", (event) => event.preventDefault());
  const species = document.createElement("input");
  species.type = "search";
  species.value = data.filters?.species || "";
  species.placeholder = "Species key";
  species.addEventListener("change", () => actions.onFiltersChange?.({
    species: species.value, favorite: favorite.checked, date: date.value,
  }));
  filters.append(field("Species", species));

  const favorite = document.createElement("input");
  favorite.type = "checkbox";
  favorite.checked = Boolean(data.filters?.favorite);
  favorite.dataset.historyFavorite = "true";
  favorite.addEventListener("change", () => actions.onFiltersChange?.({
    species: species.value, favorite: favorite.checked, date: date.value,
  }));
  filters.append(field("Favorites only", favorite));

  const date = document.createElement("input");
  date.type = "date";
  date.value = data.filters?.date || "";
  date.addEventListener("change", () => actions.onFiltersChange?.({
    species: species.value, favorite: favorite.checked, date: date.value,
  }));
  filters.append(field("Date", date));
  page.append(filters);

  const grid = element("div", "visit-grid");
  grid.dataset.historyGrid = "true";
  appendHistoryVisits(grid, data.detections || [], actions);
  page.append(grid);
  if (!(data.detections || []).length) {
    page.append(element("p", "empty-postcard", "No visits match these filters yet."));
  }
  if (data.next_cursor) {
    const more = element("button", "load-more", "Load older visits");
    more.type = "button";
    more.dataset.loadMore = "true";
    more.dataset.cursor = data.next_cursor;
    more.addEventListener("click", () => actions.onLoadMore?.(more.dataset.cursor, grid, more));
    page.append(more);
  }
  outlet.replaceChildren(page);
}
