// Stefanos Garage - Version-based update banner (reliable on Android PWA)

const VERSION_URL = "/static/version.json";
const STORAGE_KEY = "stefanos_garage_version_seen";

function showUpdateBanner(newVersion) {
  if (document.getElementById("update-banner")) return;

  const el = document.createElement("div");
  el.id = "update-banner";
  el.style.cssText =
    "position:fixed;bottom:12px;left:12px;right:12px;z-index:9999;" +
    "background:#198754;color:#fff;padding:12px 14px;border-radius:12px;" +
    "display:flex;gap:12px;align-items:center;justify-content:space-between;" +
    "box-shadow:0 10px 30px rgba(0,0,0,.2);font-size:14px;";

  el.innerHTML = `
    <div>Υπάρχει νέα έκδοση (${newVersion}) — Ανανεώστε</div>
    <button id="update-btn" style="background:#fff;color:#198754;border:0;padding:8px 12px;border-radius:10px;cursor:pointer;font-weight:600;">
      Ανανεώστε
    </button>
  `;

  document.body.appendChild(el);

  document.getElementById("update-btn").onclick = async () => {
    try {
      // Clear SW caches for a truly fresh reload
      if ("caches" in window) {
        const keys = await caches.keys();
        await Promise.all(keys.map((k) => caches.delete(k)));
      }
    } catch (e) {}

    // Hard reload
    window.location.reload(true);
  };
}

async function checkVersionAndMaybeShowBanner() {
  try {
    const res = await fetch(`${VERSION_URL}?t=${Date.now()}`, { cache: "no-store" });
    if (!res.ok) return;

    const data = await res.json();
    const v = (data && data.version) ? String(data.version) : "";
    if (!v) return;

    const lastSeen = localStorage.getItem(STORAGE_KEY);

    // First run: store version, no banner
    if (!lastSeen) {
      localStorage.setItem(STORAGE_KEY, v);
      return;
    }

    // New version: show banner
    if (lastSeen !== v) {
      showUpdateBanner(v);
      // update stored version so banner doesn't loop forever
      localStorage.setItem(STORAGE_KEY, v);
    }
  } catch (e) {
    // ignore
  }
}

// Still register SW (for offline caching), but banner does NOT depend on it
(async function registerSW() {
  if (!("serviceWorker" in navigator)) return;
  try {
    await navigator.serviceWorker.register(`/static/sw.js?v=${Date.now()}`);
  } catch (e) {}
})();

window.addEventListener("load", () => {
  checkVersionAndMaybeShowBanner();
});
