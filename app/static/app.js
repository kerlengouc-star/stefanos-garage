// Stefanos Garage - Reliable update banner based on HTML meta version (no version.json)

const STORAGE_KEY = "stefanos_garage_app_version_seen";

function getHtmlVersion() {
  const meta = document.querySelector('meta[name="app-version"]');
  return meta ? String(meta.getAttribute("content") || "").trim() : "";
}

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
      // Delete caches to force fresh assets
      if ("caches" in window) {
        const keys = await caches.keys();
        await Promise.all(keys.map((k) => caches.delete(k)));
      }
    } catch (e) {}

    // Reload hard
    window.location.reload();
  };
}

function checkAndShowBanner() {
  const current = getHtmlVersion();
  if (!current) return;

  const lastSeen = localStorage.getItem(STORAGE_KEY);

  // First run: store only, no banner
  if (!lastSeen) {
    localStorage.setItem(STORAGE_KEY, current);
    return;
  }

  // New version detected
  if (lastSeen !== current) {
    localStorage.setItem(STORAGE_KEY, current);
    showUpdateBanner(current);
  }
}

// Keep SW registration for offline caching (banner does NOT depend on SW waiting)
async function registerSW() {
  if (!("serviceWorker" in navigator)) return;
  try {
    await navigator.serviceWorker.register("/static/sw.js");
  } catch (e) {}
}

window.addEventListener("load", () => {
  registerSW();
  checkAndShowBanner();
});
