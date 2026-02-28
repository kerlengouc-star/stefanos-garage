// Stefanos Garage OFFLINE PHASE 1 (serve cached pages when offline)
const CACHE_VERSION = "offline-v7";
const SW_CACHE = `sg-sw-${CACHE_VERSION}`;

// αυτός είναι ο cache που γεμίζει από το app.js
const PAGES_CACHE = "sg-pages-v1";

const PRECACHE = [
  "/static/app.js",
  "/static/manifest.webmanifest",
  "/static/icon-192.png",
  "/static/icon-512.png"
];

const OFFLINE_HTML = `<!doctype html>
<html lang="el">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Offline</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { padding: 18px; background:#f5f6f8; }
    .page { background:#fff; border-radius:16px; padding:18px; box-shadow:0 6px 24px rgba(0,0,0,.08); }
  </style>
</head>
<body>
  <div class="container-fluid">
    <div class="page">
      <h4 class="mb-2">Offline mode</h4>
      <div class="text-muted mb-3">
        Δεν υπάρχει σύνδεση. Αν έχεις ανοίξει τις σελίδες online έστω 1 φορά, θα ανοίγουν και offline.
      </div>

      <div class="d-flex gap-2 flex-wrap">
        <a class="btn btn-outline-secondary btn-sm" href="/">Αρχική</a>
        <a class="btn btn-outline-secondary btn-sm" href="/history">Ιστορικό</a>
        <a class="btn btn-outline-secondary btn-sm" href="/checklist">Checklist</a>
        <a class="btn btn-outline-secondary btn-sm" href="/visits/new">Νέα Επίσκεψη (φόρμα)</a>
      </div>
    </div>
  </div>

  <script src="/static/app.js"></script>
</body>
</html>`;

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(SW_CACHE);
    await cache.addAll(PRECACHE);
    self.skipWaiting();
  })().catch(() => {}));
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.map((k) => (k !== SW_CACHE && k !== PAGES_CACHE ? caches.delete(k) : Promise.resolve())));
    await self.clients.claim();
  })());
});

async function matchFromPagesCache(pathname) {
  try {
    const cache = await caches.open(PAGES_CACHE);
    const hit = await cache.match(pathname, { ignoreSearch: true });
    return hit || null;
  } catch {
    return null;
  }
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);

  // HTML pages
  if (req.mode === "navigate") {
    event.respondWith((async () => {
      try {
        return await fetch(req);
      } catch (e) {
        // OFFLINE: πρώτα προσπάθησε cached snapshot από PAGES_CACHE
        const cached = await matchFromPagesCache(url.pathname);
        if (cached) return cached;

        // μετά fallback στην offline page
        return new Response(OFFLINE_HTML, {
          status: 200,
          headers: { "Content-Type": "text/html; charset=utf-8" }
        });
      }
    })());
    return;
  }

  // Static assets: cache-first (SW cache)
  event.respondWith((async () => {
    const cache = await caches.open(SW_CACHE);
    const cached = await cache.match(req, { ignoreSearch: true });
    if (cached) return cached;

    try {
      const fresh = await fetch(req);
      cache.put(req, fresh.clone()).catch(() => {});
      return fresh;
    } catch {
      return cached || new Response("", { status: 504 });
    }
  })());
});
