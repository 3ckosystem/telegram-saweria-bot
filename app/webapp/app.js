// Mini App: uniform price & groups dari Railway (via /api/config)
const tg = window.Telegram?.WebApp; tg?.expand?.();
const API_BASE = (window.API_BASE ?? "").replace(/\/+$/,""); // set di index.html jika beda origin

const state = {
  price_idr: 0,
  groups: [], // {id,label}
  cart: new Set(),
};

const $   = s => document.querySelector(s);
const idr = n => (n||0).toLocaleString("id-ID");
const esc = s => String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const buildUrl = p => (API_BASE ? `${API_BASE}${p}` : p);

function getUserId(){
  const fromInit = tg?.initDataUnsafe?.user?.id;
  if (fromInit) return fromInit;
  const v = new URLSearchParams(location.search).get("uid");
  return v ? parseInt(v,10) : null; // untuk dev di browser
}

function total(){ return state.price_idr * state.cart.size; }

function updateBar(){
  $("#count").textContent = String(state.cart.size);
  $("#total").textContent = idr(total());
  $("#checkout").disabled = state.cart.size === 0;
}

function renderList(){
  const box = $("#list"); box.innerHTML = "";
  state.groups.forEach(g=>{
    const chosen = state.cart.has(g.id);
    const wrap = document.createElement("div");
    wrap.className = "card";
    wrap.innerHTML = `
      <div style="flex:1">
        <div class="title">${esc(g.label || g.id)}</div>
        <div class="muted">${g.id}</div>
      </div>
      <div class="price">Rp ${idr(state.price_idr)}</div>
      <div class="actions">
        <button class="${chosen ? "danger" : "primary"} btn-toggle" data-id="${g.id}">
          ${chosen ? "Hapus" : "Tambah ke Keranjang"}
        </button>
      </div>
    `;
    box.appendChild(wrap);
  });

  document.querySelectorAll(".btn-toggle").forEach(btn=>{
    btn.addEventListener("click", e=>{
      const gid = e.currentTarget.getAttribute("data-id");
      if (!gid) return;
      if (state.cart.has(gid)) state.cart.delete(gid); else state.cart.add(gid);
      updateBar(); renderList();
    });
  });
}

function showSection(id){
  ["list","confirm","payview"].forEach(sec=>{
    const el = document.getElementById(sec);
    if (el) el.style.display = (sec===id ? "block" : "none");
  });
}

function toast(msg){ console.error(msg); alert(msg); }

async function loadConfig(){
  const r = await fetch(buildUrl("/api/config"));
  if (!r.ok){
    const t = await r.text().catch(()=> "");
    throw new Error(`/api/config error (${r.status}) ${t}`);
  }
  const data = await r.json();
  state.price_idr = Number(data?.price_idr || 0);
  state.groups   = Array.isArray(data?.groups) ? data.groups : [];
  if (!state.price_idr || !state.groups.length){
    throw new Error("Config tidak valid: price atau groups kosong");
  }
}

async function checkout(){
  const chosen = Array.from(state.cart);
  if (!chosen.length) return;
  const itemsHtml = chosen.map(gid=>{
    const g = state.groups.find(x=>x.id===gid);
    return `<li>${esc(g?.label||gid)} — Rp ${idr(state.price_idr)}</li>`;
  }).join("");
  $("#confirm-items").innerHTML = `<ol class="list-compact">${itemsHtml}</ol>`;
  $("#confirm-total").textContent = "Total: Rp " + idr(total());
  showSection("confirm");
}

async function createInvoiceAndPay(){
  const uid = getUserId();
  if (!uid) return toast("User ID tidak terbaca. Buka dari Telegram atau pakai ?uid=123 saat uji coba.");
  const groups = Array.from(state.cart);

  try{
    const res = await fetch(buildUrl("/api/invoice"), {
      method: "POST",
      headers: { "Content-Type":"application/json" },
      body: JSON.stringify({ user_id: uid, groups }) // amount dihitung di server
    });
    if (!res.ok){
      const txt = await res.text().catch(()=> "");
      throw new Error(`Gagal membuat invoice (${res.status}). ${txt || ""}`);
    }
    const data = await res.json();
    const invoiceId = data?.invoice_id;
    if (!invoiceId) throw new Error("invoice_id tidak ada di respons server");

    $("#inv-id").textContent = invoiceId;
    $("#inv-amt").textContent = "Rp " + idr(total());
    showSection("payview");

    const img = document.createElement("img");
    img.alt = "QRIS";
    img.src = buildUrl(`/api/qr/${invoiceId}.png`);
    const qr = $("#qr"); qr.innerHTML = ""; qr.appendChild(img);

    pollUntilPaid(invoiceId);
  }catch(e){ toast("Error: " + (e?.message || e)); }
}

async function pollUntilPaid(invoiceId){
  let tries=0, maxTries=120;
  $("#btn-done").onclick = () => checkOnce();
  async function checkOnce(){
    try{
      const r = await fetch(buildUrl(`/api/invoice/${invoiceId}/status`));
      if (!r.ok) return;
      const s = await r.json();
      if ((s?.status||"").toUpperCase() === "PAID") tg?.close?.();
    }catch{}
  }
  const timer = setInterval(async ()=>{
    tries++; await checkOnce();
    if (tries>=maxTries) clearInterval(timer);
  }, 2500);
}

async function boot(){
  try { await loadConfig(); }
  catch(e){ return toast(e.message || e); }
  renderList(); updateBar(); showSection("list");
  $("#checkout").addEventListener("click", checkout);
  $("#btn-back").addEventListener("click", ()=> showSection("list"));
  $("#btn-pay").addEventListener("click", createInvoiceAndPay);
}
document.addEventListener("DOMContentLoaded", boot);
