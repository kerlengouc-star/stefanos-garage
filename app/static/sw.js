// Stefanos Garage PWA Service Worker
// Αν θέλεις να εμφανιστεί update banner στο μέλλον,
// αλλάζεις ΜΟΝΟ το v2 σε v3, v4 κλπ.
const CACHE_VERSION = "v2";
const CACHE_NAME = `stefanos-garage-${CACHE_VERSION}`;

const ASSETS = [
  "/",
  "/history",
  "/checklist",
  "/static/app.js",
  "/static/manifest.webmanifest",
  "/static/icon-192.png",
  "/static/icon-512.png"
];

// Ενεργοποίηση άμεσα όταν πατηθεί "Ανανεώστε"
self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(ASSETS))
      .catch(() => {})
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(
      keys.map((key) => {
        if (key !== CACHE_NAME) {
          return caches.delete(key);
        }
      })
    );
    await self.clients.claim();
  })());
});

// HTML = network first (ώστε να παίρνει update)
// Static files = cache first
self.addEventListener("fetch", (event) => {
  const request = event.request;

  if (request.method !== "GET") return;

  // Για HTML pages
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE_NAME)
            .then((cache) => cache.put(request, copy))
            .catch(() => {});
          return response;
        })
        .catch(async () => {
          return await caches.match(request) || await caches.match("/");
        })
    );
    return;
  }

  // Για static αρχεία
  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) return cached;

      return fetch(request).then((response) => {
        const copy = response.clone();
        caches.open(CACHE_NAME)
          .then((cache) => cache.put(request, copy))
          .catch(() => {});
        return response;
      });
    })
  );
});
