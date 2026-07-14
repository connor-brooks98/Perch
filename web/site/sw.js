// Minimal offline shell. Caches the app frame; data is always fetched fresh.
const CACHE = "perch-shell-v2";
const SHELL = [
  "./",
  "index.html",
  "styles.css",
  "app.js",
  "api.js",
  "components.js",
  "router.js",
  "format.js",
  "views/history.js",
  "views/birds.js",
  "views/favorites.js",
  "views/species.js",
  "views/today.js",
  "views/visit.js",
  "manifest.json",
  "icons/perch-mark.svg",
  "icons/apple-touch-icon.png",
  "icons/icon-192.png",
  "icons/icon-512.png",
  "icons/icon-maskable-512.png",
  "icons/favicon-32.png",
  "favicon.ico"
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  // Dynamic responses and media always go directly to the network.
  if (
    url.pathname.includes("/api/") ||
    url.pathname.includes("/images/") ||
    url.pathname.includes("/thumbs/") ||
    url.pathname.includes("/enrichment/")
  ) return;
  e.respondWith(caches.match(e.request).then((hit) => hit || fetch(e.request)));
});
