async function registerSW() {
  if (!("serviceWorker" in navigator)) return;

  try {
    const reg = await navigator.serviceWorker.register("/static/sw.js");

    // Όταν βρεθεί νέα έκδοση → banner
    reg.addEventListener("updatefound", () => {
      const newWorker = reg.installing;
      if (!newWorker) return;

      newWorker.addEventListener("statechange", () => {
        if (newWorker.state === "installed" && navigator.serviceWorker.controller) {
          showUpdateBanner();
        }
      });
    });

    // Προαιρετικό: check για update κάθε 60s
    setInterval(() => reg.update().catch(() => {}), 60000);
  } catch (e) {
    // αν αποτύχει, δεν χαλάει τίποτα
  }
}

function showUpdateBanner() {
  if (document.getElementById("update-banner")) return;

  const el = document.createElement("div");
  el.id = "update-banner";
  el.style.cssText =
    "position:fixed;bottom:12px;left:12px;right:12px;z-index:9999;" +
    "background:#111827;color:#fff;padding:12px 14px;border-radius:12px;" +
    "display:flex;gap:12px;align-items:center;justify-content:space-between;" +
    "box-shadow:0 10px 30px rgba(0,0,0,.2);font-size:14px;";

  el.innerHTML = `
    <div>Υπάρχει νέα έκδοση — Ανανεώστε</div>
    <button id="update-btn" style="background:#fff;color:#111827;border:0;padding:8px 12px;border-radius:10px;cursor:pointer;">
      Ανανεώστε
    </button>
  `;

  document.body.appendChild(el);

  document.getElementById("update-btn").onclick = () => {
    // reload ώστε να πάρει τη νέα έκδοση
    window.location.reload();
  };
}

registerSW();
