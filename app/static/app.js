// OFFLINE INDICATOR + SW REGISTER (PHASE 1)

function showOfflineBanner() {
  if (document.getElementById("offline-banner")) return;

  const el = document.createElement("div");
  el.id = "offline-banner";
  el.style.cssText =
    "position:fixed;top:0;left:0;right:0;z-index:9999;" +
    "background:#dc3545;color:#fff;padding:8px;text-align:center;font-size:14px;";

  el.textContent = "⚠ Δεν υπάρχει σύνδεση στο internet (Offline mode)";
  document.body.appendChild(el);

  // push page down so it doesn't cover navbar
  document.body.style.paddingTop = "34px";
}

function removeOfflineBanner() {
  const el = document.getElementById("offline-banner");
  if (el) el.remove();
  document.body.style.paddingTop = "";
}

window.addEventListener("online", removeOfflineBanner);
window.addEventListener("offline", showOfflineBanner);

if (!navigator.onLine) showOfflineBanner();

// ✅ Register SW (root scope is controlled by main.py: /sw.js)
async function registerSW() {
  if (!("serviceWorker" in navigator)) return;
  try {
    await navigator.serviceWorker.register("/sw.js");
  } catch (e) {
    // ignore
  }
}

registerSW();
