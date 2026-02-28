// Stefanos Garage OFFLINE PHASE 1 (FIX for PWA open while already offline)
const CACHE_VERSION = "offline-v4";
const CACHE_NAME = `stefanos-garage-${CACHE_VERSION}`;

const PRECACHE = [
  "/",              // app shell
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
    (async () => {
      const cache = await caches.open(CACHE_NAME);
      await cache.addAll(PRECACHE);
      self.skipWaiting();
    })().catch(() => {})
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.map((k) => (k !== CACHE_NAME ? caches.delete(k) : Promise.resolve())));
    await self.clients.claim();
  })());
});

// HTML: network-first, but OFFLINE always falls back to cached "/" (ignore query params)
self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);

  // Navigations (pages)
  if (req.mode === "navigate") {
    event.respondWith((async () => {
      try {
        // online -> always prefer fresh
        return await fetch(req);
      } catch (e) {
        // offline -> try exact page ignoring search, else fallback to "/"
        const cachedPage =
          (await caches.match(req, { ignoreSearch: true })) ||
          (await caches.match(url.pathname, { ignoreSearch: true })) ||
          (await caches.match("/", { ignoreSearch: true })) ||
          (await caches.match("/"));

        return cachedPage || new Response("Offline", { status: 503, headers: { "Content-Type": "text/plain" } });
      }
    })());
    return;
  }

  // Static files: cache-first
  event.respondWith((async () => {
    const cached =
      (await caches.match(req, { ignoreSearch: true })) ||
      (await caches.match(url.pathname, { ignoreSearch: true }));
    if (cached) return cached;

    try {
      const fresh = await fetch(req);
      const copy = fresh.clone();
      caches.open(CACHE_NAME).then((c) => c.put(req, copy)).catch(() => {});
      return fresh;
    } catch (e) {
      return cached || new Response("", { status: 504 });
    }
  })());
});
