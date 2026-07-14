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

let pendingRefresh = null;
let lastPendingRefreshKey = null;

function stopPendingRefresh() {
  if (!pendingRefresh) return;
  clearTimeout(pendingRefresh.timer);
  window.removeEventListener("hashchange", pendingRefresh.cancelOnNavigation);
  pendingRefresh = null;
}

function schedulePendingRefresh(actions) {
  if (actions.pendingRefreshKey === undefined || actions.pendingRefreshKey === lastPendingRefreshKey) return;
  lastPendingRefreshKey = actions.pendingRefreshKey;
  stopPendingRefresh();
  const routeHash = window.location.hash;
  const cancelOnNavigation = () => {
    if (window.location.hash !== routeHash) stopPendingRefresh();
  };
  const timer = setTimeout(() => {
    if (pendingRefresh?.timer !== timer) return;
    stopPendingRefresh();
    if (window.location.hash === routeHash) actions.onRefresh?.();
  }, 2000);
  pendingRefresh = {timer, cancelOnNavigation};
  window.addEventListener("hashchange", cancelOnNavigation);
}

function sourceLink(label, href) {
  const link = element("a", "enrichment-source", label);
  link.href = href;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
}

function completeReferenceImage(image) {
  return image && image.creator && image.license && image.source &&
    typeof image.src === "string" && image.src.startsWith("/enrichment/");
}

function enrichmentSlot(enrichment = {status: "missing"}, commonName = "bird", actions = {}) {
  const section = element("section", "enrichment-slot");
  section.append(element("h2", "section-title", "About this bird"));
  const status = enrichment.status || "missing";
  if (status === "pending") {
    section.append(element("p", "", "We’re gathering a little more about this bird."));
    schedulePendingRefresh(actions);
    return section;
  }

  stopPendingRefresh();
  const image = enrichment.reference_image;
  const sources = enrichment.sources || {};
  const hasContent = enrichment.introduction || sources.inaturalist || sources.wikipedia || completeReferenceImage(image);
  if (status === "failed" || !hasContent) {
    section.append(element("p", "", "Your sightings are still complete; extra species notes are unavailable right now."));
    return section;
  }

  if (enrichment.introduction) {
    const introduction = element("p", "enrichment-introduction");
    introduction.textContent = enrichment.introduction;
    section.append(introduction);
  }
  const profileLinks = [];
  if (sources.inaturalist) profileLinks.push(sourceLink("iNaturalist", sources.inaturalist));
  if (sources.wikipedia) profileLinks.push(sourceLink("Wikipedia", sources.wikipedia));
  if (profileLinks.length) {
    const links = element("p", "enrichment-sources", "Learn more: ");
    profileLinks.forEach((link, index) => {
      if (index) links.append(element("span", "", " · "));
      links.append(link);
    });
    section.append(links);
  }
  if (completeReferenceImage(image)) {
    const figure = element("figure", "reference-image");
    const photo = document.createElement("img");
    photo.src = image.src;
    photo.alt = `Reference photograph of ${commonName}`;
    photo.loading = "lazy";
    const caption = element("figcaption", "reference-caption");
    caption.append(
      element("span", "", `Reference photo by ${image.creator} · ${image.license} · `),
      sourceLink("View source", image.source),
    );
    figure.append(photo, caption);
    section.append(figure);
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
  intro.append(enrichmentSlot(data.enrichment, data.common_name, actions));
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
  page.append(gallerySection);
  outlet.replaceChildren(page);
}
