// ===== Setup & Config =====
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
  renderNetflix(LOADED_GROUPS);
  syncTotalText();
  document.getElementById('pay')?.addEventListener('click', onPay);
}

// ===== Netflix-style render =====
function renderNetflix(groups){
  const rowsEl = document.getElementById('rows');
  rowsEl.innerHTML = '';

  // HERO (pakai item pertama yang punya image)
  const hero = document.getElementById('hero');
  const firstImg = groups.find(g => g.image)?.image;
  if (firstImg){
    hero.hidden = false;
    hero.style.setProperty('--hero', `url("${firstImg}")`);
    hero.style.setProperty('background-image', `url("${firstImg}")`);
    hero.querySelector('.heroTitle').textContent = (groups[0]?.name || 'Featured');
    hero.style.setProperty('--bg', firstImg);
    hero.style.setProperty('--img', `url("${firstImg}")`);
    hero.style.setProperty('--size','cover');
    hero.style.setProperty('--pos','center');
    hero.style.backgroundImage = `url("${firstImg}")`;
    hero.style.setProperty('background-size','cover');
    hero.style.setProperty('background-position','center');
  }

  // Bikin beberapa row “kategori” dari satu list (chunking)
  const chunks = chunk(groups, 10); // 10 poster per row
  chunks.forEach((items, idx) => {
    const title = document.createElement('div');
    title.className = 'rowTitle';
    title.textContent = idx === 0 ? 'Semua Grup' : `Lainnya ${idx+1}`;

    const list = document.createElement('div');
    list.className = 'hlist';

    items.forEach(g => list.appendChild(makePoster(g)));

    rowsEl.appendChild(title);
    rowsEl.appendChild(list);
  });

  updateCartBadge();
}

function makePoster(g){
  const id = String(g.id);
  const name = String(g.name ?? id);
  const img = String(g.image ?? '').trim();

  const poster = document.createElement('article');
  poster.className = 'poster';
  poster.dataset.id = id;

  const imgEl = document.createElement('div');
  imgEl.className = 'posterImg';
  if (img) imgEl.style.backgroundImage = `url("${img}")`;

  const shade = document.createElement('div'); shade.className = 'posterShade';
  const nameEl = document.createElement('div'); nameEl.className = 'posterName'; nameEl.textContent = name;

  const sel = document.createElement('div'); sel.className = 'sel';
  sel.innerHTML = `<svg viewBox="0 0 24 24"><path fill="#fff" d="M9,16.2 4.8,12 3.4,13.4 9,19 21,7 19.6,5.6"/></svg>`;

  poster.append(imgEl, shade, nameEl, sel);
  poster.addEventListener('click', () => {
    poster.classList.toggle('selected');
    syncTotalText();
    updateCartBadge();
  });

  return poster;
}

function chunk(arr, size){
  const out=[]; for(let i=0;i<arr.length;i+=size) out.push(arr.slice(i,i+size)); return out;
}

function getSelectedGroupIds(){
  return [...document.querySelectorAll('.poster.selected')].map(el => el.dataset.id);
}

function updateCartBadge(){
  const count = getSelectedGroupIds().length;
  const badge = document.getElementById('cartBadge');
  if (count > 0){ badge.hidden = false; badge.textContent = count; } else { badge.hidden = true; }
}

// ===== Total & Checkout =====
function formatRupiah(n){ if(!Number.isFinite(n)) return "Rp 0"; return "Rp " + n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, "."); }
function syncTotalText(){
  const count = getSelectedGroupIds().length;
  const total = count * PRICE_PER_GROUP;
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

document.getElementById('pay')?.addEventListener('click', onPay);

async function onPay(){
  const selected = getSelectedGroupIds();
  const amount = selected.length * PRICE_PER_GROUP;
  if (!selected.length) return;

  const userId = getUserId();
  if (!userId) return showQRModal(`<div style="color:#f55">Gagal membaca user Telegram. Buka lewat tombol bot.</div>`);

  // 1) create invoice
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

  // 2) QR
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

  // 3) polling status
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

// ===== Modal helpers =====
function showQRModal(html){
  const m = document.getElementById('qr'); m.innerHTML = `<div>${html}</div>`; m.hidden = false;
}
function hideQRModal(){ const m = document.getElementById('qr'); m.hidden = true; m.innerHTML=''; }
function escapeHtml(s){ return String(s).replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;','\'':'&#39;'}[c])); }
