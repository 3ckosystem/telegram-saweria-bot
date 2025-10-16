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

async def _click_donate_and_get_checkout_page(page, context):
    """
    Klik "Kirim Dukungan" dan kembalikan object 'target' yang berisi:
    - page   : Page (jika membuka tab baru / same-page nav)
    - frame  : Frame (jika pembayaran di dalam iframe)
    - root   : element handle panel pembayaran (opsional)
    """
    # calon tombol
    donate_selectors = [
        'button[data-testid="donate-button"]',
        'button:has-text("Kirim Dukungan")',
        'text=/\\bKirim\\s+Dukungan\\b/i',
    ]

    # siapkan listener new page
    new_page_task = context.wait_for_event("page")

    # klik tombol
    clicked = False
    for sel in donate_selectors:
        try:
            el = await page.wait_for_selector(sel, timeout=3000)
            await el.scroll_into_view_if_needed()
            await el.click()
            print("[scraper] clicked DONATE via", sel)
            clicked = True
            break
        except:
            pass
    if not clicked:
        raise RuntimeError("Tombol 'Kirim Dukungan' tidak ditemukan")

    # tunggu salah satu: (1) tab baru, (2) same-page nav, (3) muncul iframe
    target_page = None
    try:
        target_page = await new_page_task
    except:
        pass

    if target_page:
        await target_page.wait_for_load_state("domcontentloaded")
        await target_page.wait_for_load_state("networkidle")
        print("[scraper] checkout opened in NEW TAB:", target_page.url)
        return {"page": target_page, "frame": None, "root": None}

    # coba same-page navigation
    try:
        await page.wait_for_load_state("networkidle", timeout=7000)
        print("[scraper] checkout likely SAME PAGE:", page.url)
        return {"page": page, "frame": None, "root": None}
    except:
        pass

    # terakhir: coba iframe
    for fr in page.frames:
        u = (fr.url or "").lower()
        if any(k in u for k in ["gopay","qris","xendit","midtrans","snap","checkout","pay"]):
            print("[scraper] checkout appears in IFRAME:", u[:120])
            return {"page": None, "frame": fr, "root": None}

    # gagal menemukan target; tetap kembalikan page
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


async def fetch_gopay_checkout_png(amount: int, message: str) -> bytes | None:
    """
    Alur: buka profil -> isi form -> pilih GoPay -> klik 'Kirim Dukungan'
          -> tunggu halaman/iframe pembayaran -> screenshot QR / panel.
    """
    if not PROFILE_URL:
        print("[scraper] ERROR: SAWERIA_USERNAME belum di-set")
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
            timezone_id="Asia/Jakarta",
        )
        page = await context.new_page()
        try:
            # 1) buka profil & isi form
            await page.goto(PROFILE_URL, wait_until="domcontentloaded")
            await page.wait_for_timeout(700)
            await page.mouse.wheel(0, 480)

            await _fill_without_submit(page, amount, message, "gopay")

            # 2) klik "Kirim Dukungan"
            target = await _click_donate_and_get_checkout_page(page, context)

            # 3) pilih node (page atau frame) untuk dicari QR
            node = target["frame"] if target["frame"] else (target["page"] or page)

            # 4) cari QR / panel lalu screenshot
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

            await context.close(); await browser.close()
            return png

        except Exception as e:
            print("[scraper] error(fetch_gopay_checkout_png):", e)
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