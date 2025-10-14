import os, json
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from telegram.ext import Application
from .bot import build_app, register_handlers, send_invite_link
from . import payments

BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET","")
BASE_URL = os.environ["BASE_URL"]
GROUPS = json.loads(os.environ.get("GROUP_IDS_JSON","[]"))

app = FastAPI()
bot_app: Application = build_app()
register_handlers(bot_app)

# --- Serve Mini App static ---
app.mount("/webapp", StaticFiles(directory="app/webapp", html=True), name="webapp")

# --- Telegram webhook endpoint ---
@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    if WEBHOOK_SECRET and request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        raise HTTPException(403, "Invalid secret")
    update = await request.json()
    await bot_app.update_queue.put(update)
    return JSONResponse({"ok": True})

# --- Mini App API: create invoice ---
class CreateInvoiceIn(BaseModel):
    user_id: int
    groups: list[str]
    amount: int

@app.post("/api/invoice")
async def create_invoice(payload: CreateInvoiceIn):
    # Validasi grup
    valid = {g["id"] for g in GROUPS}
    for gid in payload.groups:
        if gid not in valid:
            raise HTTPException(400, f"Invalid group {gid}")
    inv = payments.create_invoice(payload.user_id, payload.groups, payload.amount)
    return inv

# --- Saweria Webhook ---
class SaweriaWebhookIn(BaseModel):
    # Sesuaikan dengan payload webhook Saweria (lihat referensi)
    invoice_id: str
    status: str

@app.post("/api/saweria/webhook")
async def saweria_webhook(data: SaweriaWebhookIn):
    # Verifikasi signature kalau tersedia (opsional)
    if data.status.lower() != "paid":
        return {"ok": True}
    inv = payments.mark_paid(data.invoice_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    # Kirim invite link untuk tiap grup
    for gid in inv["groups"]:
        await send_invite_link(bot_app, inv["user_id"], gid)  # bot_app -> ContextTypes via shortcut
    return {"ok": True}

# --- Health ---
@app.get("/")
def root():
    return {"ok": True}

# --- Startup: set webhook ---
@app.on_event("startup")
async def on_start():
    await bot_app.initialize()
    await bot_app.bot.set_webhook(
        url=f"{BASE_URL}/telegram/webhook",
        secret_token=WEBHOOK_SECRET
    )
