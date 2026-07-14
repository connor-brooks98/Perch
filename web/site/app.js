import {startRouter} from "./router.js";
import {getToday, patchDetection} from "./api.js";
import {inlineError, showStatus} from "./components.js";
import {renderToday} from "./views/today.js";

const view = document.querySelector("#view");
let renderVersion = 0;

function removeInlineError() {
  view.querySelector("[data-inline-error]")?.remove();
}

async function loadToday(version) {
  removeInlineError();
  try {
    const data = await getToday();
    if (version !== renderVersion) return;
    renderToday(view, data, {
      onToggleFavorite: (detection, favorite) => patchDetection(detection.id, {favorite}),
      onCorrect: (detection) => {
        window.location.hash = `#/visits/${encodeURIComponent(detection.id)}`;
      },
    });
    showStatus("");
  } catch (_error) {
    if (version !== renderVersion) return;
    const retry = () => loadToday(version);
    view.append(inlineError("The feeder could not be refreshed.", retry));
  }
}

function render(route) {
  const version = ++renderVersion;
  view.dataset.route = route.name;
  if (route.name === "today") {
    loadToday(version);
    return;
  }
  view.replaceChildren();
}

startRouter(render);

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}
