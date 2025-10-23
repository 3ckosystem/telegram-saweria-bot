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
    fetch_gopay_qr_hd_png,
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
                nm  = str(it.get("name") or it.get("label") or it.get("text") or "").strip()
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
storage.init_db()

bot_app: Application = build_app()
register_handlers(bot_app)

# Helper kirim undangan
async def _send_invites_for_invoice(inv: dict) -> None:
    """Kirim undangan ke semua grup pada invoice (aman dipanggil berulang)."""
    try:
        groups = json.loads(inv.get("groups_json") or "[]")
    except Exception:
        groups = []
    if not groups:
        return

    logs = storage.list_invite_logs(inv["invoice_id"])
    already = {
        l.get("group_id")
        for l in logs
        if l.get("invite_link") or "(sent" in (l.get("invite_link") or "")
    }

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
    import logging
    logging.info(f"[create_invoice] uid={payload.user_id} groups={payload.groups} amount={payload.amount}")

    try:
        MIN_PRICE_IDR = int(os.environ.get("MIN_PRICE_IDR", "1"))
    except Exception:
        MIN_PRICE_IDR = 1
    if not isinstance(payload.amount, int) or payload.amount < MIN_PRICE_IDR:
        raise HTTPException(400, f"Invalid amount. Min {MIN_PRICE_IDR}")

    try:
        allowed = {str(g["id"]) for g in GROUPS}
    except Exception:
        allowed = set()
    for gid in payload.groups:
        if str(gid) not in allowed:
            raise HTTPException(400, f"Invalid group {gid}. Allowed={list(allowed)[:5]}...")

    try:
        inv = await payments.create_invoice(payload.user_id, payload.groups, payload.amount)
        return inv
    except Exception as e:
        import traceback, logging
        logging.error("create_invoice failed: %s", e)
        logging.error(traceback.format_exc())
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
async def invoice_status(invoice_id: str):
    st = payments.get_status(invoice_id)
    if not st:
        raise HTTPException(404, "Invoice not found")

    try:
        if (st.get("status") or "").upper() == "PAID":
            logs = storage.list_invite_logs(invoice_id)
            if not logs:
                inv = payments.get_invoice(invoice_id)
                if inv:
                    await _send_invites_for_invoice(inv)
    except Exception as e:
        print("[invoice_status] auto-send invites failed:", e)

    return st

@app.get("/api/qr/{raw_id}")
async def qr_png(raw_id: str, hd: bool = Query(False), wait: int = Query(0),
                 amount: int | None = Query(None), msg: str | None = Query(None)):
    invoice_id = re.sub(r"\.(png|jpg|jpeg)$", "", raw_id, flags=re.I)
    inv = payments.get_invoice(invoice_id)
    if not inv:
        if amount and msg:
            try:
                png = await fetch_gopay_qr_hd_png(int(amount), msg)
                if png:
                    return Response(content=png, media_type="image/png")
            except Exception as e:
                print("[qr_png] fallback:", e)
        raise HTTPException(404, "Invoice not found")

    amt = inv.get("amount") or amount or 0
    try:
        id_to_initial = {str(g["id"]): str(g.get("initial", "")).strip() for g in GROUPS}
    except Exception:
        id_to_initial = {}
    try:
        inv_groups = inv.get("groups") or json.loads(inv.get("groups_json") or "[]")
    except Exception:
        inv_groups = []
    initials = [id_to_initial.get(str(g), "") for g in inv_groups]
    message = " ".join([s.strip() for s in initials if s.strip()]) or f"INV:{invoice_id}"

    payload = inv.get("qris_payload")
    if payload:
        m = _DATA_URL_RE.match(payload)
        if not m:
            raise HTTPException(400, "Bad image payload")
        mime, b64 = m.groups()
        return Response(content=base64.b64decode(b64), media_type=mime)

    try:
        png = await fetch_gopay_qr_hd_png(amt, message)
        if not png:
            return Response(content=b"QR not found", status_code=502)
        try:
            b64 = base64.b64encode(png).decode()
            storage.update_qris_payload(invoice_id, f"data:image/png;base64,{b64}")
        except Exception:
            pass
        return Response(content=png, media_type="image/png")
    except Exception as e:
        print("[qr_png] error:", e)
        return Response(content=b"Error", status_code=500)

# ------------- SAWERIA WEBHOOK (tahan-banting) -------------
SAWERIA_WEBHOOK_SECRET = os.getenv("SAWERIA_WEBHOOK_SECRET", "")
_UUID_RE = re.compile(r"(?i)\bINV:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b")

@app.post("/api/saweria/webhook")
async def saweria_webhook(request: Request):
    import traceback
    try:
        raw = await request.body()

        if SAWERIA_WEBHOOK_SECRET:
            sig_hdr = request.headers.get("X-Saweria-Signature")
            calc = hmac.new(SAWERIA_WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
            if not sig_hdr or not hmac.compare_digest(calc, sig_hdr):
                return JSONResponse({"ok": False, "reason": "bad signature"}, status_code=403)

        try:
            body = json.loads(raw.decode() or "{}")
        except Exception as e:
            return {"ok": False, "reason": f"bad json: {e.__class__.__name__}"}

        if (body.get("status") or "").lower() != "paid":
            return {"ok": True, "ignored": True}

        candidate_id = (str(body.get("invoice_id") or "")).strip()
        if not candidate_id and body.get("external_id"):
            candidate_id = str(body.get("external_id")).strip()
        if not candidate_id and body.get("message"):
            m = _UUID_RE.search(body.get("message") or "")
            if m:
                candidate_id = m.group(1)

        if not candidate_id:
            return {"ok": False, "reason": "no invoice id in payload"}

        try:
            inv = payments.mark_paid(candidate_id)
        except Exception as e:
            return {"ok": False, "reason": f"mark_paid error: {e.__class__.__name__}", "invoice_id": candidate_id}

        if not inv:
            inv = payments.get_invoice(candidate_id)
        if not inv:
            return {"ok": False, "reason": "invoice not found", "invoice_id": candidate_id}

        try:
            groups = json.loads(inv.get("groups_json") or "[]")
        except Exception:
            groups = []

        sent, failed = [], []
        for gid in groups:
            try:
                await send_invite_link(bot_app, inv["user_id"], gid)
                storage.add_invite_log(inv["invoice_id"], gid, "(sent-via-webhook)", None)
                sent.append(gid)
            except Exception as e:
                storage.add_invite_log(inv["invoice_id"], gid, None, str(e))
                failed.append({"group_id": gid, "error": str(e)})

        return {"ok": True, "invoice_id": inv["invoice_id"], "sent": sent, "failed": failed}

    except Exception as e:
        last = traceback.format_exc().splitlines()[-1] if traceback.format_exc() else str(e)
        return JSONResponse({"ok": False, "unhandled": str(e), "trace_last": last}, status_code=200)

# Manual trigger kirim undangan
@app.post("/api/invoice/{invoice_id}/send-invites")
async def manual_send_invites(invoice_id: str, secret: Optional[str] = Query(None)):
    if WEBHOOK_SECRET and secret != WEBHOOK_SECRET:
        raise HTTPException(403, "Forbidden")
    inv = payments.get_invoice(invoice_id)
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

# ---- DEBUG: SAWERIA ----
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
        raise HTTPException(500, "Gagal snapshot setelah pengisian form")
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
