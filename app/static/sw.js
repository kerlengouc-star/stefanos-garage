// Stefanos Garage - STABLE Offline Queue (does NOT break online pages)
const CACHE_VERSION = "stable-phaseB-v1";
const SW_CACHE = `sg-sw-${CACHE_VERSION}`;

const PRECACHE = [
  "/static/app.js",
  "/static/manifest.webmanifest",
  "/static/icon-192.png",
  "/static/icon-512.png"
];

// Offline "New Visit" page only (safe)
const OFFLINE_NEW_VISIT_HTML = `<!doctype html>
<html lang="el">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Νέα Επίσκεψη (Offline)</title>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; padding:16px; background:#f5f6f8; }
    .card { background:#fff;border-radius:14px;padding:16px;box-shadow:0 6px 24px rgba(0,0,0,.08); }
    label { display:block;font-size:12px;color:#6b7280;margin-top:10px; }
    input, textarea { width:100%;padding:10px;border:1px solid #e5e7eb;border-radius:10px;font-size:14px;background:#fff; }
    .row { display:grid;grid-template-columns:1fr 1fr;gap:10px; }
    .btns { display:flex;gap:10px;flex-wrap:wrap;margin-top:14px; }
    button,a { appearance:none;border:0;padding:10px 12px;border-radius:10px;font-size:14px;cursor:pointer;text-decoration:none; }
    .btn { background:#111827;color:#fff; }
    .btn2 { background:#e5e7eb;color:#111827; }
    .note { margin-top:10px;font-size:12px;color:#6b7280; }
    @media (max-width:600px){ .row{ grid-template-columns:1fr; } }
  </style>
</head>
<body>
  <div class="card">
    <h3 style="margin:0 0 6px 0;">Νέα Επίσκεψη (Offline)</h3>
    <div style="color:#dc2626;font-size:13px;margin-bottom:10px;">
      Είσαι offline. Η καταχώρηση θα αποθηκευτεί στο κινητό/PC και θα ανέβει όταν επανέλθει internet.
    </div>

    <div class="note">Ημερομηνία/Ώρα συσκευής: <b id="sg-device-time">—</b></div>

    <form id="sg-offline-new-visit-form">
      <div class="row">
        <div>
          <label>Όνομα Πελάτη</label>
          <input id="customer_name" placeholder="π.χ. Ανδρέας">
        </div>
        <div>
          <label>Τηλέφωνο</label>
          <input id="phone" placeholder="π.χ. 99xxxxxx">
        </div>
        <div>
          <label>Email</label>
          <input id="email" placeholder="π.χ. test@email.com">
        </div>
        <div>
          <label>Πινακίδα</label>
          <input id="plate_number" placeholder="π.χ. KAA123">
        </div>
        <div>
          <label>Μοντέλο</label>
          <input id="model" placeholder="π.χ. Toyota">
        </div>
        <div>
          <label>VIN</label>
          <input id="vin" placeholder="π.χ. ...">
        </div>
      </div>

      <label>Σημειώσεις</label>
      <textarea id="notes" rows="3" placeholder="τι θέλει ο πελάτης..."></textarea>

      <div class="btns">
        <button class="btn" type="submit">Αποθήκευση Offline</button>
        <a class="btn2" href="/">Αρχική (online)</a>
      </div>
    </form>

    <div class="note">
      Tip: όταν έρθει internet θα εμφανιστεί πράσινο banner “Συγχρονισμός τώρα”.
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
    await Promise.all(keys.map((k) => (k !== SW_CACHE ? caches.delete(k) : Promise.resolve())));
    await self.clients.claim();
  })());
});

// ✅ IMPORTANT: Do NOT hijack normal online pages.
// We only provide offline fallback for /visits/new when fetch fails (offline).
self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);

  if (req.mode === "navigate") {
    event.respondWith((async () => {
      try {
        // online → always fetch from server (normal app)
        return await fetch(req);
      } catch (e) {
        // offline → only handle New Visit
        if (url.pathname.startsWith("/visits/new")) {
          return new Response(OFFLINE_NEW_VISIT_HTML, {
            status: 200,
            headers: { "Content-Type": "text/html; charset=utf-8" }
          });
        }
        // everything else: simple offline page (no broken redirects)
        return new Response(
          "<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>" +
          "<div style='font-family:system-ui;padding:16px'>Offline. Άνοιξε <a href=\"/visits/new\">Νέα Επίσκεψη</a> για offline καταχώρηση.</div>" +
          "<script src='/static/app.js'></script>",
          { status: 200, headers: { "Content-Type": "text/html; charset=utf-8" } }
        );
      }
    })());
    return;
  }

  // static: cache-first
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
