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
# ------------- ENV -------------
ENV = os.getenv("ENV", "dev")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

def _read_env_json(name: str, default: str = "[]"):
    raw = os.environ.get(name, default)
    try:
        return json.loads(raw)
    except Exception:
        return json.loads(default)

def _parse_groups_from_any(data) -> List[dict]:
    groups = []
    if isinstance(data, dict):
        for k, v in data.items():
            groups.append({"id": str(k), "name": str(v)})
    elif isinstance(data, list):
        for it in data:
            if isinstance(it, dict):
                gid = str(it.get("id") or it.get("group_id") or it.get("value") or "").strip()
                nm  = str(it.get("name") or it.get("label")    or it.get("text")  or "").strip()
                init = str(it.get("initial") or "").strip()
                if gid and nm:
                    groups.append({"id": gid, "name": nm, "initial": init})
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

# init DB
storage.init_db()

bot_app: Application = build_app()
register_handlers(bot_app)

# Helper: kirim undangan untuk sebuah invoice (idempotent-ish)
async def _send_invites_for_invoice(inv: dict) -> None:
    """
    Kirim undangan ke semua grup pada invoice.
    Aman dipanggil berkali-kali karena kita log ke invite_logs.
    """
    try:
        groups = json.loads(inv.get("groups_json") or "[]")
    except Exception:
        groups = []
    if not groups:
        return
    # kalau sudah pernah log sukses, jangan kirim ulang (minimalkan duplikasi)
    logs = storage.list_invite_logs(inv["invoice_id"])
    already = {l.get("group_id") for l in logs if l.get("invite_link") or "(sent" in (l.get("invite_link") or "")}
    for gid in groups:
        if gid in already:
            continue
        try:
            await send_invite_link(bot_app, inv["user_id"], gid)
            storage.add_invite_log(inv["invoice_id"], gid, "(sent-via-status)", None)
        except Exception as e:
            storage.add_invite_log(inv["invoice_id"], gid, None, str(e))

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

# ------------- API: CONFIG (untuk Mini App) -------------
@app.get("/api/config")
def api_config():
    return {"price_idr": PRICE_IDR, "groups": GROUPS}

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
        inv = await payments.create_invoice(payload.user_id, payload.groups, payload.amount)
        # bentuk response minimal agar UI jalan
        return inv  # biasanya: {"invoice_id": "...", "status": "PENDING", "qr_url": "...", ...}
    except Exception as e:
        # log stacktrace biar kelihatan jelas di Railway logs
        import traceback, logging
        logging.error("create_invoice failed: %s", e)
        logging.error(traceback.format_exc())
        # balas 400 ke UI agar tampil pesan manusiawi, bukan 500
        raise HTTPException(400, f"Create invoice error: {e}")

# ------------- API: QR (PNG data) -------------
# NOTE: server Anda sudah menyiapkan berbagai jalur: cached payload, wait polling, atau scrape on-demand

import base64, re
from .scraper import fetch_gopay_qr_hd_png

_DATA_URL_RE = re.compile(r"^data:(image/[^;]+);base64,([A-Za-z0-9+/=]+)$")

@app.get("/api/invoice/{invoice_id}/status")
async def invoice_status(invoice_id: str):
    st = payments.get_status(invoice_id)
    if not st:
        raise HTTPException(404, "Invoice not found")

    # Jika sudah PAID tapi belum ada invite_logs, kirim sekarang (fallback bila webhook gagal)
    try:
        if (st.get("status") or "").upper() == "PAID":
            logs = storage.list_invite_logs(invoice_id)
            if not logs:
                inv = storage.get_invoice(invoice_id)
                if inv:
                    await _send_invites_for_invoice(inv)
    except Exception:
        # Tidak perlu menggagalkan status endpoint; cukup log di server
        import traceback, logging
        logging.error("Auto-send invites on status failed: %s", traceback.format_exc())

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

    # 2) Coba payload dari DB
    inv = payments.get_invoice(invoice_id)
    if inv:
        payload = inv.get("qris_payload") or inv.get("qr_payload")
        if payload:
            m = _DATA_URL_RE.match(payload)
            if not m:
                raise HTTPException(400, "Bad image payload in DB")
            mime, b64 = m.groups()
            return Response(
                content=base64.b64decode(b64),
                media_type=mime,
                headers={"Cache-Control": "public, max-age=300"},
            )

    # 3) (opsional) coba tunggu background cache sejenak
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
            # cache ke DB
            b64 = base64.b64encode(png).decode()
            payments._storage_update_qr_payload(invoice_id, f"data:image/png;base64,{b64}")
        except Exception:
            pass

        return Response(content=png, media_type="image/png", headers={"Cache-Control": "public, max-age=300"})
    except Exception:
        import traceback, logging
        logging.error("qr_png error\n%s", traceback.format_exc())
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
    mac = hmac.new(SAWERIA_WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, sig_hdr)

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

# Manual trigger: kirim ulang undangan (aman untuk debug)
@app.post("/api/invoice/{invoice_id}/send-invites")
async def manual_send_invites(invoice_id: str, secret: str | None = Query(None)):
    # agar tidak disalahgunakan, harus ada secret yang sama dengan WEBHOOK_SECRET
    if WEBHOOK_SECRET and secret != WEBHOOK_SECRET:
        raise HTTPException(403, "Forbidden")
    inv = storage.get_invoice(invoice_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    await _send_invites_for_invoice(inv)
    return {"ok": True, "invoice_id": invoice_id, "logs": storage.list_invite_logs(invoice_id)}

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
    return {"url": url, "status": r.status_code, "len": len(r.text), "sample": r.text[:300]}
