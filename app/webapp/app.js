// Telegram Mini App client – QR disajikan sebagai URL PNG langsung
// FINAL: message tidak lagi pakai 'initial', tapi 'INV:<invoice_id>' setelah create invoice sukses.

const tg = window.Telegram?.WebApp;
tg?.expand();

// === Global state ===
let PRICE_PER_GROUP = 25000;
let LOADED_GROUPS = [];

// --- Utils ---
function htmlEscape(s) {
  return String(s || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function formatRupiah(n) {
  try {
    const v = Number(n || 0);
    return v.toLocaleString("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 });
  } catch {
    return `Rp ${n}`;
  }
}

function getTelegramUserId() {
  // Ambil user_id dari Telegram WebApp initData jika ada
  try {
    const id = tg?.initDataUnsafe?.user?.id || tg?.initData?.user?.id;
    if (id) return Number(id);
  } catch {}
  return null;
}

// --- Render groups & config ---
async function loadConfigAndRender() {
  try {
    const r = await fetch("/api/config");
    const cfg = await r.json();

    PRICE_PER_GROUP = parseInt(cfg?.price_idr ?? "25000", 10) || 25000;
    LOADED_GROUPS = Array.isArray(cfg?.groups) ? cfg.groups : [];

    const box = document.getElementById("groups");
    if (box) {
      box.innerHTML = "";
      LOADED_GROUPS.forEach((g, idx) => {
        // Struktur group contoh: { id: "100xxx", initial: "M", name: "Group M" }
        const id = `g-${idx}`;
        const wrapper = document.createElement("label");
        wrapper.style.display = "flex";
        wrapper.style.alignItems = "center";
        wrapper.style.gap = "10px";
        wrapper.style.padding = "8px 10px";
        wrapper.style.border = "1px solid #eee";
        wrapper.style.borderRadius = "8px";
        wrapper.style.marginBottom = "8px";

        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.id = id;
        cb.value = g?.id || "";
        cb.dataset.initial = (g?.initial || "").trim();
        cb.dataset.name = (g?.name || "").trim();

        const text = document.createElement("div");
        text.innerHTML = `<div style="font-weight:600">${htmlEscape(g?.name || g?.id || "Group")}</div>
                          <div style="font-size:12px;color:#666">ID: ${htmlEscape(g?.id || "-")}</div>`;

        wrapper.appendChild(cb);
        wrapper.appendChild(text);
        box.appendChild(wrapper);
      });

      // event: pilih/ubah grup -> hitung ulang total & amount
      box.addEventListener("change", () => {
        recalcAmountFromGroups();
        setTimeout(syncTotalText, 0);
      });
    }

    // set placeholder harga default
    const amountEl = document.getElementById("amount");
    if (amountEl && !amountEl.value) {
      amountEl.value = String(PRICE_PER_GROUP);
    }

    // set tampilan total awal
    setTimeout(syncTotalText, 0);
  } catch (e) {
    console.error("loadConfig error:", e);
  }
}

function recalcAmountFromGroups() {
  try {
    const amountEl = document.getElementById("amount");
    const checked = [...document.querySelectorAll('#groups input[type="checkbox"]:checked')];
    const total = (checked.length || 0) * PRICE_PER_GROUP;
    if (amountEl && total > 0) {
      amountEl.value = String(total);
    }
  } catch (_) {}
}

function syncTotalText() {
  const tt = document.getElementById("total-text");
  const amt = parseInt(document.getElementById("amount")?.value || "0", 10);
  if (tt) tt.textContent = formatRupiah(amt || 0);
}

// --- Checkout flow ---
async function handleCheckout() {
  const qrContainer = document.getElementById("qr");
  if (qrContainer) qrContainer.innerHTML = "";

  // Kumpulkan data
  const userId = getTelegramUserId() || Number(document.getElementById("user_id")?.value || 0) || null;
  const amount = parseInt(document.getElementById("amount")?.value || "0", 10) || 0;
  const checked = [...document.querySelectorAll('#groups input[type="checkbox"]:checked')];
  const groups = checked.map(i => (i.value || "").trim()).filter(Boolean);

  // Validasi
  if (!userId) {
    qrContainer.innerHTML = `<div style="color:#c00">User ID Telegram tidak terdeteksi. Buka dari Telegram Mini App atau isi manual.</div>`;
    return;
  }
  if (!groups.length) {
    qrContainer.innerHTML = `<div style="color:#c00">Pilih minimal satu grup terlebih dahulu.</div>`;
    return;
  }
  if (!amount || amount <= 0) {
    qrContainer.innerHTML = `<div style="color:#c00">Nominal tidak valid.</div>`;
    return;
  }

  // 1) Create invoice
  let inv;
  try {
    const res = await fetch("/api/invoice", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ user_id: userId, groups, amount })
    });
    if (!res.ok) throw new Error(await res.text());
    inv = await res.json(); // { invoice_id: "..." }
  } catch (e) {
    qrContainer.innerHTML =
      `<div style="color:#c00">Create invoice gagal: ${htmlEscape(e.message || String(e))}</div>`;
    return;
  }

  // 2) SET PESAN = NOMOR INVOICE (bukan lagi initial)
  const invMessage = `INV:${inv.invoice_id}`;
  const msgEl = document.getElementById("msg-preview");
  if (msgEl) msgEl.textContent = `Pesan: ${invMessage}`;

  // 3) Tampilkan QR PNG + detail invoice
  const qrPngUrl = `${window.location.origin}/api/qr/${encodeURIComponent(inv.invoice_id)}`;
  const detailHtml = `
    <div style="padding:8px 0">
      <div><b>Invoice:</b> ${htmlEscape(inv.invoice_id)}</div>
      <div><b>Total:</b> ${htmlEscape(formatRupiah(amount))}</div>
      <div><b>Groups:</b> ${htmlEscape(groups.join(", "))}</div>
      <div style="font-size:12px;color:#666;margin-top:4px">Gunakan QR berikut untuk pembayaran.</div>
    </div>
    <div><img src="${qrPngUrl}" alt="QRIS" style="max-width:240px;border:1px solid #eee;padding:6px;border-radius:8px" /></div>
    <div style="margin-top:10px">
      <button id="btn-paid" style="padding:8px 12px;border-radius:8px;border:1px solid #ddd;background:#f5f5f5">Saya sudah bayar</button>
    </div>
  `;
  qrContainer.innerHTML = detailHtml;

  // 4) Tombol "Saya sudah bayar" (opsional: ping webhook/cek status)
  document.getElementById("btn-paid")?.addEventListener("click", async () => {
    // Kamu bisa tambahkan call ke endpoint cek status kalau ada:
    // const r = await fetch(`/api/invoice/${inv.invoice_id}/status`);
    // dst. Untuk sekarang tampilkan feedback sederhana:
    alert("Oke! Kami akan memverifikasi pembayaranmu segera.");
  });
}

// --- Bind UI ---
function bindUI() {
  document.getElementById("pay")?.addEventListener("click", handleCheckout);

  // Bila user ubah nominal manual, update tampilan total
  document.getElementById("amount")?.addEventListener("input", () => {
    syncTotalText();
  });
}

// --- Init ---
window.addEventListener("DOMContentLoaded", async () => {
  bindUI();
  await loadConfigAndRender();
});
