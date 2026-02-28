// OFFLINE INDICATOR + SW REGISTER

function showOfflineBanner() {
  if (document.getElementById("offline-banner")) return;

  const el = document.createElement("div");
  el.id = "offline-banner";
  el.style.cssText =
    "position:fixed;top:0;left:0;right:0;z-index:9999;" +
    "background:#dc3545;color:#fff;padding:8px;text-align:center;font-size:14px;";

  el.innerText = "⚠ Δεν υπάρχει σύνδεση στο internet (Offline mode)";
  document.body.appendChild(el);
}

function removeOfflineBanner() {
  const el = document.getElementById("offline-banner");
  if (el) el.remove();
}

window.addEventListener("online", removeOfflineBanner);
window.addEventListener("offline", showOfflineBanner);

if (!navigator.onLine) showOfflineBanner();

// Service Worker registration
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/static/sw.js")
    .catch(() => {});
}
