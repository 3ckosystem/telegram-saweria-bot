// app/webapp/app.js
// Telegram Mini App client for Saweria flow (GoPay scraper only-show-if-ready)

const tg = window.Telegram?.WebApp;
tg?.expand();

// (opsional) link bantu
const yourSaweriaUrl = "https://saweria.co/3ckosystem";

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

async function renderGroups() {
  const groups = (window.injectedGroups || [
    { id: "-1002593237267", label: "Group Model" },
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

document.getElementById("pay")?.addEventListener("click", async () => {
  const selected = [...document.querySelectorAll("#groups input:checked")].map(i => i.value);
  const amount = parseInt(document.getElementById("amount")?.value || "0", 10);

  if (!selected.length) return alert("Pilih minimal 1 grup");
  if (!Number.isFinite(amount) || amount <= 0) return alert("Masukkan nominal pembayaran yang valid (> 0)");

  const userId = getUserId();
  if (!userId) {
    document.getElementById("qr").innerHTML =
      `<div style="color:#c00">Gagal membaca user Telegram. Tutup & buka lagi Mini App via tombol bot.</div>`;
    return;
  }

  // Buat invoice
  let inv;
  try {
    const res = await fetch(`${window.location.origin}/api/invoice`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, groups: selected, amount }),
    });
    if (!res.ok) throw new Error(await res.text());
    inv = await res.json();
  } catch (e) {
    document.getElementById("qr").innerHTML =
      `<div style="color:#c00">Create invoice gagal: ${htmlEscape(e.message || String(e))}</div>`;
    return;
  }

  const ref = `INV:${inv.invoice_id}`;
  const qrContainer = document.getElementById('qr');
  qrContainer.innerHTML = `
    <div><b>Pembayaran GoPay</b></div>
    <div id="qruistate" style="margin:8px 0 12px 0; opacity:.85">Menyiapkan QRIS GoPay…</div>
    <!-- QR akan disisipkan DI SINI hanya jika siap -->
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

  // tombol copy
  document.getElementById('copyinv')?.addEventListener('click', async () => {
    await navigator.clipboard.writeText(ref);
    const btn = document.getElementById('copyinv');
    btn.textContent = "Copied!";
    setTimeout(() => (btn.textContent = "Copy"), 1500);
  });

  // === POLLING: cek QR dari scraper (GoPay) ===
  const statusUrl = `${window.location.origin}/api/invoice/${inv.invoice_id}/status`;
  const qrUrl = `${window.location.origin}/api/qr/${inv.invoice_id}`;
  const stateEl = document.getElementById('qruistate');

  let triesQR = 0;
  let qrShown = false;
  const pollQR = async () => {
    triesQR++;
    try {
      const r = await fetch(statusUrl);
      if (r.ok) {
        const s = await r.json();
        if (s.has_qr) {
          // render IMG hanya jika QR siap
          if (!qrShown) {
            const img = document.createElement('img');
            img.id = 'qrimg';
            img.alt = 'GoPay QR';
            img.style = 'max-width:240px;border:1px solid #eee;padding:6px;border-radius:8px';
            img.src = `${qrUrl}?t=${Date.now()}`; // cache buster
            qrContainer.insertBefore(img, document.getElementById('invcode').parentElement);
            qrShown = true;
            if (stateEl) stateEl.textContent = "QRIS GoPay siap. Silakan scan dengan GoPay.";
          }
          return; // berhenti polling QR
        }
      }
    } catch (_) {}
    if (triesQR < 10) {
      setTimeout(pollQR, 1500);
    } else {
      if (!qrShown && stateEl) stateEl.innerHTML = `<span style="color:#c00">QRIS gagal dimuat.</span>`;
    }
  };
  setTimeout(pollQR, 800);

  // === POLLING: status pembayaran (auto-close saat PAID) ===
  let pollPaidTimer = setInterval(checkPaid, 2000);
  document.getElementById('btn-done')?.addEventListener("click", () => checkPaid(true));

  async function checkPaid(manual = false) {
    try {
      const r = await fetch(statusUrl);
      if (!r.ok) return;
      const s = await r.json();
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
});