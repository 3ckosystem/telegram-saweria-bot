<script>
// app/webapp/app.js
const tg = window.Telegram?.WebApp; 
tg?.expand();

let PRICE_PER_GROUP = 25000;
let LOADED_GROUPS = [];

// ====== Config truncate ======
const MAX_DESC_CHARS = 120;

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
    const folder = String(g.image_folder ?? g.ik_folder ?? '').trim();

    const card = document.createElement('article');
    card.className = 'card';
    card.dataset.id = id;
    // simpan folder untuk modal
    if (folder) card.dataset.folder = folder;

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
    btn.className = 'btn-outline btn-primary-right';
    btn.textContent = 'Pilih Grup';

    // === BEHAVIOR ===
    // 1) Klik tombol: toggle select (HANYA tombol)
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      toggleSelect(card);
    });

    // 2) Klik area kartu selain tombol: buka modal dengan deskripsi FULL
    card.addEventListener('click', async (e) => {
      if (btn.contains(e.target)) return;
      const item = { id, name, desc: longDesc || desc, image: img, folder };
      openDetailModal(item);
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
  const btn = card.querySelector('.btn-outline');
  if (btn) updateButtonState(card, btn);
  syncTotalText(); 
  updateBadge();
}

function updateButtonState(card, btn){
  const selected = card.classList.contains('selected');
  btn.textContent = selected ? 'Batal' : 'Pilih Grup';
  btn.classList.toggle('btn-muted', selected); // styled via CSS
  btn.classList.toggle('btn-colored', !selected);
}

// --------- CAROUSEL UTIL ---------
async function fetchFolderImages(folder, limit = 15){
  if (!folder) return [];
  try{
    const u = `/api/images/list?folder=${encodeURIComponent(folder)}&limit=${limit}&t=${Date.now()}`;
    const r = await fetch(u, { cache: 'no-store' });
    if (!r.ok) return [];
    const j = await r.json();
    // expect {items:[{url:...}, ...]} or [url,...]
    if (Array.isArray(j)) return j;
    if (Array.isArray(j.items)) return j.items.map(x => x.url || x);
    return [];
  }catch{ return []; }
}

function buildCarouselHtml(){
  return `
    <div class="hero">
      <div class="carousel">
        <button class="nav prev" aria-label="Sebelumnya">‹</button>
        <img class="slide" alt="">
        <button class="nav next" aria-label="Berikutnya">›</button>
        <div class="dots"></div>
      </div>
    </div>
  `;
}

function initCarousel(root, urls, autoMs = 3500){
  const imgEl = root.querySelector('.carousel .slide');
  const dotsEl = root.querySelector('.carousel .dots');
  const prevBtn = root.querySelector('.carousel .prev');
  const nextBtn = root.querySelector('.carousel .next');

  let idx = 0;
  let timer = null;
  let urlsClean = (urls || []).filter(Boolean);
  if (urlsClean.length === 0) {
    urlsClean = [imgEl.getAttribute('src')].filter(Boolean);
  }

  // build dots
  dotsEl.innerHTML = urlsClean.map((_, i) => `<button class="dot" data-i="${i}" aria-label="Go to slide ${i+1}"></button>`).join('');
  const dotBtns = [...dotsEl.querySelectorAll('.dot')];

  function show(i){
    idx = (i + urlsClean.length) % urlsClean.length;
    imgEl.src = urlsClean[idx];
    dotBtns.forEach((d, di) => d.classList.toggle('active', di === idx));
  }

  function next(){ show(idx + 1); }
  function prev(){ show(idx - 1); }

  nextBtn.addEventListener('click', next);
  prevBtn.addEventListener('click', prev);
  dotBtns.forEach(d => d.addEventListener('click', () => show(parseInt(d.dataset.i,10)||0)));

  // swipe
  let sx = 0, sy = 0, dx = 0, dy = 0;
  imgEl.addEventListener('touchstart', (e)=>{ const t=e.touches[0]; sx=t.clientX; sy=t.clientY; dx=0; dy=0;}, {passive:true});
  imgEl.addEventListener('touchmove',  (e)=>{ const t=e.touches[0]; dx=t.clientX-sx; dy=t.clientY-sy; }, {passive:true});
  imgEl.addEventListener('touchend',   ()=>{ if (Math.abs(dx)>40 && Math.abs(dx)>Math.abs(dy)) (dx<0?next:prev)(); });

  // hover pause (desktop)
  const car = root.querySelector('.carousel');
  const start = ()=>{ if (autoMs>0 && urlsClean.length>1){ stop(); timer=setInterval(next, autoMs); } };
  const stop  = ()=>{ if (timer){ clearInterval(timer); timer=null; } };
  car.addEventListener('mouseenter', stop);
  car.addEventListener('mouseleave', start);

  show(0);
  start();
  // return controller if needed
  return { show, next, prev, stop, start };
}

// --------- MODAL ----------
async function openDetailModal(item){
  const m = document.getElementById('detail');
  const card = document.querySelector(`.card[data-id="${CSS.escape(item.id)}"]`);
  const selected = card?.classList.contains('selected');

  // build basic sheet (carousel will be injected)
  m.innerHTML = `
    <div class="sheet sheet-fluid">
      ${buildCarouselHtml()}
      <div class="title">${escapeHtml(item.name)}</div>
      <div class="desc">${escapeHtml(item.desc || '')}</div>
      <div class="row">
        <button class="close">Tutup</button>
        <button class="add">${selected ? 'Batal' : 'Pilih Grup'}</button>
      </div>
    </div>
  `;
  m.hidden = false;

  // Fetch all images from folder (fallback to single image)
  let urls = [];
  if (item.folder) {
    urls = await fetchFolderImages(item.folder, 20);
  }
  if ((!urls || urls.length === 0) && item.image) {
    urls = [item.image];
  }

  // If still empty, hide carousel area
  if (!urls || urls.length === 0) {
    const hero = m.querySelector('.hero');
    if (hero) hero.remove();
  } else {
    // preload first quickly
    const first = urls[0];
    const slide = m.querySelector('.carousel .slide');
    if (slide) slide.src = first;
    // init carousel
    initCarousel(m, urls, 3500);
  }

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
</script>
