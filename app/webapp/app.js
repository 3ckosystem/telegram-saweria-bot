// app/webapp/app.js
const tg = window.Telegram?.WebApp; 
tg?.expand();

let PRICE_PER_GROUP = 25000;
let LOADED_GROUPS = [];

// ====== Config truncate ======
const MAX_DESC_CHARS = 120; // ubah sesuai kebutuhan

// Truncate aman emoji + potong di batas kata
function truncateText(text, max = MAX_DESC_CHARS) {
  if (!text) return "";
  try {
    const seg = new Intl.Segmenter('id', { granularity: 'grapheme' });
    const graphemes = Array.from(seg.segment(text), s => s.segment);
    if (graphemes.length <= max) return text;
    const partial = graphemes.slice(0, max).join('');
    const lastSpace = partial.lastIndexOf(' ');
    const safe = lastSpace > 40 ? partial.slice(0, lastSpace) : partial;
    return safe.replace(/[.,;:!\s]*$/,'') + '…';
  } catch {
    // Fallback sederhana
    if (text.length <= max) return text;
    let t = text.slice(0, max);
    const lastSpace = t.lastIndexOf(' ');
    if (lastSpace > 40) t = t.slice(0, lastSpace);
    return t.replace(/[.,;:!\s]*$/,'') + '…';
  }
}

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

function renderNeonList(groups) {
  const root = document.getElementById('list');
  root.innerHTML = '';

  (groups || []).forEach(g => {
    const id   = String(g.id);
    const name = String(g.name ?? id);
    const desc = String(g.desc ?? '').trim();
    const longDesc = String(g.long_desc ?? desc).trim();
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
    // ===== truncate untuk tampilan kartu =====
    p.textContent = truncateText(desc || 'Akses eksklusif grup pilihan.');

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn-outline';
    btn.textContent = 'Pilih Grup';

    // === BEHAVIOR ===
    // 1) Klik tombol: toggle select (HANYA tombol)
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      toggleSelect(card);
    });

    // 2) Klik area kartu selain tombol: buka modal dengan deskripsi FULL
    card.addEventListener('click', (e) => {
      if (btn.contains(e.target)) return; // safety
      openDetailModal({ id, name, desc: longDesc || desc, image: img });
    });

    meta.append(title, p, btn);
    card.append(check, thumb, meta);
    root.appendChild(card);

    // set label awal sesuai state
    updateButtonState(card, btn);
  });

  updateBadge();
}

function toggleSelect(card){
  card.classList.toggle('selected');
  const btn = card.querySelector('.btn-outline');
  if (btn) updateButtonState(card, btn);
  syncTotalText(); 
  updateBadge();
}

function updateButtonState(card, btn){
  const selected = card.classList.contains('selected');
  btn.textContent = selected ? 'Batal' : 'Pilih Grup';
}

function openDetailModal(item){
  const m = document.getElementById('detail');
  const card = document.querySelector(`.card[data-id="${CSS.escape(item.id)}"]`);
  const selected = card?.classList.contains('selected');

  m.innerHTML = `
    <div class="sheet">
      <div class="hero" style="${item.image ? `background-image:url('${item.image}')` : ''}"></div>
      <div class="title">${escapeHtml(item.name)}</div>
      <div class="desc">${escapeHtml(item.desc || '')}</div>
      <div class="row">
        <button class="close">Tutup</button>
        <button class="add">${selected ? 'Batal' : 'Pilih Grup'}</button>
      </div>
    </div>
  `;
  m.hidden = false;

  m.querySelector('.close')?.addEventListener('click', () => closeDetailModal());
  m.querySelector('.add')?.addEventListener('click', () => {
    if (card) toggleSelect(card);
    closeDetailModal();
  });
  // klik backdrop untuk tutup
  m.addEventListener('click', (e) => { if (e.target === m) closeDetailModal(); }, { once:true });
}

function closeDetailModal(){ 
  const m = document.getElementById('detail'); 
  m.hidden = true; 
  m.innerHTML=''; 
}

function escapeHtml(s){ 
  return String(s).replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  })[c]); 
}

function getSelectedIds(){ 
  return [...document.querySelectorAll('.card.selected')].map(el => el.dataset.id); 
}

function updateBadge(){ 
  const n = getSelectedIds().length, b = document.getElementById('cartBadge'); 
  if(n>0){ b.hidden=false; b.textContent=String(n); } else b.hidden=true; 
}

function formatRupiah(n){ 
  if(!Number.isFinite(n)) return "Rp 0"; 
  return "Rp " + n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, "."); 
}

function syncTotalText(){ 
  const t = getSelectedIds().length * PRICE_PER_GROUP; 
  document.getElementById('total-text').textContent = formatRupiah(t); 
  document.getElementById('pay')?.toggleAttribute('disabled', t<=0); 
}

function getUserId(){
  const u1 = tg?.initDataUnsafe?.user?.id; 
  if (u1) return u1;
  const qp = new URLSearchParams(window.location.search); 
  const u2 = qp.get("uid");
  return u2 ? parseInt(u2, 10) : null;
}

async function onPay(){
  const selected = getSelectedIds();
  const amount = selected.length * PRICE_PER_GROUP;
  if (!selected.length) return;

  const userId = getUserId();
  if (!userId) return showQRModal(`<div style="color:#f55">Gagal membaca user Telegram. Buka lewat tombol bot.</div>`);

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

  const qrPngUrl = `${window.location.origin}/api/qr/${inv.invoice_id}.png?amount=${amount}&t=${Date.now()}`;
  showQRModal(`
    <div><b>Pembayaran GoPay</b></div>
    <div style="margin:8px 0 12px; opacity:.85">QRIS sedang dimuat…</div>
    <img alt="QR" src="${qrPngUrl}">
    <button class="close" id="closeModal">Tutup</button>
  `);
  document.getElementById('closeModal')?.addEventListener('click', hideQRModal);

  const statusUrl = `${window.location.origin}/api/invoice/${inv.invoice_id}/status`;
  let t = setInterval(async ()=>{
    try{
      const r = await fetch(statusUrl); if(!r.ok) return;
      const s = await r.json();
      if (s.status === "PAID"){ clearInterval(t); hideQRModal(); tg?.close?.(); }
    }catch{}
  }, 2000);
}

function showQRModal(html){ 
  const m=document.getElementById('qr'); 
  m.innerHTML=`<div>${html}</div>`; 
  m.hidden=false; 
}
function hideQRModal(){ 
  const m=document.getElementById('qr'); 
  m.hidden=true; 
  m.innerHTML=''; 
}
