# app/scraper.py (FINAL) — pastikan Nama/Email/Pesan terisi + pilih GoPay + ambil QR HD
from __future__ import annotations
import os, re, uuid, base64, asyncio
from typing import Optional
from urllib.parse import urljoin
from playwright.async_api import async_playwright, Page, Frame

SAWERIA_USERNAME = os.getenv("SAWERIA_USERNAME", "").strip()
PROFILE_URL = f"https://saweria.co/{SAWERIA_USERNAME}" if SAWERIA_USERNAME else None

WAIT_TOTAL_MS = int(os.getenv("SCRAPER_WAIT_TOTAL_MS", "6000"))
WAIT_QR_MS    = int(os.getenv("SCRAPER_WAIT_QR_MS", "12000"))
MAX_RETRY     = int(os.getenv("SCRAPER_MAX_RETRY", "3"))
FORCE_DISPATCH = True

_PLAY = None
_BROWSER = None

_UUID_RE = re.compile(r"(?i)\b([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b")

# ----------------- browser ctx -----------------
async def _get_browser():
    global _PLAY, _BROWSER
    if _PLAY is None:
        _PLAY = await async_playwright().start()
    if _BROWSER is None:
        _BROWSER = await _PLAY.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox","--disable-gpu","--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled"
            ],
        )
    return _BROWSER

async def _new_context():
    b = await _get_browser()
    return await b.new_context(
        user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
        viewport={"width": 1366, "height": 960},
        device_scale_factor=2, locale="id-ID", timezone_id="Asia/Jakarta",
    )

# ----------------- helpers -----------------
async def _maybe_dispatch(page: Page, handle):
    if not FORCE_DISPATCH or handle is None:
        return
    try:
        await page.evaluate(
            "(e)=>{ if(!e) return;"
            " const ev=(t)=>e.dispatchEvent(new Event(t,{bubbles:true}));"
            " ev('input'); ev('change'); e.blur && e.blur(); }",
            handle,
        )
    except Exception:
        pass

async def _native_set_and_dispatch(page: Page, handle, value: str):
    """Set via native setter (untuk React-controlled input) + event input/change."""
    try:
        await page.evaluate(
            """(e, val) => {
                if(!e) return;
                const d = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')
                        || Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value');
                if (d && d.set) d.set.call(e, val); else e.value = val;
                e.dispatchEvent(new Event('input', {bubbles:true}));
                e.dispatchEvent(new Event('change', {bubbles:true}));
                e.blur && e.blur();
            }""",
            handle, value
        )
    except Exception:
        pass

async def _set_input_and_commit(locator, value: str):
    # kombinasi: clear + type + native setter + events
    try:
        await locator.click()
        try: await locator.fill("")  # cepat
        except Exception:
            try:
                await locator.press("Control+A")
            except Exception:
                await locator.press("Meta+A")
            await locator.press("Backspace")
        await locator.type(str(value), delay=25)
        await locator.dispatch_event("input")
        await locator.dispatch_event("change")
        await locator.blur()
    except Exception:
        pass

async def _wait_total_updated(page: Page, timeout_ms: int) -> bool:
    step = 250
    for _ in range(max(1, timeout_ms // step)):
        try:
            ok = await page.evaluate(
                """
                () => {
                  const nodes = Array.from(document.querySelectorAll('*'));
                  const target = nodes.find(n => /Total\\s*:\\s*Rp/i.test(n.textContent||''));
                  if (!target) return false;
                  const txt = (target.textContent||'').replace(/\\s+/g,' ');
                  const m = txt.match(/Total\\s*:\\s*Rp\\s*([\\d.]+)/i);
                  if (!m) return false;
                  const val = parseInt(m[1].replace(/[.]/g,''));
                  return Number.isFinite(val) && val > 0;
                }
                """
            )
            if ok:
                return True
        except Exception:
            pass
        await asyncio.sleep(step / 1000)
    return False

async def _select_gopay_and_wait_total(page: Page, amount: int):
    sels = [
        '[data-testid="gopay-button"]',
        'button[data-testid="gopay-button"]',
        'button:has-text("GoPay")',
        '[role="radio"]:has-text("GoPay")',
        '[data-testid*="gopay"]',
    ]
    for sel in sels:
        try:
            el = await page.wait_for_selector(sel, timeout=2500)
            await el.scroll_into_view_if_needed()
            await el.click(force=True)
            break
        except Exception:
            pass
    await page.wait_for_timeout(200)
    if await _wait_total_updated(page, WAIT_TOTAL_MS):
        return
    # recovery: retype amount
    for sel in [
        'input[placeholder*="Ketik jumlah" i]',
        'input[aria-label*="Nominal" i]',
        'input[name="amount"]',
        'input[type="number"]',
        'input[autocomplete="off"] >> nth=0',
    ]:
        try:
            loc = page.locator(sel)
            if await loc.count() > 0:
                await _set_input_and_commit(loc.first(), str(int(amount)))
                await page.wait_for_timeout(350)
                if await _wait_total_updated(page, 3000):
                    return
                break
        except Exception:
            pass

# ----------------- name/email/message fill (super-robust) -----------------
async def _ensure_name_filled(page: Page, value: str = "Budi") -> bool:
    sels = [
        'input[name="name"]',
        'input[placeholder*="Dari" i]',
        'input[aria-label*="Dari" i]',
        'label:has-text("Dari") ~ input',
        'input[required][type="text"]',
        'input[type="text"]',
    ]
    # 1) coba selector umum
    for sel in sels:
        try:
            el = await page.wait_for_selector(sel, timeout=1500)
            await el.scroll_into_view_if_needed()
            await _set_input_and_commit(el, value)
            await _maybe_dispatch(page, el)
            ok = await el.evaluate("e => !!(e.value && e.value.trim().length)")
            if ok:
                return True
            # 2) paksa via native setter
            await _native_set_and_dispatch(page, el, value)
            ok = await el.evaluate("e => !!(e.value && e.value.trim().length)")
            if ok:
                return True
        except Exception:
            pass

    # 3) heuristik: cari input terdekat label 'Dari'
    try:
        found = await page.evaluateHandle("""
        () => {
          const labs = Array.from(document.querySelectorAll('label'));
          const lab = labs.find(l => /\\bDari\\b/i.test(l.textContent||''));
          if (!lab) return null;
          const next = lab.nextElementSibling;
          if (next && next.tagName==='INPUT') return next;
          return lab.parentElement && lab.parentElement.querySelector('input');
        }""")
        if found:
            await _native_set_and_dispatch(page, found, value)
            ok = await page.evaluate("(e)=>!!(e.value && e.value.trim().length)", found)
            if ok:
                return True
    except Exception:
        pass

    # 4) brute force: isi semua input text yang kosong pertama
    try:
        inputs = page.locator('input[type="text"]')
        n = await inputs.count()
        for i in range(min(n, 4)):
            el = inputs.nth(i)
            v = await el.evaluate("e => e.value || ''")
            if not v:
                await _native_set_and_dispatch(page, el, value)
                ok = await el.evaluate("e => !!(e.value && e.value.trim().length)")
                if ok:
                    return True
    except Exception:
        pass
    return False

# ----------------- fill form -----------------
async def _fill_without_submit(page: Page, amount: int, message: str, method: str):
    # amount
    amount_handle = None
    for sel in [
        'input[placeholder*="Ketik jumlah" i]',
        'input[aria-label*="Nominal" i]',
        'input[name="amount"]',
        'input[type="number"]',
        'input[autocomplete="off"] >> nth=0',
    ]:
        try:
            el = await page.wait_for_selector(sel, timeout=3000)
            await el.scroll_into_view_if_needed()
            await el.click()
            await _set_input_and_commit(el, str(int(amount)))
            amount_handle = el
            break
        except Exception:
            pass
    await _maybe_dispatch(page, amount_handle)
    await page.wait_for_timeout(160)

    # NAME — pastikan benar-benar terisi
    filled = await _ensure_name_filled(page, "Budi")
    if not filled:
        # satu tembakan terakhir: cari input apa saja yang required dan kosong
        try:
            el = await page.wait_for_selector('input[required]', timeout=800)
            await _native_set_and_dispatch(page, el, "Budi")
        except Exception:
            pass

    # email
    try:
        el = await page.wait_for_selector('input[type="email"]', timeout=1800)
        await _native_set_and_dispatch(page, el, f"donor+{uuid.uuid4().hex[:8]}@example.com")
    except Exception:
        pass

    # message normalization -> ensure INV:<uuid>
    norm = (message or "").strip()
    if not norm.upper().startswith("INV:"):
        m = _UUID_RE.search(norm)
        if m:
            norm = f"INV:{m.group(1)}"
    try:
        el = await page.wait_for_selector('input[name="message"], input[data-testid="message-input"], #message, textarea[name="message"], textarea', timeout=1800)
        await el.scroll_into_view_if_needed()
        await _native_set_and_dispatch(page, el, norm)
    except Exception:
        pass

    # centang checkbox wajib
    for text in ["17 tahun", "tujuh belas tahun", "menyetujui", "ketentuan", "kebijakan privasi"]:
        try:
            node = page.get_by_text(re.compile(text, re.I))
            await node.scroll_into_view_if_needed()
            await node.click()
        except Exception:
            pass
    try:
        # jaga-jaga: centang langsung input[type=checkbox]
        boxes = page.locator('input[type="checkbox"]')
        n = await boxes.count()
        for i in range(min(n, 3)):
            b = boxes.nth(i)
            if not await b.is_checked():
                await b.check(force=True)
    except Exception:
        pass

    # pilih GoPay
    if (method or "gopay").lower() == "gopay":
        await _select_gopay_and_wait_total(page, amount)
    await page.wait_for_timeout(280)

# ----------------- donate & checkout -----------------
async def _click_donate_and_get_checkout_page(page: Page, context):
    new_page_task = context.wait_for_event("page")
    clicked = False
    for sel in [
        'button[data-testid="donate-button"]',
        'button:has-text("Kirim Dukungan")',
        'text=/\\bKirim\\s+Dukungan\\b/i',
    ]:
        try:
            el = await page.wait_for_selector(sel, timeout=3000)
            await el.scroll_into_view_if_needed()
            await el.click()
            clicked = True
            break
        except Exception:
            pass
    if not clicked:
        raise RuntimeError("Tombol 'Kirim Dukungan' tidak ditemukan")
    try:
        target_page = await new_page_task
        await target_page.wait_for_load_state("domcontentloaded")
        await target_page.wait_for_load_state("networkidle")
        return {"page": target_page, "frame": None}
    except Exception:
        pass
    try:
        await page.wait_for_load_state("networkidle", timeout=7000)
        return {"page": page, "frame": None}
    except Exception:
        pass
    for fr in page.frames:
        u = (fr.url or "").lower()
        if any(k in u for k in ["gopay", "qris", "xendit", "midtrans", "snap", "checkout", "pay"]):
            return {"page": None, "frame": fr}
    return {"page": page, "frame": None}

async def _wait_qr_ready(node: Page | Frame, timeout_ms: int):
    sels = [
        'img[alt*="QR" i]',
        'img[src^="data:image"]',
        'img[src*="qris" i]',
        'img.qr-image',
        'img.qr-image--with-wrapper',
        '[data-testid="qrcode"] img',
        '[class*="qrcode" i] img',
        "canvas",
    ]
    step = 250
    for _ in range(max(1, timeout_ms // step)):
        for sel in sels:
            try:
                loc = node.locator(sel)
                if await loc.count() > 0:
                    box = await loc.first().bounding_box()
                    if box and box["width"] > 80 and box["height"] > 80:
                        return loc.first()
            except Exception:
                pass
        await asyncio.sleep(step / 1000)
    return None

# ----------------- ENTRYPOINT -----------------
async def fetch_gopay_qr_hd_png(amount: int, message: str) -> Optional[bytes]:
    if not PROFILE_URL:
        return None
    for attempt in range(1, MAX_RETRY + 1):
        context = await _new_context()
        page = await context.new_page()
        try:
            await page.goto(PROFILE_URL, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_load_state("networkidle", timeout=8000)
            await page.wait_for_timeout(600)

            await _fill_without_submit(page, amount, message, "gopay")
            target = await _click_donate_and_get_checkout_page(page, context)
            node = target["frame"] if target["frame"] else (target["page"] or page)

            qr = await _wait_qr_ready(node, WAIT_QR_MS)
            if not qr:
                # fallback: screenshot halaman/panel
                png = await (node.screenshot(full_page=True))
                await context.close()
                return png

            tag = await qr.evaluate("(el)=>el.tagName.toLowerCase()")
            if tag == "img":
                src = await qr.evaluate("(img)=>img.currentSrc || img.src || ''")
                if src.startswith("data:image/"):
                    header, b64 = src.split(",", 1)
                    data = base64.b64decode(b64)
                    await context.close()
                    return data
                base_url = node.url if hasattr(node, "url") else page.url
                abs_url = urljoin(base_url, src)
                r = await context.request.get(abs_url, headers={"Referer": base_url}, timeout=15000)
                if r.ok:
                    data = await r.body()
                    await context.close()
                    return data
                # fallback: screenshot elemen img
                png = await qr.screenshot()
                await context.close()
                return png
            else:
                # canvas / elemen lain
                png = await qr.screenshot()
                await context.close()
                return png

        except Exception:
            try:
                await context.close()
            except Exception:
                pass
            if attempt >= MAX_RETRY:
                return None
            await asyncio.sleep(0.6 * attempt)
    return None

# (opsional) debug stubs
async def debug_snapshot(): return None
async def debug_fill_snapshot(amount:int, message:str, method:str="gopay"): return None
async def fetch_gopay_checkout_png(amount:int, message:str): return None
