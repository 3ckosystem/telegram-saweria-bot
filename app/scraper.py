# app/scraper.py
import os
from playwright.async_api import async_playwright

SAWERIA_USERNAME = os.getenv("SAWERIA_USERNAME", "")
SAWERIA_SESSION  = os.getenv("SAWERIA_SESSION", "")
SAWERIA_EMAIL    = os.getenv("SAWERIA_EMAIL", "")
SAWERIA_PASSWORD = os.getenv("SAWERIA_PASSWORD", "")
SCRAPER_PAYMENT_METHOD = os.getenv("SCRAPER_PAYMENT_METHOD", "gopay").lower()

PROFILE_URL = f"https://saweria.co/{SAWERIA_USERNAME}"

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
    for sel in ['button:has-text("Masuk")','button:has-text("Login")','text=/Masuk|Login/i']:
        try:
            await page.click(sel); print("[scraper] clicked login via", sel); break
        except: pass
    await page.wait_for_load_state("networkidle")

async def _fill_amount(page, amount: int):
    try:
        amt = await page.wait_for_selector('input[name="amount"], input[type="number"]', timeout=6000)
        await amt.click()
        try: await page.keyboard.press("Control+A")
        except: await page.keyboard.press("Meta+A")
        await page.keyboard.press("Backspace")
        await amt.type(str(amount))
        print("[scraper] filled amount")
        return True
    except Exception as e:
        print("[scraper] ERROR filling amount:", e)
        return False

async def _reveal_message_box_if_hidden(page):
    for sel in [
        'button:has-text("Pesan")',
        'button:has-text("Tambah")',
        'text=/Tulis pesan/i',
        'text=/Tambahkan pesan/i',
        '[data-testid*="message"]:has-text("Tambah")',
    ]:
        try:
            el = await page.wait_for_selector(sel, timeout=1200)
            await el.click(); print("[scraper] clicked message toggler via", sel); break
        except: pass

async def _fill_message(page, message: str) -> bool:
    await _reveal_message_box_if_hidden(page)
    for sel in [
        'textarea[name="message"]','textarea[placeholder*="pesan" i]','textarea',
        'input[name="message"]','input[placeholder*="pesan" i]',
    ]:
        try:
            el = await page.wait_for_selector(sel, timeout=1500)
            await el.fill(message); print("[scraper] filled message via", sel); return True
        except: pass
    try:
        el = await page.wait_for_selector('[contenteditable="true"], [contenteditable]', timeout=1500)
        await el.click(); await page.keyboard.type(message)
        print("[scraper] typed message into contenteditable"); return True
    except: pass
    print("[scraper] WARN: message field not found"); return False

async def _choose_payment_method(page, method: str):
    method = (method or "").lower()
    sels = ([
        'button:has-text("GoPay")','[data-testid="payment-gopay"]',
        '[role="tab"]:has-text("GoPay")','img[alt*="GoPay"]','text=GoPay'
    ] if method=="gopay" else [
        'button:has-text("QRIS")','[data-testid="payment-qris"]',
        '[role="tab"]:has-text("QRIS")','text=QRIS'
    ])
    for sel in sels:
        try:
            el = await page.wait_for_selector(sel, timeout=1500)
            await el.click(); print("[scraper] clicked method via", sel); return
        except: pass
    print(f"[scraper] WARN: method tab '{method}' not found, continue anyway")

async def _click_pay(page):
    for sel in ['button:has-text("Bayar")','button:has-text("Donate")','text=Bayar','text=Donate']:
        try:
            await page.click(sel); print("[scraper] clicked pay via", sel); return True
        except: pass
    print("[scraper] WARN: pay button not found"); return False

async def _find_qr_in(page_or_frame, method: str):
    # cari elemen QR/aksi di node ini
    candidates = ([
        'img[alt*="GoPay"]','img[src*="gopay"]','img[src^="data:image"]','canvas',
        '[data-testid*="qr"]','[class*="qr"] img','a[href^="gopay://"]','button:has-text("Buka GoPay")'
    ] if method=="gopay" else [
        'img[alt="QRIS"]','img[alt*="QR"]','img[src^="data:image"]','canvas',
        '[data-testid*="qr"]','[class*="qr"] img'
    ])
    for sel in candidates:
        try:
            el = await page_or_frame.wait_for_selector(sel, timeout=4000)
            print("[scraper] found pay element via", sel); return el
        except: pass
    return None

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

        if not await _fill_amount(page, amount): raise RuntimeError("Amount field not found")
        await _fill_message(page, message)  # kalau gagal, lanjut (webhook masih bisa lewat nominal)

        await _choose_payment_method(page, method)
        await _click_pay(page)

        # beri waktu modal/iframe muncul
        await page.wait_for_timeout(1200)

        # 1) coba cari di page utama
        el = await _find_qr_in(page, method)
        if not el:
            # 2) cari di semua iframe
            frames = page.frames
            print(f"[scraper] frames found: {len(frames)}")
            for fr in frames:
                try:
                    url = fr.url or ""
                except:
                    url = ""
                if any(k in url.lower() for k in ["gopay","qris","payment","pay","xendit","midtrans","snap","checkout","iframe"]):
                    print("[scraper] scanning frame:", url[:120])
                el = await _find_qr_in(fr, method)
                if el: break

        if el:
            try:
                png = await el.screenshot()
            except:
                png = await page.screenshot(full_page=False)
        else:
            print("[scraper] WARN: nothing found; fallback screenshot")
            png = await page.screenshot(full_page=False)

        print("[scraper] captured PNG bytes:", len(png))
        await context.close(); await browser.close()
        return png
