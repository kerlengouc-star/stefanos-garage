// Stefanos Garage PWA Service Worker - OFFLINE SHELL v9
// Στόχος: να ανοίγει offline η εφαρμογή και ειδικά η "Νέα Επίσκεψη" (/visits/new)

const CACHE_NAME = "stefanos-garage-offline-shell-v9";

const OFFLINE_PAGES = [
  "/",
  "/visits/new",
  "/checklist",
  "/history"
];

const STATIC_ASSETS = [
  "/static/manifest.webmanifest",
  "/static/icon-192.png",
  "/static/icon-512.png",
  "/static/app.js",
  "/static/sw.js"
];

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll([...OFFLINE_PAGES, ...STATIC_ASSETS]);
    }).catch(() => {})
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.map((k) => (k !== CACHE_NAME ? caches.delete(k) : Promise.resolve())));
    await self.clients.claim();
  })());
});

function isStatic(url) {
  return url.pathname.startsWith("/static/");
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);

  // 1) Static: cache-first
  if (isStatic(url)) {
    event.respondWith(
      caches.match(req).then((cached) => cached || fetch(req).then((res) => {
        const copy = res.clone();
        caches.open(CACHE_NAME).then((c) => c.put(req, copy)).catch(() => {});
        return res;
      }))
    );
    return;
  }

  // 2) Pages: network-first, fallback cache
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req).then((res) => {
        // cache the latest HTML page when online
        const copy = res.clone();
        caches.open(CACHE_NAME).then((c) => c.put(req, copy)).catch(() => {});
        return res;
      }).catch(async () => {
        // offline fallback: try exact page, else /visits/new, else /
        return (await caches.match(req))
          || (await caches.match("/visits/new"))
          || (await caches.match("/"));
      })
    );
    return;
  }

  // 3) Other GET: try cache, then network
  event.respondWith(
    caches.match(req).then((cached) => cached || fetch(req))
  );
});
