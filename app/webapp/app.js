// === Config & Telegram ===
let PRICE_PER_GROUP = 25000;
let LOADED_GROUPS = [];
const tg = window.Telegram?.WebApp; tg?.expand();

document.addEventListener('DOMContentLoaded', loadConfigAndRender);

async function loadConfigAndRender() {
  try {
    const r = await fetch('/api/config');
    const cfg = await r.json();
    PRICE_PER_GROUP = parseInt(cfg?.price_idr ?? '25000', 10) || 25000;
    LOADED_GROUPS = Array.isArray(cfg?.groups) ? cfg.groups : [];
  } catch {}
  renderCarousel(LOADED_GROUPS);
  syncTotalText();
}

// ------ Carousel render ------
function renderCarousel(groups){
  const wrap = document.getElementById('groupsCarousel');
  wrap.innerHTML = '';

  groups.forEach((g, i) => {
    const id = String(g.id);
    const title = String(g.name ?? id);
    const imgUrl = String(g.image ?? '').trim();

    const card = document.createElement('article');
    card.className = 'card' + (i === 0 ? ' focus' : '');
    card.dataset.id = id;
    card.title = title;

    const img = document.createElement('div');
    img.className = 'img';
    if (imgUrl) img.style.backgroundImage = `url("${imgUrl}")`;

    const shade = document.createElement('div'); shade.className = 'shade';
    const titleEl = document.createElement('div'); titleEl.className = 'title'; titleEl.textContent = title;

    const tick = document.createElement('div'); tick.className = 'tick';
    tick.innerHTML = `<svg viewBox="0 0 24 24"><path fill="#fff" d="M9.0,16.2 4.8,12.0 3.4,13.4 9.0,19.0 21.0,7.0 19.6,5.6"/></svg>`;

    card.append(img, shade, titleEl, tick);
    card.addEventListener('click', () => { card.classList.toggle('selected'); syncTotalText(); renderPills(); });
    wrap.appendChild(card);
  });

  // Snap focus handler
  wrap.addEventListener('scroll', () => {
    clearTimeout(wrap._snapTimer);
    wrap._snapTimer = setTimeout(() => setFocusByCenter(wrap), 60);
  });
  setFocusByCenter(wrap);

  // Arrows
  document.getElementById('prev')?.addEventListener('click', () => scrollByCard(wrap, -1));
  document.getElementById('next')?.addEventListener('click', () => scrollByCard(wrap, +1));

  renderPills();
}

function setFocusByCenter(container){
  const rect = container.getBoundingClientRect();
  const mid = rect.left + rect.width/2;
  let best = null, bestDist = 1e9;
  [...container.children].forEach(card => {
    const r = card.getBoundingClientRect();
    const center = r.left + r.width/2;
    const d = Math.abs(center - mid);
    if (d < bestDist){ bestDist = d; best = card; }
  });
  if (best) {
    container.querySelectorAll('.card.focus').forEach(c => c.classList.remove('focus'));
    best.classList.add('focus');
  }
}

function scrollByCard(container, dir){
  const cards = [...container.children];
  const focusedIndex = cards.findIndex(c => c.classList.contains('focus'));
  const nextIndex = Math.max(0, Math.min(cards.length-1, focusedIndex + dir));
  const next = cards[nextIndex];
  next?.scrollIntoView({behavior:'smooth', inline:'center'});
}

// ------ Selection helpers ------
function getSelectedGroupIds(){
  return [...document.querySelectorAll('.card.selected')].map(el => el.dataset.id);
}
function renderPills(){
  const pills = document.getElementById('selectedPills');
  const ids = getSelectedGroupIds();
  const nameMap = Object.fromEntries((LOADED_GROUPS||[]).map(g => [String(g.id), String(g.name ?? g.id)]));
  pills.innerHTML = ids.map(id => `<span class="pill">${escapeHtml(nameMap[id]||id)}</span>`).join('');
}

// ------ Rupiah, total, CTA ------
function formatRupiah(n){ if(!Number.isFinite(n)) return "Rp 0"; return "Rp " + n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, "."); }
function syncTotalText(){
  const count = getSelectedGroupIds().length;
  const total = count * PRICE_PER_GROUP;
  document.getElementById('total-text').textContent = formatRupiah(total);
  document.getElementById('pay')?.toggleAttribute('disabled', total <= 0);
}

// ------ QR + checkout flow (tetap) ------
function getUserId(){
  const fromInit = tg?.initDataUnsafe?.user?.id;
  if (fromInit) return fromInit;
  const qp = new URLSearchParams(window.location.search);
  const fromQuery = qp.get("uid");
  return fromQuery ? parseInt(fromQuery, 10) : null;
}
document.getElementById('pay')?.addEventListener('click', onPay);

async function onPay(){
  const selected = getSelectedGroupIds();
  const amount = selected.length * PRICE_PER_GROUP;
  if (!selected.length) return;

  const userId = getUserId();
  if (!userId) return showQRModal(`<div style="color:#f55">Gagal membaca user Telegram. Buka via tombol bot.</div>`);

  // create invoice
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

  // show QR
  const ref = `INV:${inv.invoice_id}`;
  const qrPngUrl = `${window.location.origin}/api/qr/${inv.invoice_id}.png?amount=${amount}&t=${Date.now()}`;
  showQRModal(`
    <div><b>Pembayaran GoPay</b></div>
    <div id="qruistate" style="margin:8px 0 12px 0; opacity:.85">QRIS sedang dimuat…</div>
    <img id="qrimg" alt="QR" src="${qrPngUrl}">
    <div style="margin-top:10px"><b>Kode:</b> <code>${escapeHtml(ref)}</code></div>
    <button class="close" id="closeModal">Tutup</button>
  `);
  document.getElementById('closeModal')?.addEventListener('click', hideQRModal);

  // poll status
  const statusUrl = `${window.location.origin}/api/invoice/${inv.invoice_id}/status`;
  let timer = setInterval(async () => {
    try{
      const r = await fetch(statusUrl); if(!r.ok) return;
      const s = await r.json();
      if (s.status === "PAID"){
        clearInterval(timer);
        hideQRModal();
        tg?.close?.();
      }
    }catch{}
  }, 2000);
}

// ------ Modal helpers ------
function showQRModal(html){
  const m = document.getElementById('qr'); m.innerHTML = `<div>${html}</div>`; m.hidden = false;
}
function hideQRModal(){ const m = document.getElementById('qr'); m.hidden = true; m.innerHTML=''; }
function escapeHtml(s){ return String(s).replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;','\'':'&#39;'}[c])); }
