import {visitCard} from "../components.js";

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function renderFavorites(outlet, data, actions = {}) {
  const page = element("div", "collection-page");
  page.append(element("p", "section-kicker", "The family album"));
  page.append(element("h1", "page-title", "Favorites"));
  const grid = element("div", "visit-grid");
  for (const detection of data.detections || []) grid.append(visitCard(detection, actions));
  page.append(grid);
  if (!(data.detections || []).length) {
    page.append(element("p", "empty-postcard", "Favorite visits will gather here."));
  }
  outlet.replaceChildren(page);
}
