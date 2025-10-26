// ===== Setup =====
const tg = window.Telegram?.WebApp; tg?.expand();

let PRICE_PER_GROUP = 25000;
let LOADED_GROUPS = [];

document.addEventListener('DOMContentLoaded', async () => {
  try {
    const r = await fetch('/api/config', { cache: 'no-store' });
    const cfg = await r.json();
    PRICE_PER_GROUP = parseInt(cfg?.price_idr ?? '25000', 10) || 25000;
    LOADED_GROUPS = Array.isArray(cfg?.groups) ? cfg.groups : [];
  } catch {}
  renderNeonList(LOADED_GROUPS);
  syncTotalText();
  document.getElementById('pay')?.addEventListener('click', onPay);
});

// ===== Render Neon List (no overflow) =====
function renderNeonList(groups) {
  const root = document.getElementById('list');
  root.innerHTML = '';

  (groups || []).forEach(g => {
    const id   = String(g.id);
    const name = String(g.name ?? id);
    const desc = String(g.desc ?? '').trim();
    const img  = String(g.image ?? '').trim();

    const card = document.createElement('article');
    card.className = 'card';
    card.dataset.id = id;

    const check = document.createElement('div');
    check.className = 'check';
    check.innerHTML = `<svg viewBox="0 0 24 24" width="16" height="16"><path fill="#fff" d="M9,16.2 4.8,12 3.4,13.4 9,19 21,7 19.6,5.6"/></svg>`;

    const thumb = document.createElement('div');
    thumb.className = 'thumb';
    if (img) thumb.style.backgroundImage = `url("${img}")`;

    const meta = document.createElement('div');
    meta.className = 'meta';

    const title = document.createElement('div');
    title.className = 'title';
    title.textContent = name;

    const p = document.createElement('div');
    p.className = 'desc';
    p.textContent = desc || 'Akses eksklusif grup pilihan.';

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn-outline';
    btn.textContent = 'Tambah ke Keranjang';

    // klik card = toggle select
    card.addEventListener('click', (e) => {
      // hindari double toggle saat klik tombol
      if (e.target === btn) return;
      card.classList.toggle('selected');
      syncTotalText();
      updateBadge();
    });
    btn.addEventListener('click', () => {
      card.classList.toggle('selected');
      syncTotalText();
      updateBadge();
    });

    meta.append(title, p, btn);
    card.append(check, thumb, meta);
    root.appendChild(card);
  });

  updateBadge();
}

function getSelectedIds(){
  return [...document.querySelectorAll('.card.selected')].map(el => el.dataset.id);
}

function updateBadge(){
  const n = getSelectedIds().length;
  const b = document.getElementById('cartBadge');
  if (n>0){ b.hidden = false; b.textContent = String(n); } else { b.hidden = true; }
}

// ===== Total & Checkout =====
function formatRupiah(n){ if(!Number.isFinite(n)) return "Rp 0";
  return "Rp " + n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, "."); }

function syncTotalText(){
  const total = getSelectedIds().length * PRICE_PER_GROUP;
  document.getElementById('total-text').textContent = formatRupiah(total);
  document.getElementById('pay')?.toggleAttribute('disabled', total <= 0);
}

function getUserId(){
  const fromInit = tg?.initDataUnsafe?.user?.id;
  if (fromInit) return fromInit;
  const qp = new URLSearchParams(window.location.search);
  const fromQuery = qp.get("uid");
  return fromQuery ? parseInt(fromQuery, 10) : null;
}

async function onPay(){
  const selected = getSelectedIds();
  const amount = selected.length * PRICE_PER_GROUP;
  if (!selected.length) return;

  const userId = getUserId();
  if (!userId) return showQRModal(`<div style="color:#f55">Gagal membaca user Telegram. Buka lewat tombol bot.</div>`);

  // Create invoice
  let inv;
  try{
    const res = await fetch(`${window.location.origin}/api/invoice`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ user_id:userId, groups:selected, amount })
    });
    if (!res.ok) throw new Error(await res.text());
    inv = await res.json();
  }catch(e){
    return showQRModal(`<div style="color:#f55">Create invoice gagal:<br><code>${escapeHtml(e.message||String(e))}</code></div>`);
  }

  // QR
  const qrPngUrl = `${window.location.origin}/api/qr/${inv.invoice_id}.png?amount=${amount}&t=${Date.now()}`;
  showQRModal(`
    <div><b>Pembayaran GoPay</b></div>
    <div style="margin:8px 0 12px; opacity:.85">QRIS sedang dimuat…</div>
    <img alt="QR" src="${qrPngUrl}">
    <button class="close" id="closeModal">Tutup</button>
  `);
  document.getElementById('closeModal')?.addEventListener('click', hideQRModal);

  // Poll status
  const statusUrl = `${window.location.origin}/api/invoice/${inv.invoice_id}/status`;
  let t = setInterval(async ()=>{
    try{
      const r = await fetch(statusUrl); if(!r.ok) return;
      const s = await r.json();
      if (s.status === "PAID"){ clearInterval(t); hideQRModal(); tg?.close?.(); }
    }catch{}
  }, 2000);
}

// ===== Modal helpers =====
function showQRModal(html){ const m = document.getElementById('qr'); m.innerHTML = `<div>${html}</div>`; m.hidden = false; }
function hideQRModal(){ const m = document.getElementById('qr'); m.hidden = true; m.innerHTML=''; }
function escapeHtml(s){ return String(s).replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;','\'':'&#39;'}[c])); }
