# app/scraper.py
# ------------------------------------------------------------
# Scraper Saweria:
#  - Isi form (amount, name/email random, message)
#  - Pilih GoPay (tanpa submit) untuk bikin UI siap
#  - Klik "Kirim Dukungan"
#  - Ambil QR HD dari halaman/iframe checkout:
#       * jika <img> → unduh bytes-nya via context.request (share cookie)
#       * jika <canvas> / tak ada src → screenshot elemen
#       * jika elemen QR tak ketemu → screenshot panel/halaman
#
# ENV:
#   SAWERIA_USERNAME  (contoh: "payments")
#   (opsional) Tuning waktu:
#     SCRAPER_WAIT_TOTAL_MS (default 6000)
#     SCRAPER_WAIT_QR_MS    (default 12000)
#     SCRAPER_MAX_RETRY     (default 3)
# ------------------------------------------------------------

from __future__ import annotations
import os, re, uuid, base64, asyncio
from typing import Optional
from urllib.parse import urljoin

from playwright.async_api import async_playwright, Page, Frame, Error as PWError

SAWERIA_USERNAME = os.getenv("SAWERIA_USERNAME", "").strip()
PROFILE_URL = f"https://saweria.co/{SAWERIA_USERNAME}" if SAWERIA_USERNAME else None

# Tuning via ENV
WAIT_TOTAL_MS = int(os.getenv("SCRAPER_WAIT_TOTAL_MS", "6000"))
WAIT_QR_MS    = int(os.getenv("SCRAPER_WAIT_QR_MS", "12000"))
MAX_RETRY     = int(os.getenv("SCRAPER_MAX_RETRY", "3"))

# Paksa event input/change supaya binding reaktif di halaman terpicu
FORCE_DISPATCH = True

# --- Reuse browser instance untuk menekan latency ---
_PLAY = None
_BROWSER = None


async def _get_browser():
    """Start playwright+browser sekali, reuse di panggilan berikutnya."""
    global _PLAY, _BROWSER
    if _PLAY is None:
        _PLAY = await async_playwright().start()
    if _BROWSER is None:
        _BROWSER = await _PLAY.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
    return _BROWSER


async def _new_context():
    browser = await _get_browser()
    return await browser.new_context(
        user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
        viewport={"width": 1366, "height": 960},
        device_scale_factor=2,
        locale="id-ID",
        timezone_id="Asia/Jakarta",
    )


# ---------- util umum ----------
async def _find_payment_root(node: Page | Frame):
    candidates = [
        '[data-testid*="donate" i]',
        '[data-testid*="payment" i]',
        '[class*="donate" i]',
        '[class*="payment" i]',
        'form',
        'section:has(button)',
        'div:has(button)',
    ]
    for sel in candidates:
        try:
            el = await node.wait_for_selector(sel, timeout=1800)
            return el
        except Exception:
            pass
    return None


async def _scan_all_frames_for_visual(page: Page):
    el = await _find_payment_root(page)
    if el:
        return el
    for fr in page.frames:
        try:
            url = (fr.url or "").lower()
        except Exception:
            url = ""
        if any(k in url for k in ["gopay", "qris", "payment", "pay", "xendit", "midtrans", "snap", "checkout", "iframe"]):
            print("[scraper] scanning frame:", url[:140])
        el = await _find_payment_root(fr)
        if el:
            return el
    return None


async def _maybe_dispatch(page: Page, handle):
    """Opsional: paksa event input/change bila FORCE_DISPATCH=True."""
    if not FORCE_DISPATCH or handle is None:
        return
    try:
        await page.evaluate(
            "(e)=>{"
            " if(!e) return;"
            " e.dispatchEvent(new Event('input',{bubbles:true}));"
            " e.dispatchEvent(new Event('change',{bubbles:true}));"
            " e.blur && e.blur();"
            "}", handle
        )
    except Exception:
        pass


# ---------- helpers tambahan (baru/ditingkatkan) ----------

async def _set_input_and_commit(locator, value: str):
    """Isi input secara 'ramah React' + trigger event."""
    try:
        await locator.fill("")
    except Exception:
        try:
            await locator.click()
            # clear manual
            try:
                await locator.press("Control+A")
            except Exception:
                await locator.press("Meta+A")
            await locator.press("Backspace")
        except Exception:
            pass
    await locator.type(value, delay=35)
    try:
        await locator.dispatch_event("input")
        await locator.dispatch_event("change")
        await locator.blur()
    except Exception:
        pass


async def _wait_total_updated(page: Page, timeout_ms: int) -> bool:
    """
    Menunggu sampai teks 'Total: Rp...' muncul dan bernilai > 0.
    Menggunakan scan DOM fleksibel agar tahan gonta-ganti UI.
    """
    step = 250
    rounds = max(1, timeout_ms // step)
    for _ in range(rounds):
        try:
            ok = await page.evaluate(
                """
                () => {
                  const nodes = Array.from(document.querySelectorAll('*'));
                  // cari node yang mengandung kata 'Total: Rp'
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


async def _wait_qr_ready(node: Page | Frame, timeout_ms: int):
    """Tunggu elemen QR (img/canvas/data-url/lazy) muncul dengan ukuran memadai."""
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
    rounds = max(1, timeout_ms // step)
    for _ in range(rounds):
        for sel in sels:
            try:
                loc = node.locator(sel)
                if await loc.count() > 0:
                    box = await loc.first().bounding_box()
                    if box and box["width"] > 80 and box["height"] > 80:
                        return loc.first()
            except Exception:
                pass
        # pancing lazy-load
        try:
            if hasattr(node, "mouse"):
                await node.mouse.wheel(0, 400)  # type: ignore
        except Exception:
            pass
        await asyncio.sleep(step / 1000)
    return None


# ---------- helper: pilih GoPay & tunggu Total > 0 ----------
async def _select_gopay_and_wait_total(page: Page, amount: int):
    """Klik GoPay dan tahan sampai 'Total' > 0, dengan recovery aktif jika gagal."""
    gopay_selectors = [
        '[data-testid="gopay-button"]',
        'button[data-testid="gopay-button"]',
        'button:has-text("GoPay")',
        '[role="radio"]:has-text("GoPay")',
        '[data-testid*="gopay"]',
    ]
    alt_method_selectors = [  # untuk toggle memicu re-calc
        'button:has-text("OVO")',
        'button:has-text("QRIS")',
        '[data-testid*="qris"]',
    ]

    # 1) klik GoPay (pertama)
    clicked = False
    for sel in gopay_selectors:
        try:
            el = await page.wait_for_selector(sel, timeout=2500)
            await el.scroll_into_view_if_needed()
            await el.click(force=True)
            print("[scraper] clicked GoPay via", sel)
            clicked = True
            break
        except Exception:
            pass
    if not clicked:
        print("[scraper] WARN: GoPay button not found")

    await page.wait_for_timeout(200)

    # 2) pastikan amount tercermin
    try:
        rupiah = f"{amount:,}".replace(",", ".")
        await page.get_by_text(re.compile(rf"(Jumlah Dukungan|Subtotal).*Rp\s*{rupiah}\b", re.I)).wait_for(timeout=3500)
        print("[scraper] amount reflected in UI")
    except Exception:
        print("[scraper] INFO: amount reflection not found; will rely on total scanner")

    # 3) tunggu total > 0, dengan recovery langkah demi langkah
    if await _wait_total_updated(page, WAIT_TOTAL_MS):
        print("[scraper] Total > 0 (OK)")
        return

    print("[scraper] WARN: Total still 0 → recovery: retype amount & dispatch")
    # retype amount
    amount_input = None
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
                amount_input = loc.first()
                break
        except Exception:
            pass
    if amount_input:
        await amount_input.focus()
        await _set_input_and_commit(amount_input, str(int(amount)))
        await page.wait_for_timeout(350)
        if await _wait_total_updated(page, 3000):
            print("[scraper] Total > 0 (OK) after retype")
            return

    print("[scraper] INFO: toggle payment method to force re-calc")
    # 4) toggle OVO/QRIS lalu balik ke GoPay
    toggled = False
    for alt in alt_method_selectors:
        try:
            loc = page.locator(alt)
            if await loc.count() > 0:
                await loc.first().click()
                await page.wait_for_timeout(300)
                toggled = True
                break
        except Exception:
            pass

    # klik GoPay lagi
    for sel in gopay_selectors:
        try:
            el = page.locator(sel)
            if await el.count() > 0:
                await el.first().click()
                await page.wait_for_timeout(350)
                break
        except Exception:
            pass

    if await _wait_total_updated(page, 2500):
        print("[scraper] Total > 0 (OK) after toggle")
        return

    print("[scraper] WARN: Total still 0 after recovery steps")


# ---------- isi form TANPA submit ----------
async def _fill_without_submit(page: Page, amount: int, message: str, method: str):
    # ===== amount =====
    amount_ok = False
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
            amount_ok = True
            print("[scraper] filled amount via", sel)
            break
        except Exception:
            pass
    if not amount_ok:
        print("[scraper] WARN: amount field not found")
    await _maybe_dispatch(page, amount_handle)
    await page.wait_for_timeout(200)

    # ===== name (Dari) =====
    name_ok = False
    for sel in [
        'input[name="name"]',
        'input[placeholder*="Dari" i]',
        'input[aria-label*="Dari" i]',
        'label:has-text("Dari") ~ input',
        'input[required][type="text"]',
        'input[type="text"]',
    ]:
        try:
            el = await page.wait_for_selector(sel, timeout=2000)
            await el.scroll_into_view_if_needed()
            await el.fill("Budi")
            await _maybe_dispatch(page, el)
            name_ok = True
            print("[scraper] filled name via", sel)
            break
        except Exception:
            pass
    if not name_ok:
        print("[scraper] WARN: name field not found")
    await page.wait_for_timeout(150)

    # ===== email =====
    email_val = f"donor+{uuid.uuid4().hex[:8]}@example.com"
    for sel in ['input[type="email"]', 'input[name="email"]', 'input[placeholder*="email" i]']:
        try:
            el = await page.wait_for_selector(sel, timeout=2000)
            await el.scroll_into_view_if_needed()
            await el.fill(email_val)
            await _maybe_dispatch(page, el)
            print("[scraper] filled email via", sel)
            break
        except Exception:
            pass
    await page.wait_for_timeout(150)

    # ===== message (Pesan) — INPUT/TEXTAREA =====
    msg_ok = False
    for sel in [
        'input[name="message"]',
        'input[data-testid="message-input"]',
        '#message',
        'input[placeholder*="Selamat pagi" i]',
        'input[placeholder*="pesan" i]',
        'textarea[name="message"]',
        'textarea',
    ]:
        try:
            el = await page.wait_for_selector(sel, timeout=1800)
            await el.scroll_into_view_if_needed()
            await el.fill(message)
            await _maybe_dispatch(page, el)
            msg_ok = True
            print("[scraper] filled message via", sel)
            break
        except Exception:
            pass
    if not msg_ok:
        print("[scraper] WARN: message field not found at all")
    await page.wait_for_timeout(200)

    # ===== centang checkbox wajib (kalau ada) =====
    for text in ["17 tahun", "menyetujui", "kebijakan privasi", "ketentuan"]:
        try:
            node = page.get_by_text(re.compile(text, re.I))
            await node.scroll_into_view_if_needed()
            await node.click()
            print("[scraper] checked:", text)
        except Exception:
            pass
    await page.wait_for_timeout(150)

    # ===== pilih metode (GoPay) =====
    if (method or "gopay").lower() == "gopay":
        # scroll ke area metode (biar visible)
        try:
            area = await page.get_by_text(
                re.compile("Moda pembayaran|Metode pembayaran|GoPay|QRIS", re.I)
            ).element_handle()
            if area:
                await area.scroll_into_view_if_needed()
        except Exception:
            await page.mouse.wheel(0, 600)

        await _select_gopay_and_wait_total(page, amount)

    # selesai; TIDAK submit
    await page.wait_for_timeout(350)


# ====== Klik DONATE + ambil target checkout ======
async def _click_donate_and_get_checkout_page(page: Page, context):
    """
    Klik "Kirim Dukungan" dan kembalikan object 'target' berisi:
    - page   : Page (jika membuka tab baru / same-page nav)
    - frame  : Frame (jika pembayaran di dalam iframe)
    """
    donate_selectors = [
        'button[data-testid="donate-button"]',
        'button:has-text("Kirim Dukungan")',
        'text=/\\bKirim\\s+Dukungan\\b/i',
    ]

    # siapkan listener tab baru (kalau ada)
    new_page_task = context.wait_for_event("page")

    clicked = False
    for sel in donate_selectors:
        try:
            el = await page.wait_for_selector(sel, timeout=3000)
            await el.scroll_into_view_if_needed()
            await el.click()
            print("[scraper] clicked DONATE via", sel)
            clicked = True
            break
        except Exception:
            pass
    if not clicked:
        raise RuntimeError("Tombol 'Kirim Dukungan' tidak ditemukan")

    # 1) tab baru?
    target_page = None
    try:
        target_page = await new_page_task
    except Exception:
        pass
    if target_page:
        await target_page.wait_for_load_state("domcontentloaded")
        await target_page.wait_for_load_state("networkidle")
        print("[scraper] checkout opened in NEW TAB:", target_page.url)
        return {"page": target_page, "frame": None}

    # 2) same-page navigation?
    try:
        await page.wait_for_load_state("networkidle", timeout=7000)
        print("[scraper] checkout likely SAME PAGE:", page.url)
        return {"page": page, "frame": None}
    except Exception:
        pass

    # 3) iframe?
    for fr in page.frames:
        u = (fr.url or "").lower()
        if any(k in u for k in ["gopay", "qris", "xendit", "midtrans", "snap", "checkout", "pay"]):
            print("[scraper] checkout appears in IFRAME:", u[:120])
            return {"page": None, "frame": fr}

    print("[scraper] WARN: fallback to current page for checkout")
    return {"page": page, "frame": None}


async def _find_qr_or_checkout_panel(node: Page | Frame):
    """Cari elemen QR / panel checkout untuk discreenshot."""
    selectors = [
        # gambar/canvas QR umum
        'img.qr-image',
        'img.qr-image--with-wrapper',
        'img[alt*="qr-code" i]',
        'img[src*="/qr-code"]',
        '[data-testid="qrcode"] img',
        '[class*="qrcode" i] img',
        'img[alt*="QRIS" i]',
        "canvas",
        # panel pembayaran
        '[data-testid*="checkout" i]',
        '[class*="checkout" i]',
        'div:has-text("Cek status")',
        'div:has-text("Download QRIS")',
    ]
    for sel in selectors:
        try:
            el = await node.wait_for_selector(sel, timeout=5000)
            return el
        except Exception:
            pass
    return None


# ---------- entrypoint: QR HD ----------
async def fetch_gopay_qr_hd_png(amount: int, message: str) -> Optional[bytes]:
    """
    Isi form -> klik 'Kirim Dukungan' -> tunggu checkout GoPay/Midtrans
    -> ambil sumber <img> QR (HD). Fallback: screenshot elemen / panel.
    Selalu mengembalikan bytes PNG (atau None jika gagal total).
    """
    if not PROFILE_URL:
        print("[scraper] ERROR: SAWERIA_USERNAME belum di-set")
        return None

    # Lakukan beberapa attempt agar stabil saat UI lambat
    for attempt in range(1, MAX_RETRY + 1):
        context = await _new_context()
        page = await context.new_page()
        try:
            await page.goto(PROFILE_URL, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_load_state("networkidle", timeout=8000)
            await page.wait_for_timeout(600)
            await page.mouse.wheel(0, 500)

            await _fill_without_submit(page, amount, message, "gopay")

            # klik "Kirim Dukungan" -> checkout target
            target = await _click_donate_and_get_checkout_page(page, context)
            node: Page | Frame = target["frame"] if target["frame"] else (target["page"] or page)

            # QR sel
            qr_handle = await _wait_qr_ready(node, WAIT_QR_MS)
            if not qr_handle:
                # scroll lagi untuk memicu lazy-load, lalu coba sekali lagi
                try:
                    if hasattr(node, "mouse"):
                        await node.mouse.wheel(0, 800)  # type: ignore
                    await asyncio.sleep(0.4)
                except Exception:
                    pass
                qr_handle = await _wait_qr_ready(node, 4000)

            if not qr_handle:
                print(f"[scraper] attempt {attempt}: QR not found; fallback to panel")
                panel = await _find_qr_or_checkout_panel(node) or node
                png = await (panel.screenshot() if hasattr(panel, "screenshot") else node.screenshot(full_page=True))
                await context.close()
                return png

            tag_name = await qr_handle.evaluate("(el)=>el.tagName.toLowerCase()")
            if tag_name == "img":
                src = await qr_handle.evaluate("(img)=>img.currentSrc || img.src || ''")
                if not src:
                    print("[scraper] WARN: img src empty; fallback to screenshot")
                    await qr_handle.scroll_into_view_if_needed()
                    png = await qr_handle.screenshot()
                    await context.close()
                    return png

                if src.startswith("data:image/"):
                    header, b64 = src.split(",", 1)
                    try:
                        data = base64.b64decode(b64)
                        await context.close()
                        return data
                    except Exception as e:
                        print("[scraper] WARN: decode data URL failed:", e)

                base_url = node.url if hasattr(node, "url") else page.url
                abs_url = urljoin(base_url, src)

                try:
                    r = await context.request.get(
                        abs_url,
                        headers={
                            "Referer": base_url,
                            "User-Agent": await page.evaluate("() => navigator.userAgent"),
                            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                        },
                        timeout=15000,
                    )
                    if r.ok:
                        data = await r.body()
                        print("[scraper] downloaded QR img bytes:", len(data))
                        await context.close()
                        return data
                    else:
                        print("[scraper] WARN: request img failed", r.status)
                except Exception as e:
                    print("[scraper] WARN: fetch img error:", e)

                # fallback: screenshot elemen
                await qr_handle.scroll_into_view_if_needed()
                png = await qr_handle.screenshot()
                await context.close()
                return png

            # non-IMG (canvas/dll) → screenshot
            await qr_handle.scroll_into_view_if_needed()
            png = await qr_handle.screenshot()
            await context.close()
            return png

        except Exception as e:
            print(f"[scraper] attempt {attempt} failed:", e)
            try:
                snap = await page.screenshot(full_page=True)
                print("[scraper] debug page screenshot bytes:", len(snap))
            except Exception:
                pass
            await context.close()
            if attempt >= MAX_RETRY:
                return None
            await asyncio.sleep(0.6 * attempt)  # backoff ringan

    return None


# ---------- entrypoints tambahan (opsional / debugging) ----------
async def fetch_qr_png(amount: int, message: str, method: Optional[str] = "gopay") -> Optional[bytes]:
    """
    TANPA submit: isi form + pilih GoPay → screenshot panel/halaman (untuk debugging).
    """
    if not PROFILE_URL:
        print("[scraper] ERROR: SAWERIA_USERNAME belum di-set")
        return None

    context = await _new_context()
    page = await context.new_page()
    try:
        await page.goto(PROFILE_URL, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_load_state("networkidle", timeout=8000)
        await page.wait_for_timeout(700)
        await page.mouse.wheel(0, 480)

        await _fill_without_submit(page, amount, message, method or "gopay")
        await page.wait_for_timeout(700)

        target = page
        el = await _scan_all_frames_for_visual(target)
        if el:
            try:
                await el.scroll_into_view_if_needed()
                png = await el.screenshot()
                print("[scraper] captured filled panel PNG:", len(png))
            except Exception:
                png = await target.screenshot(full_page=False)
                print("[scraper] fallback target screenshot:", len(png))
        else:
            png = await target.screenshot(full_page=False)
            print("[scraper] WARN: no panel; page screenshot:", len(png))

        await context.close()
        return png

    except Exception as e:
        print("[scraper] error(fetch_qr_png):", e)
        try:
            snap = await page.screenshot(full_page=True)
            print("[scraper] debug page screenshot bytes:", len(snap))
        except Exception:
            pass
        await context.close()
        return None


async def fetch_gopay_checkout_png(amount: int, message: str) -> Optional[bytes]:
    """
    Klik 'Kirim Dukungan' dan screenshot panel checkout (jika butuh tampilan penuh).
    """
    if not PROFILE_URL:
        print("[scraper] ERROR: SAWERIA_USERNAME belum di-set")
        return None

    context = await _new_context()
    page = await context.new_page()
    try:
        await page.goto(PROFILE_URL, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_load_state("networkidle", timeout=8000)
        await page.wait_for_timeout(700)
        await page.mouse.wheel(0, 480)

        await _fill_without_submit(page, amount, message, "gopay")
        target = await _click_donate_and_get_checkout_page(page, context)
        node = target["frame"] if target["frame"] else (target["page"] or page)

        el = await _find_qr_or_checkout_panel(node)
        if el:
            await el.scroll_into_view_if_needed()
            png = await el.screenshot()
            print("[scraper] captured CHECKOUT panel PNG:", len(png))
        else:
            # fallback screenshot halaman
            if target["page"]:
                png = await target["page"].screenshot(full_page=True)
            else:
                png = await page.screenshot(full_page=True)
            print("[scraper] WARN: no specific QR element; page screenshot:", len(png))
        await context.close()
        return png

    except Exception as e:
        print("[scraper] error(fetch_gopay_checkout_png):", e)
        try:
            snap = await page.screenshot(full_page=True)
            print("[scraper] debug page screenshot bytes:", len(snap))
        except Exception:
            pass
        await context.close()
        return None


# ---------- debug helpers ----------
async def debug_snapshot() -> Optional[bytes]:
    if not PROFILE_URL:
        print("[debug_snapshot] ERROR: SAWERIA_USERNAME belum di-set")
        return None
    context = await _new_context()
    page = await context.new_page()
    await page.goto(PROFILE_URL, wait_until="domcontentloaded", timeout=20000)
    await page.wait_for_load_state("networkidle", timeout=8000)
    await page.wait_for_timeout(1000)
    await page.mouse.wheel(0, 600)
    png = await page.screenshot(full_page=True)
    await context.close()
    return png


async def debug_fill_snapshot(amount: int, message: str, method: str = "gopay") -> Optional[bytes]:
    if not PROFILE_URL:
        print("[debug_fill_snapshot] ERROR: SAWERIA_USERNAME belum di-set")
        return None
    context = await _new_context()
    page = await context.new_page()
    try:
        await page.goto(PROFILE_URL, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_load_state("networkidle", timeout=8000)
        await page.wait_for_timeout(700)
        await page.mouse.wheel(0, 480)

        await _fill_without_submit(page, amount, message, method or "gopay")
        await page.wait_for_timeout(700)

        png = await page.screenshot(full_page=True)
        print(f"[debug_fill_snapshot] bytes={len(png)}")
        await context.close()
        return png
    except Exception as e:
        print("[debug_fill_snapshot] error:", e)
        try:
            snap = await page.screenshot(full_page=True)
            await context.close()
            return snap
        except Exception:
            await context.close()
            return None
