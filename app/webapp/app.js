/* ========= Data Grup (ganti harga sesuai kebutuhan) ========= */
const GROUPS = [
  { id: 'group_model', name: 'Group Model', price: 25000, img: 'https://images.unsplash.com/photo-1512436991641-6745cdb1723f?q=80&auto=format&fit=crop&w=1200' },
  { id: 'group_a',     name: 'Group A',     price: 25000, img: 'https://images.unsplash.com/photo-1518674660708-6d0ef7a10054?q=80&auto=format&fit=crop&w=1200' },
  { id: 'group_s',     name: 'Group S',     price: 25000, img: 'https://images.unsplash.com/photo-1598899134739-24b5cbe8c8e5?q=80&auto=format&fit=crop&w=1200' },
];

// Keranjang: Map<groupId, qty> — untuk use-case kamu qty kemungkinan 1 per grup
const CART = new Map();

/* ========= Elemen ========= */
const $grid = document.getElementById('groupGrid');
const $tpl  = document.getElementById('tplGroupCard');

const $totalText = document.getElementById('totalText');
const $btnCheckout = document.getElementById('btnCheckout');

const $screenCatalog = document.getElementById('screenCatalog');
const $screenConfirm = document.getElementById('screenConfirm');
const $screenPayment = document.getElementById('screenPayment');

const $confirmSummary = document.getElementById('confirmSummary');

const $invId = document.getElementById('invId');
const $invAmount = document.getElementById('invAmount');
const $qrisImage = document.getElementById('qrisImage');
const $payCode = document.getElementById('payCode');
const $qrisStatus = document.getElementById('qrisStatus');
const $saweriaLink = document.getElementById('saweriaLink');

/* ========= Util ========= */
const fmtIDR = n => new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(n);
const show = el => el.classList.remove('is-hidden');
const hide = el => el.classList.add('is-hidden');

function setScreen(name) {
  const map = { catalog: $screenCatalog, confirm: $screenConfirm, payment: $screenPayment };
  Object.values(map).forEach(hide);
  show(map[name]);
}

/* ========= Render Kartu Grup ========= */
function renderCatalog() {
  $grid.innerHTML = '';
  GROUPS.forEach(g => {
    const n = $tpl.content.cloneNode(true);
    const img = n.querySelector('img');
    const ttl = n.querySelector('.card-title');
    const bAdd = n.querySelector('.btn-add');
    const bRm  = n.querySelector('.btn-remove');

    img.src = g.img;
    img.alt = g.name;
    ttl.textContent = g.name;

    const syncButtons = () => {
      const inCart = CART.has(g.id);
      bAdd.classList.toggle('is-hidden', inCart);
      bRm.classList.toggle('is-hidden', !inCart);
    };

    bAdd.addEventListener('click', () => {
      CART.set(g.id, 1); // satuan per grup
      updateTotal();
      syncButtons();
      try { Telegram.WebApp.HapticFeedback.impactOccurred('light'); } catch {}
    });

    bRm.addEventListener('click', () => {
      CART.delete(g.id);
      updateTotal();
      syncButtons();
      try { Telegram.WebApp.HapticFeedback.impactOccurred('light'); } catch {}
    });

    syncButtons();
    $grid.appendChild(n);
  });
}

/* ========= Total ========= */
function getSummary() {
  const items = [];
  let total = 0;
  for (const [id, qty] of CART.entries()) {
    const g = GROUPS.find(x => x.id === id);
    if (!g) continue;
    const subtotal = g.price * qty;
    total += subtotal;
    items.push({ id: g.id, name: g.name, qty, price: g.price, subtotal });
  }
  return { items, total };
}
function updateTotal() {
  const { total } = getSummary();
  $totalText.textContent = fmtIDR(total);
}

/* ========= Checkout → Confirm ========= */
function buildConfirmUI() {
  const { items, total } = getSummary();
  if (!items.length) {
    $confirmSummary.innerHTML = '<div class="card">Keranjang kosong. Pilih grup terlebih dahulu.</div>';
    return;
  }

  const lines = items.map(i => `
    <div class="line">
      <div>${i.name} × ${i.qty}</div>
      <div>${fmtIDR(i.subtotal)}</div>
    </div>
  `).join('');

  $confirmSummary.innerHTML = `
    <div class="card">
      ${lines}
      <div class="total">
        <div>Total</div>
        <div>${fmtIDR(total)}</div>
      </div>
    </div>
  `;
}

/* ========= Confirm → Payment (Create Invoice + Show QRIS) ========= */
/**
 * Integrasi server:
 * 1) Buat endpoint untuk membuat invoice, misal:
 *    POST /api/invoice  { items: [...], total: number }
 *    -> { invoice_id, amount }
 * 2) Endpoint untuk fetch QRIS dari Saweria (punyamu sudah ada):
 *    GET /api/qris?invoice_id=...
 *    -> { qr_png_url, payment_code, saweria_payment_url }
 * 
 * Di bawah ini ada fallback (demo) kalau endpoint belum disambungkan.
 */
async function createInvoiceOnServer(payload) {
  // TODO: GANTI dgn fetch ke FastAPI milik kamu.
  // Contoh:
  // const r = await fetch('/api/invoice', { method: 'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
  // if (!r.ok) throw new Error('Gagal membuat invoice');
  // return await r.json();

  // DEMO fallback:
  await delay(500);
  const fakeId = 'INV:' + Math.random().toString(16).slice(2, 10).toUpperCase();
  return { invoice_id: fakeId, amount: payload.total };
}

async function fetchQrisFromServer(invoice_id) {
  // TODO: GANTI dgn endpoint kamu yang sudah menghasilkan QR dari Saweria/GoPay.
  // Contoh:
  // const r = await fetch(`/api/qris?invoice_id=${encodeURIComponent(invoice_id)}`);
  // if (!r.ok) throw new Error('Gagal ambil QRIS');
  // return await r.json();

  // DEMO fallback (pakai placeholder QR):
  await delay(700);
  return {
    qr_png_url: 'https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=' + encodeURIComponent(invoice_id),
    payment_code: invoice_id.replace('INV:', 'INV-FAKE-'),
    saweria_payment_url: 'https://saweria.co/payments'
  };
}

const delay = ms => new Promise(r => setTimeout(r, ms));

/* ========= Events ========= */
document.getElementById('ctaShop').addEventListener('click', () => {
  window.scrollTo({ top: document.querySelector('.content').offsetTop, behavior: 'smooth' });
});

$btnCheckout.addEventListener('click', () => {
  const { items } = getSummary();
  if (!items.length) {
    alert('Keranjang kosong.');
    return;
  }
  buildConfirmUI();
  setScreen('confirm');
});

document.getElementById('btnBackToCatalog').addEventListener('click', () => {
  setScreen('catalog');
});

document.getElementById('btnProceedPayment').addEventListener('click', async () => {
  const summary = getSummary();
  if (!summary.items.length) return alert('Keranjang kosong.');

  // 1) Buat invoice di server
  try {
    const inv = await createInvoiceOnServer(summary);
    $invId.textContent = inv.invoice_id;
    $invAmount.textContent = fmtIDR(inv.amount);

    // 2) Ambil QRIS utk invoice tsb
    const qris = await fetchQrisFromServer(inv.invoice_id);
    $qrisImage.src = qris.qr_png_url;
    $payCode.textContent = qris.payment_code;
    $saweriaLink.href = qris.saweria_payment_url || 'https://saweria.co/payments';

    setScreen('payment');
    try { Telegram.WebApp.HapticFeedback.notificationOccurred('success'); } catch {}
  } catch (e) {
    console.error(e);
    alert('Gagal membuat invoice/QRIS. Coba lagi.');
  }
});

document.getElementById('btnCopyCode').addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText($payCode.textContent.trim());
    alert('Kode pembayaran tersalin.');
  } catch {
    alert('Tidak bisa menyalin otomatis.');
  }
});

document.getElementById('btnDone').addEventListener('click', () => {
  // Tutup Mini App atau kembali ke katalog
  if (window.Telegram && Telegram.WebApp) Telegram.WebApp.close();
  else setScreen('catalog');
});

/* ========= Init ========= */
renderCatalog();
updateTotal();
