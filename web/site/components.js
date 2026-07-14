import {formatConfidence, formatRelativeTime} from "./format.js";

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function speciesName(detection) {
  return detection.effective_species?.common_name || "Bird";
}

export function showStatus(message) {
  const status = document.querySelector("#connection-status");
  if (status) status.textContent = message;
}

export function missingImage() {
  const fallback = element("div", "missing-image");
  fallback.setAttribute("role", "img");
  fallback.setAttribute("aria-label", "Photograph unavailable");
  fallback.append(element("span", "missing-image-mark", "Perch"));
  return fallback;
}

export function birdImage(source, alt, className = "") {
  const frame = element("div", className);
  if (!source) {
    frame.append(missingImage());
    return frame;
  }

  const image = document.createElement("img");
  image.src = source;
  image.alt = alt;
  image.addEventListener("error", () => frame.replaceChildren(missingImage()), {once: true});
  frame.append(image);
  return frame;
}

export function favoriteButton(detection, onToggle) {
  const button = element("button", "favorite-button");
  button.type = "button";

  const update = (favorite) => {
    detection.favorite = favorite;
    const species = speciesName(detection);
    button.setAttribute("aria-pressed", String(favorite));
    button.setAttribute(
      "aria-label",
      favorite
        ? `Remove ${species} visit from favorites`
        : `Add ${species} visit to favorites`,
    );
    button.textContent = favorite ? "★" : "☆";
  };

  update(Boolean(detection.favorite));
  button.addEventListener("click", async () => {
    const prior = Boolean(detection.favorite);
    update(!prior);
    button.disabled = true;
    try {
      const saved = await onToggle(detection, !prior);
      update(typeof saved?.favorite === "boolean" ? saved.favorite : !prior);
      showStatus("");
    } catch (_error) {
      update(prior);
      showStatus("Favorite was not saved. Try again.");
    } finally {
      button.disabled = false;
    }
  });
  return button;
}

export function visitCard(detection, actions = {}) {
  const article = element("article", "visit-card");
  const name = speciesName(detection);
  article.append(birdImage(detection.thumbnail, `${name} at the feeder`, "visit-photo"));

  const body = element("div", "visit-card-body");
  const heading = element("h3", "visit-species", name);
  const scientific = detection.effective_species?.scientific;
  body.append(heading);
  if (scientific) body.append(element("p", "scientific-name", scientific));

  const metadata = element("p", "visit-meta");
  const when = formatRelativeTime(detection.captured_at);
  metadata.textContent = [when, formatConfidence(detection.confidence)].filter(Boolean).join(" · ");
  body.append(metadata);

  const controls = element("div", "visit-actions");
  controls.append(favoriteButton(detection, actions.onToggleFavorite || (() => Promise.resolve())));
  const correction = element("button", "text-button", "Wrong bird?");
  correction.type = "button";
  correction.addEventListener("click", () => actions.onCorrect?.(detection, correction));
  controls.append(correction);
  body.append(controls);
  article.append(body);
  return article;
}

export function inlineError(message, onRetry) {
  const status = element("div", "inline-error");
  status.dataset.inlineError = "true";
  status.setAttribute("role", "status");
  status.append(element("span", "", message));
  const retry = element("button", "text-button", "Retry");
  retry.type = "button";
  retry.addEventListener("click", onRetry);
  status.append(retry);
  return status;
}
