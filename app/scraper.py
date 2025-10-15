# app/scraper.py
# Auto-fill Saweria (amount, name, email, message), centang checkbox,
# pilih GoPay, TIDAK menekan "Kirim Dukungan".
# Hasil: screenshot panel/halaman sebagai PNG (bytes) untuk ditampilkan di Mini App.
#
# ENV yang dibutuhkan:
#   SAWERIA_USERNAME  -> username saweria (mis. "3ckosystem")

import os, re, uuid
from typing import Optional
from playwright.async_api import async_playwright, Page, Frame

SAWERIA_USERNAME = os.getenv("SAWERIA_USERNAME", "").strip()
PROFILE_URL = f"https://saweria.co/{SAWERIA_USERNAME}" if SAWERIA_USERNAME else None


# ---------- util: cari panel besar untuk discreenshot ----------
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
    frames = page.frames
    print(f"[scraper] frames found: {len(frames)}")
    for fr in frames:
        try:
            url = (fr.url or "").lower()
        except:
            url = ""
        if any(k in url for k in ["gopay","qris","payment","pay","xendit","midtrans","snap","checkout","iframe"]):
            print("[scraper] scanning frame:", url[:160])
        el = await _find_payment_root(fr)
        if el:
            return el
    return None

async def _try_click(page: Page | Frame, selectors, timeout_each=1800) -> bool:
    for sel in selectors:
        try:
            el = await page.wait_for_selector(sel, timeout=timeout_each)
            await el.scroll_into_view_if_needed()
            await el.click()
            print("[scraper] clicked via", sel)
            return True
        except:
            pass
    return False


# ---------- isi form publik TANPA submit ----------
# ganti seluruh isi fungsi _fill_without_submit di app/scraper.py
async def _fill_without_submit(page: Page, amount: int, message: str, method: str):
    # ===== amount (nominal) =====
    amount_ok = False
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
            try: await page.keyboard.press("Control+A")
            except: await page.keyboard.press("Meta+A")
            await page.keyboard.press("Backspace")
            await el.type(str(amount))
            # paksa fire event supaya total ter-update
            await page.evaluate("(e)=>{e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));}", el)
            amount_ok = True
            print("[scraper] filled amount via", sel)
            break
        except:
            pass
    if not amount_ok:
        print("[scraper] WARN: amount field not found")

    await page.wait_for_timeout(300)

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
            try: await page.keyboard.press("Control+A")
            except: await page.keyboard.press("Meta+A")
            await page.keyboard.press("Backspace")
            await el.type("Budi")
            name_ok = True
            print("[scraper] filled name via", sel)
            break
        except:
            pass
    if not name_ok:
        print("[scraper] WARN: name field not found")

    await page.wait_for_timeout(200)

    # ===== email =====
    email_val = f"donor+{uuid.uuid4().hex[:8]}@example.com"
    for sel in ['input[type="email"]','input[name="email"]','input[placeholder*="email" i]']:
        try:
            el = await page.wait_for_selector(sel, timeout=1800)
            await el.scroll_into_view_if_needed()
            await el.click()
            try: await page.keyboard.press("Control+A")
            except: await page.keyboard.press("Meta+A")
            await page.keyboard.press("Backspace")
            await el.type(email_val)
            print("[scraper] filled email via", sel)
            break
        except:
            pass

    await page.wait_for_timeout(200)

    # ===== message (Pesan) =====
    msg_ok = False
    for sel in [
        'textarea[name="message"]',
        'textarea[placeholder*="Pesan" i]',
        'textarea[placeholder*="Selamat pagi" i]',
        'textarea',
    ]:
        try:
            el = await page.wait_for_selector(sel, timeout=2000)
            await el.scroll_into_view_if_needed()
            await el.click()
            try:
                await el.fill(message)
            except:
                await page.keyboard.type(message)
            msg_ok = True
            print("[scraper] filled message via", sel)
            break
        except:
            pass

    if not msg_ok:
        # fallback ke contenteditable (beberapa tema pakai div)
        try:
            el = await page.wait_for_selector('[contenteditable="true"], [contenteditable]', timeout=2000)
            await el.scroll_into_view_if_needed()
            await el.click()
            # clear konten lama, lalu ketik
            await page.keyboard.down("Meta"); await page.keyboard.press("KeyA"); await page.keyboard.up("Meta")
            await page.keyboard.press("Backspace")
            await page.keyboard.type(message)
            # paksa event
            await page.evaluate("(e)=>{e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));}", el)
            msg_ok = True
            print("[scraper] filled message via contenteditable")
        except:
            print("[scraper] WARN: message field not found at all")

    # ===== centang checkbox wajib =====
    for text in ["17 tahun", "menyetujui", "kebijakan privasi", "ketentuan"]:
        try:
            node = page.get_by_text(re.compile(text, re.I))
            await node.scroll_into_view_if_needed()
            await node.click()
            print("[scraper] checked:", text)
        except:
            pass

    await page.wait_for_timeout(200)

    # ===== pilih metode (GoPay) =====
    method = (method or "gopay").lower()
    if method == "gopay":
        # scroll ke area metode pembayaran dulu
        try:
            area = await page.get_by_text(re.compile("Moda pembayaran|Metode pembayaran|GoPay|QRIS", re.I)).element_handle()
            if area:
                await area.scroll_into_view_if_needed()
        except:
            await page.mouse.wheel(0, 600)

        # klik GoPay pakai beberapa cara, dengan force
        clicked = False
        for sel in [
            'button:has-text("GoPay")',
            '[role="radio"]:has-text("GoPay")',
            '[data-testid*="gopay"]',
            'text=/\\bGoPay\\b/i',
        ]:
            try:
                el = await page.wait_for_selector(sel, timeout=1500)
                await el.scroll_into_view_if_needed()
                await el.click(force=True)
                clicked = True
                print("[scraper] selected GoPay via", sel)
                break
            except:
                pass
        if not clicked:
            print("[scraper] WARN: GoPay not found; continue anyway")

    await page.wait_for_timeout(400)




# ---------- entrypoint yang dipanggil payments.create_invoice ----------
async def fetch_qr_png(amount: int, message: str, method: Optional[str] = "gopay") -> bytes | None:
    """
    1) Buka profil,
    2) Isi form + pilih GoPay + centang checkbox (tanpa submit),
    3) Screenshot panel pembayaran; fallback ke screenshot halaman.
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
            await page.wait_for_timeout(800)
            await page.mouse.wheel(0, 500)

            await _fill_without_submit(page, amount, message, method or "gopay")
            await page.wait_for_timeout(800)  # beri waktu UI re-render

            target = page   # tidak ada popup/modal karena kita tidak submit
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


# ---------- debug snapshot full page (tanpa isi form) ----------
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
        await page.wait_for_timeout(1200)
        await page.mouse.wheel(0, 600)
        png = await page.screenshot(full_page=True)
        await context.close(); await browser.close()
        return png


# ---------- debug: isi form (tanpa submit) lalu screenshot full page ----------
async def debug_fill_snapshot(amount: int, message: str, method: str = "gopay") -> bytes | None:
    if not PROFILE_URL:
        print("[debug_fill_snapshot] ERROR: SAWERIA_USERNAME belum di-set")
        return None

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
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
            await page.wait_for_timeout(800)
            await page.mouse.wheel(0, 500)

            await _fill_without_submit(page, amount, message, method or "gopay")
            await page.wait_for_timeout(800)

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
