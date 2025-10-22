# app/main.py
import os, json, re, base64, hmac, hashlib, httpx
from typing import Optional, List

from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from telegram import Update
from telegram.ext import Application

from .bot import build_app, register_handlers, send_invite_link
from . import payments, storage

# === penting: import nama fungsi yang benar
from .scraper import (
    debug_snapshot,
    debug_fill_snapshot,
    fetch_gopay_checkout_png,
    fetch_gopay_qr_hd_png,   # <- betul (png)
)

# ------------- ENV -------------
BOT_TOKEN = os.environ["BOT_TOKEN"]
BASE_URL = os.environ["BASE_URL"].strip()
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
ENV = os.getenv("ENV", "dev")  # "prod" di Railway untuk mematikan debug endpoints

# Robust reader utk GROUP_IDS_JSON & PRICE_IDR
def _read_env_json(name: str, default_text: str = "[]"):
    raw = os.environ.get(name, default_text)
    if raw is None:
        return []
    s = raw.strip()
    try:
        return json.loads(s)
    except Exception:
        # fallback jika ada single quotes
        try:
            return json.loads(s.replace("'", '"'))
        except Exception:
            return []

def _parse_groups_from_any(data):
    groups = []
    if isinstance(data, dict):
        for k, v in data.items():
            groups.append({"id": str(k), "name": str(v)})
    elif isinstance(data, list):
        for it in data:
            if isinstance(it, dict):
                gid = str(it.get("id") or it.get("group_id") or it.get("value") or "").strip()
                nm  = str(it.get("name") or it.get("label")    or it.get("text")  or "").strip()
                if gid and nm:
                    groups.append({"id": gid, "name": nm})
            else:
                gid = str(it).strip()
                if gid:
                    groups.append({"id": gid, "name": gid})
    return groups

# BACA ENV SEKARANG (module scope)
GROUPS_DATA = _read_env_json("GROUP_IDS_JSON", "[]")
GROUPS = _parse_groups_from_any(GROUPS_DATA)

try:
    PRICE_IDR = int(os.environ.get("PRICE_IDR", "25000"))
except Exception:
    PRICE_IDR = 25000


# ------------- APP & BOT -------------
app = FastAPI()
storage.init_db()

bot_app: Application = build_app()
register_handlers(bot_app)

# Serve Mini App statics
app.mount("/webapp", StaticFiles(directory="app/webapp", html=True), name="webapp")

# ------------- TELEGRAM WEBHOOK -------------
@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    # optional secret validation
    if WEBHOOK_SECRET and request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        raise HTTPException(403, "Invalid secret")

    data = await request.json()
    update = Update.de_json(data, bot_app.bot)
    await bot_app.process_update(update)
    return JSONResponse({"ok": True})


# ------------- API: CREATE INVOICE -------------
class CreateInvoiceIn(BaseModel):
    user_id: int
    groups: List[str]
    amount: int

@app.post("/api/invoice")
async def create_invoice(payload: CreateInvoiceIn):
    # --- DEBUG LOG (bisa hapus setelah stabil)
    import logging, json as _json
    logging.info(f"[create_invoice] uid={payload.user_id} groups={payload.groups} amount={payload.amount}")

    # --- VALIDASI amount (minimal>0; boleh set MIN_PRICE_IDR di env)
    try:
        MIN_PRICE_IDR = int(os.environ.get("MIN_PRICE_IDR", "1"))
    except Exception:
        MIN_PRICE_IDR = 1
    if not isinstance(payload.amount, int) or payload.amount < MIN_PRICE_IDR:
        raise HTTPException(400, f"Invalid amount. Min {MIN_PRICE_IDR}")

    # --- VALIDASI groups dari ENV (id harus match)
    try:
        allowed = {str(g["id"]) for g in GROUPS}
    except Exception:
        allowed = set()
    for gid in payload.groups:
        if str(gid) not in allowed:
            # kasih tahu id yang valid untuk debug cepat
            raise HTTPException(400, f"Invalid group {gid}. Allowed={list(allowed)[:5]}...")

    # --- CALL payments.create_invoice dengan proteksi error
    try:
        id_to_initial = {str(g['id']): str(g.get('initial','')).strip() for g in GROUPS}
        initials = [id_to_initial.get(str(gid), '') for gid in payload.groups]
        message = ' '.join([s.strip() for s in initials if s.strip()])
        inv = await payments.create_invoice(payload.user_id, payload.groups, payload.amount, message=message)
        # bentuk response minimal agar UI jalan
        return inv  # biasanya: {"invoice_id": "...", "status": "PENDING", "qr_url": "...", ...}
    except Exception as e:
        # log stacktrace biar kelihatan jelas di Railway logs
        import traceback, logging
        logging.error("create_invoice failed: %s", e)
        logging.error(traceback.format_exc())
        # balas 400 ke UI agar tampil pesan manusiawi, bukan 500
        raise HTTPException(400, f"Create invoice error: {e}")


# ------------- API: CONFIG -------------
@app.get("/api/config")
def get_config():
    try:
        return {"price_idr": PRICE_IDR, "groups": GROUPS}
    except Exception:
        return {"price_idr": 25000, "groups": []}



# ------------- API: STATUS & QR IMAGE -------------
_DATA_URL_RE = re.compile(r"^data:(image/[^;]+);base64,(.+)$")

@app.get("/api/invoice/{invoice_id}/status")
def invoice_status(invoice_id: str):
    st = payments.get_status(invoice_id)
    if not st:
        raise HTTPException(404, "Invoice not found")
    # contoh balikan: {"status":"PENDING"|"PAID","paid_at":..., "has_qr": true|false}
    return st

# --- ganti seluruh fungsi ini ---
@app.get("/api/qr/{raw_id}")
async def qr_png(
    raw_id: str,
    hd: bool = Query(False, description="Force scrape QR HD if not cached"),
    wait: int = Query(0, description="Seconds to wait for background cache"),
    amount: int | None = Query(None, description="(legacy) amount for on-demand"),
    msg: str | None = Query(None, description="(legacy) message for on-demand"),
):
    # 1) Normalisasi ID: izinkan .../{invoice_id}.png atau .jpg
    invoice_id = re.sub(r"\.(png|jpg|jpeg)$", "", raw_id, flags=re.I)

    # 2) Ambil invoice dari DB
    inv = payments.get_invoice(invoice_id)
    if not inv:
        # fallback super-legacy: kalau belum ada di DB tapi ada amount+msg, kita masih
        # coba hasilkan QR on-demand supaya tidak blank (opsional)
        if amount and msg:
            try:
                png = await fetch_gopay_qr_hd_png(int(amount), msg)
                if png:
                    return Response(content=png, media_type="image/png",
                                    headers={"Cache-Control": "public, max-age=120"})
            except Exception as e:
                print("[qr_png] legacy-fallback error:", e)
        raise HTTPException(404, "Invoice not found")

    # siapkan nilai umum
    amt = inv.get("amount") or amount or 0
    message = f"INV:{invoice_id}"

    # 3) Jika sudah ada payload di DB → langsung kirim
    payload = inv.get("qris_payload")
    if payload:
        m = _DATA_URL_RE.match(payload)
        if not m:
            raise HTTPException(400, "Bad image payload")
        mime, b64 = m.groups()
        return Response(
            content=base64.b64decode(b64),
            media_type=mime,
            headers={"Cache-Control": "public, max-age=300"},
        )

    # 4) Tunggu sebentar background (opsional)
    if wait and isinstance(wait, int) and wait > 0:
        import asyncio
        for _ in range(min(wait, 8)):
            await asyncio.sleep(1)
            inv2 = payments.get_invoice(invoice_id)
            payload2 = inv2.get("qris_payload") if inv2 else None
            if payload2:
                m = _DATA_URL_RE.match(payload2)
                if not m:
                    break
                mime, b64 = m.groups()
                return Response(
                    content=base64.b64decode(b64),
                    media_type=mime,
                    headers={"Cache-Control": "public, max-age=300"},
                )

    # 5) Generate on-demand (HD) + cache ke DB 
    try:
        png = await fetch_gopay_qr_hd_png(amt, message)
        if not png:
            return Response(content=b"QR not found", status_code=502)

        try:
            b64 = base64.b64encode(png).decode()
            storage.update_qris_payload(invoice_id, f"data:image/png;base64,{b64}")
        except Exception:
            pass

        return Response(
            content=png,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=300"},
        )
    except Exception as e:
        print("[qr_png] error:", e)
        return Response(content=b"Error", status_code=500)
# --- sampai sini ---


# ------------- SAWERIA WEBHOOK (opsional) -------------
# Jika kamu sudah menghubungkan webhook Saweria untuk tandai pembayaran "PAID"
class SaweriaWebhookIn(BaseModel):
    status: str
    invoice_id: Optional[str] = None
    external_id: Optional[str] = None
    message: Optional[str] = None

SAWERIA_WEBHOOK_SECRET = os.getenv("SAWERIA_WEBHOOK_SECRET", "")

def _verify_saweria_signature(req: Request, raw_body: bytes) -> bool:
    if not SAWERIA_WEBHOOK_SECRET:
        return True
    sig_hdr = req.headers.get("X-Saweria-Signature")
    if not sig_hdr:
        return False
    calc = hmac.new(SAWERIA_WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(calc, sig_hdr)

@app.post("/api/saweria/webhook")
async def saweria_webhook(request: Request):
    raw = await request.body()
    if not _verify_saweria_signature(request, raw):
        raise HTTPException(403, "Bad signature")
    data = SaweriaWebhookIn.model_validate_json(raw)
    if data.status.lower() != "paid":
        return {"ok": True}

    # tandai invoice paid (gunakan message atau external_id/invoice_id sesuai implementasi kamu)
    inv = None
    if data.invoice_id:
        inv = payments.mark_paid(data.invoice_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")

    # kirim undangan ke semua grup terkait
    groups = json.loads(inv["groups_json"])
    for gid in groups:
        try:
            await send_invite_link(bot_app, inv["user_id"], gid)
            storage.add_invite_log(inv["invoice_id"], gid, "(sent-via-bot)", None)
        except Exception as e:
            storage.add_invite_log(inv["invoice_id"], gid, None, str(e))
    return {"ok": True}

# ------------- HEALTH / DEBUG -------------
@app.get("/health")
def health():
    return {"ok": True}

if ENV != "prod":
    @app.get("/debug/invoices")
    def debug_invoices(limit: int = 20):
        return {"items": payments.list_invoices(limit)}

    @app.get("/debug/invite-logs/{invoice_id}")
    def debug_invite_logs(invoice_id: str):
        return {"invoice_id": invoice_id, "logs": storage.list_invite_logs(invoice_id)}

# ---- DEBUG: tes HTTP fetch langsung (tanpa Chromium) ----
@app.get("/debug/fetch-saweria")
async def debug_fetch_saweria():
    username = os.getenv("SAWERIA_USERNAME", "").strip()
    if not username:
        raise HTTPException(400, "SAWERIA_USERNAME belum di-set")
    url = f"https://saweria.co/{username}"
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(url, headers={
            "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
        })
    return {"url": url, "status": r.status_code, "len": len(r.text), "snippet": r.text[:300]}

# ---- DEBUG: ambil PNG dari Chromium (Playwright) ----
@app.get("/debug/saweria-snap")
async def debug_saweria_snap():
    png = await debug_snapshot()
    if not png:
        raise HTTPException(500, "Gagal snapshot (lihat logs)")
    return Response(content=png, media_type="image/png")

@app.get("/debug/saweria-fill")
async def debug_saweria_fill(amount: int = 25000, msg: str = "INV:debug", method: str = "gopay"):
    png = await debug_fill_snapshot(amount, msg, method)
    if not png:
        raise HTTPException(500, "Gagal snapshot setelah pengisian form (lihat logs)")
    return Response(content=png, media_type="image/png")

@app.get("/debug/saweria-pay")
async def debug_saweria_pay(amount: int = 25000, msg: str = "INV:debug"):
    png = await fetch_gopay_checkout_png(amount, msg)
    if not png:
        raise HTTPException(500, "Gagal menuju halaman pembayaran")
    return Response(content=png, media_type="image/png")

@app.get("/debug/saweria-qr-hd")
async def debug_saweria_qr_hd(amount: int = 25000, msg: str = "INV:qr-hd"):
    png = await fetch_gopay_qr_hd_png(amount, msg)
    if not png:
        raise HTTPException(500, "Gagal ambil QR HD")
    return Response(content=png, media_type="image/png")

# ------------- STARTUP / SHUTDOWN -------------
@app.on_event("startup")
async def on_start():
    await bot_app.initialize()
    if BASE_URL.startswith("https://"):
        await bot_app.bot.set_webhook(
            url=f"{BASE_URL}/telegram/webhook",
            secret_token=WEBHOOK_SECRET or None,
        )
    else:
        print("Skipping set_webhook: BASE_URL must start with https://")
    await bot_app.start()

@app.on_event("shutdown")
async def on_stop():
    await bot_app.stop()
    await bot_app.shutdown()
