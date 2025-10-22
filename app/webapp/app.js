// Telegram Mini App client – QR disajikan sebagai URL PNG langsung

const tg = window.Telegram?.WebApp;
tg?.expand();

// === Load config (groups + price) from backend ===
let PRICE_PER_GROUP = 25000;
let LOADED_GROUPS = [];

async function loadConfigAndRender() {
  try {
    const r = await fetch('/api/config');
    const cfg = await r.json();
    PRICE_PER_GROUP = parseInt(cfg?.price_idr ?? '25000', 10) || 25000;
    LOADED_GROUPS = Array.isArray(cfg?.groups) ? cfg.groups : [];
    const box = document.getElementById('groups');
    if (box) {
      box.innerHTML = '';
      (LOADED_GROUPS || []).forEach(g => {
        const id = String(g.id);
        const name = String(g.name ?? id);
        const row = document.createElement('div');
        row.innerHTML = `<label><input type="checkbox" value="${id}"/> ${name}</label>`;
        box.appendChild(row);
      });
    }
    // trigger recalc & sync after rendering
    setTimeout(() => { recalcAmountFromGroups?.(); syncTotalText?.(); }, 0);
  } catch (_) {
    // fallback: nothing
  }
}

document.addEventListener('DOMContentLoaded', loadConfigAndRender);


// (opsional) link bantu
const yourSaweriaUrl = "https://saweria.co/payments";

// -------- util ----------
function getUserId() {
  const fromInit = tg?.initDataUnsafe?.user?.id;
  if (fromInit) return fromInit;
  const qp = new URLSearchParams(window.location.search);
  const fromQuery = qp.get("uid");
  return fromQuery ? parseInt(fromQuery, 10) : null;
}
function htmlEscape(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

// ------- render daftar grup (boleh di-inject dari server lewat window.injectedGroups) ------
async function renderGroups() {
  const groups = (window.injectedGroups || [
    { id: "-1002593237267", label: "Group Model" },
    { id: "-1001320707949", label: "Group A" },
    { id: "-1002306015599", label: "Group S" },
  ]);
  const wrap = document.getElementById("groups");
  if (!wrap) return;
  wrap.innerHTML = "";
  groups.forEach((g, idx) => {
    const el = document.createElement("label");
    el.style.display = "block";
    el.innerHTML = `<input type="checkbox" ${idx===0 ? "checked" : ""} value="${g.id}"/> ${htmlEscape(g.label)}`;
    wrap.appendChild(el);
  });
}
renderGroups();

// ------------- aksi bayar ----------------
document.getElementById("pay")?.addEventListener("click", onPay);

async function onPay() {
  const selected = [...document.querySelectorAll("#groups input:checked")].map(i => i.value);
  const amount = parseInt(document.getElementById("amount")?.value || "0", 10);

  if (!selected.length) return alert("Pilih minimal 1 grup");
  if (!Number.isFinite(amount) || amount <= 0) return alert("Masukkan nominal pembayaran yang valid (> 0)");

  const userId = getUserId();
  const qrContainer = document.getElementById("qr");
  if (!userId) {
    qrContainer.innerHTML =
      `<div style="color:#c00">Gagal membaca user Telegram. Tutup & buka lagi Mini App via tombol bot.</div>`;
    return;
  }

  // 1) Buat invoice di server
  let inv;
  try {
    const res = await fetch(`${window.location.origin}/api/invoice`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, groups: selected, amount }),
    });
    if (!res.ok) throw new Error(await res.text());
    inv = await res.json(); // { invoice_id: "..." }
  } catch (e) {
    qrContainer.innerHTML =
      `<div style="color:#c00">Create invoice gagal: ${htmlEscape(e.message || String(e))}</div>`;
    return;
  }

  // 2) Susun tampilan + QR IMG LANGSUNG
  const ref = `INV:${inv.invoice_id}`;
  const qrPngUrl = `${window.location.origin}/api/qr/${inv.invoice_id}.png?amount=${amount}&msg=${encodeURIComponent(ref)}`;

  qrContainer.innerHTML = `
    <div><b>Pembayaran GoPay</b></div>
    <div id="qruistate" style="margin:8px 0 12px 0; opacity:.85">QRIS GoPay sedang dimuat…</div>

    <div id="qrwrap" style="margin-bottom:8px"></div>

    <div style="margin-top:8px"><b>Kode pembayaran:</b> <code id="invcode">${htmlEscape(ref)}</code>
      <button id="copyinv" style="margin-left:6px">Copy</button>
    </div>
    <ol style="margin-top:8px;padding-left:18px">
      <li>Jika perlu, buka: <a href="${yourSaweriaUrl}" target="_blank" rel="noopener">${yourSaweriaUrl}</a></li>
      <li>Tempel kode <b>${htmlEscape(ref)}</b> di kolom <i>pesan</i> sebelum bayar (opsional bila scan QR).</li>
      <li>Setelah bayar, Mini App menutup otomatis dan bot mengirim link undangan.</li>
    </ol>

    <div id="wait" style="margin-top:12px">
      <b>Menunggu pembayaran…</b>
      <div id="spinner" style="opacity:.75">Bot akan kirim undangan otomatis setelah pembayaran diterima.</div>
      <button id="btn-done" style="margin-top:8px">Saya sudah bayar</button>
    </div>
  `;

  // sisipkan IMG QR; biarkan browser "menunggu" sampai server selesai render PNG
  const img = document.createElement("img");
  img.id = "qrimg";
  img.alt = "GoPay QR";
  img.src = qrPngUrl + `&t=${Date.now()}`;     // cache buster
  img.onload = () => {
    const st = document.getElementById("qruistate");
    if (st) st.textContent = "QRIS GoPay siap. Silakan scan dengan GoPay.";
  };
  img.onerror = () => {
    const st = document.getElementById("qruistate");
    if (st) st.innerHTML = `<span style="color:#c00">QRIS gagal dimuat.</span> Coba buka <a href="${yourSaweriaUrl}" target="_blank" rel="noopener">Saweria</a> dan tempel kode di atas.`;
  };
  document.getElementById("qrwrap")?.appendChild(img);

  // tombol copy
  document.getElementById('copyinv')?.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(ref);
      const btn = document.getElementById('copyinv');
      btn.textContent = "Copied!";
      setTimeout(() => (btn.textContent = "Copy"), 1500);
    } catch (_) {}
  });

  // 3) POLLING status pembayaran (auto-close saat PAID)
  const statusUrl = `${window.location.origin}/api/invoice/${inv.invoice_id}/status`;
  let pollPaidTimer = setInterval(checkPaid, 2000);
  document.getElementById('btn-done')?.addEventListener("click", () => checkPaid(true));

  async function checkPaid(manual = false) {
    try {
      const r = await fetch(statusUrl);
      if (!r.ok) return;
      const s = await r.json(); // {status: "PENDING"|"PAID", ...}
      if (s.status === "PAID") {
        clearInterval(pollPaidTimer);
        const wait = document.getElementById('wait');
        if (wait) wait.innerHTML = `<div style="color:green"><b>Pembayaran diterima.</b> Undangan dikirim via DM bot.</div>`;
        setTimeout(() => tg?.close?.(), 2000);
      } else if (manual) {
        const sp = document.getElementById('spinner');
        if (sp) sp.textContent = "Belum terdeteksi. Jika sudah bayar, tunggu beberapa detik…";
      }
    } catch (_) {}
  }
}


// === Auto-calc total based on selected groups =====================
// Harga per grup (IDR)
/* PRICE_PER_GROUP moved to config */

// Hitung ulang total saat user centang/menyangga pilihan
function recalcAmountFromGroups() {
  try {
    const checked = document.querySelectorAll('#groups input[type="checkbox"]:checked');
    const amountEl = document.getElementById('amount');
    if (!amountEl) return;
    const total = (checked?.length || 0) * PRICE_PER_GROUP;
    if (total > 0) {
      amountEl.value = String(total);
    } else {
      // fallback jika belum ada yang dipilih, biarkan default di input
    }
  } catch (_) {}
}

// Pasang event listener delegasi pada container groups
(function initGroupRecalc() {
  const container = document.getElementById('groups');
  if (!container) return;
  container.addEventListener('change', (e) => {
    // hanya respons saat checkbox berubah
    const t = e.target;
    if (t && t.matches && t.matches('input[type="checkbox"]')) {
      recalcAmountFromGroups();
    }
  });
  // Recalc saat awal render juga (jaga-jaga jika ada default tercentang)
  setTimeout(recalcAmountFromGroups, 0);
})();


// helper format rupiah
function formatRupiah(n) {
  if (!Number.isFinite(n)) return "0";
  return "Rp " + n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
}

/** sinkronkan tampilan total (Rp) dengan nilai #amount */
function syncTotalText() {
  const tt = document.getElementById('total-text');
  const amt = parseInt(document.getElementById('amount')?.value || '0', 10);
  if (tt) tt.textContent = formatRupiah(amt || 0);
}

// update saat user ganti pilihan grup
document.getElementById('groups')?.addEventListener('change', () => {
  setTimeout(syncTotalText, 0); // setelah recalcAmountFromGroups jalan
});

// set nilai awal tampilan total
setTimeout(syncTotalText, 0);
