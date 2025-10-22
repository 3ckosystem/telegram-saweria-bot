// app/webapp/app.js
const tg = window.Telegram?.WebApp; tg?.expand?.();

const API_BASE = (window.API_BASE ?? "").replace(/\/+$/,""); // optional
const state = { price_idr: 0, groups: [], cart: new Set() };

function $(s){ return document.querySelector(s); }
function idr(n){ return (n||0).toLocaleString("id-ID"); }
function buildUrl(p){ return API_BASE ? `${API_BASE}${p}` : p; }

function getUserId(){
  const fromInit = tg?.initDataUnsafe?.user?.id;
  if (fromInit) return fromInit;
  const q = new URLSearchParams(location.search);
  const v = q.get("uid");
  return v ? parseInt(v,10) : null;
}

function escapeHtml(s){ return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

function total(){ return state.price_idr * state.cart.size; }

function renderList(){
  const box = $("#list"); box.innerHTML = "";
  state.groups.forEach(g=>{
    const chosen = state.cart.has(g.id);
    const el = document.createElement("div");
    el.className = "card";
    el.innerHTML = `
      <div style="flex:1">
        <div class="title">${escapeHtml(g.label || g.id)}</div>
        <div class="muted">${g.id}</div>
      </div>
      <div class="price">Rp ${idr(state.price_idr)}</div>
      <div class="actions">
        <button class="${chosen?"danger":"primary"} btn-toggle" data-id="${g.id}">
          ${chosen?"Hapus":"Tambah ke Keranjang"}
        </button>
      </div>
    `;
    box.appendChild(el);
  });
  document.querySelectorAll(".btn-toggle").forEach(btn=>{
    btn.onclick = e=>{
      const gid = e.currentTarget.dataset.id;
      if (state.cart.has(gid)) state.cart.delete(gid); else state.cart.add(gid);
      updateBar(); renderList();
    };
  });
}

function updateBar(){
  $("#count").textContent = state.cart.size;
  $("#total").textContent = idr(total());
  $("#checkout").disabled = state.cart.size===0;
}

function showSection(id){
  ["list","confirm","payview"].forEach(s=>{
    const el = document.getElementById(s);
    if (el) el.style.display = (s===id?"block":"none");
  });
}

async function loadConfig(){
  const r = await fetch(buildUrl("/api/config"));
  const data = await r.json();
  state.price_idr = data.price_idr;
  state.groups = data.groups;
}

async function checkout(){
  const chosen = Array.from(state.cart);
  const items = chosen.map(gid=>{
    const g = state.groups.find(x=>x.id===gid);
    return `<li>${escapeHtml(g?.label||gid)} — Rp ${idr(state.price_idr)}</li>`;
  }).join("");
  $("#confirm-items").innerHTML = `<ol>${items}</ol>`;
  $("#confirm-total").textContent = "Total: Rp " + idr(total());
  showSection("confirm");
}

async function createInvoiceAndPay(){
  const uid = getUserId();
  if (!uid) return alert("User ID tidak terbaca. Buka Mini App dari Telegram.");
  const groups = Array.from(state.cart);
  const res = await fetch(buildUrl("/api/invoice"), {
    method: "POST", headers: { "Content-Type":"application/json" },
    body: JSON.stringify({ user_id: uid, groups })
  });
  if (!res.ok){
    const txt = await res.text(); throw new Error(`Gagal membuat invoice: ${txt}`);
  }
  const data = await res.json();
  $("#inv-id").textContent = data.invoice_id;
  $("#inv-amt").textContent = "Rp " + idr(data.amount);
  showSection("payview");
  const img = document.createElement("img");
  img.src = buildUrl(`/api/qr/${data.invoice_id}.png`);
  $("#qr").innerHTML = ""; $("#qr").appendChild(img);
  pollUntilPaid(data.invoice_id);
}

async function pollUntilPaid(invoiceId){
  let tries=0; const maxTries=120;
  const check = async ()=>{
    const r = await fetch(buildUrl(`/api/invoice/${invoiceId}/status`));
    const s = await r.json();
    if ((s.status||"").toUpperCase()==="PAID") tg?.close?.();
  };
  $("#btn-done").onclick = check;
  const timer=setInterval(async()=>{
    tries++; await check();
    if (tries>=maxTries) clearInterval(timer);
  },2500);
}

async function boot(){
  await loadConfig();
  renderList(); updateBar(); showSection("list");
  $("#checkout").onclick = checkout;
  $("#btn-back").onclick = ()=> showSection("list");
  $("#btn-pay").onclick = createInvoiceAndPay;
}
document.addEventListener("DOMContentLoaded", boot);
