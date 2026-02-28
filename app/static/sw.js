// Stefanos Garage OFFLINE PHASE 1 (fix /visits/new offline)
const CACHE_VERSION = "offline-v8";
const SW_CACHE = `sg-sw-${CACHE_VERSION}`;
const PAGES_CACHE = "sg-pages-v1";

const PRECACHE = [
  "/static/app.js",
  "/static/manifest.webmanifest",
  "/static/icon-192.png",
  "/static/icon-512.png"
];

const OFFLINE_NEW_VISIT_HTML = `<!doctype html>
<html lang="el">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Νέα Επίσκεψη (Offline)</title>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; padding: 16px; background:#f5f6f8; }
    .card { background:#fff; border-radius:14px; padding:16px; box-shadow:0 6px 24px rgba(0,0,0,.08); }
    label { display:block; font-size:12px; color:#6b7280; margin-top:10px; }
    input, textarea { width:100%; padding:10px; border:1px solid #e5e7eb; border-radius:10px; font-size:14px; background:#fff; }
    .row { display:grid; grid-template-columns: 1fr 1fr; gap:10px; }
    .btns { display:flex; gap:10px; flex-wrap:wrap; margin-top:14px; }
    button, a { appearance:none; border:0; padding:10px 12px; border-radius:10px; font-size:14px; cursor:pointer; text-decoration:none; }
    .btn { background:#111827; color:#fff; }
    .btn2 { background:#e5e7eb; color:#111827; }
    .note { margin-top:10px; font-size:12px; color:#6b7280; }
    @media (max-width: 600px){ .row{ grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <div class="card">
    <h3 style="margin:0 0 6px 0;">Νέα Επίσκεψη (Offline)</h3>
    <div style="color:#dc2626;font-size:13px;margin-bottom:10px;">
      Είσαι offline. Μπορείς να γράψεις στοιχεία, αλλά δεν γίνεται αποθήκευση στη βάση ακόμα.
    </div>

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
      <button class="btn" id="save_draft">Αποθήκευση Προσωρινά</button>
      <button class="btn2" id="clear_draft">Καθαρισμός</button>
      <a class="btn2" href="/">Αρχική</a>
      <a class="btn2" href="/history">Ιστορικό</a>
      <a class="btn2" href="/checklist">Checklist</a>
    </div>

    <div class="note">
      Στη Φάση 2 θα γίνει Sync: θα αποθηκεύει offline και θα ανεβάζει όταν έχει internet.
    </div>
  </div>

  <script src="/static/app.js"></script>
  <script>
    const KEY = "offline_new_visit_draft_v1";
    const ids = ["customer_name","phone","email","plate_number","model","vin","notes"];

    function loadDraft(){
      try{
        const d = JSON.parse(localStorage.getItem(KEY) || "{}");
        ids.forEach(id => { if(d[id] !== undefined) document.getElementById(id).value = d[id]; });
      }catch(e){}
    }
    function saveDraft(){
      const d = {};
      ids.forEach(id => d[id] = document.getElementById(id).value || "");
      localStorage.setItem(KEY, JSON.stringify(d));
      alert("Αποθηκεύτηκε προσωρινά (offline draft).");
    }
    function clearDraft(){
      localStorage.removeItem(KEY);
      ids.forEach(id => document.getElementById(id).value = "");
    }

    document.getElementById("save_draft").onclick = saveDraft;
    document.getElementById("clear_draft").onclick = clearDraft;

    loadDraft();
  </script>
</body>
</html>`;

const OFFLINE_FALLBACK_HTML = `<!doctype html>
<html lang="el">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Offline</title>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; padding: 16px; background:#f5f6f8; }
    .card { background:#fff; border-radius:14px; padding:16px; box-shadow:0 6px 24px rgba(0,0,0,.08); }
    a { display:inline-block; margin-right:10px; margin-top:10px; padding:10px 12px; border-radius:10px; background:#e5e7eb; color:#111827; text-decoration:none; }
  </style>
</head>
<body>
  <div class="card">
    <h3 style="margin:0 0 6px 0;">Offline mode</h3>
    <div style="color:#6b7280;">Δεν υπάρχει σύνδεση. Μπορείς να δεις σελίδες που έχουν αποθηκευτεί.</div>
    <div>
      <a href="/">Αρχική</a>
      <a href="/history">Ιστορικό</a>
      <a href="/checklist">Checklist</a>
      <a href="/visits/new">Νέα Επίσκεψη</a>
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
    return (await cache.match(pathname, { ignoreSearch: true })) || null;
  } catch {
    return null;
  }
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);

  if (req.mode === "navigate") {
    event.respondWith((async () => {
      try {
        return await fetch(req);
      } catch (e) {
        // ειδική offline σελίδα για /visits/new
        if (url.pathname === "/visits/new") {
          return new Response(OFFLINE_NEW_VISIT_HTML, { status: 200, headers: { "Content-Type": "text/html; charset=utf-8" } });
        }

        // αλλιώς προσπάθησε cached snapshot
        const cached = await matchFromPagesCache(url.pathname);
        if (cached) return cached;

        // fallback generic
        return new Response(OFFLINE_FALLBACK_HTML, { status: 200, headers: { "Content-Type": "text/html; charset=utf-8" } });
      }
    })());
    return;
  }

  // static assets: cache-first
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
