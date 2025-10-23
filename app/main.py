
# app/main.py — FINAL
# - Pesan Saweria selalu "INV:<invoice_id>"
# - Webhook Saweria menandai PAID dan langsung kirim undangan via bot
# - Idempotent & aman dari 500 (return JSON terkontrol)
import os, json, re, base64, hmac, hashlib, logging
from typing import Optional, List

from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from telegram import Update
from telegram.ext import Application

from .bot import build_app, register_handlers, send_invite_link
from . import payments, storage
from .scraper import fetch_gopay_qr_hd_png, debug_snapshot, debug_fill_snapshot, fetch_gopay_checkout_png

# ------------- ENV -------------
BOT_TOKEN = os.environ["BOT_TOKEN"]
BASE_URL = os.environ["BASE_URL"].strip()
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
ENV = os.getenv("ENV", "dev")

def _read_env_json(name: str, default_text: str = "[]"):
    raw = os.environ.get(name, default_text)
    if raw is None:
        return []
    s = raw.strip()
    try:
        return json.loads(s)
    except Exception:
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
                init = str(it.get("initial") or "").strip()
                if gid and nm:
                    groups.append({"id": gid, "name": nm, "initial": init})
            else:
                gid = str(it).strip()
                if gid:
                    groups.append({"id": gid, "name": gid})
    return groups

GROUPS = _parse_groups_from_any(_read_env_json("GROUP_IDS_JSON", "[]"))
try:
    PRICE_IDR = int(os.environ.get("PRICE_IDR", "25000"))
except Exception:
    PRICE_IDR = 25000

SAWERIA_WEBHOOK_SECRET = os.getenv("SAWERIA_WEBHOOK_SECRET", "")

# ------------- APP & BOT -------------
app = FastAPI()
storage.init_db()

bot_app: Application = build_app()
register_handlers(bot_app)

# Serve Mini App statics (biarkan kalau folder tersedia)
app.mount("/webapp", StaticFiles(directory="app/webapp", html=True), name="webapp")

# ===== Helper logging aman (hindari 500 kalau kolom DB beda) =====
def _safe_invite_log(invoice_id: str, group_id: str, invite_link: Optional[str], error: Optional[str]) -> None:
    try:
        storage.add_invite_log(invoice_id, group_id, invite_link, error)
    except Exception as e:
        logging.info("[invite_log][skip] inv=%s gid=%s err=%s", invoice_id, group_id, e)

async def _send_invites_for_invoice(inv: dict) -> None:
    """Kirim undangan untuk semua group di invoice (idempotent-ish)."""
    try:
        groups = json.loads(inv.get("groups_json") or "[]")
    except Exception:
        groups = inv.get("groups") or []
    if not groups:
        return
    user_id = inv.get("user_id") or 0
    for gid in groups:
        try:
            await send_invite_link(bot_app, user_id, gid)
            _safe_invite_log(inv["invoice_id"], gid, "(sent)", None)
        except Exception as e:
            _safe_invite_log(inv["invoice_id"], gid, None, str(e))

# ------------- TELEGRAM WEBHOOK -------------
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
    user_id: int = 0   # opsional agar tetap bisa dites dari browser
    groups: List[str]
    amount: int

@app.post("/api/invoice")
async def create_invoice(payload: CreateInvoiceIn):
    logging.info("[create_invoice] uid=%s groups=%s amount=%s", payload.user_id, payload.groups, payload.amount)

    try:
        MIN_PRICE_IDR = int(os.environ.get("MIN_PRICE_IDR", "1"))
    except Exception:
        MIN_PRICE_IDR = 1
    if not isinstance(payload.amount, int) or payload.amount < MIN_PRICE_IDR:
        raise HTTPException(400, f"Invalid amount. Min {MIN_PRICE_IDR}")

    allowed = {str(g.get("id")) for g in GROUPS if "id" in g}
    for gid in payload.groups:
        if str(gid) not in allowed:
            raise HTTPException(400, f"Invalid group {gid}")

    inv = await payments.create_invoice(payload.user_id, payload.groups, payload.amount)
    return inv

# ------------- API: CONFIG -------------
@app.get("/api/config")
def get_config():
    return {"price_idr": PRICE_IDR, "groups": GROUPS}

# ------------- API: STATUS -------------
@app.get("/api/invoice/{invoice_id}/status")
async def invoice_status(invoice_id: str):
    st = payments.get_status(invoice_id)
    if not st:
        raise HTTPException(404, "Invoice not found")
    # Jika sudah PAID, tidak usah kirim apa-apa di sini (webhook yang kirim)
    return st

# ------------- API: QR IMAGE -------------
_DATA_URL_RE = re.compile(r"^data:(image/[^;]+);base64,(.+)$")

@app.get("/api/qr/{raw_id}")
async def qr_png(
    raw_id: str,
    amount: int | None = Query(None, description="(legacy) amount for on-demand"),
    msg: str | None = Query(None, description="(legacy) message for on-demand"),
):
    # izinkan suffix .png/.jpg
    invoice_id = re.sub(r"\.(png|jpg|jpeg)$", "", raw_id, flags=re.I)

    inv = payments.get_invoice(invoice_id)
    if not inv:
        # legacy fallback: jika amount+msg dikirim manual
        if amount and msg:
            png = await fetch_gopay_qr_hd_png(int(amount), str(msg))
            if png:
                return Response(content=png, media_type="image/png", headers={"Cache-Control":"public, max-age=120"})
        raise HTTPException(404, "Invoice not found")

    # kalau sudah ada payload → kirim
    payload = inv.get("qris_payload")
    if payload:
        m = _DATA_URL_RE.match(payload)
        if m:
            mime, b64 = m.groups()
            return Response(content=base64.b64decode(b64), media_type=mime, headers={"Cache-Control":"public, max-age=300"})

    # belum ada → generate menggunakan pesan INV:<invoice_id>
    amt = int(inv.get("amount") or amount or 0)
    message = f"INV:{invoice_id}"
    png = await fetch_gopay_qr_hd_png(amt, message)
    if not png:
        return Response(content=b"QR not found", status_code=502)

    # cache ke DB
    try:
        storage.update_qris_payload(invoice_id, f"data:image/png;base64,{base64.b64encode(png).decode()}")
    except Exception as e:
        logging.info("[qr_png][cache][skip]: %s", e)

    return Response(content=png, media_type="image/png", headers={"Cache-Control":"public, max-age=300"})

# ------------- SAWERIA WEBHOOK: mark PAID + kirim undangan -------------
_INV_RE = re.compile(r"(?i)\bINV:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b")

def _verify_saweria_sig(req: Request, raw: bytes) -> bool:
    if not SAWERIA_WEBHOOK_SECRET:
        return True
    sig = req.headers.get("X-Saweria-Signature") or ""
    calc = hmac.new(SAWERIA_WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, calc)

@app.post("/api/saweria/webhook")
async def saweria_webhook(request: Request):
    raw = await request.body()
    if not _verify_saweria_sig(request, raw):
        return JSONResponse({"ok": False, "reason": "bad signature"}, status_code=403)

    try:
        body = json.loads(raw.decode() or "{}")
    except Exception as e:
        return {"ok": False, "reason": f"bad json: {e.__class__.__name__}"}

    # ambil invoice id
    status = str(body.get("status") or body.get("event") or "").lower()
    msg    = str(body.get("message") or body.get("note") or body.get("payload") or "")
    inv_id = (body.get("invoice_id") or body.get("external_id") or "").strip()
    if not inv_id:
        m = _INV_RE.search(msg)
        if m:
            inv_id = m.group(1)
    if not inv_id:
        return {"ok": False, "reason": "no invoice id"}

    # hanya proses kalau sukses
    if "paid" not in status:
        return {"ok": True, "ignored": True, "invoice_id": inv_id}

    # tandai PAID
    try:
        inv = payments.mark_paid(inv_id) or payments.get_invoice(inv_id)
    except Exception as e:
        return {"ok": False, "reason": f"mark_paid error: {e}", "invoice_id": inv_id}
    if not inv:
        return {"ok": False, "reason": "invoice not found", "invoice_id": inv_id}

    # kirim undangan
    sent, failed = [], []
    try:
        groups = json.loads(inv.get("groups_json") or "[]")
    except Exception:
        groups = inv.get("groups") or []
    for gid in groups:
        try:
            await send_invite_link(bot_app, inv.get("user_id") or 0, gid)
            _safe_invite_log(inv_id, gid, "(sent-via-webhook)", None)
            sent.append(gid)
        except Exception as e:
            _safe_invite_log(inv_id, gid, None, str(e))
            failed.append({"group_id": gid, "error": str(e)})
    return {"ok": True, "invoice_id": inv_id, "sent": sent, "failed": failed}

# ------------- Misc endpoints -------------
@app.get("/api/invoice/{invoice_id}/send-invites")
async def manual_send_invites(invoice_id: str, secret: Optional[str] = Query(None)):
    if WEBHOOK_SECRET and secret != WEBHOOK_SECRET:
        raise HTTPException(403, "Forbidden")
    inv = payments.get_invoice(invoice_id)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    await _send_invites_for_invoice(inv)
    return {"ok": True, "invoice_id": invoice_id}

@app.get("/api/config/raw")
def raw_config():
    return {"env_groups": os.environ.get("GROUP_IDS_JSON", "[]")}

# ---- DEBUG ----
@app.get("/debug/saweria-snap")
async def debug_saweria_snap():
    png = await debug_snapshot()
    if not png:
        raise HTTPException(500, "snapshot failed")
    return Response(content=png, media_type="image/png")

@app.get("/debug/saweria-fill")
async def debug_saweria_fill(amount: int = 25000, msg: str = "INV:debug", method: str = "gopay"):
    png = await debug_fill_snapshot(amount, msg, method)
    if not png:
        raise HTTPException(500, "fill snapshot failed")
    return Response(content=png, media_type="image/png")

@app.get("/debug/saweria-pay")
async def debug_saweria_pay(amount: int = 25000, msg: str = "INV:debug"):
    png = await fetch_gopay_checkout_png(amount, msg)
    if not png:
        raise HTTPException(500, "checkout snapshot failed")
    return Response(content=png, media_type="image/png")

# ------------- HEALTH -------------
@app.get("/health")
def health():
    return {"ok": True}

# ------------- STARTUP/SHUTDOWN -------------
@app.on_event("startup")
async def on_start():
    await bot_app.initialize()
    if BASE_URL.startswith("https://"):
        await bot_app.bot.set_webhook(
            url=f"{BASE_URL}/telegram/webhook",
            secret_token=WEBHOOK_SECRET or None,
        )
    else:
        logging.info("Skipping set_webhook: BASE_URL must start with https://")
    await bot_app.start()

@app.on_event("shutdown")
async def on_stop():
    await bot_app.stop()
    await bot_app.shutdown()
