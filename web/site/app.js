import {startRouter} from "./router.js";

const view = document.querySelector("#view");

function render(route) {
  view.dataset.route = route.name;
  view.replaceChildren();
}

startRouter(render);

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}
