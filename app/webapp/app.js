// Mini App cart flow with QR checkout
const tg = window.Telegram?.WebApp; tg?.expand();

// --- CONFIG ---
// If backend injects window.GROUPS, use it. Else fallback examples.
const GROUPS = (window.GROUPS && Array.isArray(window.GROUPS) ? window.GROUPS : [
  { id: "-100123456", label: "Group A" },
  { id: "-1007891011", label: "Group B" }
]);

// Price map; if a group id not found, defaultPrice used
const defaultPrice = 5000;
const PRICES = (window.PRICES || {
  "-100123456": 5000,
  "-1007891011": 10000
});

// --- STATE ---
const state = {
  cart: new Set(), // group ids
};

// --- HELPERS ---
function getUserId() {
  const fromInit = tg?.initDataUnsafe?.user?.id;
  if (fromInit) return fromInit;
  const qp = new URLSearchParams(window.location.search);
  const v = qp.get("uid");
  return v ? parseInt(v, 10) : null;
}

function idr(n) {
  return (n || 0).toLocaleString("id-ID");
}

function priceOf(gid) {
  return PRICES[gid] != null ? PRICES[gid] : defaultPrice;
}

function calcTotal() {
  let t = 0;
  state.cart.forEach(gid => t += priceOf(gid));
  return t;
}

function renderList() {
  const $list = document.getElementById("list");
  $list.innerHTML = "";
  GROUPS.forEach(g => {
    const chosen = state.cart.has(g.id);
    const wrap = document.createElement("div");
    wrap.className = "card";
    wrap.innerHTML = `
      <div style="flex:1">
        <div class="title">${escapeHtml(g.label)}</div>
        <div class="muted">${g.id}</div>
      </div>
      <div class="price">Rp ${idr(priceOf(g.id))}</div>
      <div class="actions">
        <button class="${chosen ? "danger" : "primary"} btn-toggle" data-id="${g.id}">
          ${chosen ? "Hapus" : "Tambah ke Keranjang"}
        </button>
      </div>
    `;
    $list.appendChild(wrap);
  });

  // bind buttons
  document.querySelectorAll(".btn-toggle").forEach(btn => {
    btn.addEventListener("click", (e) => {
      const gid = e.currentTarget.getAttribute("data-id");
      if (!gid) return;
      if (state.cart.has(gid)) state.cart.delete(gid); else state.cart.add(gid);
      updateBar();
      renderList();
    });
  });
}

function updateBar() {
  const cnt = state.cart.size;
  const tot = calcTotal();
  document.getElementById("count").textContent = String(cnt);
  document.getElementById("total").textContent = idr(tot);
  const btn = document.getElementById("checkout");
  btn.disabled = cnt === 0;
}

function showSection(id) {
  ["list", "confirm", "payview"].forEach(sec => {
    const el = document.getElementById(sec);
    el.style.display = (sec === id ? "block" : "none");
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// --- CHECKOUT FLOW ---
async function checkout() {
  const groups = Array.from(state.cart);
  const amount = calcTotal();
  if (!groups.length) return;
  // Show confirm page
  const itemsHtml = groups.map(gid => {
    const g = GROUPS.find(x => x.id === gid);
    return `<li>${escapeHtml(g?.label || gid)} — Rp ${idr(priceOf(gid))}</li>`;
  }).join("");
  document.getElementById("confirm-items").innerHTML = `<ol class="list-compact">${itemsHtml}</ol>`;
  document.getElementById("confirm-total").textContent = "Total: Rp " + idr(amount);
  showSection("confirm");
}

async function createInvoiceAndPay() {
  const uid = getUserId();
  const groups = Array.from(state.cart);
  const amount = calcTotal();
  if (!uid) {
    alert("User ID Telegram tidak terbaca. Bukalah dari dalam Telegram atau tambahkan ?uid=123 di URL saat uji coba.");
    return;
  }
  try {
    const res = await fetch("/api/invoice", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: uid, groups, amount })
    });
    if (!res.ok) throw new Error("Gagal membuat invoice");
    const data = await res.json();
    const invoiceId = data.invoice_id || data.id || data.invoice || data?.data?.invoice_id;
    if (!invoiceId) throw new Error("invoice_id tidak ditemukan di respons server");

    // Go to pay view
    document.getElementById("inv-id").textContent = invoiceId;
    document.getElementById("inv-amt").textContent = "Rp " + idr(amount);
    showSection("payview");

    // Render QR PNG served by backend
    const img = document.createElement("img");
    img.alt = "QRIS";
    img.src = `/api/qr/${invoiceId}.png`;
    const qr = document.getElementById("qr");
    qr.innerHTML = "";
    qr.appendChild(img);

    // Start polling payment status
    pollUntilPaid(invoiceId);
  } catch (e) {
    console.error(e);
    alert("Error: " + e.message);
  }
}

async function pollUntilPaid(invoiceId) {
  let tries = 0;
  const maxTries = 120; // ~5 menit @2.5s
  const btnDone = document.getElementById("btn-done");
  btnDone.onclick = () => checkOnce();

  async function checkOnce() {
    try {
      const r = await fetch(`/api/invoice/${invoiceId}/status`);
      if (!r.ok) throw new Error("Cek status gagal");
      const s = await r.json();
      const st = (s.status || "").toUpperCase();
      if (st === "PAID") {
        tg?.close?.();
        return;
      }
    } catch (err) {
      console.warn("Polling error:", err);
    }
  }

  const timer = setInterval(async () => {
    tries++;
    await checkOnce();
    if (tries >= maxTries) clearInterval(timer);
  }, 2500);
}

// --- INIT ---
renderList();
updateBar();
showSection("list");

document.getElementById("checkout").addEventListener("click", checkout);
document.getElementById("btn-back").addEventListener("click", () => showSection("list"));
document.getElementById("btn-pay").addEventListener("click", createInvoiceAndPay);
