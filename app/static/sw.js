const CACHE_VERSION = "offline-v3";
const CACHE_NAME = `stefanos-garage-${CACHE_VERSION}`;

const PRECACHE = [
  "/",
  "/history",
  "/checklist",
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

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  // ΠΟΛΥ ΣΗΜΑΝΤΙΚΟ: HTML πάντα network-first, για να μη "κολλάει" παλιά χαλασμένη σελίδα
  if (req.mode === "navigate") {
    event.respondWith((async () => {
      try {
        return await fetch(req);
      } catch (e) {
        // offline fallback μόνο για σελίδες που έχουμε precache
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
