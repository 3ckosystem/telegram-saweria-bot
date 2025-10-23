// Telegram Mini App client — Option A (user_id opsional, tidak memblokir browser biasa)
// message = 'INV:<invoice_id>'

const tg = window.Telegram?.WebApp;
tg?.expand();

// === Global state ===
let PRICE_PER_GROUP = 25000;
let LOADED_GROUPS = [];

// --- Utils ---
function htmlEscape(s) {
  return String(s || "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}
function formatRupiah(n) {
  try { return Number(n||0).toLocaleString('id-ID',{style:'currency',currency:'IDR',maximumFractionDigits:0}); }
  catch { return `Rp ${n}`; }
}
function getTelegramUserId() {
  try {
    const id = tg?.initDataUnsafe?.user?.id;
    return id ? Number(id) : null;
  } catch { return null; }
}

// --- Render groups & config ---
async function loadConfigAndRender() {
  try {
    const r = await fetch('/api/config');
    const cfg = await r.json();
    PRICE_PER_GROUP = parseInt(cfg?.price_idr ?? '25000', 10) || 25000;
    LOADED_GROUPS = Array.isArray(cfg?.groups) ? cfg.groups : [];

    const box = document.getElementById('groups');
    if (box) {
      box.innerHTML = '';
      LOADED_GROUPS.forEach((g, idx) => {
        const id = `g-${idx}`;
        const wrapper = document.createElement('label');
        wrapper.style.display='flex'; wrapper.style.alignItems='center'; wrapper.style.gap='10px';
        wrapper.style.padding='10px'; wrapper.style.border='1px solid #eee'; wrapper.style.borderRadius='10px';
        wrapper.style.marginBottom='8px'; wrapper.style.background='#fff';

        const cb = document.createElement('input');
        cb.type='checkbox'; cb.id=id; cb.value=g?.id || ''; cb.dataset.initial=(g?.initial||'').trim(); cb.dataset.name=(g?.name||'').trim();

        const text = document.createElement('div');
        text.innerHTML = `<div style="font-weight:600">${htmlEscape(g?.name || g?.id || 'Group')}</div>
                          <div style="font-size:12px;color:#666">ID: ${htmlEscape(g?.id || '-')}</div>`;

        wrapper.appendChild(cb); wrapper.appendChild(text); box.appendChild(wrapper);
      });
      box.addEventListener('change', () => { recalcAmountFromGroups(); setTimeout(syncTotalText,0); });
    }

    const amountEl = document.getElementById('amount');
    if (amountEl && !amountEl.value) amountEl.value = String(PRICE_PER_GROUP);

    setTimeout(syncTotalText, 0);
  } catch (e) { console.error('loadConfig error:', e); }
}

function recalcAmountFromGroups() {
  try {
    const amountEl = document.getElementById('amount');
    const checked = [...document.querySelectorAll('#groups input[type="checkbox"]:checked')];
    const total = (checked.length || 0) * PRICE_PER_GROUP;
    if (amountEl && total > 0) amountEl.value = String(total);
  } catch {}
}
function syncTotalText() {
  const tt = document.getElementById('total-text');
  const amt = parseInt(document.getElementById('amount')?.value || '0', 10);
  if (tt) tt.textContent = formatRupiah(amt || 0);
}

// --- Checkout flow ---
async function handleCheckout() {
  const qrContainer = document.getElementById('qr');
  if (qrContainer) qrContainer.innerHTML = '';

  const userId = getTelegramUserId(); // opsional (null kalau bukan dari Telegram)
  const amount = parseInt(document.getElementById('amount')?.value || '0', 10) || 0;
  const checked = [...document.querySelectorAll('#groups input[type="checkbox"]:checked')];
  const groups = checked.map(i => (i.value || '').trim()).filter(Boolean);

  if (!groups.length) {
    qrContainer.innerHTML = `<div style="color:#c00">Pilih minimal satu grup terlebih dahulu.</div>`;
    return;
  }
  if (!amount || amount <= 0) {
    qrContainer.innerHTML = `<div style="color:#c00">Nominal tidak valid.</div>`;
    return;
  }

  // Tampilkan tips kalau bukan dari Telegram (non-blocking)
  if (!userId) {
    qrContainer.innerHTML = `<div class="tip">Tips: sebaiknya buka via tombol Mini App di Telegram agar user terdeteksi otomatis.</div>`;
  }

  // 1) Create invoice (kirim user_id=0 jika null)
  let inv;
  try {
    const res = await fetch('/api/invoice', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ user_id: userId ?? 0, groups, amount })
    });
    if (!res.ok) throw new Error(await res.text());
    inv = await res.json(); // { invoice_id: "..." }
  } catch (e) {
    qrContainer.innerHTML += `<div style="color:#c00">Create invoice gagal: ${htmlEscape(e.message || String(e))}</div>`;
    return;
  }

  // 2) Set pesan = INV:<invoice_id>
  const invMessage = `INV:${inv.invoice_id}`;
  const msgEl = document.getElementById('msg-preview');
  if (msgEl) msgEl.textContent = `Pesan: ${invMessage}`;

  // 3) Tampilkan QR PNG + detail
  const qrPngUrl = `${window.location.origin}/api/qr/${encodeURIComponent(inv.invoice_id)}`;
  qrContainer.innerHTML += `
    <div style="padding:8px 0">
      <div><b>Invoice:</b> ${htmlEscape(inv.invoice_id)}</div>
      <div><b>Total:</b> ${htmlEscape(formatRupiah(amount))}</div>
      <div><b>Groups:</b> ${htmlEscape(groups.join(', '))}</div>
    </div>
    <div><img src="${qrPngUrl}" alt="QRIS" style="max-width:240px;border:1px solid #eee;padding:6px;border-radius:8px" /></div>
    <div style="margin-top:10px">
      <button id="btn-paid" style="padding:8px 12px;border-radius:8px;border:1px solid #ddd;background:#f5f5f5">Saya sudah bayar</button>
    </div>
  `;

  document.getElementById('btn-paid')?.addEventListener('click', () => {
    alert('Oke! Kami akan memverifikasi pembayaranmu segera.');
  });
}

// --- Bind & init ---
function bindUI() {
  document.getElementById('pay')?.addEventListener('click', handleCheckout);
  document.getElementById('amount')?.addEventListener('input', syncTotalText);
}
window.addEventListener('DOMContentLoaded', async () => { bindUI(); await loadConfigAndRender(); });
