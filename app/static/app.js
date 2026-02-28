// Stefanos Garage - Offline Phase 1 (stable)
// 1) Offline red banner
// 2) Auto-cache key pages when online (so they open offline)
// 3) Auto-fill date/time inputs from device clock

const PAGES_CACHE = "sg-pages-v2";
const PAGES_TO_CACHE = ["/", "/history", "/checklist", "/visits/new"];

function showOfflineBanner() {
  if (document.getElementById("offline-banner")) return;

  const el = document.createElement("div");
  el.id = "offline-banner";
  el.style.cssText =
    "position:fixed;top:0;left:0;right:0;z-index:9999;" +
    "background:#dc3545;color:#fff;padding:8px;text-align:center;font-size:14px;";
  el.textContent = "⚠ Δεν υπάρχει σύνδεση στο internet (Offline mode)";
  document.body.appendChild(el);
  document.body.style.paddingTop = "34px";
}

function removeOfflineBanner() {
  const el = document.getElementById("offline-banner");
  if (el) el.remove();
  document.body.style.paddingTop = "";
}

function refreshOfflineUI() {
  if (navigator.onLine) removeOfflineBanner();
  else showOfflineBanner();
}

async function cachePagesBestEffort() {
  if (!("caches" in window)) return;
  if (!navigator.onLine) return;

  try {
    const cache = await caches.open(PAGES_CACHE);

    for (const path of PAGES_TO_CACHE) {
      try {
        const res = await fetch(path, { cache: "no-store" });
        if (res && res.ok) {
          await cache.put(path, res.clone());
        }
      } catch (_) {}
    }
  } catch (_) {}
}

// ✅ Auto-fill date/time from device clock
function pad2(n) {
  return String(n).padStart(2, "0");
}

function setDateTimeDefaults() {
  const now = new Date();
  const yyyy = now.getFullYear();
  const mm = pad2(now.getMonth() + 1);
  const dd = pad2(now.getDate());
  const hh = pad2(now.getHours());
  const mi = pad2(now.getMinutes());

  const today = `${yyyy}-${mm}-${dd}`;
  const time = `${hh}:${mi}`;

  // common names/ids we might have in templates
  const dateFields = [
    'input[name="date_in"]', "#date_in",
    'input[name="date_out"]', "#date_out",
    'input[name="delivery_date"]', "#delivery_date"
  ];
  const timeFields = [
    'input[name="time_in"]', "#time_in",
    'input[name="time_out"]', "#time_out",
    'input[name="delivery_time"]', "#delivery_time"
  ];

  for (const sel of dateFields) {
    const el = document.querySelector(sel);
    if (el && !el.value) el.value = today;
  }
  for (const sel of timeFields) {
    const el = document.querySelector(sel);
    if (el && !el.value) el.value = time;
  }
}

// Events
window.addEventListener("online", () => {
  refreshOfflineUI();
  cachePagesBestEffort();
});
window.addEventListener("offline", refreshOfflineUI);

window.addEventListener("load", () => {
  refreshOfflineUI();
  setDateTimeDefaults();
  cachePagesBestEffort();
  setTimeout(() => {
    refreshOfflineUI();
    setDateTimeDefaults();
  }, 400);
});

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) {
    refreshOfflineUI();
    setDateTimeDefaults();
    cachePagesBestEffort();
  }
});

// Service Worker register
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
