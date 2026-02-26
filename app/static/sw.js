// Simple offline cache (banner is handled by version.json, not SW waiting)
const CACHE_NAME = "stefanos-garage-offline-v4";

const ASSETS = [
  "/",
  "/history",
  "/checklist",
  "/static/manifest.webmanifest?v=v4",
  "/static/icon-192.png",
  "/static/icon-512.png",
  "/static/version.json"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((c) => c.addAll(ASSETS)).catch(() => {})
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req).catch(async () => (await caches.match("/")) || Response.error())
    );
    return;
  }

  event.respondWith(
    caches.match(req).then((cached) => cached || fetch(req))
  );
});
