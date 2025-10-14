# import os, json
# from fastapi import FastAPI, Request, HTTPException
# from fastapi.responses import FileResponse, JSONResponse
# from fastapi.staticfiles import StaticFiles
# from pydantic import BaseModel
# from telegram.ext import Application
# from .bot import build_app, register_handlers, send_invite_link
# from . import payments
# from telegram import Update

import os, json, hmac, hashlib
from telegram import Update
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from telegram.ext import Application
from .bot import build_app, register_handlers, send_invite_link
from . import payments, storage


BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET","")
BASE_URL = os.environ["BASE_URL"]
GROUPS = json.loads(os.environ.get("GROUP_IDS_JSON","[]"))

# ... existing env
SAWERIA_WEBHOOK_SECRET = os.getenv("SAWERIA_WEBHOOK_SECRET","")  # opsional

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
@app.get("/api/invoice/{invoice_id}")
def get_invoice(invoice_id: str):
    inv = payments.get_invoice(invoice_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    # normalisasi
    inv["groups"] = json.loads(inv["groups_json"]); inv.pop("groups_json", None)
    return inv

# --- Saweria Webhook ---
# class SaweriaWebhookIn(BaseModel):
#     # Sesuaikan dengan payload webhook Saweria (lihat referensi)
#     invoice_id: str
#     status: str

# @app.post("/api/saweria/webhook")
# async def saweria_webhook(data: SaweriaWebhookIn):
#     # Verifikasi signature kalau tersedia (opsional)
#     if data.status.lower() != "paid":
#         return {"ok": True}
#     inv = payments.mark_paid(data.invoice_id)
#     if not inv:
#         raise HTTPException(404, "Invoice not found")
#     # Kirim invite link untuk tiap grup
#     for gid in inv["groups"]:
#         await send_invite_link(bot_app, inv["user_id"], gid)  # bot_app -> ContextTypes via shortcut
#     return {"ok": True}

# --- Saweria Webhook ---
class SaweriaWebhookIn(BaseModel):
    invoice_id: str
    status: str

def verify_saweria_signature(req: Request, raw_body: bytes):
    # Contoh: jika Saweria kirim header 'X-Saweria-Signature' dengan HMAC-SHA256
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
    if not verify_saweria_signature(request, raw):
        raise HTTPException(403, "Bad signature")

    data = SaweriaWebhookIn.model_validate_json(raw)
    if data.status.lower() != "paid":
        return {"ok": True}

    inv = payments.mark_paid(data.invoice_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")

    groups = json.loads(inv["groups_json"])
    # kirim undangan per grup (dengan penanganan error)
    for gid in groups:
        try:
            await send_invite_link(bot_app, inv["user_id"], gid)
            storage.add_invite_log(inv["invoice_id"], gid, "(sent-via-bot)", None)
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

# --- Startup: set webhook ---
# app/main.py (bagian bawah)

# @app.on_event("startup")
# async def on_start():
#     await bot_app.initialize()
#     base = os.getenv("BASE_URL", "").strip()
#     if base.startswith("https://"):
#         await bot_app.bot.set_webhook(
#             url=f"{base}/telegram/webhook",
#             secret_token=WEBHOOK_SECRET
#         )
#     else:
#         print("Skipping set_webhook: BASE_URL must be public https")

#     # Penting: mulai PTB agar handler /start jalan
#     await bot_app.start()

# @app.on_event("shutdown")
# async def on_stop():
#     await bot_app.stop()
#     await bot_app.shutdown()

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


