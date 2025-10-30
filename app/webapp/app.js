// app/webapp/app.js
const tg = window.Telegram?.WebApp;
tg?.expand();

let PRICE_PER_GROUP = 25000;
let LOADED_GROUPS = [];

// ====== Config truncate ======
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
    const r = await fetch('/api/config?t=' + Date.now(), { cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const cfg = await r.json();
    PRICE_PER_GROUP = parseInt(cfg?.price_idr ?? '25000', 10) || 25000;
    LOADED_GROUPS = Array.isArray(cfg?.groups) ? cfg.groups : [];
  } catch (e) {
    console.error('Gagal ambil /api/config:', e);
  }

  if (!LOADED_GROUPS?.length) {
    renderFallbackEmpty();
  } else {
    renderNeonList(LOADED_GROUPS);
  }

  syncTotalText();
  document.getElementById('pay')?.addEventListener('click', onPay);
});

function renderFallbackEmpty() {
  const root = document.getElementById('list');
  root.innerHTML = `
    <div style="padding:16px;color:#cdd0d4">
      Tidak ada data grup untuk ditampilkan.<br/>
      Cek <code>GROUP_IDS_JSON</code> di server atau reload.
    </div>
  `;
}

function renderNeonList(groups) {
  const root = document.getElementById('list');
  root.innerHTML = '';

  (groups || []).forEach(g => {
    const id   = String(g.id);
    const name = String(g.name ?? id);
    const desc = String(g.desc ?? '').trim();
    const longDesc = String(g.long_desc ?? desc).trim();
    const img  = String(g.image ?? '').trim();
    const imageFolder = String(g.image_folder ?? '').trim();

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
      openDetailModal({
        id, name,
        desc: longDesc || desc,
        image: img,
        image_folder: imageFolder
      });
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

/* =======================
   DETAIL MODAL + CAROUSEL
   ======================= */
let _carouselTimer = null;
const ROTATE_MS = 4000;

async function openDetailModal(item){
  const m = document.getElementById('detail');
  const card = document.querySelector(`.card[data-id="${CSS.escape(item.id)}"]`);
  const selected = card?.classList.contains('selected');

  m.innerHTML = `
    <div class="sheet" id="sheet">
      <div class="hero" id="hero">
        <div class="carousel" id="carousel" aria-live="polite">
          <button class="nav prev" id="cPrev" aria-label="Sebelumnya">‹</button>
          <img id="cImg" alt="${escapeHtml(item.name)}"/>
          <button class="nav next" id="cNext" aria-label="Berikutnya">›</button>
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

  const sheet = document.getElementById('sheet');
  const hero  = document.getElementById('hero');
  const cImg  = document.getElementById('cImg');
  const cPrev = document.getElementById('cPrev');
  const cNext = document.getElementById('cNext');
  const cDots = document.getElementById('cDots');
  const ttl   = document.getElementById('ttl');
  const dsc   = document.getElementById('dsc');
  const btns  = document.getElementById('btns');

  let images = await loadImagesForItem(item);
  if (!images.length && item.image) images = [item.image];

  let idx = 0;

  const renderDots = () => {
    if (images.length <= 1) { cDots.innerHTML = ''; return; }
    cDots.innerHTML = images.map((_, i) =>
      `<span class="dot ${i===idx?'active':''}" data-i="${i}"></span>`).join('');
    cDots.querySelectorAll('.dot').forEach(el => {
      el.addEventListener('click', (ev) => {
        ev.stopPropagation();
        idx = parseInt(el.dataset.i,10)||0;
        renderSlide(true);
      });
    });
  };

  const renderSlide = (userAction = false) => {
    if (!images.length) { hero.style.display='none'; return; }
    hero.style.display='';
    cImg.src = images[idx];
    renderDots();
    if (userAction) restartAutoRotate();
  };

  const restartAutoRotate = () => {
    if (_carouselTimer) clearInterval(_carouselTimer);
    if (images.length > 1) {
      _carouselTimer = setInterval(() => {
        idx = (idx + 1) % images.length;
        renderSlide(false);
      }, ROTATE_MS);
    }
  };

  cPrev.addEventListener('click', (e) => {
    e.stopPropagation();
    if (!images.length) return;
    idx = (idx - 1 + images.length) % images.length;
    renderSlide(true);
  });
  cNext.addEventListener('click', (e) => {
    e.stopPropagation();
    if (!images.length) return;
    idx = (idx + 1) % images.length;
    renderSlide(true);
  });

  addSwipe(document.getElementById('carousel'),
    () => cPrev.click(),
    () => cNext.click()
  );

  // === Fit image tanpa zoom (rasio asli) ===
  const fitHero = () => {
    const vh = window.innerHeight;
    const styles = getComputedStyle(sheet);
    const pad = parseFloat(styles.paddingTop) + parseFloat(styles.paddingBottom);
    const gaps = 12 * 2;
    const nonImg = ttl.offsetHeight + dsc.offsetHeight + btns.offsetHeight + pad + gaps;
    const target = Math.max(220, Math.min(vh * 0.98 - nonImg, vh * 0.92)); // ketinggian maksimum gambar

    hero.style.maxHeight = `${Math.floor(target)}px`;
    hero.style.height = 'auto';

    // KUNCI: jangan pakai height:100% atau object-fit
    // biar tidak ter-zoom, cukup batasi max-height & max-width
    cImg.style.maxHeight = `${Math.floor(target)}px`;
    cImg.style.maxWidth = '100%';
    cImg.style.width = 'auto';
    cImg.style.height = 'auto';
  };

  cImg.addEventListener('load', fitHero);
  window.addEventListener('resize', fitHero, { passive:true });

  renderSlide(false);
  restartAutoRotate();
  fitHero();

  m.querySelector('.close')?.addEventListener('click', () => closeDetailModal());
  m.querySelector('.add')?.addEventListener('click', () => { if (card) toggleSelect(card); closeDetailModal(); });
  m.addEventListener('click', (e) => { if (e.target === m) closeDetailModal(); }, { once:true });
}

async function loadImagesForItem(item){
  const folder = (item.image_folder || "").trim();
  if (!folder) return item.image ? [item.image] : [];
  try {
    const url = `/api/images?folder=${encodeURIComponent(folder)}&t=${Date.now()}`;
    const r = await fetch(url, { cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    const arr = Array.isArray(data?.items) ? data.items
              : Array.isArray(data?.images) ? data.images
              : [];
    return arr.filter(u => typeof u === 'string' && /^https?:\/\//i.test(u)).slice(0, 12);
  } catch (e) {
    console.warn('[carousel] fallback single image. Error:', e);
    return item.image ? [item.image] : [];
  }
}

function addSwipe(el, onLeft, onRight){
  let x0 = null, y0 = null, t0 = 0;
  const TH = 30;
  el.addEventListener('touchstart', (e) => {
    const t = e.touches[0];
    x0 = t.clientX; y0 = t.clientY; t0 = Date.now();
  }, {passive:true});
  el.addEventListener('touchend', (e) => {
    if (x0 == null) return;
    const dx = (e.changedTouches[0].clientX - x0);
    const dy = (e.changedTouches[0].clientY - y0);
    const dt = Date.now() - t0;
    if (Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > TH && dt < 600) {
      if (dx < 0) onRight?.(); else onLeft?.();
    }
    x0 = y0 = null;
  });
}

function closeDetailModal(){
  const m = document.getElementById('detail');
  if (_carouselTimer) { clearInterval(_carouselTimer); _carouselTimer = null; }
  m.hidden = true;
  m.innerHTML = '';
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
