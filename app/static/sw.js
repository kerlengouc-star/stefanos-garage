const CACHE_VERSION = "offline-v6";
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
      <div class="text-muted mb-3">Δεν υπάρχει σύνδεση στο internet.</div>

      <div class="d-flex gap-2 flex-wrap">
        <button class="btn btn-outline-secondary btn-sm" data-go="/">Αρχική</button>
        <button class="btn btn-outline-secondary btn-sm" data-go="/history">Ιστορικό</button>
        <button class="btn btn-outline-secondary btn-sm" data-go="/checklist">Checklist</button>
        <button class="btn btn-outline-secondary btn-sm" data-go="/visits/new">Νέα Επίσκεψη (φόρμα)</button>
      </div>

      <div class="mt-3 small text-muted">
        Σημείωση: Offline καταχώρηση στη βάση θα γίνει στη Φάση 2 (sync).
      </div>
    </div>
  </div>

  <script src="/static/app.js"></script>
  <script>
    // offline navigation helper
    document.addEventListener("click", function(e){
      const btn = e.target.closest("[data-go]");
      if(!btn) return;
      const path = btn.getAttribute("data-go");
      if(path) location.href = path;
    });
  </script>
</body>
</html>`;

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_NAME);
    await cache.addAll(PRECACHE);
    self.skipWaiting();
  })().catch(() => {}));
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.map((k) => (k !== CACHE_NAME ? caches.delete(k) : Promise.resolve())));
    await self.clients.claim();
  })());
});

async function cachedOrOffline(req) {
  const url = new URL(req.url);
  const cached =
    (await caches.match(req, { ignoreSearch: true })) ||
    (await caches.match(url.pathname, { ignoreSearch: true })) ||
    (await caches.match("/", { ignoreSearch: true })) ||
    (await caches.match("/"));

  if (cached) return cached;

  return new Response(OFFLINE_HTML, {
    headers: { "Content-Type": "text/html; charset=utf-8" },
    status: 200
  });
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  // Pages
  if (req.mode === "navigate") {
    event.respondWith((async () => {
      try {
        // online -> fresh
        const res = await fetch(req);
        // cache latest html too (best-effort)
        const copy = res.clone();
        caches.open(CACHE_NAME).then((c) => c.put(req, copy)).catch(() => {});
        return res;
      } catch (e) {
        // offline -> cached or offline html
        return await cachedOrOffline(req);
      }
    })());
    return;
  }

  // Static assets
  event.respondWith((async () => {
    const url = new URL(req.url);
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
      return new Response("", { status: 504 });
    }
  })());
});
