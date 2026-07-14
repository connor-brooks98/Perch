import {birdImage} from "../components.js";
import {formatDate, formatVisitCount} from "../format.js";

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function albumCard(album) {
  const link = element("a", "species-card");
  link.href = `#/species/${encodeURIComponent(album.species_key)}`;
  link.append(birdImage(album.thumbnail, `${album.common_name} at the feeder`, "species-thumbnail", "lazy"));
  const body = element("div", "species-card-body");
  const heading = element("div", "species-card-heading");
  heading.append(element("h2", "visit-species", album.common_name));
  if (album.is_new) {
    const badge = element("span", "new-badge", "New");
    badge.dataset.newBird = "true";
    heading.append(badge);
  }
  body.append(heading);
  if (album.scientific) body.append(element("p", "scientific-name", album.scientific));
  body.append(element("p", "album-count", formatVisitCount(album.visits)));
  body.append(element("p", "album-date", `First seen ${formatDate(album.first_seen)}`));
  body.append(element("p", "album-date", `Last seen ${formatDate(album.last_seen)}`));
  link.append(body);
  return link;
}

export function renderBirds(outlet, data, actions = {}) {
  const page = element("div", "collection-page");
  page.append(element("p", "section-kicker", "The family field guide"));
  page.append(element("h1", "page-title", "My Birds"));
  const controls = element("div", "collection-filters");
  const search = document.createElement("input");
  search.type = "search";
  search.value = data.q || "";
  search.placeholder = "Search birds";
  search.setAttribute("aria-label", "Search My Birds");
  search.addEventListener("input", () => actions.onQueryChange?.(search.value, sort.value));
  controls.append(search);
  const sort = document.createElement("select");
  sort.setAttribute("aria-label", "Sort My Birds");
  for (const [value, label] of [
    ["newest", "Newest discoveries"], ["visits", "Most visits"],
    ["recent", "Recently seen"], ["alphabetical", "Alphabetical"],
  ]) {
    const option = element("option", "", label);
    option.value = value;
    option.selected = value === (data.sort || "newest");
    sort.append(option);
  }
  sort.value = data.sort || "newest";
  sort.addEventListener("change", () => actions.onQueryChange?.(search.value, sort.value));
  controls.append(sort);
  page.append(controls);
  const grid = element("div", "species-grid");
  for (const album of data.species || []) grid.append(albumCard(album));
  page.append(grid);
  if (!(data.species || []).length) page.append(element("p", "empty-postcard", "No birds match this search yet."));
  outlet.replaceChildren(page);
}
