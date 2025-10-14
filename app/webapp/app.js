// app/webapp/app.js
// Telegram Mini App client for Saweria flow (with scraper QR + status polling)

const tg = window.Telegram?.WebApp;
tg?.expand();

// GANTI dengan username Saweria kamu (untuk link bantu di UI)
const yourSaweriaUrl = "https://saweria.co/3ckosystem";

// ---------- helpers ----------
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

// ---------- render groups (sinkronkan dengan GROUP_IDS_JSON server) ----------
async function renderGroups() {
  const groups = (window.injectedGroups || [
    { id: "-1002593237267", label: "Group M" },
    { id: "-1001320707949", label: "Group A" },
    { id: "-1002306015599", label: "Group S" },
  ]);
  const wrap = document.getElementById("groups");
  if (!wrap) return;
  wrap.innerHTML = "";
  groups.forEach((g) => {
    const el = document.createElement("label");
    el.style.display = "block";
    el.innerHTML = `<input type="checkbox" value="${g.id}"/> ${htmlEscape(g.label)}`;
    wrap.appendChild(el);
  });
}
renderGroups();

// ---------- main click handler ----------
document.getElementById("pay")?.addEventListener("click", async () => {
  const selected = [...document.querySelectorAll("#groups input:checked")].map(i => i.value);
  const amount = parseInt(document.getElementById("amount")?.value || "0", 10);

  // Validasi sederhana
  if (!selected.length) {
    alert("Pilih minimal 1 grup");
    return;
  }
  if (!Number.isFinite(amount) || amount <= 0) {
    alert("Masukkan nominal pembayaran yang valid (> 0)");
    return;
  }

  const userId = getUserId();
  if (!userId) {
    document.getElementById("qr").innerHTML =
      `<div style="color:#c00">Gagal membaca user Telegram. Tutup & buka lagi Mini App via tombol bot.</div>`;
    return;
  }

  // Create invoice
  let inv;
  try {
    const res = await fetch(`${window.location.origin}/api/invoice`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, groups: selected, amount }),
    });
    if (!res.ok) {
      const txt = await res.text();
      throw new Error(`Create invoice gagal: ${txt}`);
    }
    inv = await res.json();
  } catch (e) {
    document.getElementById("qr").innerHTML =
      `<div style="color:#c00">${htmlEscape(e.message)}</div>`;
    return;
  }

  // Ref code (untuk ditempel user di kolom pesan jika perlu)
  const ref = `INV:${inv.invoice_id}`;

  // URL QR di backend (akan menampilkan PNG dari qris_payload atau fallback)
  const qrUrl = `${window.location.origin}/api/qr/${inv.invoice_id}`;

  // Render UI pembayaran
  document.getElementById('qr').innerHTML = `
    <div><b>Scan QR (akan diperbarui otomatis):</b></div>
    <img id="qrimg" alt="QRIS" style="max-width:240px;border:1px solid #eee;padding:6px;border-radius:8px"
         src="${qrUrl}" />
    <div style="margin-top:12px"><b>Kode pembayaran:</b> <code id="invcode">${htmlEscape(ref)}</code>
      <button id="copyinv" style="margin-left:6px">Copy</button>
    </div>
    <ol style="margin-top:8px;padding-left:18px">
      <li>Buka halaman Saweria (opsional jika tidak scan): <a href="${yourSaweriaUrl}" target="_blank" rel="noopener">${yourSaweriaUrl}</a></li>
      <li>Jika diperlukan, tempel kode <b>${htmlEscape(ref)}</b> di kolom <i>pesan</i> sebelum bayar.</li>
      <li>Setelah bayar, Mini App akan menutup otomatis dan bot mengirim link undangan.</li>
    </ol>
    <div id="wait" style="margin-top:12px">
      <b>Menunggu pembayaran...</b>
      <div id="spinner" style="opacity:.75">Bot akan kirim undangan otomatis setelah pembayaran diterima.</div>
      <button id="btn-done" style="margin-top:8px">Saya sudah bayar</button>
    </div>
  `;

  // Tombol copy + error handler untuk QR image
  setTimeout(() => {
    const btn = document.getElementById('copyinv');
    if (btn) btn.onclick = async () => {
      await navigator.clipboard.writeText(ref);
      btn.textContent = "Copied!";
      setTimeout(() => btn.textContent = "Copy", 1500);
    };
    const img = document.getElementById('qrimg');
    if (img) img.onerror = () => {
      document.getElementById('qr').insertAdjacentHTML(
        'beforeend',
        `<div style="color:#c00;margin-top:6px">QR gagal dimuat. Coba buka langsung: <a href="${qrUrl}" target="_blank" rel="noopener">${qrUrl}</a></div>`
      );
    };
  }, 0);

  // === AUTO-RELOAD QR hasil scraper (max 10x @1.5s) ===
  (function autoReloadQR() {
    let tries = 0;
    const img = document.getElementById('qrimg');
    if (!img) return;
    const reload = () => {
      tries++;
      img.src = `${qrUrl}?t=${Date.now()}`; // cache buster
      if (tries < 10) setTimeout(reload, 1500);
    };
    setTimeout(reload, 1200);
  })();

  // === POLLING STATUS (tutup otomatis saat PAID) ===
  let pollTimer = setInterval(() => checkPaid(inv.invoice_id, false), 2000);
  document.getElementById('btn-done')?.addEventListener("click", () => checkPaid(inv.invoice_id, true));

  async function checkPaid(id, manual) {
    try {
      const r = await fetch(`${window.location.origin}/api/invoice/${id}/status`);
      if (!r.ok) return;
      const s = await r.json();
      if (s.status === "PAID") {
        clearInterval(pollTimer);
        const wait = document.getElementById('wait');
        if (wait) {
          wait.innerHTML = `<div style="color:green"><b>Pembayaran diterima.</b> Undangan dikirim via DM bot.</div>`;
        }
        setTimeout(() => tg?.close?.(), 2000);
      } else if (manual) {
        const sp = document.getElementById('spinner');
        if (sp) sp.textContent = "Belum terdeteksi. Jika sudah bayar, tunggu beberapa detik…";
      }
    } catch (_) { /* abaikan error jaringan ringan */ }
  }
});
