# app/scraper.py
import os
from playwright.async_api import async_playwright

SAWERIA_USERNAME = os.getenv("SAWERIA_USERNAME", "")
SAWERIA_SESSION  = os.getenv("SAWERIA_SESSION", "")
SAWERIA_EMAIL    = os.getenv("SAWERIA_EMAIL", "")
SAWERIA_PASSWORD = os.getenv("SAWERIA_PASSWORD", "")
SCRAPER_PAYMENT_METHOD = os.getenv("SCRAPER_PAYMENT_METHOD", "qris").lower()

PROFILE_URL = f"https://saweria.co/{SAWERIA_USERNAME}"

async def _login_with_cookie(context):
    if not SAWERIA_SESSION:
        return False
    await context.add_cookies([{
        "name": "_session", "value": SAWERIA_SESSION,
        "domain": "saweria.co", "path": "/", "httpOnly": True, "secure": True, "sameSite": "Lax"
    }])
    return True

async def _login_with_form(page):
    await page.goto("https://saweria.co/auth/login", wait_until="domcontentloaded")
    await page.fill('input[type="email"]', SAWERIA_EMAIL)
    await page.fill('input[type="password"]', SAWERIA_PASSWORD)
    await page.click('button:has-text("Masuk"), button:has-text("Login")')
    await page.wait_for_load_state("networkidle")

async def _choose_payment_method(page, method: str):
    method = method.lower()
    if method == "gopay":
        # Coba beberapa selector yang mungkin:
        for sel in [
            'button:has-text("GoPay")',
            '[data-testid="payment-gopay"]',
            '[role="tab"]:has-text("GoPay")',
            'img[alt*="GoPay"]',        # kadang ikon klik-able
        ]:
            try:
                el = await page.wait_for_selector(sel, timeout=2000)
                await el.click()
                return
            except:
                pass
        # jika gagal, biarkan default (akan tetap coba ambil QR umum)
    else:
        # QRIS (default) — biasanya sudah aktif; tetap coba klik kalau tersedia
        for sel in [
            'button:has-text("QRIS")',
            '[data-testid="payment-qris"]',
            '[role="tab"]:has-text("QRIS")',
        ]:
            try:
                el = await page.wait_for_selector(sel, timeout=1500)
                await el.click()
                return
            except:
                pass

async def fetch_qr_png(amount: int, message: str, method: str | None = None) -> bytes | None:
    method = (method or SCRAPER_PAYMENT_METHOD).lower()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox","--disable-gpu"])
        context = await browser.new_context(user_agent="Mozilla/5.0")
        ok_cookie = await _login_with_cookie(context)
        page = await context.new_page()

        await page.goto(PROFILE_URL, wait_until="domcontentloaded")
        if not ok_cookie and SAWERIA_EMAIL and SAWERIA_PASSWORD:
            await _login_with_form(page)
            await page.goto(PROFILE_URL, wait_until="networkidle")

        # Nominal
        try:
            await page.fill('input[name="amount"]', str(amount))
        except:
            amt = await page.wait_for_selector('input[type="number"]', timeout=5000)
            await amt.fill(str(amount))

        # Pesan
        try:
            await page.fill('textarea[name="message"]', message)
        except:
            await page.locator('[contenteditable="true"]').first.fill(message)

        # Pilih metode (GoPay / QRIS)
        await _choose_payment_method(page, method)

        # Klik tombol bayar/donate
        try:
            await page.click('button:has-text("Bayar")')
        except:
            await page.click('button:has-text("Donate")')

        # Tunggu tampilan pembayaran
        # Untuk GoPay, bisa muncul: QR GoPay, kode, atau tombol "Buka GoPay"
        qr_el = None
        candidate_selectors = []
        if method == "gopay":
            candidate_selectors = [
                'img[alt*="GoPay"]',
                'img[src*="gopay"]',
                'img[src^="data:image"]',
                'canvas',
                '[data-testid="qrcode"]',
                '[class*="qrcode"] img',
                'a[href^="gopay://"]',  # deeplink (kalau ada)
                'button:has-text("Buka GoPay")',
            ]
        else:
            candidate_selectors = [
                'img[alt="QRIS"]',
                'img[alt*="QR"]',
                'img[src^="data:image"]',
                'canvas',
                '[data-testid="qrcode"]',
            ]

        # Cari elemen visual QR/aksi
        for sel in candidate_selectors:
            try:
                qr_el = await page.wait_for_selector(sel, timeout=10000)
                if qr_el:
                    break
            except:
                pass

        # Ambil PNG
        if qr_el:
            try:
                png = await qr_el.screenshot()
            except:
                png = await page.screenshot(full_page=False)
        else:
            # fallback: screenshot modal/halaman
            png = await page.screenshot(full_page=False)

        await context.close(); await browser.close()
        return png
