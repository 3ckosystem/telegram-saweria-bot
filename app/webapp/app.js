// app/webapp/app.js
const tg = window.Telegram.WebApp;
tg.expand();

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
  if (!selected.length || amount <= 0) {
    alert("Pilih minimal 1 grup dan nominal > 0");
    return;
  }

  const userId = tg.initDataUnsafe?.user?.id;
  if (!userId) {
    document.getElementById("qr").innerHTML =
      `<div style="color:#c00">Gagal membaca user Telegram. Tutup & buka lagi Mini App.</div>`;
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

  document.getElementById("qr").innerHTML = `
    <div><b>Scan QRIS:</b></div>
    <img id="qrimg" alt="QRIS" style="max-width:240px;border:1px solid #eee;padding:6px;border-radius:8px"
         src="${qrUrl}" />
    <div style="margin-top:6px">
      <small>Invoice ID: <code>${htmlEscape(inv.invoice_id)}</code></small>
    </div>
    <div><small>Jika gambar tidak muncul, 
      <a href="${qrUrl}" target="_blank" rel="noopener">buka di tab baru</a>.
    </small></div>
    <div style="margin-top:6px"><small>Setelah pembayaran, bot akan kirim link undangan.</small></div>
  `;

  // Tampilkan pesan kalau <img> gagal load
  setTimeout(() => {
    const img = document.getElementById("qrimg");
    if (img) {
      img.onerror = () => {
        document.getElementById("qr").insertAdjacentHTML(
          "beforeend",
          `<div style="color:#c00;margin-top:6px">QR gagal dimuat. Coba buka link di atas.</div>`
        );
      };
    }
  }, 0);
};
