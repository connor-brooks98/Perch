import assert from "node:assert/strict";
import test from "node:test";

import {detection, flushTasks, installDom, todayData} from "./web_test_dom.mjs";

test("Today renders authoritative lifetime visitor status", async () => {
  const {view} = installDom();
  const {renderToday} = await import("../web/site/views/today.js");
  const latest = detection({is_first_visit: false});
  renderToday(view, todayData({latest, recent: [latest]}));

  assert.equal(view.querySelector(".visitor-status").textContent, "A returning visitor");

  const first = detection({is_first_visit: true});
  renderToday(view, todayData({latest: first, recent: [detection(), detection()]}));
  assert.equal(view.querySelector(".visitor-status").textContent, "A new visitor");
});

test("recent thumbnails are lazy while the hero remains eager", async () => {
  const {view} = installDom();
  const {renderToday} = await import("../web/site/views/today.js");
  renderToday(view, todayData());

  const images = view.querySelectorAll("img");
  assert.equal(images.length, 2);
  assert.equal(images[0].loading || "", "");
  assert.equal(images[1].loading, "lazy");
});

test("favorite rejection restores state and announces failure", async () => {
  const {status} = installDom();
  const {favoriteButton} = await import("../web/site/components.js");
  const visit = detection({favorite: false});
  const button = favoriteButton(visit, async () => { throw new Error("offline"); });

  const settled = button.dispatch("click");
  assert.equal(button.getAttribute("aria-pressed"), "true");
  assert.equal(button.disabled, true);
  await settled;

  assert.equal(visit.favorite, false);
  assert.equal(button.getAttribute("aria-pressed"), "false");
  assert.equal(button.disabled, false);
  assert.equal(status.textContent, "Favorite was not saved. Try again.");
});

test("failed Today refresh preserves the last successful DOM", async () => {
  const {view} = installDom();
  const listeners = new Map();
  globalThis.window = {
    location: {hash: "#/today"},
    addEventListener(name, callback) { listeners.set(name, callback); },
    removeEventListener(name) { listeners.delete(name); },
  };
  Object.defineProperty(globalThis, "navigator", {value: {}, configurable: true});
  const responses = [
    {ok: true, json: async () => todayData()},
    new Error("offline"),
  ];
  globalThis.fetch = async () => {
    const response = responses.shift();
    if (response instanceof Error) throw response;
    return response;
  };

  await import(`../web/site/app.js?test=${Date.now()}`);
  await flushTasks();
  const successfulPage = view.children[0];
  listeners.get("hashchange")();
  await flushTasks();

  assert.equal(view.children[0], successfulPage);
  assert.equal(view.children.length, 2);
  assert.equal(view.querySelector("[data-inline-error]").textContent, "The feeder could not be refreshed.Retry");
});
