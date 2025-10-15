# app/scraper.py
# No-login scraper: isi form publik Saweria, pilih GoPay, submit, lalu ambil QR.
# Env yang dipakai:
#   SAWERIA_USERNAME           -> username profil Saweria (WAJIB)
#   SCRAPER_PAYMENT_METHOD     -> "gopay" (default), atau "qris"
#   SCRAPER_NOLOGIN            -> "1" untuk paksa no-login (opsional; default no-login)

import os, re, uuid
from playwright.async_api import async_playwright, Page, Frame

SAWERIA_USERNAME = os.getenv("SAWERIA_USERNAME", "")
SCRAPER_PAYMENT_METHOD = os.getenv("SCRAPER_PAYMENT_METHOD", "gopay").lower()
SCRAPER_NOLOGIN = os.getenv("SCRAPER_NOLOGIN", "1") == "1"  # paksa no-login jadi default

PROFILE_URL = f"https://saweria.co/{SAWERIA_USERNAME}"

# ---------- Util cari QR di page/frame ----------
async def _find_qr_in(page_or_frame: Page | Frame, method: str):
    method = (method or "gopay").lower()
    candidates = ([
        'img[alt*="GoPay" i]',
        'img[src*="gopay" i]',
        'img[src^="data:image"]',
        'canvas',
        '[data-testid*="qr" i]',
        '[class*="qr" i] img',
        'a[href^="gopay://"]',
        'button:has-text("Buka GoPay")',
        'text=/GoPay/i >> xpath=..//img'
    ] if method == "gopay" else [
        'img[alt*="QRIS" i]',
        'img[alt*="QR" i]',
        'img[src^="data:image"]',
        'canvas',
        '[data-testid*="qr" i]',
        '[class*="qr" i] img',
    ])
    for sel in candidates:
        try:
            el = await page_or_frame.wait_for_selector(sel, timeout=4000)
            print("[scraper] found pay element via", sel)
            return el
        except:
            pass
    return None

async def _scan_all_frames_for_qr(page: Page, method: str):
    # coba di page utama
    el = await _find_qr_in(page, method)
    if el:
        return el
    # lalu di semua iframe
    frames = page.frames
    print(f"[scraper] frames found: {len(frames)}")
    for fr in frames:
        url = ""
        try:
            url = fr.url or ""
        except:
            pass
        if any(k in url.lower() for k in ["gopay","qris","payment","pay","xendit","midtrans","snap","checkout","iframe"]):
            print("[scraper] scanning frame:", url[:160])
        el = await _find_qr_in(fr, method)
        if el:
            return el
    return None

# ---------- Isi form publik (tanpa login) ----------
async def _fill_public_form(page: Page, amount: int, message: str, donor_name: str, donor_email: str):
    # Nominal
    amt = await page.wait_for_selector('input[type="number"], input[name="amount"]', timeout=8000)
    await amt.click()
    try:
        await page.keyboard.press("Control+A")
    except:
        await page.keyboard.press("Meta+A")
    await page.keyboard.press("Backspace")
    await amt.type(str(amount))
    print("[scraper] filled amount (public)")

    # Dari / Nama
    for sel in ['input[name="name"]', 'input[placeholder*="Dari" i]', 'input[placeholder*="nama" i]']:
        try:
            el = await page.wait_for_selector(sel, timeout=2000)
            await el.fill(donor_name)
            print("[scraper] filled name via", sel)
            break
        except:
            pass

    # Email
    for sel in ['input[type="email"]', 'input[name="email"]', 'input[placeholder*="email" i]']:
        try:
            el = await page.wait_for_selector(sel, timeout=2000)
            await el.fill(donor_email)
            print("[scraper] filled email via", sel)
            break
        except:
            pass

    # Pesan
    for sel in [
        'textarea[name="message"]',
        'textarea[placeholder*="pesan" i]',
        'textarea',
        '[contenteditable="true"], [contenteditable]',
    ]:
        try:
            el = await page.wait_for_selector(sel, timeout=2000)
            try:
                await el.fill(message)
            except:
                await el.click()
                await page.keyboard.type(message)
            print("[scraper] filled message via", sel)
            break
        except:
            pass

    # Centang 2 checkbox persetujuan (jika ada)
    for text in ["17 tahun", "menyetujui", "kebijakan privasi"]:
        try:
            await page.get_by_text(re.compile(text, re.I)).click()
            print("[scraper] checked:", text)
        except:
            pass

    # Pilih GoPay (atau QRIS bila method diubah)
    method = SCRAPER_PAYMENT_METHOD
    if method == "gopay":
        opts = [
            'button:has-text("gopay")',
            '[role="radio"]:has-text("gopay")',
            '[data-testid*="gopay"]',
            'text=/\\bgopay\\b/i',
        ]
    else:
        opts = [
            'button:has-text("QRIS")',
            '[role="radio"]:has-text("QRIS")',
            '[data-testid*="qris"]',
            'text=/\\bQRIS\\b/i',
        ]
    for sel in opts:
        try:
            el = await page.wait_for_selector(sel, timeout=2500)
            await el.click()
            print("[scraper] selected method via", sel)
            break
        except:
            pass

    # Klik Kirim Dukungan
    clicked = False
    for sel in ['button:has-text("Kirim Dukungan")', 'text=/Kirim Dukungan/i', 'button[type="submit"]']:
        try:
            await page.click(sel)
            print("[scraper] clicked submit via", sel)
            clicked = True
            break
        except:
            pass
    if not clicked:
        print("[scraper] WARN: submit button not found")

# ---------- Entry point dipanggil dari payments.create_invoice ----------
async def fetch_qr_png(amount: int, message: str, method: str | None = None) -> bytes | None:
    """
    Tanpa login: buka profil publik, isi form, pilih metode (default GoPay),
    submit, lalu cari QR di page/popup/iframe. Return PNG bytes atau None.
    """
    method = (method or SCRAPER_PAYMENT_METHOD).lower()
    donor_name = "user"
    donor_email = f"donor+{uuid.uuid4().hex[:8]}@example.com"

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
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="id-ID",
        )
        page = await context.new_page()

        try:
            await page.goto(PROFILE_URL, wait_until="domcontentloaded")
            await _fill_public_form(page, amount, message, donor_name, donor_email)

            # Payment bisa muncul di tab/popup baru atau tetap di page.
            target_page = page
            # coba deteksi popup cepat
            try:
                popup = await page.context.wait_for_event("page", timeout=2000)
                if popup and not popup.is_closed():
                    await popup.wait_for_load_state("domcontentloaded")
                    print("[scraper] detected popup payment page:", popup.url)
                    target_page = popup
            except:
                pass

            # beri waktu render payment
            await target_page.wait_for_timeout(1500)

            el = await _scan_all_frames_for_qr(target_page, method)
            if el:
                try:
                    png = await el.screenshot()
                except:
                    png = await target_page.screenshot(full_page=False)
            else:
                print("[scraper] WARN: nothing found; fallback screenshot")
                png = await target_page.screenshot(full_page=False)

            print("[scraper] captured PNG bytes:", len(png))
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
  