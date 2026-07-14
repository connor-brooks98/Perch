import assert from "node:assert/strict";
import test from "node:test";

import {detection, installDom} from "./web_test_dom.mjs";

const waitForDebounce = () => new Promise((resolve) => setTimeout(resolve, 230));

function buttonNamed(root, name) {
  return root.querySelectorAll("button").find((button) => button.textContent.startsWith(name));
}

test("visit detail identifies effective and original species and correction state", async () => {
  const {view} = installDom();
  const {renderVisit} = await import("../web/site/views/visit.js");
  renderVisit(view, detection({
    corrected: true,
    original_species: {common_name: "American Robin", scientific: "Turdus migratorius"},
    effective_species: {common_name: "Blue Jay", scientific: "Cyanocitta cristata"},
  }));

  assert.match(view.textContent, /Blue Jay/);
  assert.match(view.textContent, /Cyanocitta cristata/);
  assert.match(view.textContent, /Original identification: American Robin/);
  assert.match(view.textContent, /Corrected identification/);
  assert.match(view.textContent, /91%/);
  assert.ok(view.querySelector(".visit-detail-photo").querySelector("img").src.endsWith("images/1.jpg"));
  assert.equal(view.querySelector(".favorite-button").getAttribute("aria-pressed"), "false");
});

test("catalog search is debounced, capped, and only a selected result is submitted", async () => {
  const {document} = installDom();
  const {openCorrectionPicker} = await import("../web/site/views/visit.js");
  const searches = [];
  const patches = [];
  const taxa = Array.from({length: 25}, (_, index) => ({
    common_name: `Catalog Bird ${index + 1}`,
    scientific: `Avis catalogus ${index + 1}`,
  }));
  const picker = openCorrectionPicker(detection(), {
    searchTaxa: async (query) => { searches.push(query); return {taxa}; },
    onSaveCorrection: async (_visit, patch) => { patches.push(patch); return detection(); },
  });
  const input = picker.querySelector("input");
  assert.equal(document.activeElement, input);

  input.value = "cat";
  await input.dispatch("input");
  input.value = "catalog";
  await input.dispatch("input");
  assert.deepEqual(searches, []);
  await waitForDebounce();

  assert.deepEqual(searches, ["catalog"]);
  assert.equal(picker.querySelectorAll("[data-taxon-choice]").length, 20);
  assert.deepEqual(patches, []);
  await buttonNamed(picker, "Catalog Bird 1").dispatch("click");
  assert.deepEqual(patches, [{correction: "Catalog Bird 1", excluded: false}]);
});

test("correction controls submit only the three exact PATCH shapes", async () => {
  installDom();
  const {openCorrectionPicker} = await import("../web/site/views/visit.js");
  const submitted = [];
  const save = async (_visit, patch) => { submitted.push(patch); return detection(); };

  const excludedPicker = openCorrectionPicker(detection(), {onSaveCorrection: save});
  await buttonNamed(excludedPicker, "Not a bird").dispatch("click");
  const restoredPicker = openCorrectionPicker(detection({corrected: true}), {onSaveCorrection: save});
  await buttonNamed(restoredPicker, "Restore original identification").dispatch("click");

  assert.deepEqual(submitted, [
    {excluded: true},
    {correction: null, excluded: false},
  ]);
});

test("failed correction restores the complete visit, keeps picker open, announces, and returns focus", async () => {
  const {document} = installDom();
  const {openCorrectionPicker} = await import("../web/site/views/visit.js");
  const visit = detection({
    corrected: false,
    excluded: false,
    original_species: {common_name: "Blue Jay", scientific: "Cyanocitta cristata"},
    nested: {preserve: ["every", "field"]},
  });
  const prior = structuredClone(visit);
  const picker = openCorrectionPicker(visit, {
    searchTaxa: async () => [{common_name: "Northern Cardinal", scientific: "Cardinalis cardinalis"}],
    onSaveCorrection: async () => { throw new Error("offline"); },
  });
  const input = picker.querySelector("input");
  input.value = "cardinal";
  await input.dispatch("input");
  await waitForDebounce();
  const choice = buttonNamed(picker, "Northern Cardinal");
  const saving = choice.dispatch("click");
  assert.equal(visit.effective_species.common_name, "Northern Cardinal");
  await saving;

  assert.deepEqual(visit, prior);
  assert.equal(picker.parentNode, document.body);
  assert.match(picker.textContent, /That correction was not saved\. Try again\./);
  assert.equal(document.activeElement, choice);
});
