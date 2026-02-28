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

window.addEventListener("online", refreshOfflineUI);
window.addEventListener("offline", refreshOfflineUI);

window.addEventListener("load", () => {
  refreshOfflineUI();
  setTimeout(refreshOfflineUI, 300);
});

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) {
    refreshOfflineUI();
    setTimeout(refreshOfflineUI, 200);
  }
});

// ✅ όταν πατάς link/κουμπί, κάνε ξανά check
document.addEventListener("click", () => {
  setTimeout(refreshOfflineUI, 50);
});

// SW register
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
