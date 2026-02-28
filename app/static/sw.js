// Stefanos Garage OFFLINE PHASE 1
// Αν θες να "αναγκάσεις" update test: άλλαξε offline-v2 -> offline-v3 κλπ
const CACHE_VERSION = "offline-v2";
const CACHE_NAME = `stefanos-garage-${CACHE_VERSION}`;

const PRECACHE = [
  "/",
  "/history",
  "/checklist",
  "/visits/new",
  "/static/app.js",
  "/static/manifest.webmanifest",
  "/static/icon-192.png",
  "/static/icon-512.png"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE)).catch(() => {})
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.map((k) => (k !== CACHE_NAME ? caches.delete(k) : Promise.resolve())));
    await self.clients.claim();
  })());
});

// HTML = network-first, fallback σε cached ίδιας σελίδας, αλλιώς fallback στο "/"
self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  if (req.mode === "navigate") {
    event.respondWith((async () => {
      try {
        const fresh = await fetch(req);
        const copy = fresh.clone();
        caches.open(CACHE_NAME).then((c) => c.put(req, copy)).catch(() => {});
        return fresh;
      } catch (e) {
        const cached = await caches.match(req);
        if (cached) return cached;
        return (await caches.match("/")) || Response.error();
      }
    })());
    return;
  }

  // static: cache-first
  event.respondWith(
    caches.match(req).then((cached) => cached || fetch(req))
  );
});
