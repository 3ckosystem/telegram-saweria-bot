// app/webapp/app.js
const tg = window.Telegram?.WebApp; tg?.expand();
const yourSaweriaUrl = "https://saweria.co/3ckosystem";

function getUserId() {
  const fromInit = tg?.initDataUnsafe?.user?.id;
  if (fromInit) return fromInit;
  const qp = new URLSearchParams(window.location.search);
  const fromQuery = qp.get("uid");
  return fromQuery ? parseInt(fromQuery, 10) : null;
}

async function renderGroups() {
  const groups = (window.injectedGroups || [
    { id: "-1002593237267", label: "Group M" },
    { id: "-1001320707949", label: "Group A" },
    { id: "-1002306015599", label: "Group S" },
  ]);
  const wrap = document.getElementById("groups");
  wrap.innerHTML = "";
  groups.forEach((g) => {
    const el = document.createElement("label");
    el.style.display = "block";
    el.innerHTML = `<input type="checkbox" value="${g.id}"> ${g.label}`;
    wrap.appendChild(el);
  });
}
renderGroups();

document.getElementById("pay")?.addEventListener("click", async () => {
  const selected = [...document.querySelectorAll("#groups input:checked")].map(i=>i.value);
  const amount = parseInt(document.getElementById("amount")?.value || "0", 10);
  if (!selected.length) return alert("Pilih minimal 1 grup");
  if (!(amount > 0)) return alert("Masukkan nominal > 0");

  const userId = getUserId();
  if (!userId) {
    document.getElementById("qr").innerHTML = `<div style="color:#c00">Gagal membaca user Telegram. Tutup & buka lagi Mini App via tombol bot.</div>`;
    return;
  }

  let inv;
  try {
    const res = await fetch(`${window.location.origin}/api/invoice`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, groups: selected, amount }),
    });
    if (!res.ok) throw new Error(await res.text());
    inv = await res.json();
  } catch (e) {
    document.getElementById("qr").innerHTML = `<div style="color:#c00">Create invoice gagal: ${String(e.message || e)}</div>`;
    return;
  }

  // pakai endpoint debug QR-only untuk preview cepat
  const qrOnlyUrl = `${window.location.origin}/debug/fetch_gopay_qr_only_png?amount=${amount}&msg=${encodeURIComponent("INV:"+inv.invoice_id)}`;
  document.getElementById("qr").innerHTML = `
    <div><b>QRIS GoPay:</b></div>
    <img id="qrimg" alt="QR" style="max-width:280px;border-radius:8px;border:1px solid #eee;padding:6px" src="${qrOnlyUrl}">
    <div style="margin-top:10px"><small>Jika gagal muat, coba buka profil: <a href="${yourSaweriaUrl}" target="_blank" rel="noopener">${yourSaweriaUrl}</a></small></div>
  `;
});
