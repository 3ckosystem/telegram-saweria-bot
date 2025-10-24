# =============================
# app/scraper.py
# =============================
from __future__ import annotations
import os
from typing import Optional

from playwright.async_api import async_playwright, Page

SAWERIA_USERNAME = os.getenv("SAWERIA_USERNAME", "").strip()
PROFILE_URL = f"https://saweria.co/{SAWERIA_USERNAME}" if SAWERIA_USERNAME else "https://saweria.co/"

# Selector yang lebih tahan perubahan DOM
SELECTOR_BUTTON_CTA = "button, a[role=button]"
SELECTOR_QR_CANDIDATES = (
    "img[alt*=QR i], img[src*='qris' i], canvas.qr, "
    ".qr-image img, .qr-image--with-wrapper img, div:has(canvas)"
)

async def _click_support_button(page: Page):
    """
    Cari & klik tombol kirim dukungan/donasi secara robust
    """
    candidates = page.locator(SELECTOR_BUTTON_CTA)
    count = await candidates.count()
    for i in range(count):
        el = candidates.nth(i)
        name = ""
        try:
            name = (await el.inner_text()).lower()
        except:
            try:
                name = (await el.get_attribute("aria-label") or "").lower()
            except:
                name = ""
        if any(k in name for k in ["dukungan", "donasi", "support", "kirim", "bayar"]):
            await el.scroll_into_view_if_needed()
            await el.click()
            return True

    # Fallback: klik tombol pertama yang visible
    await candidates.first.wait_for(state="visible", timeout=15000)
    await candidates.first.click()
    return True

async def fetch_gopay_qr_hd_png(amount: int, msg: str) -> bytes:
    """
    Buka halaman Saweria, isi amount & message (INV:uuid),
    pilih GoPay, tunggu QR muncul, lalu screenshot ke PNG bytes.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 900})
        page = await context.new_page()

        await page.goto(PROFILE_URL, wait_until="networkidle")

        # Klik tombol donasi/kirim dukungan
        await _click_support_button(page)

        # Isi amount
        amount_input = (
            page.get_by_placeholder("Rp", exact=False)
            .or_(page.locator("input[type='number'], input[mode='numeric']"))
        )
        await amount_input.first.fill(str(amount))

        # Isi message
        msg_input = (
            page.get_by_placeholder("Pesan", exact=False)
            .or_(page.locator("textarea, input[name*='message' i]"))
        )
        await msg_input.first.fill(msg)

        # Pilih GoPay
        gopay = page.locator("[class*='gopay' i], img[alt*='gopay' i], [data-method*='gopay' i]")
        await gopay.first.wait_for(state="visible", timeout=15000)
        await gopay.first.click()

        # Tunggu QR muncul
        qr = page.locator(SELECTOR_QR_CANDIDATES)
        await qr.first.wait_for(state="visible", timeout=30000)

        # Screenshot area QR (kalau bounding_box tersedia), otherwise fullpage
        box = await qr.first.bounding_box()
        if box:
            png = await page.screenshot(clip=box, type="png")
        else:
            png = await page.screenshot(type="png")

        await context.close()
        await browser.close()
        return png
