(function () {
  const elId = "update-banner";
  if (document.getElementById(elId)) return;

  const el = document.createElement("div");
  el.id = elId;
  el.style.cssText =
    "position:fixed;bottom:12px;left:12px;right:12px;z-index:9999;" +
    "background:#198754;color:#fff;padding:12px 14px;border-radius:12px;" +
    "display:flex;gap:12px;align-items:center;justify-content:space-between;" +
    "box-shadow:0 10px 30px rgba(0,0,0,.2);font-size:14px;";

  el.innerHTML = `
    <div>TEST: Το app.js (dev3) φορτώθηκε ✅</div>
    <button id="close-btn" style="background:#fff;color:#198754;border:0;padding:8px 12px;border-radius:10px;cursor:pointer;">
      OK
    </button>
  `;

  document.body.appendChild(el);
  document.getElementById("close-btn").onclick = () => el.remove();
})();
