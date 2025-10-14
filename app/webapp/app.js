const tg = window.Telegram.WebApp;
tg.expand();

const GROUPS = JSON.parse(decodeURIComponent((new URLSearchParams(location.search)).get('groups') || '[]'));
// Atau render dari server: untuk contoh, hardcode via window.injected

async function renderGroups() {
  // Untuk demo, minta list dari server via env (bisa embed di HTML via template)
  const res = await fetch(window.location.origin + '/');
  // Lewatkan; di produksi kirim array groups via SSR atau endpoint khusus
  const groups = (window.injectedGroups || [
    {id: "-1002593237267", label:"Group M"},
    {id: "-1001320707949", label:"Group A"},
    {id: "-1002306015599", label:"Group S"},
  ]);
  const wrap = document.getElementById('groups');
  groups.forEach(g=>{
    const el = document.createElement('label');
    el.style.display="block";
    el.innerHTML = `<input type="checkbox" value="${g.id}"/> ${g.label}`;
    wrap.appendChild(el);
  });
}

renderGroups();

document.getElementById('pay').onclick = async () => {
  const selected = [...document.querySelectorAll('#groups input:checked')].map(i=>i.value);
  const amount = parseInt(document.getElementById('amount').value||'0',10);
  if (!selected.length || amount<=0) {
    alert('Pilih minimal 1 grup dan nominal > 0');
    return;
  }
  const userId = tg.initDataUnsafe?.user?.id; // id Telegram user
  const inv = await fetch(window.location.origin + '/api/invoice', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ user_id: userId, groups: selected, amount })
  }).then(r=>r.json());

  // Tampilkan QR (di produksi: render image QR dari Saweria)
  document.getElementById('qr').innerHTML = `
    <div><b>Scan QRIS berikut:</b></div>
    <pre style="white-space:pre-wrap;border:1px solid #ddd;padding:8px">${inv.qr}</pre>
    <small>Setelah paid, bot akan kirim link undangan ke chat kamu.</small>
  `;
};
