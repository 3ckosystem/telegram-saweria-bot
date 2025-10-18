# app/scraper.py
# ------------------------------------------------------------
# Isi form Saweria + pilih GoPay (tanpa submit) → klik "Kirim Dukungan"
# → tangkap panel/QR atau unduh QR HD langsung dari <img src=".../qr-code">.
# ------------------------------------------------------------
from __future__ import annotations

import os, re, uuid, base64
from typing import Optional
from urllib.parse import urljoin

from playwright.async_api import async_playwright, Page, Frame
from playwright.async_api import Error as PWError

SAWERIA_USERNAME = os.getenv("SAWERIA_USERNAME", "").strip()
PROFILE_URL = f"https://saweria.co/{SAWERIA_USERNAME}" if SAWERIA_USERNAME else None

# Trigger event input/change untuk beberapa UI reaktif
FORCE_DISPATCH = True
# Mode cepat: lewati field yang tidak wajib
FAST_MODE = True

# --- Reuse browser instance untuk menekan latency ---
_PLAY = None
_BROWSER = None

async def _get_browser():
    global _PLAY, _BROWSER
    if _PLAY is None:
        _PLAY = await async_playwright().start()
    if _BROWSER is None:
        _BROWSER = await _PLAY.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
    return _BROWSER

async def _new_context():
    browser = await _get_browser()
    context = await browser.new_context(
        user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
        viewport={"width": 1366, "height": 960},
        device_scale_factor=2,
        locale="id-ID",
        timezone_id="Asia/Jakarta",
    )

    # Block resource tak penting agar load lebih cepat
    async def _route_handler(route):
        req = route.request
        rtype = req.resource_type
        url = (req.url or "").lower()
        if rtype in ("font", "media"):
            return await route.abort()
        if "googletagmanager" in url or "analytics" in url:
            return await route.abort()
        if rtype == "stylesheet" and ("midtrans" not in url):
            return await route.abort()
        return await route.continue_()

    await context.route("**/*", _route_handler)
    return context

# Warm-up agar Chromium siap sejak awal (dipanggil di main.py startup)
async def warmup_browser():
    try:
        await _get_browser()
        print("[scraper] browser warmed")
    except Exception as e:
        print("[scraper] warmup failed:", e)

# ---------- util ----------
async def _find_payment_root(node: Page | Frame):
    for sel in (
        '[data-testid*="donate" i]',
        '[data-testid*="payment" i]',
        '[class*="donate" i]',
        '[class*="payment" i]',
        'form',
        'section:has(button)',
        'div:has(button)',
    ):
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
    if not FORCE_DISPATCH or handle is None:
        return
    try:
        await page.evaluate(
            "(e)=>{ if(!e) return; e.dispatchEvent(new Event('input',{bubbles:true}));"
            " e.dispatchEvent(new Event('change',{bubbles:true})); e.blur && e.blur(); }",
            handle,
        )
    except:
        pass

async def _select_gopay_and_wait_total(page: Page, amount: int):
    gopay_selectors = [
        '[data-testid="gopay-button"]',
        'button[data-testid="gopay-button"]',
        'button:has-text("GoPay")',
        '[role="radio"]:has-text("GoPay")',
        '[data-testid*="gopay"]',
    ]
    for sel in gopay_selectors:
        try:
            el = await page.wait_for_selector(sel, timeout=2500)
            await el.scroll_into_view_if_needed()
            await el.click(force=True)
            print("[scraper] clicked GoPay via", sel)
            break
        except:
            pass

    try:
        await page.keyboard.press("Tab")
    except:
        pass
    await page.wait_for_timeout(150)

    try:
        rupiah = f"{amount:,}".replace(",", ".")
        await page.get_by_text(re.compile(rf"Jumlah Dukungan:\s*Rp{rupiah}\b")).wait_for(timeout=2500)
        print("[scraper] amount reflected in UI")
    except:
        print("[scraper] WARN: amount not reflected in 'Jumlah Dukungan'")

    try:
        await page.wait_for_function("""
            () => {
              const el = [...document.querySelectorAll('*')]
                .find(n => /Total:\s*Rp/i.test(n.textContent||''));
              if (!el) return false;
              const m = (el.textContent||'').match(/Total:\s*Rp\s*([\d.]+)/i);
              if (!m) return false;
              const num = parseInt(m[1].replace(/\./g,''));
              return Number.isFinite(num) && num > 0;
            }
        """, timeout=5000)
        print("[scraper] Total > 0 (OK)")
    except:
        print("[scraper] WARN: Total still 0 after selecting GoPay")

async def _fill_without_submit(page: Page, amount: int, message: str, method: str):
    # amount
    amount_handle = None
    for sel in (
        'input[placeholder*="Ketik jumlah" i]',
        'input[aria-label*="Nominal" i]',
        'input[name="amount"]',
        'input[type="number"]',
    ):
        try:
            el = await page.wait_for_selector(sel, timeout=2000)
            await el.scroll_into_view_if_needed()
            await el.click()
            try:
                await page.keyboard.press("Control+A")
            except:
                await page.keyboard.press("Meta+A")
            await page.keyboard.press("Backspace")
            await el.type(str(amount))
            amount_handle = el
            print("[scraper] filled amount via", sel)
            break
        except:
            pass
    await _maybe_dispatch(page, amount_handle)
    await page.wait_for_timeout(120)

    # name/email/checkbox → skip jika FAST_MODE
    if not FAST_MODE:
        try:
            el = await page.wait_for_selector('input[name="name"], input[placeholder*="Dari" i]', timeout=1200)
            await el.scroll_into_view_if_needed()
            await el.fill("Budi")
            await _maybe_dispatch(page, el)
            print("[scraper] filled name")
        except:
            pass
        try:
            el = await page.wait_for_selector('input[type="email"], input[name="email"]', timeout=1200)
            await el.scroll_into_view_if_needed()
            await el.fill(f"donor+{uuid.uuid4().hex[:8]}@example.com")
            await _maybe_dispatch(page, el)
            print("[scraper] filled email")
        except:
            pass
        for text in ["17 tahun", "menyetujui", "kebijakan privasi", "ketentuan"]:
            try:
                node = page.get_by_text(re.compile(text, re.I))
                await node.scroll_into_view_if_needed()
                await node.click()
                print("[scraper] checked:", text)
            except:
                pass

    # message
    for sel in (
        'input[name="message"]','input[data-testid="message-input"]','#message',
        'input[placeholder*="pesan" i]','textarea[name="message"]','textarea',
    ):
        try:
            el = await page.wait_for_selector(sel, timeout=1500)
            await el.scroll_into_view_if_needed()
            await el.fill(message)
            await _maybe_dispatch(page, el)
            print("[scraper] filled message via", sel)
            break
        except:
            pass
    await page.wait_for_timeout(140)

    # pilih GoPay
    if (method or "gopay").lower() == "gopay":
        try:
            area = await page.get_by_text(
                re.compile("Moda pembayaran|Metode pembayaran|GoPay|QRIS", re.I)
            ).element_handle()
            if area:
                await area.scroll_into_view_if_needed()
        except:
            await page.mouse.wheel(0, 600)
        await _select_gopay_and_wait_total(page, amount)

    await page.wait_for_timeout(250)

async def _click_donate_and_get_checkout_page(page: Page, context):
    donate_selectors = [
        'button[data-testid="donate-button"]',
        'button:has-text("Kirim Dukungan")',
        'text=/\\bKirim\\s+Dukungan\\b/i',
    ]
    new_page_task = context.wait_for_event("page")
    for sel in donate_selectors:
        try:
            el = await page.wait_for_selector(sel, timeout=2500)
            await el.scroll_into_view_if_needed()
            await el.click()
            print("[scraper] clicked DONATE via", sel)
            break
        except:
            pass

    target_page = None
    try:
        target_page = await new_page_task
    except:
        pass
    if target_page:
        await target_page.wait_for_load_state("domcontentloaded")
        await target_page.wait_for_load_state("networkidle")
        print("[scraper] checkout NEW TAB:", target_page.url)
        return {"page": target_page, "frame": None}

    try:
        await page.wait_for_load_state("networkidle", timeout=6000)
        print("[scraper] checkout SAME PAGE:", page.url)
        return {"page": page, "frame": None}
    except:
        pass

    for fr in page.frames:
        u = (fr.url or "").lower()
        if any(k in u for k in ["gopay","qris","xendit","midtrans","snap","checkout","pay"]):
            print("[scraper] checkout IFRAME:", u[:120])
            return {"page": None, "frame": fr}

    return {"page": page, "frame": None}

async def _find_qr_or_checkout_panel(node):
    for sel in (
        'img[alt*="QR" i]','img[src^="data:image"]','[data-testid="qrcode"] img',
        '[class*="qrcode" i] img',"canvas",
        '[data-testid*="checkout" i]','[class*="checkout" i]',
        'div:has-text("Cek status")','div:has-text("Download QRIS")',
    ):
        try:
            el = await node.wait_for_selector(sel, timeout=4000)
            return el
        except:
            pass
    return None

# ---------- screenshot panel checkout (fallback) ----------
async def fetch_gopay_checkout_png(amount: int, message: str) -> bytes | None:
    if not PROFILE_URL:
        print("[scraper] ERROR: SAWERIA_USERNAME belum di-set")
        return None

    context = await _new_context()
    page = await context.new_page()
    try:
        await page.goto(PROFILE_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(600)
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
            png = await (target["page"] or page).screenshot(full_page=True)
            print("[scraper] WARN: no specific QR element; page screenshot:", len(png))
        await context.close()
        return png
    except Exception as e:
        print("[scraper] error(fetch_gopay_checkout_png):", e)
        try:
            snap = await page.screenshot(full_page=True)
            print("[scraper] debug page screenshot bytes:", len(snap))
        except:
            pass
        await context.close()
        return None

# ---------- panel tanpa submit ----------
async def fetch_qr_png(amount: int, message: str, method: Optional[str] = "gopay") -> bytes | None:
    if not PROFILE_URL:
        print("[scraper] ERROR: SAWERIA_USERNAME belum di-set")
        return None

    context = await _new_context()
    page = await context.new_page()
    try:
        await page.goto(PROFILE_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(600)
        await page.mouse.wheel(0, 480)

        await _fill_without_submit(page, amount, message, method or "gopay")
        await page.wait_for_timeout(600)

        el = await _scan_all_frames_for_visual(page)
        if el:
            await el.scroll_into_view_if_needed()
            png = await el.screenshot()
            print("[scraper] captured filled panel PNG:", len(png))
        else:
            png = await page.screenshot(full_page=False)
            print("[scraper] WARN: no panel; page screenshot:", len(png))

        await context.close()
        return png
    except Exception as e:
        print("[scraper] error:", e)
        try:
            snap = await page.screenshot(full_page=True)
            print("[scraper] debug page screenshot bytes:", len(snap))
        except:
            pass
        await context.close()
        return None

# ---------- QR HD (<img src=".../qr-code">) ----------
async def fetch_gopay_qr_hd_png(amount: int, message: str) -> bytes | None:
    if not PROFILE_URL:
        print("[scraper] ERROR: SAWERIA_USERNAME belum di-set")
        return None

    context = await _new_context()
    page = await context.new_page()

    def _selectors():
        return [
            'img.qr-image','img.qr-image--with-wrapper','img[alt*="qr-code" i]',
            'img[src*="/qr-code"]','[data-testid="qrcode"] img','[class*="qrcode" i] img',
            'img[alt*="QRIS" i]','canvas',
        ]

    try:
        await page.goto(PROFILE_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(500)
        await page.mouse.wheel(0, 500)
        await _fill_without_submit(page, amount, message, "gopay")

        target = await _click_donate_and_get_checkout_page(page, context)
        node: Page | Frame = target["frame"] if target["frame"] else (target["page"] or page)

        qr_handle = None
        for sel in _selectors():
            try:
                qr_handle = await node.wait_for_selector(sel, timeout=3200)
                if qr_handle:
                    print("[scraper] QR handle via", sel)
                    break
            except PWError:
                pass

        if not qr_handle:
            frames = node.page.frames if hasattr(node, "page") else page.frames
            for fr in frames:
                url = (fr.url or "").lower()
                if any(k in url for k in ["gopay","qris","midtrans","snap","checkout","pay"]):
                    for sel in _selectors():
                        try:
                            qr_handle = await fr.wait_for_selector(sel, timeout=2200)
                            if qr_handle:
                                print("[scraper] QR handle via", sel, "in frame", url[:100])
                                break
                        except PWError:
                            pass
                if qr_handle:
                    break

        if not qr_handle:
            print("[scraper] WARN: QR handle not found; fallback to panel shot")
            panel = await _find_qr_or_checkout_panel(node) or node
            png = await (panel.screenshot() if hasattr(panel, "screenshot") else node.screenshot(full_page=True))
            await context.close()
            return png

        tag = await qr_handle.evaluate("(el)=>el.tagName.toLowerCase()")
        if tag == "img":
            src = await qr_handle.evaluate("(img)=>img.currentSrc || img.src || ''")
            if not src:
                await qr_handle.scroll_into_view_if_needed()
                png = await qr_handle.screenshot()
                await context.close()
                return png

            if src.startswith("data:image/"):
                header, b64 = src.split(",", 1)
                try:
                    data = base64.b64decode(b64)
                    await context.close()
                    return data
                except Exception as e:
                    print("[scraper] WARN: decode data URL failed:", e)

            abs_url = urljoin((node.url if hasattr(node, "url") else page.url), src)
            try:
                r = await context.request.get(abs_url, headers={
                    "Referer": (node.url if hasattr(node, "url") else page.url),
                    "User-Agent": await page.evaluate("() => navigator.userAgent"),
                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                })
                if r.ok:
                    data = await r.body()
                    print("[scraper] downloaded QR img bytes:", len(data))
                    await context.close()
                    return data
                else:
                    print("[scraper] WARN: request img failed", r.status)
            except Exception as e:
                print("[scraper] WARN: fetch img error:", e)

            await qr_handle.scroll_into_view_if_needed()
            png = await qr_handle.screenshot()
            await context.close()
            return png

        await qr_handle.scroll_into_view_if_needed()
        png = await qr_handle.screenshot()
        await context.close()
        return png

    except Exception as e:
        print("[scraper] error(fetch_gopay_qr_hd_png):", e)
        try:
            snap = await page.screenshot(full_page=True)
            print("[scraper] debug page screenshot bytes:", len(snap))
        except:
            pass
        await context.close()
        return None
