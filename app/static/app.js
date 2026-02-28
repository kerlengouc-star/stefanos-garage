// OFFLINE INDICATOR + SW REGISTER + AUTO CACHE PAGES (PHASE 1 FIX)

const PAGES_CACHE = "sg-pages-v1";
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

window.addEventListener("online", () => {
  refreshOfflineUI();
  // όταν ξαναέρθει internet, ξανακάνε cache pages
  cachePagesBestEffort();
});
window.addEventListener("offline", refreshOfflineUI);

window.addEventListener("load", () => {
  refreshOfflineUI();
  // όταν έχει internet, αποθήκευσε offline snapshots αυτόματα
  cachePagesBestEffort();
  // έξτρα “σπρώξιμο” για PWA resume
  setTimeout(refreshOfflineUI, 300);
});

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) {
    refreshOfflineUI();
    cachePagesBestEffort();
  }
});

async function cachePagesBestEffort() {
  if (!("caches" in window)) return;
  if (!navigator.onLine) return;

  try {
    const cache = await caches.open(PAGES_CACHE);

    for (const path of PAGES_TO_CACHE) {
      try {
        // no-store για να πάρει fresh HTML
        const res = await fetch(path, { cache: "no-store" });
        if (res && res.ok) {
          await cache.put(path, res.clone());
        }
      } catch (_) {
        // ignore per-page errors
      }
    }
  } catch (_) {
    // ignore
  }
}

// SW register
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
