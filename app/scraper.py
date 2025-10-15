# app/scraper.py
# SIMPLE CAPTURE: buka profil Saweria (tanpa isi form), cari panel donasi/pembayaran,
# lalu screenshot elemen itu (atau fallback screenshot halaman).
#
# ENV wajib:
#   SAWERIA_USERNAME  -> username profil Saweria (mis. "3ckosystem")

import os
from playwright.async_api import async_playwright, Page, Frame

SAWERIA_USERNAME = os.getenv("SAWERIA_USERNAME", "").strip()
PROFILE_URL = f"https://saweria.co/{SAWERIA_USERNAME}" if SAWERIA_USERNAME else None

async def _find_payment_root(node: Page | Frame):
    """Cari kontainer 'besar' terkait panel donasi/pembayaran untuk di-screenshot."""
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
    # Coba di page utama
    el = await _find_payment_root(page)
    if el:
        return el

    # Coba di semua iframe (kalau ada gateway/payment iframe)
    frames = page.frames
    print(f"[scraper] frames found: {len(frames)}")
    for fr in frames:
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

async def fetch_qr_png(amount: int, message: str, method: str | None = None) -> bytes | None:
    """
    TANPA ISI FORM. Hanya buka profil Saweria dan capture panel pembayaran (atau halaman).
    Dikembalikan bytes PNG (atau None jika gagal).
    """
    if not PROFILE_URL:
        print("[scraper] ERROR: SAWERIA_USERNAME belum di-set")
        return None

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
            viewport={"width": 1280, "height": 900},
            locale="id-ID",
        )
        page = await context.new_page()

        try:
            await page.goto(PROFILE_URL, wait_until="domcontentloaded")
            # beri waktu render + pancing lazy-load
            await page.wait_for_timeout(1200)
            await page.mouse.wheel(0, 500)
            await page.wait_for_timeout(500)

            el = await _scan_all_frames_for_visual(page)

            if el:
                try:
                    await el.scroll_into_view_if_needed()
                    png = await el.screenshot()
                    print("[scraper] captured panel PNG bytes:", len(png))
                except:
                    png = await page.screenshot(full_page=False)
                    print("[scraper] fallback page screenshot bytes:", len(png))
            else:
                png = await page.screenshot(full_page=False)
                print("[scraper] WARN: panel not found; page screenshot bytes:", len(png))

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
        


# --- DEBUG: snapshot full page tanpa isi form ---
async def debug_snapshot() -> bytes | None:
    """
    Buka https://saweria.co/<SAWERIA_USERNAME> dan kirim balik screenshot PNG full page.
    Murni untuk uji konektivitas & kompatibilitas Chromium di Railway.
    """
    import os
    from playwright.async_api import async_playwright

    SAWERIA_USERNAME = os.getenv("SAWERIA_USERNAME", "").strip()
    if not SAWERIA_USERNAME:
        print("[debug_snapshot] ERROR: SAWERIA_USERNAME kosong")
        return None
    url = f"https://saweria.co/{SAWERIA_USERNAME}"

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
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_timeout(1500)
            # pancing lazy-load
            await page.mouse.wheel(0, 600)
            await page.wait_for_timeout(500)

            png = await page.screenshot(full_page=True)
            print(f"[debug_snapshot] captured {len(png)} bytes from {url}")
            await context.close(); await browser.close()
            return png
        except Exception as e:
            print("[debug_snapshot] error:", e)
            try:
                snap = await page.screenshot(full_page=True)
                print("[debug_snapshot] fallback bytes:", len(snap))
                await context.close(); await browser.close()
                return snap
            except:
                await context.close(); await browser.close()
                return None
