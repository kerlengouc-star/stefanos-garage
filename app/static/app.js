async function registerSW() {
  if (!("serviceWorker" in navigator)) return;

  try {
    const reg = await navigator.serviceWorker.register("/static/sw.js");

    if (reg.waiting && navigator.serviceWorker.controller) {
      showUpdateBanner(reg);
    }

    reg.addEventListener("updatefound", () => {
      const w = reg.installing;
      if (!w) return;

      w.addEventListener("statechange", () => {
        if (w.state === "installed" && navigator.serviceWorker.controller) {
          showUpdateBanner(reg);
        }
      });
    });

    setInterval(() => reg.update().catch(() => {}), 60000);
  } catch (e) {}
}

function showUpdateBanner(reg) {
  if (document.getElementById("update-banner")) return;

  const el = document.createElement("div");
  el.id = "update-banner";
  el.style.cssText =
    "position:fixed;bottom:12px;left:12px;right:12px;z-index:9999;" +
    "background:#198754;color:#fff;padding:12px 14px;border-radius:12px;" +
    "display:flex;gap:12px;align-items:center;justify-content:space-between;" +
    "box-shadow:0 10px 30px rgba(0,0,0,.2);font-size:14px;";

  el.innerHTML = `
    <div>Υπάρχει νέα έκδοση — Ανανεώστε</div>
    <button id="update-btn" style="background:#fff;color:#198754;border:0;padding:8px 12px;border-radius:10px;cursor:pointer;">
      Ανανεώστε
    </button>
  `;

  document.body.appendChild(el);

  document.getElementById("update-btn").onclick = () => {
    if (reg && reg.waiting) reg.waiting.postMessage({ type: "SKIP_WAITING" });
    window.location.reload();
  };
}

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (window.__reloaded_for_sw) return;
    window.__reloaded_for_sw = true;
    window.location.reload();
  });
}

registerSW();
