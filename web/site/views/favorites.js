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
  grid.dataset.favoritesGrid = "true";
  appendFavorites(grid, data.detections || [], actions);
  page.append(grid);
  if (!(data.detections || []).length) {
    page.append(element("p", "empty-postcard", "Favorite visits will gather here."));
  }
  if (data.next_cursor) {
    const loadMore = element("button", "secondary-button", "Load older favorites");
    loadMore.type = "button";
    loadMore.dataset.loadMore = "true";
    loadMore.dataset.cursor = data.next_cursor;
    loadMore.addEventListener("click", () => actions.onLoadMore?.(loadMore.dataset.cursor, grid, loadMore));
    page.append(loadMore);
  }
  outlet.replaceChildren(page);
}

export function appendFavorites(grid, detections, actions = {}) {
  for (const detection of detections) {
    let card;
    card = visitCard(detection, {
      ...actions,
      onToggleFavorite: async (visit, favorite) => {
        const saved = await (actions.onToggleFavorite?.(visit, favorite) ?? Promise.resolve({...visit, favorite}));
        if (saved?.favorite === false) card.remove();
        return saved;
      },
    });
    grid.append(card);
  }
}
