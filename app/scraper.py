# app/scraper.py
# Isi form Saweria + pilih GoPay (tanpa submit) lalu screenshot.
# ENV: SAWERIA_USERNAME  (contoh: "3ckosystem")

import os, re, uuid
from typing import Optional
from playwright.async_api import async_playwright, Page, Frame

SAWERIA_USERNAME = os.getenv("SAWERIA_USERNAME", "").strip()
PROFILE_URL = f"https://saweria.co/{SAWERIA_USERNAME}" if SAWERIA_USERNAME else None

# Set True bila validasi form masih tidak kebaca (akan memicu event via JS)
FORCE_DISPATCH = False


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
        except:
            pass
    return None

async def _scan_all_frames_for_visual(page: Page):
    el = await _find_payment_root(page)
    if el:
        return el
    for fr in page.frames:
        try:
            url = (fr.url or "").lower()
        except:
            url = ""
        if any(k in url for k in ["gopay","qris","payment","pay","xendit","midtrans","snap","checkout","iframe"]):
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
        await page.evaluate("(e)=>{e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));}", handle)
    except:
        pass

async def _try_click(page: Page | Frame, selectors, timeout_each=1600, force=False) -> bool:
    for sel in selectors:
        try:
            el = await page.wait_for_selector(sel, timeout=timeout_each)
            await el.scroll_into_view_if_needed()
            await el.click(force=force)
            print("[scraper] clicked via", sel)
            return True
        except:
            pass
    return False


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
    ]:
        try:
            el = await page.wait_for_selector(sel, timeout=2500)
            await el.scroll_into_view_if_needed()
            await el.click()
            try:
                await page.keyboard.press("Control+A")
            except:
                await page.keyboard.press("Meta+A")
            await page.keyboard.press("Backspace")
            # gunakan type agar event terpicu karakter demi karakter
            await el.type(str(amount))
            amount_handle = el
            amount_ok = True
            print("[scraper] filled amount via", sel)
            break
        except:
            pass
    if not amount_ok:
        print("[scraper] WARN: amount field not found")
    await _maybe_dispatch(page, amount_handle)
    await page.keyboard.press("Tab")   # trigger blur/validasi
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
            await el.click()
            try:
                await page.keyboard.press("Control+A")
            except:
                await page.keyboard.press("Meta+A")
            await page.keyboard.press("Backspace")
            await el.type("Budi")
            print("[scraper] filled name via", sel)
            await _maybe_dispatch(page, el)
            name_ok = True
            break
        except:
            pass
    if not name_ok:
        print("[scraper] WARN: name field not found")
    await page.wait_for_timeout(150)

    # ===== email =====
    email_val = f"donor+{uuid.uuid4().hex[:8]}@example.com"
    for sel in ['input[type="email"]','input[name="email"]','input[placeholder*="email" i]']:
        try:
            el = await page.wait_for_selector(sel, timeout=1800)
            await el.scroll_into_view_if_needed()
            await el.click()
            try:
                await page.keyboard.press("Control+A")
            except:
                await page.keyboard.press("Meta+A")
            await page.keyboard.press("Backspace")
            await el.type(email_val)
            print("[scraper] filled email via", sel)
            await _maybe_dispatch(page, el)
            break
        except:
            pass
    await page.wait_for_timeout(150)

    # ===== message (Pesan) — INPUT → TEXTAREA → contenteditable =====
    msg_ok = False
    msg_handle = None

    # 1) INPUT (kasus layout kamu)
    for sel in [
        'input[name="message"]',
        'input[data-testid="message-input"]',
        '#message',
        'input[placeholder*="Selamat pagi" i]',
        'input[placeholder*="pesan" i]',
    ]:
        try:
            el = await page.wait_for_selector(sel, timeout=1800)
            await el.scroll_into_view_if_needed()
            await el.click()
            try:
                await page.keyboard.press("Control+A")
            except:
                await page.keyboard.press("Meta+A")
            await page.keyboard.press("Backspace")
            await el.type(message)
            msg_ok = True
            msg_handle = el
            print("[scraper] filled message via INPUT", sel)
            break
        except:
            pass

    # 2) TEXTAREA
    if not msg_ok:
        for sel in [
            'textarea[name="message"]',
            'textarea[placeholder*="Pesan" i]',
            'textarea[placeholder*="Selamat pagi" i]',
            'textarea',
        ]:
            try:
                el = await page.wait_for_selector(sel, timeout=1500)
                await el.scroll_into_view_if_needed()
                await el.click()
                await el.fill(message)  # textarea.fill aman
                msg_ok = True
                msg_handle = el
                print("[scraper] filled message via TEXTAREA", sel)
                break
            except:
                pass

    # 3) contenteditable
    if not msg_ok:
        try:
            el = await page.wait_for_selector('[contenteditable="true"], [contenteditable]', timeout=1500)
            await el.scroll_into_view_if_needed()
            await el.click()
            # clear lalu ketik
            try:
                await page.keyboard.press("Control+A")
            except:
                await page.keyboard.press("Meta+A")
            await page.keyboard.press("Backspace")
            await page.keyboard.type(message)
            msg_ok = True
            msg_handle = el
            print("[scraper] filled message via contenteditable")
        except:
            print("[scraper] WARN: message field not found at all")

    await _maybe_dispatch(page, msg_handle)
    await page.wait_for_timeout(200)

    # ===== centang checkbox wajib =====
    for text in ["17 tahun", "menyetujui", "kebijakan privasi", "ketentuan"]:
        try:
            node = page.get_by_text(re.compile(text, re.I))
            await node.scroll_into_view_if_needed()
            await node.click()
            print("[scraper] checked:", text)
        except:
            pass
    await page.wait_for_timeout(150)

    # ===== pilih metode (GoPay) =====
    method = (method or "gopay").lower()
    if method == "gopay":
        # scroll ke area metode
        try:
            area = await page.get_by_text(re.compile("Moda pembayaran|Metode pembayaran|GoPay|QRIS", re.I)).element_handle()
            if area:
                await area.scroll_into_view_if_needed()
        except:
            await page.mouse.wheel(0, 600)

        clicked = await _try_click(page, [
            'button:has-text("GoPay")',
            '[role="radio"]:has-text("GoPay")',
            '[data-testid*="gopay"]',
            'text=/\\bGoPay\\b/i',
        ], force=True)
        if not clicked:
            print("[scraper] WARN: GoPay not found; continue anyway")

    # selesai; TIDAK submit
    await page.wait_for_timeout(350)

# ====== SUBMIT + tangkap halaman pembayaran GoPay ======

async def _click_donate_and_get_checkout_page(page: Page, context):
    """
    Klik 'Kirim Dukungan' dengan robust:
    - pastikan tombol enabled & terlihat
    - paksa blur agar validasi/total ter-update
    - tunggu: tab baru / same-page / iframe checkout
    """
    from playwright.async_api import TimeoutError as PWTimeout

    # 1) Pastikan tombol ada
    donate_locators = [
        page.get_by_test_id("donate-button"),
        page.locator('button:has-text("Kirim Dukungan")'),
        page.locator('text=/\\bKirim\\s+Dukungan\\b/i'),
    ]
    donate = None
    for loc in donate_locators:
        try:
            await loc.wait_for(state="visible", timeout=4000)
            donate = loc
            break
        except:
            pass
    if donate is None:
        raise RuntimeError("Tombol 'Kirim Dukungan' tidak ditemukan")

    # 2) Paksa blur agar form/total terhitung
    try:
        await page.keyboard.press("Tab")
        await page.wait_for_timeout(150)
        await page.evaluate("""
            () => {
              const ev = (name)=>new Event(name,{bubbles:true});
              document.querySelectorAll('input,textarea,select').forEach(el=>{
                el.dispatchEvent(ev('input')); el.dispatchEvent(ev('change')); el.blur?.();
              });
            }
        """)
        await page.wait_for_timeout(250)
    except:
        pass

    # 3) Pastikan tombol enabled
    try:
        await page.wait_for_function(
            """(btn) => {
                 if (!btn) return false;
                 const disabled = btn.disabled || btn.getAttribute('aria-disabled') === 'true';
                 const hidden = btn.offsetParent === null;
                 return !disabled && !hidden;
               }""",
            donate.element_handle(),
            timeout=4000
        )
    except PWTimeout:
        # tetap dicoba klik paksa
        pass

    # 4) Siapkan listener tab baru
    new_page_task = context.wait_for_event("page")

    # 5) Scroll ke tombol & klik (beberapa layout perlu force)
    try:
        await donate.scroll_into_view_if_needed()
    except:
        pass
    clicked = False
    for click_try in range(3):
        try:
            await donate.click(force=True)
            clicked = True
            print("[scraper] DONATE clicked (try", click_try+1, ")")
            break
        except:
            await page.wait_for_timeout(250)

    if not clicked:
        # terakhir: paksa via JS
        try:
            handle = await donate.element_handle()
            if handle:
                await page.evaluate("(b)=>b.click()", handle)
                clicked = True
                print("[scraper] DONATE clicked via JS")
        except:
            pass

    if not clicked:
        raise RuntimeError("Gagal klik tombol 'Kirim Dukungan'")

    # 6) Tentukan target checkout
    target_page = None
    try:
        target_page = await new_page_task.wait_for(timeout=7000)
    except Exception:
        pass

    if target_page:
        await target_page.wait_for_load_state("domcontentloaded")
        try:
            await target_page.wait_for_load_state("networkidle", timeout=8000)
        except PWTimeout:
            pass
        print("[scraper] checkout opened in NEW TAB:", target_page.url)
        return {"page": target_page, "frame": None, "root": None}

    # same-page?
    try:
        await page.wait_for_load_state("networkidle", timeout=8000)
        print("[scraper] checkout likely SAME PAGE:", page.url)
        return {"page": page, "frame": None, "root": None}
    except PWTimeout:
        pass

    # iframe?
    for fr in page.frames:
        u = (fr.url or "").lower()
        if any(k in u for k in ["gopay","qris","xendit","midtrans","snap","checkout","pay"]):
            print("[scraper] checkout appears in IFRAME:", u[:120])
            return {"page": None, "frame": fr, "root": None}

    print("[scraper] WARN: fallback to current page for checkout")
    return {"page": page, "frame": None, "root": None}



async def _find_qr_or_checkout_panel(node):
    """
    Cari elemen QR / panel checkout untuk discreenshot.
    """
    selectors = [
        # gambar/canvas QR umum
        'img[alt*="QR"]',
        'img[src^="data:image"]',
        '[data-testid="qrcode"] img',
        'canvas',
        '[class*="qrcode"] img',
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
        except:
            pass
    return None


# ---------- poster checkout (masked) ----------
async def fetch_gopay_checkout_png(amount: int, message: str) -> bytes | None:
    """
    Profil → isi form → pilih GoPay → klik 'Kirim Dukungan' → tunggu checkout
    → screenshot poster/QR (lalu timpa tulisan saweria.co & 'Dicetak oleh: GoPay').
    """
    if not PROFILE_URL:
        print("[scraper] ERROR: SAWERIA_USERNAME belum di-set")
        return None

    from playwright.async_api import TimeoutError as PWTimeout

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
            viewport={"width": 1366, "height": 960},
            locale="id-ID",
            timezone_id="Asia/Jakarta",
        )
        page = await context.new_page()

        try:
            # 1) profil + isi form + pastikan GoPay ON
            await page.goto(PROFILE_URL, wait_until="domcontentloaded")
            await page.wait_for_timeout(600)
            await page.mouse.wheel(0, 600)
            await _fill_without_submit(page, amount, message, "gopay")

            # beberapa layout perlu klik ulang metode supaya Total ter-update
            await _try_click(page, [
                '[role="radio"]:has-text("GoPay")',
                '[data-testid*="gopay"]',
                'button:has-text("GoPay")',
            ], force=True)

            # 2) klik 'Kirim Dukungan' dan siapkan listener tab baru
            new_page_task = context.wait_for_event("page")
            await _try_click(page, [
                'button[data-testid="donate-button"]',
                'button:has-text("Kirim Dukungan")',
                'text=/\\bKirim\\s+Dukungan\\b/i',
            ], force=True)

            # 3) tentukan target checkout (tab baru / same-page / iframe)
            target_page = None
            try:
                target_page = await new_page_task.wait_for(timeout=7000)
            except Exception:
                pass

            node = None
            if target_page:
                await target_page.wait_for_load_state("domcontentloaded")
                try:
                    await target_page.wait_for_load_state("networkidle", timeout=8000)
                except PWTimeout:
                    pass
                node = target_page
                print("[scraper] checkout in NEW TAB:", target_page.url)
            else:
                # same-page navigation?
                try:
                    await page.wait_for_load_state("networkidle", timeout=8000)
                    node = page
                    print("[scraper] checkout SAME PAGE:", page.url)
                except PWTimeout:
                    # cari iframe checkout
                    for fr in page.frames:
                        u = (fr.url or "").lower()
                        if any(k in u for k in ["gopay","qris","xendit","midtrans","snap","checkout","pay"]):
                            node = fr
                            print("[scraper] checkout in IFRAME:", u[:120])
                            break

            if not node:
                print("[scraper] WARN: checkout node not found; snapshotting page")
                png_raw = await page.screenshot(full_page=True)
                await context.close(); await browser.close()
                return png_raw

            # 4) tunggu poster/QR muncul, lalu screenshot elemen
            #    (cari yang paling khas dulu supaya tidak memotret form)
            selectors = [
                'img[alt*="QR" i]',
                '[data-testid="qrcode"] img',
                '[class*="qrcode" i] img',
                "canvas",
                'div:has-text("Cek status")',
                'div:has-text("Download QRIS")',
            ]
            el = None
            for sel in selectors:
                try:
                    el = await node.wait_for_selector(sel, timeout=7000)
                    if el:
                        break
                except PWTimeout:
                    continue

            if el:
                await el.scroll_into_view_if_needed()
                poster_png = await el.screenshot()
                print("[scraper] captured checkout poster:", len(poster_png))
            else:
                # fallback halaman penuh dari node target
                poster_png = await (node.screenshot(full_page=True) if hasattr(node, "screenshot")
                                    else page.screenshot(full_page=True))
                print("[scraper] WARN: poster not found; page shot:", len(poster_png))

            # 5) masker tulisan default
            try:
                masked = mask_poster_text(poster_png)
            except Exception as e:
                print("[scraper] WARN mask fail:", e)
                masked = poster_png

            await context.close(); await browser.close()
            return masked

        except Exception as e:
            print("[scraper] error(fetch_gopay_checkout_png):", e)
            try:
                snap = await page.screenshot(full_page=True)
                print("[scraper] debug page screenshot bytes:", len(snap))
            except:
                pass
            await context.close(); await browser.close()
            return None


# app/scraper.py — REPLACE fungsi ini saja

async def fetch_gopay_qr_only_png(amount: int, message: str) -> bytes | None:
    """
    Isi form -> klik 'Kirim Dukungan' -> tunggu checkout GoPay
    -> ambil HANYA gambar QR (high-res, element screenshot).
    """
    if not PROFILE_URL:
        print("[scraper] ERROR: SAWERIA_USERNAME belum di-set")
        return None

    from playwright.async_api import Error as PWError

    async def find_qr_handle_on(node: Page | Frame):
        """
        Cari handle elemen QR pada node (Page/Frame).
        Prioritas: canvas -> img dataURL -> img alt*QR -> testid umum.
        """
        selectors = [
            # paling umum dulu
            "canvas",
            'img[src^="data:image"]',
            'img[alt*="QR" i]',
            '[data-testid="qrcode"] img',
            '[class*="qrcode" i] img',
            # variasi lain yang sering muncul
            'img[alt*="QRIS" i]',
            '[role="img"][aria-label*="QR" i]',
        ]
        for sel in selectors:
            try:
                el = await node.wait_for_selector(sel, timeout=3500)
                if el:
                    return el
            except PWError:
                pass
        return None

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox","--disable-gpu","--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = await browser.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
            viewport={"width": 1366, "height": 960},
            device_scale_factor=3,           # lebih tajam
            locale="id-ID",
            timezone_id="Asia/Jakarta",
        )
        page = await context.new_page()
        try:
            # 1) profil + isi form + pilih GoPay
            await page.goto(PROFILE_URL, wait_until="domcontentloaded")
            await page.wait_for_timeout(600)
            await page.mouse.wheel(0, 500)
            await _fill_without_submit(page, amount, message, "gopay")

            # 2) klik "Kirim Dukungan" -> dapat checkout target
            target = await _click_donate_and_get_checkout_page(page, context)
            # node utama untuk dicari QR (page / frame)
            node = target["frame"] if target["frame"] else (target["page"] or page)

            # 3) langsung cari QR di node utamanya
            qr_el = await find_qr_handle_on(node)

            # 4) kalau belum ketemu, scan semua frame (kadang QR ada di iframe lain)
            if not qr_el:
                # kumpulkan kandidat frame "checkout"
                frames = node.page.frames if hasattr(node, "page") else (page.frames)
                for fr in frames:
                    url = (fr.url or "").lower()
                    if any(k in url for k in ["gopay","qris","xendit","midtrans","snap","checkout","pay"]):
                        qr_el = await find_qr_handle_on(fr)
                        if qr_el:
                            print("[scraper] QR found in frame:", url[:120])
                            break

            # 5) kalau tetap ga ketemu, coba cari di page biasa sebagai fallback
            if not qr_el:
                qr_el = await find_qr_handle_on(page)

            if not qr_el:
                # masih belum—kirim panel checkout biar kelihatan konteksnya
                panel = await _find_qr_or_checkout_panel(node) or node
                png = await (panel.screenshot() if hasattr(panel, "screenshot") else node.screenshot(full_page=True))
                print("[scraper] WARN: QR not found; fallback panel/page:", len(png))
                await context.close(); await browser.close()
                return png

            # 6) screenshot elemen QR saja (auto crop tajam)
            await qr_el.scroll_into_view_if_needed()
            png = await qr_el.screenshot()
            print("[scraper] captured QR element only:", len(png))

            await context.close(); await browser.close()
            return png

        except Exception as e:
            print("[scraper] error(fetch_gopay_qr_only_png):", e)
            try:
                snap = await page.screenshot(full_page=True)
                print("[scraper] debug page screenshot bytes:", len(snap))
            except:
                pass
            await context.close(); await browser.close()
            return None


# ---------- entrypoints ----------
async def fetch_qr_png(amount: int, message: str, method: Optional[str] = "gopay") -> bytes | None:
    """
    1) Buka profil
    2) Isi form + pilih GoPay + centang checkbox (tanpa submit)
    3) Screenshot panel; fallback screenshot halaman
    """
    if not PROFILE_URL:
        print("[scraper] ERROR: SAWERIA_USERNAME belum di-set")
        return None

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = await browser.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
            viewport={"width": 1280, "height": 900},
            locale="id-ID",
            timezone_id="Asia/Jakarta",
        )
        page = await context.new_page()

        try:
            await page.goto(PROFILE_URL, wait_until="domcontentloaded")
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
                except:
                    png = await target.screenshot(full_page=False)
                    print("[scraper] fallback target screenshot:", len(png))
            else:
                png = await target.screenshot(full_page=False)
                print("[scraper] WARN: no panel; page screenshot:", len(png))

            await context.close(); await browser.close()
            return png

        except Exception as e:
            print("[scraper] error:", e)
            try:
                snap = await page.screenshot(full_page=True)
                print("[scraper] debug page screenshot bytes:", len(snap))
            except:
                pass
            await context.close(); await browser.close()
            return None


# ---------- debug helpers ----------
async def debug_snapshot() -> bytes | None:
    if not PROFILE_URL:
        print("[debug_snapshot] ERROR: SAWERIA_USERNAME belum di-set")
        return None
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox","--disable-gpu","--disable-dev-shm-usage","--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
            viewport={"width": 1280, "height": 900},
            locale="id-ID",
        )
        page = await context.new_page()
        await page.goto(PROFILE_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(1000)
        await page.mouse.wheel(0, 600)
        png = await page.screenshot(full_page=True)
        await context.close(); await browser.close()
        return png


async def debug_fill_snapshot(amount: int, message: str, method: str = "gopay") -> bytes | None:
    if not PROFILE_URL:
        print("[debug_fill_snapshot] ERROR: SAWERIA_USERNAME belum di-set")
        return None
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox","--disable-gpu","--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = await browser.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
            viewport={"width": 1280, "height": 900},
            locale="id-ID",
            timezone_id="Asia/Jakarta",
        )
        page = await context.new_page()
        try:
            await page.goto(PROFILE_URL, wait_until="domcontentloaded")
            await page.wait_for_timeout(700)
            await page.mouse.wheel(0, 480)

            await _fill_without_submit(page, amount, message, method or "gopay")
            await page.wait_for_timeout(700)

            png = await page.screenshot(full_page=True)
            print(f"[debug_fill_snapshot] bytes={len(png)}")
            await context.close(); await browser.close()
            return png
        except Exception as e:
            print("[debug_fill_snapshot] error:", e)
            try:
                snap = await page.screenshot(full_page=True)
                await context.close(); await browser.close()
                return snap
            except:
                await context.close(); await browser.close()
                return None