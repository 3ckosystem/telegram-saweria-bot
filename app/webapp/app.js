// ============ Config + Telegram ============
const tg = window.Telegram?.WebApp; tg?.expand();
let PRICE_PER_GROUP = 25000;
let LOADED_GROUPS = [];

document.addEventListener('DOMContentLoaded', init);

async function init(){
  try{
    const r = await fetch('/api/config');
    const cfg = await r.json();
    PRICE_PER_GROUP = parseInt(cfg?.price_idr ?? '25000', 10) || 25000;
    LOADED_GROUPS = Array.isArray(cfg?.groups) ? cfg.groups : [];
  }catch{}
  renderList(LOADED_GROUPS);
  syncTotalText();
  document.getElementById('pay')?.addEventListener('click', onPay);
}

// ============ Render Neon List ============
function renderList(groups){
  const list = document.getElementById('list');
  list.innerHTML = '';

  groups.forEach(g=>{
    const id = String(g.id);
    const name = String(g.name ?? id);
    const image = String(g.image ?? '').trim();
    const emoji = String(g.emoji ?? '🔥'); // fallback icon

    const card = document.createElement('article');
    card.className = 'card';
    card.dataset.id = id;

    const row = document.createElement('div'); row.className = 'row';

    const thumb = document.createElement('div'); thumb.className = 'thumb';
    if (image){
      const im = document.createElement('img'); im.src = image; im.alt = '';
      thumb.appendChild(im);
    }else{
      thumb.innerHTML = `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true">
        <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
          <stop stop-color="#ff3a54"/><stop offset="1" stop-color="#d60d2d"/></linearGradient></defs>
        <circle cx="12" cy="12" r="10" fill="url(#g)"/>
        <text x="12" y="16" text-anchor="middle" font-size="10" fill="#000" font-weight="700">${emoji}</text>
      </svg>`;
    }

    const content = document.createElement('div');
    const title = document.createElement('div'); title.className = 'title'; title.textContent = name;

    const btn = document.createElement('button'); btn.className = 'btn'; btn.textContent = 'Tambah ke Keranjang';

    btn.addEventListener('click', (e)=>{
      e.stopPropagation();
      card.classList.toggle('selected');
      btn.textContent = card.classList.contains('selected') ? 'Hapus dari Keranjang' : 'Tambah ke Keranjang';
      syncTotalText();
    });

    card.addEventListener('click', ()=>{
      card.classList.toggle('selected');
      btn.textContent = card.classList.contains('selected') ? 'Hapus dari Keranjang' : 'Tambah ke Keranjang';
      syncTotalText();
    });

    content.appendChild(title);
    content.appendChild(btn);
    row.appendChild(thumb);
    row.appendChild(content);
    card.appendChild(row);
    list.appendChild(card);
  });
}

function getSelectedGroupIds(){
  return [...document.querySelectorAll('.card.selected')].map(el => el.dataset.id);
}

function formatRupiah(n){
  if(!Number.isFinite(n)) return "Rp 0";
  return "Rp " + n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
}
function syncTotalText(){
  const count = getSelectedGroupIds().length;
  const total = count * PRICE_PER_GROUP;
  document.getElementById('total-text').textContent = formatRupiah(total);
  document.getElementById('pay')?.toggleAttribute('disabled', total <= 0);
}

// ============ Checkout & QR ============
function getUserId(){
  const fromInit = tg?.initDataUnsafe?.user?.id;
  if (fromInit) return fromInit;
  const qp = new URLSearchParams(window.location.search);
  const fromQuery = qp.get("uid");
  return fromQuery ? parseInt(fromQuery, 10) : null;
}

async function onPay(){
  const selected = getSelectedGroupIds();
  const amount = selected.length * PRICE_PER_GROUP;
  if (!selected.length) return;

  const userId = getUserId();
  if (!userId) return showQRModal(`<div style="color:#f55">Gagal membaca user Telegram. Buka lewat tombol bot.</div>`);

  // 1) buat invoice
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

  // 2) tampilkan QR
  const ref = `INV:${inv.invoice_id}`;
  const qrPngUrl = `${window.location.origin}/api/qr/${inv.invoice_id}.png?amount=${amount}&t=${Date.now()}`;
  showQRModal(`
    <div><b>Pembayaran GoPay</b></div>
    <div id="qruistate" style="margin:8px 0 12px; opacity:.85">QRIS sedang dimuat…</div>
    <img id="qrimg" alt="QR" src="${qrPngUrl}">
    <div style="margin-top:10px"><b>Kode:</b> <code>${escapeHtml(ref)}</code></div>
    <button class="close" id="closeModal">Tutup</button>
  `);
  document.getElementById('closeModal')?.addEventListener('click', hideQRModal);

  // 3) polling status → auto-close
  const statusUrl = `${window.location.origin}/api/invoice/${inv.invoice_id}/status`;
  let t = setInterval(async ()=>{
    try{
      const r = await fetch(statusUrl); if(!r.ok) return;
      const s = await r.json();
      if (s.status === "PAID"){
        clearInterval(t);
        hideQRModal();
        tg?.close?.();
      }
    }catch{}
  }, 2000);
}

// ============ Modal helpers ============
function showQRModal(html){
  const m = document.getElementById('qr'); m.innerHTML = `<div>${html}</div>`; m.hidden = false;
}
function hideQRModal(){ const m = document.getElementById('qr'); m.hidden = true; m.innerHTML=''; }
function escapeHtml(s){ return String(s).replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;','\'':'&#39;'}[c])); }
