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
    p.textContent = truncateText(desc || 'Akses eksklusif grup pilihan.');

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn-solid';
    btn.style.marginLeft = 'auto';
    btn.textContent = 'Pilih Grup';

    // 1) Klik tombol: toggle select
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      toggleSelect(card);
    });

    // 2) Klik kartu (kecuali tombol): buka modal detail (dengan carousel)
    card.addEventListener('click', (e) => {
      if (btn.contains(e.target)) return;
      openDetailModal({ id, name, desc: longDesc || desc, image: img });
    });

    meta.append(title, p, btn);
    card.append(check, thumb, meta);
    root.appendChild(card);

    updateButtonState(card, btn);
  });

  updateBadge();
}

function toggleSelect(card){
  card.classList.toggle('selected');
  const btn = card.querySelector('button');
  if (btn) updateButtonState(card, btn);
  syncTotalText();
  updateBadge();
}

function updateButtonState(card, btn){
  const selected = card.classList.contains('selected');
  btn.textContent = selected ? 'Batal' : 'Pilih Grup';
  btn.classList.toggle('btn-solid', !selected);
  btn.classList.toggle('btn-ghost', selected);
  if (!btn.style.marginLeft) btn.style.marginLeft = 'auto';
}

/* ---------- Detail Modal + Carousel ---------- */

async function openDetailModal(item){
  const m = document.getElementById('detail');
  const card = document.querySelector(`.card[data-id="${CSS.escape(item.id)}"]`);
  const selected = card?.classList.contains('selected');

  // Ambil daftar gambar:
  const images = await fetchImagesForItem(item);

  m.innerHTML = `
    <div class="sheet" id="sheet">
      <div class="hero">
        <div class="carousel" id="carousel" data-idx="0">
          <button class="nav prev" aria-label="Sebelumnya">‹</button>
          <img id="cImg" src="" alt="${escapeHtml(item.name)}">
          <button class="nav next" aria-label="Berikutnya">›</button>
          <div class="dots" id="cDots"></div>
        </div>
      </div>
      <div class="title" id="ttl">${escapeHtml(item.name)}</div>
      <div class="desc" id="dsc">${escapeHtml(item.desc || '')}</div>
      <div class="row" id="btns">
        <button class="close">Tutup</button>
        <button class="add">${selected ? 'Batal' : 'Pilih Grup'}</button>
      </div>
    </div>
  `;
  m.hidden = false;

  // Inisialisasi carousel
  initCarousel(images);

  // Action buttons
  m.querySelector('.close')?.addEventListener('click', () => closeDetailModal());
  m.querySelector('.add')?.addEventListener('click', () => {
    if (card) toggleSelect(card);
    closeDetailModal();
  });
  m.addEventListener('click', (e) => { if (e.target === m) closeDetailModal(); }, { once:true });
}

function closeDetailModal(){
  const m = document.getElementById('detail');
  m.hidden = true;
  m.innerHTML = '';
}

/** Ambil list gambar untuk modal:
 *  - Jika group punya `image_folder` → GET /api/images?gid=<id> (atau folder)
 *  - Else kalau `image` ada → [image]
 */
async function fetchImagesForItem(item){
  try {
    // Prefer /api/images by group id (server akan mapping id -> folder)
    const url = `/api/images?gid=${encodeURIComponent(item.id)}`;
    const r = await fetch(url, { cache: 'no-store' });
    if (r.ok) {
      const data = await r.json();
      const list = Array.isArray(data?.images) ? data.images : [];
      if (list.length) return list;
    }
  } catch {}
  // Fallback single image / kosong
  return item.image ? [item.image] : [];
}

/** Setup carousel interaksi dan auto-rotate */
function initCarousel(images){
  const car = document.getElementById('carousel');
  const img = document.getElementById('cImg');
  const dotsWrap = document.getElementById('cDots');

  let idx = 0;
  let timer = null;

  const renderDots = () => {
    dotsWrap.innerHTML = images.map((_, i) =>
      `<div class="dot${i===idx?' active':''}" data-i="${i}"></div>`
    ).join('');
    // klik dot
    dotsWrap.querySelectorAll('.dot').forEach(d =>
      d.addEventListener('click', () => setSlide(parseInt(d.dataset.i, 10)))
    );
  };

  const fitImg = () => {
    if (!img.naturalWidth || !img.naturalHeight) return;
    // Selalu pakai contain agar tidak ter-zoom
    img.style.objectFit = 'contain';
    img.style.width = 'auto';
    img.style.height = 'auto';
  };

  const setSlide = (i) => {
    if (!images.length) { img.removeAttribute('src'); return; }
    idx = (i + images.length) % images.length;
    car.dataset.idx = String(idx);
    img.src = images[idx];
    // force re-fit setelah load
    if (img.complete) fitImg();
    else img.onload = fitImg;
    renderDots();
    restartAuto();
  };

  const next = () => setSlide(idx + 1);
  const prev = () => setSlide(idx - 1);

  // Tombol nav
  car.querySelector('.next')?.addEventListener('click', (e)=>{ e.stopPropagation(); next(); });
  car.querySelector('.prev')?.addEventListener('click', (e)=>{ e.stopPropagation(); prev(); });

  // Swipe (touch)
  let tx = 0, dx = 0;
  car.addEventListener('touchstart', (e)=>{ tx = e.touches[0].clientX; dx = 0; stopAuto(); }, { passive:true });
  car.addEventListener('touchmove',  (e)=>{ dx = e.touches[0].clientX - tx; }, { passive:true });
  car.addEventListener('touchend',   ()=>{ if (Math.abs(dx) > 40) (dx<0?next:prev)(); startAuto(); });

  // Keyboard (optional)
  document.addEventListener('keydown', onKey);
  function onKey(e){
    if (document.getElementById('detail')?.hidden) return;
    if (e.key === 'ArrowRight') next();
    if (e.key === 'ArrowLeft')  prev();
  }

  // Auto-rotate
  function startAuto(){ stopAuto(); timer = setInterval(next, 4500); }
  function stopAuto(){ if (timer) { clearInterval(timer); timer = null; } }
  function restartAuto(){ stopAuto(); startAuto(); }

  // Stop saat modal ditutup
  const cleanup = () => { stopAuto(); document.removeEventListener('keydown', onKey); };
  document.getElementById('detail')?.addEventListener('hidden', cleanup, { once:true });

  // Mulai
  setSlide(0);
  startAuto();
}

/* ---------- Util lain (cart/format/pay) ---------- */

function escapeHtml(s){
  return String(s).replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  })[c]);
}

function getSelectedIds(){
  return [...document.querySelectorAll('.card.selected')].map(el => el.dataset.id);
}

function updateBadge(){
  const n = getSelectedIds().length;
  const b = document.getElementById('cartBadge');
  if (n > 0) { b.hidden = false; b.textContent = String(n); }
  else b.hidden = true;
}

function formatRupiah(n){
  if (!Number.isFinite(n)) return "Rp 0";
  return "Rp " + n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
}

function syncTotalText(){
  const t = getSelectedIds().length * PRICE_PER_GROUP;
  document.getElementById('total-text').textContent = formatRupiah(t);
  document.getElementById('pay')?.toggleAttribute('disabled', t <= 0);
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
      const r = await fetch(statusUrl);
      if(!r.ok) return;
      const s = await r.json();
      if (s.status === "PAID"){ clearInterval(t); hideQRModal(); tg?.close?.(); }
    }catch{}
  }, 2000);
}

function showQRModal(html){
  const m = document.getElementById('qr');
  m.innerHTML = `<div>${html}</div>`;
  m.hidden = false;
}
function hideQRModal(){
  const m = document.getElementById('qr');
  m.hidden = true;
  m.innerHTML = '';
}
