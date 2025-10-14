import os, json, hmac, hashlib
from telegram import Update
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from telegram.ext import Application
from .bot import build_app, register_handlers, send_invite_link
from . import payments, storage
import qrcode, io, httpx

BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET","")
BASE_URL = os.environ["BASE_URL"]
GROUPS = json.loads(os.environ.get("GROUP_IDS_JSON","[]"))

ENV = os.getenv("ENV", "dev")  # gunakan "prod" di Railway untuk mematikan debug endpoints


# ... existing env
SAWERIA_WEBHOOK_SECRET = os.getenv("SAWERIA_WEBHOOK_SECRET","")

app = FastAPI()
storage.init_db()  # <<< inisialisasi DB saat start
bot_app: Application = build_app()
register_handlers(bot_app)

# --- Serve Mini App static ---
app.mount("/webapp", StaticFiles(directory="app/webapp", html=True), name="webapp")

# --- Telegram webhook endpoint ---
# @app.post("/telegram/webhook")
# @app.post("/telegram/webhook")
# async def telegram_webhook(request: Request):
#     # Validasi secret dari Telegram
#     if WEBHOOK_SECRET and request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
#         raise HTTPException(403, "Invalid secret")

#     data = await request.json()
#     update = Update.de_json(data, bot_app.bot)
#     await bot_app.process_update(update)
#     return JSONResponse({"ok": True})

# --- Webhook Telegram: process_update langsung ---
@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    if WEBHOOK_SECRET and request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        raise HTTPException(403, "Invalid secret")
    data = await request.json()
    update = Update.de_json(data, bot_app.bot)
    await bot_app.process_update(update)
    return JSONResponse({"ok": True})

# --- Mini App API: create invoice ---
# class CreateInvoiceIn(BaseModel):
#     user_id: int
#     groups: list[str]
#     amount: int

# @app.post("/api/invoice")
# async def create_invoice(payload: CreateInvoiceIn):
#     # Validasi grup
#     valid = {g["id"] for g in GROUPS}
#     for gid in payload.groups:
#         if gid not in valid:
#             raise HTTPException(400, f"Invalid group {gid}")
#     inv = payments.create_invoice(payload.user_id, payload.groups, payload.amount)
#     return inv

# --- API create invoice ---
class CreateInvoiceIn(BaseModel):
    user_id: int
    groups: list[str]
    amount: int

@app.post("/api/invoice")
async def create_invoice(payload: CreateInvoiceIn):
    valid = {g["id"] for g in GROUPS}
    for gid in payload.groups:
        if gid not in valid:
            raise HTTPException(400, f"Invalid group {gid}")
    inv = payments.create_invoice(payload.user_id, payload.groups, payload.amount)
    return inv

# --- API cek status invoice ---
@app.get("/api/qr/{invoice_id}")
async def qr_png(invoice_id: str):
    inv = payments.get_invoice(invoice_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    payload = inv.get("qris_payload") or f"INV:{inv['invoice_id']}|AMT:{inv['amount']}"

    # Jika payload sudah berupa URL gambar dari Saweria, langsung proxy
    if isinstance(payload, str) and payload.startswith(("http://", "https://")):
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(payload)
        r.raise_for_status()
        return Response(content=r.content, media_type=r.headers.get("content-type", "image/png"))

    # Selain itu, anggap payload adalah QRIS string → generate PNG
    img = qrcode.make(payload)
    buf = io.BytesIO(); img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")

# --- Saweria Webhook ---
class SaweriaWebhookIn(BaseModel):
    invoice_id: str | None = None
    external_id: str | None = None
    status: str

def verify_saweria_signature(req: Request, raw_body: bytes):
    if not SAWERIA_WEBHOOK_SECRET:
        return True
    sig_hdr = req.headers.get("X-Saweria-Signature")  # GANTI sesuai dokumentasi
    if not sig_hdr: return False
    calc = hmac.new(SAWERIA_WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(calc, sig_hdr)

@app.post("/api/saweria/webhook")
async def saweria_webhook(request: Request):
    raw = await request.body()
    if not verify_saweria_signature(request, raw):
        raise HTTPException(403, "Bad signature")

    data = SaweriaWebhookIn.model_validate_json(raw)
    if data.status.lower() != "paid":
        return {"ok": True}

    inv_id = data.external_id or data.invoice_id
    if not inv_id:
        raise HTTPException(400, "Missing invoice reference")

    inv = payments.mark_paid(inv_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")

    groups = json.loads(inv["groups_json"])
    for gid in groups:
        try:
            invite_url = await send_invite_link(bot_app, inv["user_id"], gid)
            storage.add_invite_log(inv["invoice_id"], gid, invite_url, None)
        except Exception as e:
            storage.add_invite_log(inv["invoice_id"], gid, None, str(e))
    return {"ok": True}

# --- Health ---
# @app.get("/")
# def root():
#     return {"ok": True}

# --- Healthcheck sederhana ---
@app.get("/health")
def health():
    return {"ok": True}

@app.get("/debug/invite-logs/{invoice_id}")
def debug_invite_logs(invoice_id: str):
    return {"invoice_id": invoice_id, "logs": storage.list_invite_logs(invoice_id)}

# --- DEBUG ENDPOINTS (AKTIF SAAT ENV != "prod") ---
if ENV != "prod":
    @app.get("/debug/invite-logs/{invoice_id}")
    def debug_invite_logs(invoice_id: str):
        # menampilkan log pengiriman undangan untuk 1 invoice
        # membutuhkan storage.list_invite_logs(invoice_id)
        return {"invoice_id": invoice_id, "logs": storage.list_invite_logs(invoice_id)}

    @app.get("/debug/invoices")
    def debug_invoices(limit: int = 20):
        # menampilkan daftar invoice terbaru
        # membutuhkan storage.list_invoices(limit)
        return {"items": storage.list_invoices(limit)}

    class DebugInviteIn(BaseModel):
        user_id: int
        group_id: str

    @app.post("/debug/send-invite")
    async def debug_send_invite(payload: DebugInviteIn):
        # panggil fungsi kirim undangan secara manual untuk uji cepat
        invite_url = await send_invite_link(bot_app, payload.user_id, payload.group_id)
        return {"ok": True, "invite_link": invite_url}

@app.get("/api/qr/{invoice_id}")
def qr_png(invoice_id: str):
    inv = payments.get_invoice(invoice_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    # bikin payload sederhana; nanti bisa diganti QR string resmi dari Saweria
    payload = f"INV:{inv['invoice_id']}|AMT:{inv['amount']}"
    img = qrcode.make(payload)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


# --- Startup/shutdown ---
@app.on_event("startup")
async def on_start():
    await bot_app.initialize()
    base = os.getenv("BASE_URL", "").strip()
    if base.startswith("https://"):
        await bot_app.bot.set_webhook(
            url=f"{base}/telegram/webhook",
            secret_token=WEBHOOK_SECRET
        )
    else:
        print("Skipping set_webhook: BASE_URL must be public https")
    await bot_app.start()

@app.on_event("shutdown")
async def on_stop():
    await bot_app.stop()
    await bot_app.shutdown()


