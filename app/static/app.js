// Update banner + TEST banner

function showBanner(text, color) {
  if (document.getElementById("update-banner")) return;

  const el = document.createElement("div");
  el.id = "update-banner";
  el.style.cssText =
    "position:fixed;bottom:12px;left:12px;right:12px;z-index:9999;" +
    `background:${color};color:#fff;padding:12px 14px;border-radius:12px;` +
    "display:flex;gap:12px;align-items:center;justify-content:space-between;" +
    "box-shadow:0 10px 30px rgba(0,0,0,.2);font-size:14px;";

  el.innerHTML = `
    <div>${text}</div>
    <div style="display:flex;gap:8px;">
      <button id="reload-btn" style="background:#fff;color:#111827;border:0;padding:8px 12px;border-radius:10px;cursor:pointer;">Ανανεώστε</button>
      <button id="close-btn" style="background:transparent;color:#fff;border:1px solid rgba(255,255,255,.35);padding:8px 12px;border-radius:10px;cursor:pointer;">Κλείσιμο</button>
    </div>
  `;

  document.body.appendChild(el);
  document.getElementById("reload-btn").onclick = () => window.location.reload();
  document.getElementById("close-btn").onclick = () => el.remove();
}

async function registerSW() {
  if (!("serviceWorker" in navigator)) return;

  try {
    const reg = await navigator.serviceWorker.register("/static/sw.js");

    // If a new SW is installed while a controller exists => update available.
    reg.addEventListener("updatefound", () => {
      const nw = reg.installing;
      if (!nw) return;
      nw.addEventListener("statechange", () => {
        if (nw.state === "installed" && navigator.serviceWorker.controller) {
          showBanner("Υπάρχει νέα έκδοση — Ανανεώστε", "#111827");
        }
      });
    });

    // Periodic check
    setInterval(() => reg.update().catch(() => {}), 60000);
  } catch (e) {
    // ignore
  }
}

window.addEventListener("load", () => {
  // TEST: show for 8 seconds
  showBanner("TEST: Το banner λειτουργεί σωστά ✅", "#198754");
  setTimeout(() => {
    const el = document.getElementById("update-banner");
    if (el) el.remove();
  }, 8000);

  registerSW();
});
