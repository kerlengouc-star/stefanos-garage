// Stefanos Garage PWA Service Worker - PERF MODE
// - Pages: network-first (always fresh when online)
// - Static: cache-first
// - Do NOT cache dynamic HTML (history/visits) as offline copies (we'll handle offline data later)

const CACHE_NAME = "stefanos-garage-perf-v8";

const STATIC_ASSETS = [
  "/",
  "/static/manifest.webmanifest",
  "/static/icon-192.png",
  "/static/icon-512.png",
  "/static/app.js",
  "/static/sw.js"
];

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((c) => c.addAll(STATIC_ASSETS)).catch(() => {})
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.map((k) => (k !== CACHE_NAME ? caches.delete(k) : Promise.resolve())));
    await self.clients.claim();
  })());
});

function isStatic(reqUrl) {
  return reqUrl.pathname.startsWith("/static/");
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);

  // Pages: network-first, fallback only to "/" shell
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req).catch(async () => (await caches.match("/")) || Response.error())
    );
    return;
  }

  // Static assets: cache-first
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

  // Other GET requests: just pass-through
  // (we'll add offline data caching in Step 2)
});
