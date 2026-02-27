// Stefanos Garage PWA Service Worker (ROOT scope: registered as /sw.js)
// Offline shell + cache static assets

const CACHE_NAME = "stefanos-garage-offline-shell-v11";

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
  "/sw.js"
];

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll([...OFFLINE_PAGES, ...STATIC_ASSETS]))
      .catch(() => {})
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
  return url.pathname.startsWith("/static/") || url.pathname === "/sw.js";
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);

  // Static: cache-first
  if (isStatic(url)) {
    event.respondWith(
      caches.match(req).then((cached) => {
        if (cached) return cached;
        return fetch(req).then((res) => {
          const copy = res.clone();
          caches.open(CACHE_NAME).then((c) => c.put(req, copy)).catch(() => {});
          return res;
        });
      })
    );
    return;
  }

  // Pages: network-first, fallback cache
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req).then((res) => {
        const copy = res.clone();
        caches.open(CACHE_NAME).then((c) => c.put(req, copy)).catch(() => {});
        return res;
      }).catch(async () => {
        return (await caches.match(req))
          || (await caches.match("/visits/new"))
          || (await caches.match("/"));
      })
    );
    return;
  }

  // Other GET: cache then network
  event.respondWith(caches.match(req).then((cached) => cached || fetch(req)));
});
