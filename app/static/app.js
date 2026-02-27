// ===============================
// Stefanos Garage Offline System
// ===============================

const OFFLINE_QUEUE_KEY = "garage-offline-queue";

// --------------------------------
// Service Worker registration
// --------------------------------
async function registerSW() {
  if (!("serviceWorker" in navigator)) return;

  try {
    await navigator.serviceWorker.register("/static/sw.js");
  } catch (e) {}
}

registerSW();

// --------------------------------
// Offline Queue Logic
// --------------------------------
function getQueue() {
  try {
    return JSON.parse(localStorage.getItem(OFFLINE_QUEUE_KEY)) || [];
  } catch {
    return [];
  }
}

function saveQueue(queue) {
  localStorage.setItem(OFFLINE_QUEUE_KEY, JSON.stringify(queue));
}

function addToQueue(payload) {
  const queue = getQueue();
  queue.push(payload);
  saveQueue(queue);
}

async function syncQueue() {
  if (!navigator.onLine) return;

  const queue = getQueue();
  if (!queue.length) return;

  for (const item of queue) {
    try {
      await fetch(item.url, {
        method: item.method,
        body: item.body,
        headers: { "Content-Type": "application/x-www-form-urlencoded" }
      });
    } catch (e) {
      return; // αν αποτύχει, σταματά
    }
  }

  localStorage.removeItem(OFFLINE_QUEUE_KEY);
  showToast("Offline δεδομένα συγχρονίστηκαν ✅");
}

window.addEventListener("online", syncQueue);
window.addEventListener("load", syncQueue);

// --------------------------------
// Toast message
// --------------------------------
function showToast(msg) {
  const el = document.createElement("div");
  el.style.position = "fixed";
  el.style.bottom = "20px";
  el.style.left = "20px";
  el.style.background = "#198754";
  el.style.color = "#fff";
  el.style.padding = "10px 14px";
  el.style.borderRadius = "10px";
  el.style.zIndex = "9999";
  el.innerText = msg;
  document.body.appendChild(el);

  setTimeout(() => el.remove(), 3000);
}

// --------------------------------
// Intercept visit form submit
// --------------------------------
document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("visit-form");
  if (!form) return;

  form.addEventListener("submit", async (e) => {
    if (navigator.onLine) return;

    e.preventDefault();

    const formData = new FormData(form);
    const params = new URLSearchParams();
    for (const pair of formData.entries()) {
      params.append(pair[0], pair[1]);
    }

    addToQueue({
      url: form.action,
      method: form.method || "POST",
      body: params.toString()
    });

    showToast("Αποθηκεύτηκε offline 📦");
  });
});
