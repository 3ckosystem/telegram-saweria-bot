# app/scraper.py
import os
from playwright.async_api import async_playwright

SAWERIA_USERNAME = os.getenv("SAWERIA_USERNAME", "")
SAWERIA_SESSION  = os.getenv("SAWERIA_SESSION", "")
SAWERIA_EMAIL    = os.getenv("SAWERIA_EMAIL", "")
SAWERIA_PASSWORD = os.getenv("SAWERIA_PASSWORD", "")
SCRAPER_PAYMENT_METHOD = os.getenv("SCRAPER_PAYMENT_METHOD", "qris").lower()

PROFILE_URL = f"https://saweria.co/{SAWERIA_USERNAME}"

# -------------------- helpers: login --------------------
async def _login_with_cookie(context):
    if not SAWERIA_SESSION:
        return False
    await context.add_cookies([{
        "name": "_session", "value": SAWERIA_SESSION,
        "domain": "saweria.co", "path": "/", "httpOnly": True, "secure": True, "sameSite": "Lax"
    }])
    print("[scraper] cookie session applied")
    return True

async def _login_with_form(page):
    print("[scraper] login via form")
    await page.goto("https://saweria.co/auth/login", wait_until="domcontentloaded")
    await page.fill('input[type="email"]', SAWERIA_EMAIL)
    await page.fill('input[type="password"]', SAWERIA_PASSWORD)
    for sel in ['button:has-text("Masuk")', 'button:has-text("Login")', 'text=/Masuk|Login/i']:
        try:
            await page.click(sel)
            print("[scraper] clicked login via", sel)
            break
        except:
            pass
    await page.wait_for_load_state("networkidle")

# -------------------- helpers: form fill --------------------
async def _fill_amount(page, amount: int):
    try:
        amt = await page.wait_for_selector('input[name="amount"], input[type="number"]', timeout=5000)
        await amt.click()
        # select-all & clear (Windows/Mac/Linux)
        try:
            await page.keyboard.press("Control+A")
        except:
            await page.keyboard.press("Meta+A")
        await page.keyboard.press("Backspace")
        await amt.type(str(amount))
        print("[scraper] filled amount")
        return True
    except Exception as e:
        print("[scraper] ERROR filling amount:", e)
        return False

async def _reveal_message_box_if_hidden(page):
    # buka toggle "Tulis/Tambahkan pesan" jika ada
    for sel in [
        'button:has-text("Pesan")',
        'button:has-text("Tambah")',
        'text=/Tulis pesan/i',
        'text=/Tambahkan pesan/i',
        '[data-testid*="message"]:has-text("Tambah")',
    ]:
        try:
            el = await page.wait_for_selector(sel, timeout=1200)
            await el.click()
            print("[scraper] clicked message toggler via", sel)
            break
        except:
            pass

async def _fill_message(page, message: str) -> bool:
    await _reveal_message_box_if_hidden(page)

    # 1) coba textarea / input yang umum
    for sel in [
        'textarea[name="message"]',
        'textarea[placeholder*="pesan" i]',
        'textarea',
        'input[name="message"]',
        'input[placeholder*="pesan" i]',
    ]:
        try:
            el = await page.wait_for_selector(sel, timeout=1500)
            await el.fill(message)
            print("[scraper] filled message via", sel)
            return True
        except:
            pass

    # 2) contenteditable (type manual)
    try:
        el = await page.wait_for_selector('[contenteditable="true"], [contenteditable]', timeout=1500)
        await el.click()
        await page.keyboard.type(message)
        print("[scraper] typed message into contenteditable")
        return True
    except:
        pass

    print("[scraper] WARN: message field not found")
    return False

# -------------------- helpers: payment method --------------------
async def _choose_payment_method(page, method: str):
    method = (method or "").lower()
    if method == "gopay":
        for sel in [
            'button:has-text("GoPay")',
            '[data-testid="payment-gopay"]',
            '[role="tab"]:has-text("GoPay")',
            'img[alt*="GoPay"]',
            'text=GoPay',
        ]:
            try:
                el = await page.wait_for_selector(sel, timeout=1500)
                await el.click()
                print("[scraper] clicked method via", sel)
                return
            except:
                pass
        print("[scraper] WARN: GoPay tab not found, continue anyway")
    else:
        for sel in [
            'button:has-text("QRIS")',
            '[data-testid="payment-qris"]',
            '[role="tab"]:has-text("QRIS")',
            'text=QRIS',
        ]:
            try:
                el = await page.wait_for_selector(sel, timeout=1200)
                await el.click()
                print("[scraper] clicked method via", sel)
                return
            except:
                pass

# -------------------- main: fetch QR/visual --------------------
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

        # isi nominal & pesan
        if not await _fill_amount(page, amount):
            raise RuntimeError("Amount field not found")
        msg_ok = await _fill_message(page, message)
        if not msg_ok:
            # Kalau pesan wajib agar webhook bisa deteksi INV, sebaiknya raise:
            # raise RuntimeError("Message field not found")
            pass

        # pilih metode
        await _choose_payment_method(page, method)

        # klik bayar/donate
        clicked = False
        for sel in ['button:has-text("Bayar")', 'button:has-text("Donate")', 'text=Bayar', 'text=Donate']:
            try:
                await page.click(sel)
                print("[scraper] clicked pay via", sel)
                clicked = True
                break
            except:
                pass
        if not clicked:
            print("[scraper] WARN: pay button not found; trying to proceed anyway")

        # tunggu tampilan pembayaran (QR / deeplink / tombol buka)
        qr_el = None
        candidates = (
            ['img[alt*="GoPay"]','img[src*="gopay"]','img[src^="data:image"]','canvas',
             '[data-testid*="qr"]','[class*="qr"] img','a[href^="gopay://"]','button:has-text("Buka GoPay")']
            if method == "gopay" else
            ['img[alt="QRIS"]','img[alt*="QR"]','img[src^="data:image"]','canvas',
             '[data-testid*="qr"]','[class*="qr"] img']
        )
        for sel in candidates:
            try:
                qr_el = await page.wait_for_selector(sel, timeout=10000)
                print("[scraper] found pay element via", sel)
                if qr_el:
                    break
            except:
                pass

        # ambil PNG
        if qr_el:
            try:
                png = await qr_el.screenshot()
            except:
                png = await page.screenshot(full_page=False)
        else:
            png = await page.screenshot(full_page=False)
            print("[scraper] WARN: fallback full-page screenshot")

        print("[scraper] captured PNG bytes:", len(png))
        await context.close(); await browser.close()
        return png
