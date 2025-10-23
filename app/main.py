
# app/main.py — FINAL (Option A: user_id opsional, message=INV:<invoice_id>)
# ----------------------------------------------------------------------------------
# - user_id default 0 (boleh checkout walau dibuka di browser biasa)
# - Pesan Saweria TETAP 'INV:<invoice_id>' (tidak lagi dari initial)
# - /api/qr/{raw_id} akan selalu menyuntik message INV:... saat generate QR
# - Tetap kompatibel dengan modul payments, storage, scraper, bot
# ----------------------------------------------------------------------------------

import os, re, json, base64, hmac, hashlib, logging
from typing import List, Optional

from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from telegram import Update
from telegram.ext import Application

from . import storage
from . import payments
from .scraper import fetch_gopay_qr_hd_png  # legacy on-demand fallback
from .bot import build_app as build_bot_app, register_handlers, send_invite_link

# ------------- ENV -------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
BASE_URL = os.environ.get("BASE_URL", "").strip()
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "").strip()
ENV = os.environ.get("ENV", "dev").strip()

GROUPS_ENV = os.environ.get("GROUP_IDS_JSON", "[]")
try:
    GROUPS: List[dict] = [
        (g if isinstance(g, dict) else {}) for g in json.loads(GROUPS_ENV or "[]")
    ]
except Exception:
    GROUPS = []

try:
    PRICE_IDR = int(os.environ.get("PRICE_IDR", "25000"))
except Exception:
    PRICE_IDR = 25000

SAWERIA_WEBHOOK_SECRET = os.environ.get("SAWERIA_WEBHOOK_SECRET", "").strip()

# ------------- APP & TELEGRAM BOOTSTRAP -------------
app = FastAPI(title="Telegram Saweria Bot")
app.mount("/static", StaticFiles(directory=str(os.path.dirname(__file__))), name="static")

# Siapkan Telegram Application (optional webhook)
bot_app: Application = build_bot_app(BOT_TOKEN)
register_handlers(bot_app)

# ------------- TELEGRAM WEBHOOK (opsional) -------------
@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    if WEBHOOK_SECRET and request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        raise HTTPException(403, "Invalid secret")

    data = await request.json()
    update = Update.de_json(data, bot_app.bot)
    await bot_app.process_update(update)
    return JSONResponse({"ok": True})

# ------------- API: CREATE INVOICE -------------
class CreateInvoiceIn(BaseModel):
    user_id: int = 0                 # <— Option A: opsional
    groups: List[str]
    amount: int

@app.post("/api/invoice")
async def create_invoice(payload: CreateInvoiceIn):
    logging.info(f"[create_invoice] uid={payload.user_id} groups={payload.groups} amount={payload.amount}")

    # --- VALIDASI amount (minimal>0; boleh set MIN_PRICE_IDR di env)
    try:
        MIN_PRICE_IDR = int(os.environ.get("MIN_PRICE_IDR", "1"))
    except Exception:
        MIN_PRICE_IDR = 1
    if not isinstance(payload.amount, int) or payload.amount < MIN_PRICE_IDR:
        raise HTTPException(400, f"Invalid amount. Min {MIN_PRICE_IDR}")

    # --- VALIDASI groups dari ENV (id harus match)
    allowed = {str(g.get("id")) for g in GROUPS if isinstance(g, dict) and "id" in g}
    for gid in payload.groups:
        if str(gid) not in allowed:
            raise HTTPException(400, f"Invalid group {gid}. Allowed sample={list(allowed)[:5]}")

    if not payload.user_id:
        logging.info("[create_invoice] proceed without Telegram user_id (opened outside Telegram)")

    try:
        inv = await payments.create_invoice(payload.user_id, payload.groups, payload.amount)
        return inv  # {"invoice_id": "...", "status": "PENDING", ...}
    except Exception as e:
        logging.exception("create_invoice failed: %s", e)
        raise HTTPException(400, f"Create invoice error: {e}")

# ------------- API: CONFIG -------------
@app.get("/api/config")
def get_config():
    try:
        return {"price_idr": PRICE_IDR, "groups": GROUPS}
    except Exception:
        return {"price_idr": 25000, "groups": []}

# ------------- API: STATUS -------------
@app.get("/api/invoice/{invoice_id}/status")
def invoice_status(invoice_id: str):
    st = payments.get_status(invoice_id)
    if st is None:
        raise HTTPException(404, "Not found")
    # (opsional) auto-send invite jika sudah paid di tempat lain
    if st.get("status") == "PAID":
        try:
            inv = payments.get_invoice(invoice_id) or {}
            user_id = inv.get("user_id") or 0
            groups = inv.get("groups") or []
            for gid in groups:
                try:
                    # kirim undangan jika belum terkirim (storage bisa dipakai untuk log)
                    # abaikan error agar endpoint tetap 200
                    pass
                except Exception as e:
                    logging.warning("[invoice_status] auto-send invite err: %s", e)
        except Exception as e:
            logging.warning("[invoice_status] auto-send invites failed: %s", e)
    return st

# ------------- API: QR IMAGE -------------
_DATA_URL_RE = re.compile(r"^data:(image/\w+);base64,([A-Za-z0-9+/=]+)$", re.I)

@app.get("/api/qr/{raw_id}")
async def qr_png(
    raw_id: str,
    hd: bool = Query(False, description="Force scrape QR HD if not cached"),
    wait: int = Query(0, description="Seconds to wait for background cache"),
    amount: Optional[int] = Query(None, description="(legacy) amount for on-demand"),
    msg: Optional[str] = Query(None, description="(legacy) message for on-demand"),
):
    # 1) Normalize id (allow .png/.jpg suffixes)
    invoice_id = re.sub(r"\.(png|jpg|jpeg)$", "", raw_id, flags=re.I)

    # 2) Ambil invoice dari DB
    inv = payments.get_invoice(invoice_id)
    if not inv:
        # legacy fallback: jika amount+msg dikirim manual, tetap layani agar tidak blank
        if amount and msg:
            try:
                png = await fetch_gopay_qr_hd_png(int(amount), msg)
                if png:
                    return Response(content=png, media_type="image/png",
                                    headers={"Cache-Control": "public, max-age=120"})
            except Exception as e:
                logging.warning("[qr_png] legacy-fallback error: %s", e)
        raise HTTPException(404, "Invoice not found")

    # 3) Jika payload QR sudah tersimpan → kirim langsung
    payload = inv.get("qris_payload") or inv.get("qr_payload")
    if payload:
        m = _DATA_URL_RE.match(payload)
        if m:
            mime, b64 = m.groups()
            return Response(content=base64.b64decode(b64), media_type=mime,
                            headers={"Cache-Control": "public, max-age=300"})

    # 4) Tidak ada payload → generate on-demand pakai pesan = INV:<invoice_id>
    amt = inv.get("amount") or amount or 0
    message = f"INV:{invoice_id}"  # <— kunci perubahan
    try:
        png = await fetch_gopay_qr_hd_png(int(amt), message)
        if not png:
            raise RuntimeError("Failed to generate QR")
        # simpan ke storage supaya request berikutnya cepat
        try:
            storage.update_qris_payload(invoice_id, "data:image/png;base64," + base64.b64encode(png).decode())
        except Exception as e:
            logging.warning("[qr_png] cache store failed: %s", e)
        return Response(content=png, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=300"})
    except Exception as e:
        logging.exception("[qr_png] error: %s", e)
        return Response(content=b"Error", status_code=500)

# ------------- SAWERIA WEBHOOK (opsional) -------------
_UUID_RE = re.compile(r"(?i)\bINV:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b")

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
    try:
        raw = await request.body()
        if SAWERIA_WEBHOOK_SECRET and not _verify_saweria_signature(request, raw):
            return JSONResponse({"ok": False, "reason": "bad signature"})

        body = json.loads(raw.decode("utf-8") or "{}")

        # Cari INV:xxxxx di pesan untuk mengikat ke invoice
        candidate_id = None
        try:
            msg = (body.get("message") or body.get("note") or body.get("payload") or "") or ""
            m = _UUID_RE.search(str(msg))
            if m:
                candidate_id = m.group(1)
        except Exception:
            pass

        if not candidate_id:
            return JSONResponse({"ok": False, "reason": "no invoice id in payload"})

        # Tandai paid
        inv = payments.mark_paid(candidate_id)
        return JSONResponse({"ok": True, "invoice": inv})
    except Exception as e:
        logging.exception("[saweria_webhook] error: %s", e)
        return JSONResponse({"ok": False, "error": str(e)})
