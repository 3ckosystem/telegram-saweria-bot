# app/main.py
import os, json, re, base64, hmac, hashlib, io, httpx
from typing import Optional, List

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from telegram import Update
from telegram.ext import Application

from .bot import build_app, register_handlers, send_invite_link
from . import payments, storage

from .scraper import debug_snapshot
from .scraper import debug_fill_snapshot


# ------------- ENV -------------
BOT_TOKEN = os.environ["BOT_TOKEN"]
BASE_URL = os.environ["BASE_URL"].strip()
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
ENV = os.getenv("ENV", "dev")  # set "prod" di Railway untuk mematikan debug endpoints
GROUPS_ENV = os.environ.get("GROUP_IDS_JSON", "[]")
try:
    GROUPS: List[str] = [
        (g["id"] if isinstance(g, dict) and "id" in g else str(g))
        for g in json.loads(GROUPS_ENV)
    ]
except Exception:
    GROUPS = []

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

# ------------- MODELS -------------
class CreateInvoiceIn(BaseModel):
    user_id: int
    groups: List[str]
    amount: int

# ------------- API: CREATE INVOICE -------------
@app.post("/api/invoice")
async def create_invoice(payload: CreateInvoiceIn):
    # validasi group id terhadap ENV (opsional, aman jika kosong)
    valid = set(GROUPS) if GROUPS else None
    if valid:
        for gid in payload.groups:
            if gid not in valid:
                raise HTTPException(400, f"Invalid group {gid}")

    # trigger invoice + background simple screenshot (via payments)
    inv = await payments.create_invoice(payload.user_id, payload.groups, payload.amount)
    return inv

# ------------- API: STATUS & QR IMAGE -------------
_DATA_URL_RE = re.compile(r"^data:(image/[^;]+);base64,(.+)$")

@app.get("/api/invoice/{invoice_id}/status")
def invoice_status(invoice_id: str):
    st = payments.get_status(invoice_id)
    if not st:
        raise HTTPException(404, "Invoice not found")
    # contoh balikan: {"status":"PENDING"|"PAID","paid_at":..., "has_qr": true|false}
    return st

@app.get("/api/qr/{invoice_id}")
def qr_png(invoice_id: str):
    inv = payments.get_invoice(invoice_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    payload = inv.get("qris_payload")
    if not payload:
        raise HTTPException(404, "PNG not ready")

    # payload disimpan sebagai data URL: data:image/png;base64,...
    m = _DATA_URL_RE.match(payload)
    if not m:
        raise HTTPException(400, "Bad image payload")
    mime, b64 = m.groups()
    return Response(content=base64.b64decode(b64), media_type=mime)

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
    # di contoh minimal: coba pakai invoice_id jika dikirim
    inv = None
    if data.invoice_id:
        inv = payments.mark_paid(data.invoice_id)
    if not inv:
        # kalau tidak ketemu, abaikan atau log
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
    return {
        "url": url,
        "status": r.status_code,
        "len": len(r.text),
        "snippet": r.text[:300]
    }

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
