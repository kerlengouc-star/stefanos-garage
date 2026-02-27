// Stefanos Garage Offline Queue + Sync + Toasts
// Uses ROOT service worker registered at /sw.js for full-site offline.

const OFFLINE_QUEUE_KEY = "garage_offline_queue_v2";

// ---------- Toast ----------
function toast(msg, ok = true) {
  const el = document.createElement("div");
  el.style.cssText =
    "position:fixed;bottom:20px;left:20px;right:20px;z-index:999999;" +
    `background:${ok ? "#198754" : "#dc3545"};color:#fff;` +
    "padding:12px 14px;border-radius:12px;" +
    "box-shadow:0 10px 30px rgba(0,0,0,.2);font-size:14px;";
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3000);
}

// ---------- Queue storage ----------
function getQueue() {
  try { return JSON.parse(localStorage.getItem(OFFLINE_QUEUE_KEY)) || []; }
  catch { return []; }
}
function setQueue(q) { localStorage.setItem(OFFLINE_QUEUE_KEY, JSON.stringify(q)); }
function enqueue(item) {
  const q = getQueue();
  q.push(item);
  setQueue(q);
}

// ---------- Sync ----------
async function syncQueue() {
  if (!navigator.onLine) return;

  const q = getQueue();
  if (!q.length) return;

  for (const item of q) {
    try {
      const res = await fetch(item.url, {
        method: item.method || "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: item.body,
        credentials: "same-origin",
      });
      if (!res.ok) throw new Error("HTTP " + res.status);
    } catch (e) {
      // stop at first failure; keep queue
      toast("Αποτυχία συγχρονισμού — θα ξαναδοκιμάσει μόλις έχει internet.", false);
      return;
    }
  }

  localStorage.removeItem(OFFLINE_QUEUE_KEY);
  toast("Offline δεδομένα συγχρονίστηκαν ✅");
}

window.addEventListener("online", () => {
  // give the connection a moment
  setTimeout(syncQueue, 800);
});
window.addEventListener("load", () => {
  setTimeout(syncQueue, 800);
});

// ---------- Register Service Worker (ROOT scope) ----------
async function registerSW() {
  if (!("serviceWorker" in navigator)) return;
  try {
    await navigator.serviceWorker.register("/sw.js");
  } catch (e) {}
}
registerSW();

// ---------- Intercept visit form submit when offline ----------
document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("visit-form");
  if (!form) return;

  form.addEventListener("submit", (e) => {
    if (navigator.onLine) return; // online -> normal submit

    e.preventDefault();

    const fd = new FormData(form);
    const params = new URLSearchParams();
    for (const [k, v] of fd.entries()) params.append(k, v);

    enqueue({
      url: form.action,
      method: (form.method || "POST").toUpperCase(),
      body: params.toString(),
      ts: Date.now(),
    });

    toast("Αποθηκεύτηκε offline 📦");
  });
});
