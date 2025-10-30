// app/webapp/app.js
const tg = window.Telegram?.WebApp;
tg?.expand();

let PRICE_PER_GROUP = 25000;
let LOADED_GROUPS = [];

// ====== Truncate aman emoji ======
const MAX_DESC_CHARS = 120;
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

    btn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      toggleSelect(card);
    });

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

/* ===================== DETAIL MODAL + CAROUSEL ===================== */

async function openDetailModal(item){
  const m = document.getElementById('detail');
  const card = document.querySelector(`.card[data-id="${CSS.escape(item.id)}"]`);
  const selected = card?.classList.contains('selected');

  const images = await fetchImagesForItem(item);

  m.innerHTML = `
    <div class="sheet" id="sheet">
      <div class="hero">
        <div class="carousel" id="carousel" data-idx="0">
          <button class="nav prev" aria-label="Sebelumnya">‹</button>
          <img id="cImg" class="slide" src="" alt="${escapeHtml(item.name)}">
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

  // sizing stabil: heroImgHeight = clamp(220px, 62vh, (98vh - nonImg))
  const sheet = document.getElementById('sheet');
  const ttl = document.getElementById('ttl');
  const dsc = document.getElementById('dsc');
  const btns = document.getElementById('btns');
  const hero = sheet.querySelector('.hero');
  function fitHeroHeight() {
    const vh = window.innerHeight;
    const styles = getComputedStyle(sheet);
    const pad = parseFloat(styles.paddingTop) + parseFloat(styles.paddingBottom);
    const nonImg = ttl.offsetHeight + dsc.offsetHeight + btns.offsetHeight + pad + 24; // gap kecil
    const avail = Math.max(220, Math.min(vh * 0.98 - nonImg, vh * 0.62));
    hero.style.maxHeight = `${Math.floor(avail)}px`;
  }

  // Init carousel
  const cleanup = initCarousel(images);

  // listeners
  m.querySelector('.close')?.addEventListener('click', () => { cleanup(); closeDetailModal(); });
  m.querySelector('.add')?.addEventListener('click', () => { if (card) toggleSelect(card); cleanup(); closeDetailModal(); });
  m.addEventListener('click', (e) => { if (e.target === m) { cleanup(); closeDetailModal(); } }, { once:true });

  // first layout
  fitHeroHeight();
  window.addEventListener('resize', fitHeroHeight, { passive:true });

  // remove on close
  const detach = () => window.removeEventListener('resize', fitHeroHeight);
  m._detachFit = detach;
}

function closeDetailModal(){
  const m = document.getElementById('detail');
  try { m._detachFit?.(); } catch {}
  m.hidden = true;
  m.innerHTML = '';
}

async function fetchImagesForItem(item){
  try {
    const r = await fetch(`/api/images?gid=${encodeURIComponent(item.id)}`, { cache: 'no-store' });
    if (r.ok) {
      const data = await r.json();
      const list = Array.isArray(data?.images) ? data.images : [];
      if (list.length) return list;
    }
  } catch {}
  return item.image ? [item.image] : [];
}

function initCarousel(images){
  const car  = document.getElementById('carousel');
  const img  = document.getElementById('cImg');
  const dots = document.getElementById('cDots');

  let idx = 0;
  let timer = null;

  function renderDots(){
    dots.innerHTML = images.map((_, i) =>
      `<div class="dot${i===idx?' active':''}" data-i="${i}"></div>`
    ).join('');
    dots.querySelectorAll('.dot').forEach(el => {
      el.addEventListener('click', () => setSlide(parseInt(el.dataset.i,10)));
    });
  }

  function fitImg(){
    // pastikan tidak zoom
    img.style.objectFit = 'contain';
    img.style.width = '100%';
    img.style.height = 'auto';
  }

  function setSlide(i){
    if (!images.length) { img.removeAttribute('src'); return; }
    idx = (i + images.length) % images.length;
    car.dataset.idx = String(idx);
    const src = images[idx];
    if (img.src !== src) {
      img.onload = () => requestAnimationFrame(fitImg);
      img.src = src;
    } else {
      fitImg();
    }
    renderDots();
    restartAuto();
  }

  const next = () => setSlide(idx + 1);
  const prev = () => setSlide(idx - 1);

  // tombol
  const onNext = (e)=>{ e.stopPropagation(); next(); };
  const onPrev = (e)=>{ e.stopPropagation(); prev(); };
  car.querySelector('.next')?.addEventListener('click', onNext);
  car.querySelector('.prev')?.addEventListener('click', onPrev);

  // swipe
  let startX = 0, deltaX = 0;
  const onTs = (e)=>{ startX = e.touches[0].clientX; deltaX = 0; stopAuto(); };
  const onTm = (e)=>{ deltaX = e.touches[0].clientX - startX; };
  const onTe = ()=>{ if (Math.abs(deltaX) > 40) (deltaX < 0 ? next() : prev()); startAuto(); };
  car.addEventListener('touchstart', onTs, { passive:true });
  car.addEventListener('touchmove',  onTm, { passive:true });
  car.addEventListener('touchend',   onTe);

  // keyboard (opsional)
  const onKey = (e)=>{
    if (document.getElementById('detail')?.hidden) return;
    if (e.key === 'ArrowRight') next();
    if (e.key === 'ArrowLeft')  prev();
  };
  document.addEventListener('keydown', onKey);

  // auto-rotate
  function startAuto(){ stopAuto(); if (images.length > 1) timer = setInterval(next, 4500); }
  function stopAuto(){ if (timer) { clearInterval(timer); timer = null; } }
  function restartAuto(){ stopAuto(); startAuto(); }

  // mulai
  setSlide(0);
  startAuto();

  // cleanup saat modal ditutup
  return function cleanup(){
    stopAuto();
    document.removeEventListener('keydown', onKey);
    car.querySelector('.next')?.removeEventListener('click', onNext);
    car.querySelector('.prev')?.removeEventListener('click', onPrev);
    car.removeEventListener('touchstart', onTs);
    car.removeEventListener('touchmove', onTm);
    car.removeEventListener('touchend', onTe);
  };
}

/* ===================== UTIL & PAYMENT ===================== */

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
