import os
from playwright.async_api import async_playwright

SAWERIA_USERNAME = os.getenv("SAWERIA_USERNAME", "")
SAWERIA_SESSION  = os.getenv("SAWERIA_SESSION", "")
SAWERIA_EMAIL    = os.getenv("SAWERIA_EMAIL", "")
SAWERIA_PASSWORD = os.getenv("SAWERIA_PASSWORD", "")

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

async def fetch_qr_png(amount: int, message: str) -> bytes | None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox","--disable-gpu"])
        context = await browser.new_context(user_agent="Mozilla/5.0")
        ok_cookie = await _login_with_cookie(context)
        page = await context.new_page()

        await page.goto(PROFILE_URL, wait_until="domcontentloaded")
        if not ok_cookie and SAWERIA_EMAIL and SAWERIA_PASSWORD:
            await _login_with_form(page)
            await page.goto(PROFILE_URL, wait_until="networkidle")

        # ==== SESUAIKAN SELECTOR JIKA PERLU ====
        # nominal
        try:
            await page.fill('input[name="amount"]', str(amount))
        except:
            amt = await page.wait_for_selector('input[type="number"]', timeout=5000)
            await amt.fill(str(amount))
        # pesan
        try:
            await page.fill('textarea[name="message"]', message)
        except:
            await page.locator('[contenteditable="true"]').first.fill(message)
        # tombol bayar
        try:
            await page.click('button:has-text("Bayar")')
        except:
            await page.click('button:has-text("Donate")')

        # tunggu QR (sesuaikan kalau perlu)
        qr_el = None
        for sel in ['img[alt*="QR"]','img[alt="QRIS"]','img[src^="data:image"]','canvas']:
            try:
                qr_el = await page.wait_for_selector(sel, timeout=10000)
                if qr_el: break
            except:
                pass

        png = await (qr_el.screenshot() if qr_el else page.screenshot(full_page=False))
        await context.close(); await browser.close()
        return png
