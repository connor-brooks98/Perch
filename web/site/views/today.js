import {birdImage, favoriteButton, visitCard} from "../components.js";
import {formatConfidence, formatRelativeTime} from "../format.js";

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function localHour(hour) {
  if (hour === null || hour === undefined) return "—";
  const date = new Date(2020, 0, 1, Number(hour));
  return date.toLocaleTimeString(undefined, {hour: "numeric"});
}

function latestHero(latest, actions) {
  const section = element("section", "latest-section");
  section.setAttribute("aria-labelledby", "latest-heading");
  section.append(element("p", "section-kicker", "Latest visitor"));

  if (!latest) {
    const empty = element("div", "empty-postcard");
    const heading = element("h2", "section-title", "Waiting at the window");
    heading.id = "latest-heading";
    empty.append(heading);
    empty.append(element("p", "", "The first identified visitor will appear here automatically."));
    section.append(empty);
    return section;
  }

  const name = latest.effective_species?.common_name || "Bird";
  const card = element("article", "hero-card");
  card.append(birdImage(latest.display_image, `${name} at the feeder`, "hero-photo"));
  const content = element("div", "hero-content");
  const title = element("h2", "hero-species", name);
  title.id = "latest-heading";
  content.append(title);
  if (latest.effective_species?.scientific) {
    content.append(element("p", "scientific-name", latest.effective_species.scientific));
  }
  content.append(element(
    "p",
    "visitor-status",
    latest.is_first_visit ? "A new visitor" : "A returning visitor",
  ));
  const details = element("p", "hero-meta");
  details.textContent = [formatRelativeTime(latest.captured_at), formatConfidence(latest.confidence)]
    .filter(Boolean)
    .join(" · ");
  content.append(details);
  const actionsRow = element("div", "hero-actions");
  actionsRow.append(favoriteButton(latest, actions.onToggleFavorite || (() => Promise.resolve())));
  const correction = element("button", "text-button", "Wrong bird?");
  correction.type = "button";
  correction.addEventListener("click", () => actions.onCorrect?.(latest, correction));
  actionsRow.append(correction);
  content.append(actionsRow);
  card.append(content);
  section.append(card);
  return section;
}

function dailyStats(data) {
  const section = element("section", "daily-stats");
  section.setAttribute("aria-label", "Today's feeder summary");
  const values = [
    [String(data.visits_today), "Visits today"],
    [String(data.species_today), "Species today"],
    [localHour(data.busiest_hour), "Busiest hour"],
  ];
  for (const [value, label] of values) {
    const card = element("div", "stat-card");
    card.append(element("strong", "stat-value", value));
    card.append(element("span", "stat-label", label));
    section.append(card);
  }
  return section;
}

function activityChart(activity) {
  const section = element("section", "activity-section");
  const heading = element("h2", "section-title", "Today by the hour");
  heading.id = "activity-heading";
  section.setAttribute("aria-labelledby", heading.id);
  section.append(heading);
  const description = element("p", "chart-description", "Visits recorded during each local hour.");
  description.id = "activity-description";
  section.append(description);

  const chart = element("ol", "activity-chart");
  chart.setAttribute("aria-describedby", description.id);
  const counts = Array.from({length: 24}, (_, hour) => Number(activity?.[hour] || 0));
  const highest = Math.max(1, ...counts);
  counts.forEach((count, hour) => {
    const item = element("li", "activity-hour");
    item.setAttribute("aria-label", `${hour}: ${count} visits`);
    const bar = element("span", "activity-bar");
    bar.setAttribute("aria-hidden", "true");
    bar.style.setProperty("--activity", String(count / highest));
    item.append(bar);
    if (hour % 6 === 0) item.append(element("span", "activity-tick", localHour(hour)));
    chart.append(item);
  });
  section.append(chart);
  return section;
}

function recentVisits(recent, hasMore, actions) {
  const section = element("section", "recent-section");
  const header = element("div", "section-heading");
  const heading = element("h2", "section-title", "Recent visits");
  heading.id = "recent-heading";
  section.setAttribute("aria-labelledby", heading.id);
  header.append(heading);
  if (hasMore) {
    const history = element("a", "history-link", "View complete history");
    history.href = "#/history";
    header.append(history);
  }
  section.append(header);
  const cards = element("div", "recent-grid");
  recent.forEach((detection) => {
    const thumbnail = detection.thumbnail;
    cards.append(visitCard({...detection, thumbnail}, actions));
  });
  section.append(cards);
  return section;
}

export function renderToday(outlet, data, actions = {}) {
  const page = element("div", "today-page");
  const greeting = element("h1", "today-greeting", data.greeting);
  page.append(greeting);
  page.append(latestHero(data.latest, actions));
  page.append(dailyStats(data));
  page.append(activityChart(data.hourly_activity));
  page.append(recentVisits(data.recent || [], data.has_more, actions));
  outlet.replaceChildren(page);
}
