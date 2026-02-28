// Stefanos Garage - Offline Queue + Sync (Phase B)
// - When OFFLINE: New Visit saves locally (queue)
// - When ONLINE: Sync button uploads queued visits via POST /visits/new
// - Shows red offline banner + queued count + Sync Now button (when online & queue>0)

const QUEUE_KEY = "sg_offline_visits_queue_v1";

function loadQueue() {
  try {
    const raw = localStorage.getItem(QUEUE_KEY);
    const arr = JSON.parse(raw || "[]");
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}

function saveQueue(arr) {
  localStorage.setItem(QUEUE_KEY, JSON.stringify(arr || []));
}

function enqueueVisit(data) {
  const q = loadQueue();
  q.push({
    id: crypto?.randomUUID ? crypto.randomUUID() : String(Date.now()) + "_" + Math.random().toString(16).slice(2),
    created_at: new Date().toISOString(),
    data: data || {}
  });
  saveQueue(q);
  return q.length;
}

function dequeueById(id) {
  const q = loadQueue().filter(x => x.id !== id);
  saveQueue(q);
  return q;
}

function queueCount() {
  return loadQueue().length;
}

function pad2(n) { return String(n).padStart(2, "0"); }

function deviceNowText() {
  const d = new Date();
  return `${d.getFullYear()}-${pad2(d.getMonth()+1)}-${pad2(d.getDate())} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}

// ---------------- Offline Banner UI ----------------
function ensureBanner() {
  let el = document.getElementById("sg-status-banner");
  if (el) return el;

  el = document.createElement("div");
  el.id = "sg-status-banner";
  el.style.cssText =
    "position:fixed;top:0;left:0;right:0;z-index:9999;" +
    "padding:10px 12px;font-size:14px;color:#fff;" +
    "display:flex;gap:10px;align-items:center;justify-content:space-between;" +
    "box-shadow:0 10px 30px rgba(0,0,0,.2);";

  const left = document.createElement("div");
  left.id = "sg-status-left";

  const right = document.createElement("div");
  right.style.cssText = "display:flex;gap:8px;align-items:center;";

  const btn = document.createElement("button");
  btn.id = "sg-sync-btn";
  btn.textContent = "Συγχρονισμός τώρα";
  btn.style.cssText =
    "background:#fff;color:#111827;border:0;padding:8px 10px;border-radius:10px;cursor:pointer;display:none;";

  const close = document.createElement("button");
  close.textContent = "✕";
  close.style.cssText =
    "background:transparent;color:#fff;border:0;font-size:18px;line-height:1;cursor:pointer;opacity:.85;";
  close.onclick = () => {
    el.style.display = "none";
    document.body.style.paddingTop = "";
  };

  btn.onclick = async () => {
    btn.disabled = true;
    btn.textContent = "Συγχρονισμός...";
    try {
      await syncQueue();
    } finally {
      btn.disabled = false;
      btn.textContent = "Συγχρονισμός τώρα";
      refreshBanner();
    }
  };

  right.appendChild(btn);
  right.appendChild(close);
  el.appendChild(left);
  el.appendChild(right);
  document.body.appendChild(el);

  // push content down a bit
  document.body.style.paddingTop = "44px";
  return el;
}

function refreshBanner() {
  const el = ensureBanner();
  const left = document.getElementById("sg-status-left");
  const btn = document.getElementById("sg-sync-btn");
  const cnt = queueCount();

  if (!navigator.onLine) {
    el.style.background = "#dc3545";
    left.innerHTML = `⚠ Offline mode — Εκκρεμείς καταχωρήσεις: <b>${cnt}</b>`;
    btn.style.display = "none";
    el.style.display = "flex";
    document.body.style.paddingTop = "44px";
    return;
  }

  // online
  if (cnt > 0) {
    el.style.background = "#198754";
    left.innerHTML = `✅ Online — Εκκρεμείς καταχωρήσεις: <b>${cnt}</b>`;
    btn.style.display = "inline-block";
    el.style.display = "flex";
    document.body.style.paddingTop = "44px";
  } else {
    // hide banner when everything synced and online
    el.style.display = "none";
    document.body.style.paddingTop = "";
  }
}

// ---------------- Sync Logic ----------------
async function postNewVisit(data) {
  // Replay the same as submitting the normal form to /visits/new
  const params = new URLSearchParams();
  params.set("customer_name", data.customer_name || "");
  params.set("phone", data.phone || "");
  params.set("email", data.email || "");
  params.set("plate_number", data.plate_number || "");
  params.set("model", data.model || "");
  params.set("vin", data.vin || "");
  // some installs used notes, some notes_general - send both
  params.set("notes", data.notes || "");
  params.set("notes_general", data.notes || "");

  const res = await fetch("/visits/new", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" },
    body: params.toString(),
    redirect: "follow"
  });

  // FastAPI often returns 302 -> fetch follows it and ends with 200 HTML
  if (!res.ok) throw new Error("Failed POST /visits/new");
  return true;
}

async function syncQueue() {
  if (!navigator.onLine) return;

  const q = loadQueue();
  if (!q.length) return;

  // try sequentially to avoid server overload
  for (const item of q) {
    try {
      await postNewVisit(item.data || {});
      // remove from queue if success
      dequeueById(item.id);
    } catch (e) {
      // stop on first failure to avoid loops
      break;
    }
  }
}

// ---------------- Offline New Visit Form Hook ----------------
function hookOfflineNewVisitForm() {
  // This works for BOTH:
  // - the normal online /visits/new page (if someone is offline during submit)
  // - the offline SW page (it uses the same form id)
  const form = document.getElementById("sg-offline-new-visit-form");
  if (!form) return;

  const timeEl = document.getElementById("sg-device-time");
  if (timeEl) timeEl.textContent = deviceNowText();

  form.addEventListener("submit", async (e) => {
    if (navigator.onLine) return; // allow normal submit when online
    e.preventDefault();

    const data = {
      customer_name: (document.getElementById("customer_name")?.value || "").trim(),
      phone: (document.getElementById("phone")?.value || "").trim(),
      email: (document.getElementById("email")?.value || "").trim(),
      plate_number: (document.getElementById("plate_number")?.value || "").trim(),
      model: (document.getElementById("model")?.value || "").trim(),
      vin: (document.getElementById("vin")?.value || "").trim(),
      notes: (document.getElementById("notes")?.value || "").trim(),
      device_time: deviceNowText()
    };

    enqueueVisit(data);
    refreshBanner();

    // clear form
    ["customer_name","phone","email","plate_number","model","vin","notes"].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.value = "";
    });

    alert("✅ Αποθηκεύτηκε offline. Θα γίνει συγχρονισμός μόλις επανέλθει το internet.");
  });
}

// ---------------- Service Worker register ----------------
async function registerSW() {
  if (!("serviceWorker" in navigator)) return;
  try {
    await navigator.serviceWorker.register("/sw.js");
  } catch {}
}

// ---------------- Boot ----------------
window.addEventListener("online", async () => {
  refreshBanner();
  await syncQueue();
  refreshBanner();
});

window.addEventListener("offline", () => {
  refreshBanner();
});

window.addEventListener("load", async () => {
  await registerSW();
  refreshBanner();
  hookOfflineNewVisitForm();

  // If online and there is a queue -> auto sync once
  if (navigator.onLine && queueCount() > 0) {
    await syncQueue();
    refreshBanner();
  }
});

// Also re-hook when navigating inside cached pages
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) {
    refreshBanner();
    hookOfflineNewVisitForm();
  }
});
