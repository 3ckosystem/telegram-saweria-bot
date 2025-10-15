# app/scraper.py
# Auto-fill form Saweria + pilih GoPay (tanpa/ dengan submit) dan ambil screenshot.
# ENV minimal: SAWERIA_USERNAME  (mis. "3ckosystem")

import os
import re
import uuid
from io import BytesIO
from typing import Optional

from PIL import Image, ImageChops
from playwright.async_api import async_playwright, Page, Frame

SAWERIA_USERNAME = os.getenv("SAWERIA_USERNAME", "").strip()
PROFILE_URL = f"https://saweria.co/{SAWERIA_USERNAME}" if SAWERIA_USERNAME else None

# Set True bila validasi front-end Saweria kurang responsif (paksa event input/change via JS)
FORCE_DISPATCH = False


# ---------------------- Utils umum ----------------------
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
        if any(k in url for k in ["gopay", "qris", "payment", "pay", "xendit", "midtrans", "snap", "checkout", "iframe"]):
            print("[scraper] scanning frame:", url[:140])
        el = await _find_payment_root(fr)
        if el:
            return el
    return None


async def _maybe_dispatch(page: Page, handle):
    """Jika FORCE_DISPATCH=True, paksa event input/change biar validasi front-end kebaca."""
    if not FORCE_DISPATCH or handle is None:
        return
    try:
        await page.evaluate(
            "(e)=>{e.dispatchEvent(new Event('input',{bubbles:true}));"
            "e.dispatchEvent(new Event('change',{bubbles:true}));}", handle
        )
    except:
        pass


async def _try_click(node: Page | Frame, selectors, timeout_each=1600, force=False) -> bool:
    for sel in selectors:
        try:
            el = await node.wait_for_selector(sel, timeout=timeout_each)
            await el.scroll_into_view_if_needed()
            await el.click(force=force)
            print("[scraper] clicked via", sel)
            return True
        except:
            pass
    return False


# ---------------------- Isi form TANPA submit ----------------------
async def _fill_without_submit(page: Page, amount: int, message: str, method: str):
    # amount
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
            await el.type(str(amount))  # ketik per karakter supaya handler jalan
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

    # name (Dari)
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
            await _maybe_dispatch(page, el)
            name_ok = True
            print("[scraper] filled name via", sel)
            break
        except:
            pass
    if not name_ok:
        print("[scraper] WARN: name field not found")
    await page.wait_for_timeout(150)

    # email
    email_val = f"donor+{uuid.uuid4().hex[:8]}@example.com"
    for sel in ['input[type="email"]', 'input[name="email"]', 'input[placeholder*="email" i]']:
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
            await _maybe_dispatch(page, el)
            print("[scraper] filled email via", sel)
            break
        except:
            pass
    await page.wait_for_timeout(150)

    # message (Pesan) — INPUT → TEXTAREA → contenteditable
    msg_ok = False
    msg_handle = None

    # INPUT (kasus yang kamu kirim dari inspect)
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

    # TEXTAREA
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
                await el.fill(message)
                msg_ok = True
                msg_handle = el
                print("[scraper] filled message via TEXTAREA", sel)
                break
            except:
                pass

    # contenteditable
    if not msg_ok:
        try:
            el = await page.wait_for_selector('[contenteditable="true"], [contenteditable]', timeout=1500)
            await el.scroll_into_view_if_needed()
            await el.click()
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

    # checkbox wajib
    for text in ["17 tahun", "menyetujui", "kebijakan privasi", "ketentuan"]:
        try:
            node = page.get_by_text(re.compile(text, re.I))
            await node.scroll_into_view_if_needed()
            await node.click()
            print("[scraper] checked:", text)
        except:
            pass
    await page.wait_for_timeout(150)

    # pilih metode GoPay
    method = (method or "gopay").lower()
    if method == "gopay":
        try:
            area = await page.get_by_text(re.compile("Moda pembayaran|Metode pembayaran|GoPay|QRIS", re.I)).element_handle()
            if area:
                await area.scroll_into_view_if_needed()
        except:
            await page.mouse.wheel(0, 600)

        clicked = await _try_click(
            page,
            [
                'button:has-text("GoPay")',
                '[role="radio"]:has-text("GoPay")',
                '[data-testid*="gopay"]',
                'text=/\\bGoPay\\b/i',
            ],
            force=True,
        )
        if not clicked:
            print("[scraper] WARN: GoPay not found; continue anyway")

    await page.wait_for_timeout(350)


# ---------------------- Submit → Checkout target ----------------------
async def _click_donate_and_get_checkout_page(page, context):
    donate_selectors = [
        'button[data-testid="donate-button"]',
        'button:has-text("Kirim Dukungan")',
        'text=/\\bKirim\\s+Dukungan\\b/i',
    ]

    new_page_task = context.wait_for_event("page")
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

    target_page = None
    try:
        target_page = await new_page_task
    except:
        pass

    if target_page:
        await target_page.wait_for_load_state("domcontentloaded")
        await target_page.wait_for_load_state("networkidle")
        print("[scraper] checkout opened in NEW TAB:", target_page.url)
        return {"page": target_page, "frame": None}

    try:
        await page.wait_for_load_state("networkidle", timeout=7000)
        print("[scraper] checkout likely SAME PAGE:", page.url)
        return {"page": page, "frame": None}
    except:
        pass

    for fr in page.frames:
        u = (fr.url or "").lower()
        if any(k in u for k in ["gopay", "qris", "xendit", "midtrans", "snap", "checkout", "pay"]):
            print("[scraper] checkout appears in IFRAME:", u[:120])
            return {"page": None, "frame": fr}

    print("[scraper] WARN: fallback to current page for checkout")
    return {"page": page, "frame": None}


async def _find_qr_or_checkout_panel(node: Page | Frame):
    selectors = [
        'img[alt*="QR"]',
        'img[src^="data:image"]',
        '[data-testid="qrcode"] img',
        '[class*="qrcode"] img',
        'canvas',
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


# ---------------------- Ambil poster checkout (opsional) ----------------------
async def fetch_gopay_checkout_png(amount: int, message: str) -> bytes | None:
    if not PROFILE_URL:
        print("[scraper] ERROR: SAWERIA_USERNAME belum di-set")
        return None

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
            viewport={"width": 1280, "height": 900},
            locale="id-ID",
            timezone_id="Asia/Jakarta",
        )
        page = await context.new_page()
        try:
            await page.goto(PROFILE_URL, wait_until="domcontentloaded")
            await page.wait_for_timeout(700)
            await page.mouse.wheel(0, 480)
            await _fill_without_submit(page, amount, message, "gopay")

            target = await _click_donate_and_get_checkout_page(page, context)
            node = target["frame"] if target["frame"] else (target["page"] or page)

            el = await _find_qr_or_checkout_panel(node)
            if el:
                await el.scroll_into_view_if_needed()
                png = await el.screenshot()
                print("[scraper] captured CHECKOUT panel PNG:", len(png))
            else:
                png = await (node.screenshot(full_page=True) if hasattr(node, "screenshot") else page.screenshot(full_page=True))
                print("[scraper] WARN: no specific QR element; page screenshot:", len(png))

            await context.close()
            await browser.close()
            return png

        except Exception as e:
            print("[scraper] error(fetch_gopay_checkout_png):", e)
            try:
                snap = await page.screenshot(full_page=True)
                print("[scraper] debug page screenshot bytes:", len(snap))
            except:
                pass
            await context.close()
            await browser.close()
            return None


# ---------------------- Ambil HANYA QR matrix (crop) ----------------------
def _center_square_crop(png_bytes: bytes) -> bytes:
    im = Image.open(BytesIO(png_bytes)).convert("RGB")
    # trim margin putih
    bg = Image.new("RGB", im.size, (255, 255, 255))
    diff = ImageChops.difference(im, bg)
    bbox = diff.convert("L").point(lambda p: 255 if p > 10 else 0).getbbox()
    if bbox:
        im = im.crop(bbox)
    # crop persegi di tengah
    W, H = im.size
    side = min(W, H)
    left = (W - side) // 2
    top = (H - side) // 2
    im = im.crop((left, top, left + side, top + side))
    out = BytesIO()
    im.save(out, format="PNG")
    return out.getvalue()


async def fetch_gopay_qr_only_png(amount: int, message: str) -> bytes | None:
    """
    Isi form → klik 'Kirim Dukungan' → tunggu checkout GoPay
    → ambil elemen QR (canvas/img persegi) resolusi tinggi.
      Jika gagal, fallback poster→crop persegi tengah.
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
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
            viewport={"width": 1366, "height": 960},
            device_scale_factor=3,  # tajam
            locale="id-ID",
            timezone_id="Asia/Jakarta",
        )
        page = await context.new_page()

        async def pick_square_qr_candidate(node: Page | Frame):
            handles = []
            for q in [
                "canvas",
                'img[src^="data:image"]',
                'img[alt*="QR" i]',
                '[data-testid="qrcode"] img',
                '[class*="qrcode" i] img',
                'img[alt*="QRIS" i]',
            ]:
                try:
                    hs = await node.query_selector_all(q)
                    handles.extend(hs)
                except:
                    pass
            if not handles:
                return None

            best = None
            best_score = -1.0
            for h in handles:
                try:
                    box = await h.evaluate("el => { const r = el.getBoundingClientRect(); return {w:r.width,h:r.height}; }")
                    w = float(box["w"])
                    h = float(box["h"])
                    if w < 80 or h < 80:
                        continue
                    ratio = min(w, h) / max(w, h)
                    area = w * h
                    score = ratio * (area ** 0.5)
                    if score > best_score:
                        best_score = score
                        best = h
                except:
                    pass
            return best

        try:
            # profil + isi form
            await page.goto(PROFILE_URL, wait_until="domcontentloaded")
            await page.wait_for_timeout(600)
            await page.mouse.wheel(0, 500)
            await _fill_without_submit(page, amount, message, "gopay")

            # submit → checkout
            target = await _click_donate_and_get_checkout_page(page, context)
            node = target["frame"] if target["frame"] else (target["page"] or page)

            # cari elemen QR persegi
            qr_el = await pick_square_qr_candidate(node)
            if not qr_el:
                frames = node.page.frames if hasattr(node, "page") else page.frames
                for fr in frames:
                    url = (fr.url or "").lower()
                    if any(k in url for k in ["gopay", "qris", "xendit", "midtrans", "snap", "checkout", "pay"]):
                        qr_el = await pick_square_qr_candidate(fr)
                        if qr_el:
                            print("[scraper] square QR found in frame:", url[:100])
                            break

            if qr_el:
                await qr_el.scroll_into_view_if_needed()
                png = await qr_el.screenshot()
                print("[scraper] captured square QR element:", len(png))
                await context.close()
                await browser.close()
                return png

            # fallback: ambil poster/area lalu crop persegi tengah
            panel = await _find_qr_or_checkout_panel(node) or node
            poster = await (panel.screenshot() if hasattr(panel, "screenshot") else node.screenshot(full_page=True))
            cropped = _center_square_crop(poster)
            print("[scraper] fallback poster->center-square:", len(cropped))
            await context.close()
            await browser.close()
            return cropped

        except Exception as e:
            print("[scraper] error(fetch_gopay_qr_only_png):", e)
            try:
                snap = await page.screenshot(full_page=True)
                print("[scraper] debug page screenshot bytes:", len(snap))
            except:
                pass
            await context.close()
            await browser.close()
            return None


# ---------------------- Entrypoints lama (backward compat) ----------------------
async def fetch_qr_png(amount: int, message: str, method: Optional[str] = "gopay") -> bytes | None:
    """Isi form + pilih metode (default gopay) lalu screenshot panel (tanpa submit)."""
    if not PROFILE_URL:
        print("[scraper] ERROR: SAWERIA_USERNAME belum di-set")
        return None

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
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

            el = await _scan_all_frames_for_visual(page)
            if el:
                await el.scroll_into_view_if_needed()
                png = await el.screenshot()
                print("[scraper] captured filled panel PNG:", len(png))
            else:
                png = await page.screenshot(full_page=False)
                print("[scraper] WARN: no panel; page screenshot:", len(png))

            await context.close()
            await browser.close()
            return png

        except Exception as e:
            print("[scraper] error(fetch_qr_png):", e)
            try:
                snap = await page.screenshot(full_page=True)
                print("[scraper] debug page screenshot bytes:", len(snap))
            except:
                pass
            await context.close()
            await browser.close()
            return None


# ---------------------- Debug helpers ----------------------
async def debug_snapshot() -> bytes | None:
    if not PROFILE_URL:
        print("[debug_snapshot] ERROR: SAWERIA_USERNAME belum di-set")
        return None
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
            viewport={"width": 1280, "height": 900},
            locale="id-ID",
        )
        page = await context.new_page()
        await page.goto(PROFILE_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(1000)
        await page.mouse.wheel(0, 600)
        png = await page.screenshot(full_page=True)
        await context.close()
        await browser.close()
        return png


async def debug_fill_snapshot(amount: int, message: str, method: str = "gopay") -> bytes | None:
    if not PROFILE_URL:
        print("[debug_fill_snapshot] ERROR: SAWERIA_USERNAME belum di-set")
        return None
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
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
            await context.close()
            await browser.close()
            return png
        except Exception as e:
            print("[debug_fill_snapshot] error:", e)
            try:
                snap = await page.screenshot(full_page=True)
                await context.close()
                await browser.close()
                return snap
            except:
                await context.close()
                await browser.close()
                return None
