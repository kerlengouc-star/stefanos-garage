// Stefanos Garage PWA Service Worker (v7)
// Στόχος: να παίρνει πάντα νέο HTML όταν έχει internet (network-first)
// και να κρατάει offline fallback.

const CACHE_NAME = "stefanos-garage-v7";

const ASSETS = [
  "/",
  "/history",
  "/checklist",
  "/static/manifest.webmanifest?v=v7",
  "/static/icon-192.png",
  "/static/icon-512.png"
];

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((c) => c.addAll(ASSETS)).catch(() => {})
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.map((k) => (k !== CACHE_NAME ? caches.delete(k) : Promise.resolve())));
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  // Pages: network-first (πάντα νέο HTML όταν υπάρχει internet)
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req).catch(async () => (await caches.match(req)) || (await caches.match("/")))
    );
    return;
  }

  // Static: cache-first
  event.respondWith(
    caches.match(req).then((cached) => cached || fetch(req))
  );
});
