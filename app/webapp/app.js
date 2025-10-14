// app/webapp/app.js
const tg = window.Telegram.WebApp;
const yourSaweriaUrl = "https://saweria.co/<username_kamu>"; // ganti username

// ...setelah buat invoice & bikin qrUrl...
const ref = `INV:${inv.invoice_id}`;

tg.expand();

function getUserId() {
  const fromInit = tg?.initDataUnsafe?.user?.id;
  if (fromInit) return fromInit;
  const qp = new URLSearchParams(window.location.search);
  const fromQuery = qp.get("uid");
  return fromQuery ? parseInt(fromQuery, 10) : null;
}

// Render daftar grup (dari hardcode/SSR)
async function renderGroups() {
  const groups = (window.injectedGroups || [
    { id: "-1002593237267", label: "Group M" },
    { id: "-1001320707949", label: "Group A" },
    { id: "-1002306015599", label: "Group S" },
  ]);
  const wrap = document.getElementById("groups");
  groups.forEach((g) => {
    const el = document.createElement("label");
    el.style.display = "block";
    el.innerHTML = `<input type="checkbox" value="${g.id}"/> ${g.label}`;
    wrap.appendChild(el);
  });
}
renderGroups();

function htmlEscape(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

document.getElementById("pay").onclick = async () => {
  const selected = [...document.querySelectorAll("#groups input:checked")].map(i => i.value);
  const amount = parseInt(document.getElementById("amount").value || "0", 10);

  const userId = getUserId();
  if (!userId) {
    document.getElementById("qr").innerHTML =
      `<div style="color:#c00">Gagal membaca user Telegram. Tutup & buka lagi Mini App via tombol bot.</div>`;
    return;
  }

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

  // PENTING: pakai URL absolut agar aman di web-view Mini App
  const qrUrl = `${window.location.origin}/api/qr/${inv.invoice_id}`;

  document.getElementById('qr').innerHTML = `
  <div><b>Scan QRIS (opsional):</b></div>
  <img id="qrimg" alt="QRIS" style="max-width:240px;border:1px solid #eee;padding:6px;border-radius:8px"
       src="${qrUrl}" />
  <div style="margin-top:12px"><b>Kode pembayaran:</b> <code id="invcode">${ref}</code>
    <button id="copyinv" style="margin-left:6px">Copy</button>
  </div>
  <ol style="margin-top:8px;padding-left:18px">
    <li>Buka halaman Saweria: <a href="${yourSaweriaUrl}" target="_blank" rel="noopener">${yourSaweriaUrl}</a></li>
    <li>Tempel kode <b>${ref}</b> di kolom <i>pesan</i> sebelum bayar.</li>
    <li>Kirim pembayaran. Bot akan otomatis DM link undangan.</li>
  </ol>
`;

  // Tampilkan pesan kalau <img> gagal load
  setTimeout(() => {
    const btn = document.getElementById('copyinv');
    if (btn) btn.onclick = async () => {
        await navigator.clipboard.writeText(ref);
        btn.textContent = "Copied!";
        setTimeout(() => btn.textContent = "Copy", 1500);
    };
    }, 0);
};
