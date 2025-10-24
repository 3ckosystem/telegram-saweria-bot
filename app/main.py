# =============================
# app/main.py
# =============================
import os, re, uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict

from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from telegram.ext import Application

from .bot import build_app, send_invite_link
from .scraper import fetch_gopay_qr_hd_png

# ---------------- ENV ----------------
BOT_TOKEN = os.environ["BOT_TOKEN"]
BASE_URL = os.environ.get("BASE_URL", "").strip()
ENV = os.getenv("ENV", "dev")

# ---------------- APP ----------------
app = FastAPI()

# Reuse a single Telegram Application instance
_tg_app: Optional[Application] = None
async def _get_tg_app() -> Application:
    global _tg_app
    if _tg_app is None:
        _tg_app = await build_app(BOT_TOKEN)
    return _tg_app

# ------------- In-memory QR cache (simple) -------------
# NOTE: Cache hilang saat container restart. Untuk produksi,
# simpan ke Redis/DB jika perlu persist.
QR_CACHE: Dict[str, bytes] = {}

# ------------- Models -------------
class CreateInvoiceReq(BaseModel):
    user_id: int
    groups: List[str]
    amount: int

class CreateInvoiceRes(BaseModel):
    invoice_id: str
    msg: str
    amount: int

# ------------- Helpers -------------
async def _generate_qr_and_cache(invoice_id: str, amount: int, msg: str):
    try:
        png = await fetch_gopay_qr_hd_png(amount=amount, msg=msg)
        QR_CACHE[invoice_id] = png
    except Exception as e:
        # Biarkan kosong; frontend akan polling /status hingga ready
        print("[QR][error]", invoice_id, repr(e))

async def _send_invites_for_invoice(user_id: int, groups: List[str], invoice_id: str):
    app_tg = await _get_tg_app()
    for gid in groups:
        try:
            await send_invite_link(app_tg, chat_id=user_id, target_group_id=str(gid))
        except Exception as e:
            print("[invite][error]", invoice_id, gid, repr(e))

# ------------- API: Create Invoice -------------
@app.post("/api/invoice", response_model=CreateInvoiceRes)
async def create_invoice(req: CreateInvoiceReq, bg: BackgroundTasks):
    invoice_id = str(uuid.uuid4())
    msg = f"INV:{invoice_id}"

    # Mulai generate QR di background (non-blocking)
    bg.add_task(_generate_qr_and_cache, invoice_id, req.amount, msg)

    # Catatan: mapping invoice -> (user_id, groups) bisa kamu simpan ke DB
    # jika ingin webhook kirim undangan tanpa mengandalkan payload webhook.

    return CreateInvoiceRes(invoice_id=invoice_id, msg=msg, amount=req.amount)

# ------------- API: Invoice Status -------------
@app.get("/api/invoice/{invoice_id}/status")
async def invoice_status(invoice_id: str):
    state = "ready" if invoice_id in QR_CACHE else "pending"
    payload = {"state": state}
    if state == "ready":
        payload["qris_url"] = (
            f"{BASE_URL}/api/invoice/{invoice_id}/qris.png" if BASE_URL
            else f"/api/invoice/{invoice_id}/qris.png"
        )
    return JSONResponse(payload)

# ------------- API: Serve QR PNG -------------
@app.get("/api/invoice/{invoice_id}/qris.png")
async def invoice_qr_png(invoice_id: str):
    data = QR_CACHE.get(invoice_id)
    if not data:
        return JSONResponse({"error": "QR not ready"}, status_code=404)
    return Response(content=data, media_type="image/png", headers={"Cache-Control": "no-store"})

# ------------- WEBHOOK: Saweria (aliases) -------------
async def _handle_saweria_webhook(request: Request):
    data = await request.json()

    # Normalisasi status & catatan
    status = (data.get("status") or data.get("event") or "").upper()
    note = (
        data.get("message")
        or data.get("note")
        or data.get("msg")
        or data.get("payload")
        or ""
    )

    # Extract "INV:<uuid>" dari note/pesan
    m = re.search(r"INV:([0-9a-fA-F\-]{36})", str(note))
    if not m:
        return JSONResponse({"ok": True, "skip": "no-invoice-id"}, status_code=200)

    invoice_id = m.group(1)

    # Terima hanya status final
    if status not in ("PAID", "SETTLEMENT"):
        return JSONResponse({"ok": True, "skip": f"status {status}"}, status_code=200)

    # Ambil mapping user & groups dari payload webhook jika dikirim
    # (Alternatif yang lebih kuat: baca dari DB berdasarkan invoice_id)
    user_id = data.get("user_id") or data.get("telegram_user_id")
    groups = data.get("groups") or []

    if user_id and groups:
        try:
            await _send_invites_for_invoice(int(user_id), [str(g) for g in groups], invoice_id)
        except Exception as e:
            print("[webhook][send_invite][error]:", repr(e))

    return JSONResponse({"ok": True}, status_code=200)

@app.post("/webhook/saweria")
async def saweria_webhook_v1(request: Request):
    return await _handle_saweria_webhook(request)

@app.post("/api/saweria/webhook")
async def saweria_webhook_v2(request: Request):
    return await _handle_saweria_webhook(request)
