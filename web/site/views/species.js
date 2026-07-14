import {birdImage, visitCard} from "../components.js";
import {formatDate, formatVisitCount} from "../format.js";

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function localHour(hour) {
  return new Date(2020, 0, 1, Number(hour)).toLocaleTimeString(undefined, {hour: "numeric"});
}

function enrichmentSlot(enrichment = {status: "missing"}) {
  const section = element("section", "enrichment-slot");
  section.append(element("h2", "section-title", "Field notes"));
  const status = enrichment.status || "missing";
  if (["missing", "pending", "failed"].includes(status)) {
    section.append(element("p", "", "Local visit history is ready. More species notes will be added here later."));
  } else if (enrichment.summary) {
    section.append(element("p", "", enrichment.summary));
  }
  return section;
}

export function appendSpeciesGallery(grid, gallery, actions = {}) {
  for (const detection of gallery) {
    const card = visitCard(detection, actions);
    // visitCard applies loading="lazy" to every gallery photograph.
    grid.append(card);
  }
}

export function renderSpecies(outlet, data, actions = {}) {
  const page = element("div", "species-page");
  const hero = element("section", "species-hero");
  hero.append(birdImage(data.cover?.display_image || data.cover?.thumbnail, `${data.common_name} at the feeder`, "species-cover"));
  const intro = element("div", "species-intro");
  const back = element("a", "history-link", "← My Birds");
  back.href = "#/birds";
  intro.append(back, element("h1", "page-title", data.common_name));
  if (data.scientific) intro.append(element("p", "scientific-name", data.scientific));
  intro.append(element("p", "album-count", formatVisitCount(data.visits)));
  intro.append(element("p", "album-date", `First seen ${formatDate(data.first_seen)}`));
  intro.append(element("p", "album-date", `Last seen ${formatDate(data.last_seen)}`));
  const hours = (data.busiest_hours || []).map(localHour).join(", ");
  intro.append(element("p", "album-date", `Busiest ${hours || "—"}`));
  hero.append(intro);
  page.append(hero);

  const gallerySection = element("section", "gallery-section");
  gallerySection.append(element("h2", "section-title", "Visits"));
  const grid = element("div", "visit-grid");
  grid.dataset.speciesGallery = "true";
  appendSpeciesGallery(grid, data.gallery || [], actions);
  gallerySection.append(grid);
  if (data.next_cursor) {
    const more = element("button", "load-more", "Load older visits");
    more.type = "button";
    more.dataset.loadMore = "true";
    more.dataset.cursor = data.next_cursor;
    more.addEventListener("click", () => actions.onLoadMore?.(more.dataset.cursor, grid, more));
    gallerySection.append(more);
  }
  page.append(gallerySection, enrichmentSlot(data.enrichment));
  outlet.replaceChildren(page);
}
