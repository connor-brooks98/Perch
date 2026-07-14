import {birdImage, element, favoriteButton} from "../components.js";
import {formatConfidence, formatTime} from "../format.js";

function clone(value) {
  return typeof structuredClone === "function"
    ? structuredClone(value)
    : JSON.parse(JSON.stringify(value));
}

function replaceObject(target, value) {
  for (const key of Object.keys(target)) delete target[key];
  Object.assign(target, clone(value));
}

function applyCorrection(detection, patch, selected) {
  if (patch.excluded) {
    detection.excluded = true;
    return;
  }
  detection.excluded = false;
  detection.correction = patch.correction;
  detection.corrected = patch.correction !== null;
  detection.effective_species = patch.correction === null
    ? clone(detection.original_species)
    : {common_name: selected.common_name, scientific: selected.scientific || null};
}

export function openCorrectionPicker(detection, actions = {}) {
  const nativeDialog = document.createElement("dialog");
  const supportsDialog = typeof nativeDialog.showModal === "function";
  const picker = supportsDialog ? nativeDialog : document.createElement("section");
  picker.className = "correction-picker";
  if (!supportsDialog) {
    picker.setAttribute("role", "dialog");
    picker.setAttribute("aria-modal", "true");
  }
  picker.setAttribute("aria-labelledby", "correction-title");

  const heading = element("h2", "section-title", "Correct this identification");
  heading.id = "correction-title";
  const help = element("p", "correction-help", "Search the bird catalog, then choose one result.");
  const label = element("label", "filter-label", "Bird name");
  const input = element("input", "correction-search");
  input.type = "search";
  input.autocomplete = "off";
  label.append(input);
  const results = element("div", "taxa-results");
  results.setAttribute("aria-live", "polite");
  const announcement = element("p", "correction-announcement");
  announcement.setAttribute("role", "status");

  const controls = element("div", "correction-controls");
  const notBird = element("button", "text-button", "Not a bird");
  notBird.type = "button";
  const restore = element("button", "text-button", "Restore original identification");
  restore.type = "button";
  const cancel = element("button", "text-button", "Cancel");
  cancel.type = "button";
  controls.append(notBird, restore, cancel);
  picker.append(heading, help, label, results, controls, announcement);

  const background = supportsDialog
    ? []
    : [...document.body.children].map((node) => ({node, inert: node.inert}));
  for (const {node} of background) node.inert = true;

  let debounce;
  let searchVersion = 0;
  let cleaned = false;

  const returnFocus = (preferred) => {
    const candidate = preferred?.isConnected
      ? preferred
      : actions.returnFocus?.isConnected
        ? actions.returnFocus
        : document.querySelector("[data-correction-trigger]");
    candidate?.focus();
  };

  const cleanup = (preferred) => {
    if (cleaned) return;
    cleaned = true;
    clearTimeout(debounce);
    searchVersion += 1;
    for (const {node, inert} of background) node.inert = inert;
    picker.remove();
    returnFocus(preferred);
  };

  const dismiss = (preferred) => {
    if (supportsDialog && picker.open) picker.close();
    cleanup(preferred);
  };

  if (supportsDialog) {
    picker.addEventListener("cancel", (event) => {
      event.preventDefault();
      dismiss();
    });
    picker.addEventListener("close", () => cleanup());
  } else {
    picker.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        dismiss();
        return;
      }
      if (event.key === "Tab") {
        const focusable = [
          ...picker.querySelectorAll("input"),
          ...picker.querySelectorAll("button"),
        ].filter((node) => !node.disabled);
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && (document.activeElement === first || !picker.contains(document.activeElement))) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    });
  }

  const save = async (patch, selected, sourceButton) => {
    const prior = clone(detection);
    applyCorrection(detection, patch, selected);
    actions.onDetectionChange?.(detection);
    announcement.textContent = "";
    sourceButton.disabled = true;
    try {
      const saved = await actions.onSaveCorrection?.(detection, patch);
      if (saved && typeof saved === "object") replaceObject(detection, saved);
      const rendered = actions.onDetectionChange?.(detection);
      const replacement = rendered?.querySelector?.("[data-correction-trigger]");
      dismiss(replacement);
    } catch (_error) {
      replaceObject(detection, prior);
      actions.onDetectionChange?.(detection);
      announcement.textContent = "That correction was not saved. Try again.";
      sourceButton.disabled = false;
      sourceButton.focus();
    }
  };

  notBird.addEventListener("click", () => save({excluded: true}, null, notBird));
  restore.addEventListener("click", () => save(
    {correction: null, excluded: false},
    detection.original_species,
    restore,
  ));
  cancel.addEventListener("click", () => dismiss());

  input.addEventListener("input", () => {
    clearTimeout(debounce);
    const query = input.value.trim();
    const version = ++searchVersion;
    if (!query) {
      results.replaceChildren();
      return;
    }
    debounce = setTimeout(async () => {
      try {
        const response = await actions.searchTaxa?.(query);
        if (version !== searchVersion) return;
        const taxa = (Array.isArray(response) ? response : response?.taxa || []).slice(0, 20);
        const choices = taxa.map((selected) => {
          const button = element("button", "taxon-choice");
          button.type = "button";
          button.dataset.taxonChoice = "true";
          button.append(
            element("span", "taxon-common", selected.common_name),
            element("span", "taxon-scientific", selected.scientific || ""),
          );
          button.addEventListener("click", () => save(
            {correction: selected.common_name, excluded: false},
            selected,
            button,
          ));
          return button;
        });
        results.replaceChildren(...choices);
        if (!choices.length) results.append(element("p", "", "No catalog birds found."));
      } catch (_error) {
        if (version === searchVersion) results.replaceChildren(element("p", "", "Catalog search failed. Try again."));
      }
    }, 200);
  });

  document.body.append(picker);
  if (supportsDialog) picker.showModal();
  input.focus();
  return picker;
}

export function renderVisit(outlet, detection, actions = {}) {
  const page = element("article", "visit-detail");
  const effective = detection.effective_species || {};
  const original = detection.original_species || effective;
  const name = effective.common_name || (detection.excluded ? "Not a bird" : "Bird");
  page.append(birdImage(
    detection.display_image || detection.thumbnail,
    `${name} at the feeder`,
    "visit-detail-photo",
  ));

  const body = element("div", "visit-detail-body");
  body.append(element("p", "section-kicker", "Feeder visit"));
  body.append(element("h1", "page-title", name));
  if (effective.scientific) body.append(element("p", "scientific-name", effective.scientific));
  body.append(element("p", "visit-detail-meta", [
    formatTime(detection.captured_at),
    `${formatConfidence(detection.confidence)} confidence`,
  ].filter(Boolean).join(" · ")));

  let correctionState = "Original identification";
  if (detection.excluded) correctionState = "Marked as not a bird";
  else if (detection.corrected) correctionState = "Corrected identification";
  body.append(element("p", "correction-state", correctionState));
  if (detection.corrected || detection.excluded) {
    body.append(element("p", "original-identification", `Original identification: ${original.common_name || "Bird"}`));
  }

  const controls = element("div", "visit-detail-actions");
  controls.append(favoriteButton(detection, actions.onToggleFavorite || (() => Promise.resolve())));
  const correct = element("button", "text-button", "Correct identification");
  correct.type = "button";
  correct.dataset.correctionTrigger = "true";
  correct.addEventListener("click", () => openCorrectionPicker(detection, {
    ...actions,
    returnFocus: correct,
  }));
  controls.append(correct);
  body.append(controls);
  page.append(body);
  outlet.replaceChildren(page);
  return page;
}
