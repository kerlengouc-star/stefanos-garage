// Stefanos Garage - Offline Queue + Sync (STABLE)
// Offline: /visits/new shows offline form. Submit → store locally (queue).
// Online: Banner shows "Sync now" and uploads queued visits via POST /visits/new.

const QUEUE_KEY = "sg_offline_visits_queue_v2";

function loadQueue() {
  try { return JSON.parse(localStorage.getItem(QUEUE_KEY) || "[]") || []; }
  catch { return []; }
}

function saveQueue(q) {
  localStorage.setItem(QUEUE_KEY, JSON.stringify(q || []));
}

function enqueue(data) {
  const q = loadQueue();
  q.push({ id: Date.now() + "_" + Math.random().toString(16).slice(2), created_at: new Date().toISOString(), data });
  saveQueue(q);
  return q.length;
}

function dequeueFirst() {
  const q = loadQueue();
  const item = q.shift();
  saveQueue(q);
  return item;
}

function queueCount() { return loadQueue().length; }

function pad2(n){ return String(n).padStart(2,"0"); }
function deviceNowText(){
  const d=new Date();
  return `${d.getFullYear()}-${pad2(d.getMonth()+1)}-${pad2(d.getDate())} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}

// ---------- Banner ----------
function ensureBanner(){
  let el=document.getElementById("sg-status");
  if(el) return el;

  el=document.createElement("div");
  el.id="sg-status";
  el.style.cssText="position:fixed;top:0;left:0;right:0;z-index:9999;padding:10px 12px;font-size:14px;color:#fff;display:flex;justify-content:space-between;align-items:center;box-shadow:0 10px 30px rgba(0,0,0,.2);";
  const left=document.createElement("div"); left.id="sg-status-left";
  const right=document.createElement("div"); right.style.cssText="display:flex;gap:8px;align-items:center;";

  const btn=document.createElement("button");
  btn.id="sg-sync";
  btn.textContent="Συγχρονισμός τώρα";
  btn.style.cssText="background:#fff;color:#111827;border:0;padding:8px 10px;border-radius:10px;cursor:pointer;display:none;";
  btn.onclick=async()=>{ btn.disabled=true; btn.textContent="Συγχρονισμός..."; await syncQueue(); btn.disabled=false; btn.textContent="Συγχρονισμός τώρα"; refreshBanner(); };

  const close=document.createElement("button");
  close.textContent="✕";
  close.style.cssText="background:transparent;color:#fff;border:0;font-size:18px;cursor:pointer;opacity:.85;";
  close.onclick=()=>{ el.style.display="none"; document.body.style.paddingTop=""; };

  right.appendChild(btn); right.appendChild(close);
  el.appendChild(left); el.appendChild(right);
  document.body.appendChild(el);
  document.body.style.paddingTop="44px";
  return el;
}

function refreshBanner(){
  const el=ensureBanner();
  const left=document.getElementById("sg-status-left");
  const btn=document.getElementById("sg-sync");
  const cnt=queueCount();

  if(!navigator.onLine){
    el.style.background="#dc3545";
    left.innerHTML=`⚠ Offline — Εκκρεμείς: <b>${cnt}</b>`;
    btn.style.display="none";
    el.style.display="flex";
    document.body.style.paddingTop="44px";
    return;
  }

  if(cnt>0){
    el.style.background="#198754";
    left.innerHTML=`✅ Online — Εκκρεμείς: <b>${cnt}</b>`;
    btn.style.display="inline-block";
    el.style.display="flex";
    document.body.style.paddingTop="44px";
  } else {
    el.style.display="none";
    document.body.style.paddingTop="";
  }
}

// ---------- Sync ----------
async function postNewVisit(data){
  const params=new URLSearchParams();
  params.set("customer_name", data.customer_name || "");
  params.set("phone", data.phone || "");
  params.set("email", data.email || "");
  params.set("plate_number", data.plate_number || "");
  params.set("model", data.model || "");
  params.set("vin", data.vin || "");
  params.set("notes", data.notes || "");
  params.set("notes_general", data.notes || "");

  const res = await fetch("/visits/new", {
    method:"POST",
    headers:{ "Content-Type":"application/x-www-form-urlencoded;charset=UTF-8" },
    body: params.toString(),
    redirect:"follow"
  });
  if(!res.ok) throw new Error("POST /visits/new failed");
}

async function syncQueue(){
  if(!navigator.onLine) return;
  // sequential
  while(queueCount()>0){
    const item = dequeueFirst();
    if(!item) break;
    try{
      await postNewVisit(item.data || {});
    }catch(e){
      // put it back and stop
      const q = loadQueue();
      q.unshift(item);
      saveQueue(q);
      break;
    }
  }
}

// ---------- Offline form hook ----------
function hookOfflineForm(){
  const form=document.getElementById("sg-offline-new-visit-form");
  if(!form) return;

  const t=document.getElementById("sg-device-time");
  if(t) t.textContent=deviceNowText();

  form.addEventListener("submit",(e)=>{
    if(navigator.onLine) return; // if online, allow normal (but this page is offline anyway)
    e.preventDefault();

    const data={
      customer_name:(document.getElementById("customer_name")?.value||"").trim(),
      phone:(document.getElementById("phone")?.value||"").trim(),
      email:(document.getElementById("email")?.value||"").trim(),
      plate_number:(document.getElementById("plate_number")?.value||"").trim(),
      model:(document.getElementById("model")?.value||"").trim(),
      vin:(document.getElementById("vin")?.value||"").trim(),
      notes:(document.getElementById("notes")?.value||"").trim(),
      device_time: deviceNowText()
    };

    enqueue(data);
    refreshBanner();

    ["customer_name","phone","email","plate_number","model","vin","notes"].forEach(id=>{
      const el=document.getElementById(id); if(el) el.value="";
    });

    alert("✅ Αποθηκεύτηκε offline. Όταν επανέλθει internet, πάτα “Συγχρονισμός τώρα”.");
  });
}

// ---------- SW register ----------
async function registerSW(){
  if(!("serviceWorker" in navigator)) return;
  try{ await navigator.serviceWorker.register("/sw.js"); }catch{}
}

window.addEventListener("online", async ()=>{
  refreshBanner();
  await syncQueue();
  refreshBanner();
});

window.addEventListener("offline", refreshBanner);

window.addEventListener("load", async ()=>{
  await registerSW();
  refreshBanner();
  hookOfflineForm();

  if(navigator.onLine && queueCount()>0){
    await syncQueue();
    refreshBanner();
  }
});

document.addEventListener("visibilitychange", ()=>{
  if(!document.hidden){
    refreshBanner();
    hookOfflineForm();
  }
});
