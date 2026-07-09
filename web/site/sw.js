// Minimal offline shell. Caches the app frame; data is always fetched fresh.
const CACHE = "fieldlog-v1";
const SHELL = ["./", "index.html", "styles.css", "app.js", "manifest.json"];

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
  // Never cache detection data or thumbnails — always go to network.
  if (url.pathname.includes("/data/") || url.pathname.includes("/thumbs/")) return;
  e.respondWith(caches.match(e.request).then((hit) => hit || fetch(e.request)));
});
