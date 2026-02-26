// Stefanos Garage Update System (no TEST)

async function registerSW() {
  if (!("serviceWorker" in navigator)) return;

  try {
    const registration = await navigator.serviceWorker.register("/static/sw.js?v=dev4");

    // Αν υπάρχει ήδη νέα έκδοση έτοιμη (waiting)
    if (registration.waiting && navigator.serviceWorker.controller) {
      showUpdateBanner(registration);
    }

    // Αν βρεθεί νέα έκδοση
    registration.addEventListener("updatefound", () => {
      const newWorker = registration.installing;
      if (!newWorker) return;

      newWorker.addEventListener("statechange", () => {
        if (newWorker.state === "installed" && navigator.serviceWorker.controller) {
          showUpdateBanner(registration);
        }
      });
    });

    // περιοδικό update check
    setInterval(() => registration.update().catch(() => {}), 60000);
  } catch (e) {
    console.log("SW registration failed:", e);
  }
}

function showUpdateBanner(registration) {
  if (document.getElementById("update-banner")) return;

  const banner = document.createElement("div");
  banner.id = "update-banner";
  banner.style.cssText =
    "position:fixed;bottom:15px;left:15px;right:15px;" +
    "background:#198754;color:#fff;padding:14px 16px;" +
    "border-radius:12px;display:flex;justify-content:space-between;" +
    "align-items:center;font-size:14px;z-index:9999;" +
    "box-shadow:0 8px 20px rgba(0,0,0,0.25);";

  banner.innerHTML = `
    <div>Υπάρχει νέα έκδοση — Ανανεώστε</div>
    <button id="update-now"
      style="background:#fff;color:#198754;border:none;
      padding:8px 14px;border-radius:8px;font-weight:600;cursor:pointer;">
      Ανανεώστε
    </button>
  `;

  document.body.appendChild(banner);

  document.getElementById("update-now").onclick = () => {
    if (registration.waiting) {
      registration.waiting.postMessage({ type: "SKIP_WAITING" });
    } else {
      // fallback
      window.location.reload();
    }
  };
}

// όταν αλλάξει controller → refresh
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    window.location.reload();
  });
}

registerSW();
