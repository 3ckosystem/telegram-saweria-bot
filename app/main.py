# app/main.py
import os, json, re, hmac, hashlib, httpx
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from telegram import Update
from telegram.ext import Application

from .bot import build_app, register_handlers, send_invite_link
from . import storage

# ===================== ENV =====================
BOT_TOKEN      = os.environ["BOT_TOKEN"]
BASE_URL       = os.environ["BASE_URL"].strip()
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
ENV            = os.getenv("ENV", "dev")

GROUPS_ENV = os.environ.get("GROUP_IDS_JSON", "[]")

def parse_groups(env_val: str) -> List[Dict[str, str]]:
    groups: List[Dict[str, str]] = []
    try:
        data = json.loads(env_val)
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
    except Exception:
        pass
    return groups

GROUPS = parse_groups(GROUPS_ENV)

# ===================== FastAPI =====================
app = FastAPI(title="Telegram × Saweria Bot")

# Static (kalau ada folder public/)
if os.path.isdir("public"):
    app.mount("/public", StaticFiles(directory="public"), name="public")

# ---------- Telegram Bot lifecycle ----------
bot_app: Application = build_app()

register_handlers(bot_app)

@app.on_event("startup")
async def on_start():
    print("[startup] launching bot app…")
    await bot_app.initialize()
    if BASE_URL.startswith("https://"):
        await bot_app.bot.set_webhook(
            url=f"{BASE_URL}/telegram/webhook",
            secret_token=WEBHOOK_SECRET or None,
        )
        print(f"[startup] telegram webhook set → {BASE_URL}/telegram/webhook")
    else:
        print("[startup] SKIP set_webhook: BASE_URL must start with https://")
    await bot_app.start()

@app.on_event("shutdown")
async def on_stop():
    print("[shutdown] stopping bot…")
    await bot_app.stop()
    await bot_app.shutdown()

# ---------- Telegram webhook ----------
@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    if WEBHOOK_SECRET:
        # telegram kirim header 'X-Telegram-Bot-Api-Secret-Token'
        token = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if token != WEBHOOK_SECRET:
            raise HTTPException(status_code=401, detail="bad secret")
    update = Update.de_json(await request.json(), bot_app.bot)
    await bot_app.process_update(update)
    return JSONResponse({"ok": True})

# ==================================================
# ==============  API UNTUK MINI APP  ==============
# ==================================================

class CreateInvoiceIn(BaseModel):
    user_id: int
    group_id: str
    amount: int

def _storage_get(invoice_id: str) -> Optional[Dict[str, Any]]:
    if hasattr(storage, "get_invoice"):
        return storage.get_invoice(invoice_id)  # type: ignore
    if hasattr(storage, "find_invoice"):
        return storage.find_invoice(invoice_id)  # type: ignore
    return None

def _storage_create(user_id: int, group_id: str, amount: int) -> Dict[str, Any]:
    if hasattr(storage, "create_invoice"):
        return storage.create_invoice(user_id, group_id, amount)  # type: ignore
    # fallback minimal
    inv = {
        "invoice_id": f"INV:{os.urandom(8).hex()}",
        "user_id": user_id,
        "group_id": group_id,
        "amount": amount,
        "status": "PENDING",
    }
    if hasattr(storage, "save_invoice"):
        storage.save_invoice(inv)  # type: ignore
    return inv

def _storage_update_status(invoice_id: str, status: str) -> Optional[Dict[str, Any]]:
    if hasattr(storage, "update_invoice_status"):
        return storage.update_invoice_status(invoice_id, status)  # type: ignore
    if hasattr(storage, "mark_paid") and status.upper() == "PAID":
        return storage.mark_paid(invoice_id)  # type: ignore
    inv = _storage_get(invoice_id)
    if inv:
        inv["status"] = status
        if hasattr(storage, "save_invoice"):
            storage.save_invoice(inv)  # type: ignore
    return inv

@app.post("/api/invoice")
async def api_create_invoice(payload: CreateInvoiceIn):
    inv = _storage_create(payload.user_id, payload.group_id, payload.amount)
    # tampilkan instruksi ke Mini App
    return {
        "ok": True,
        "invoice_id": inv["invoice_id"],
        "code": inv["invoice_id"],  # disalin ke 'pesan' sebelum bayar
        "amount": inv["amount"],
        "howto": [
            "Scan QR lalu tempel kode di kolom 'pesan' sebelum bayar (opsional bila scan QR).",
            "Setelah bayar, Mini App akan menutup otomatis dan bot mengirim link undangan."
        ],
    }

@app.get("/api/status/{invoice_id}")
async def api_status(invoice_id: str):
    inv = _storage_get(invoice_id)
    if not inv:
        raise HTTPException(404, "invoice not found")
    return {"ok": True, "status": inv.get("status", "PENDING")}

# ==================================================
# ===============  SAWERIA WEBHOOK  ================
# ==================================================
# Saweria → POST ke /webhook/saweria (yang 404 di log kamu)

INV_RE = re.compile(r"(INV[:：]\s*[A-Za-z0-9\-]+)", re.I)

def _extract_invoice_id_from_payload(data: Any) -> Optional[str]:
    """Coba cari INV:xxxx dari berbagai field (pesan/note/metadata)."""
    if data is None:
        return None

    # flatten kandidat field berbentuk string
    candidates: List[str] = []
    if isinstance(data, dict):
        # payload standar sering di bawah 'data'/'payload'/'message'/'note'
        for k in ["message", "pesan", "note", "notes", "comment", "payload", "metadata", "data", "custom_field", "custom"]:
            v = data.get(k)
            if isinstance(v, str):
                candidates.append(v)
            elif isinstance(v, (dict, list)):
                candidates.append(json.dumps(v))
        # juga cek root-as-string
        candidates.append(json.dumps(data))
    elif isinstance(data, list):
        candidates.append(json.dumps(data))
    elif isinstance(data, str):
        candidates.append(data)

    for text in candidates:
        m = INV_RE.search(text or "")
        if m:
            # normalisasi spasi setelah titik dua
            return m.group(1).replace("：", ":").replace(" ", "")
    return None

def _is_success_status(data: Any) -> bool:
    # fleksibel: cari status sukses
    # beberapa integrasi pakai 'status':'PAID' / 'success':true / 'paid_at':<ts>
    if isinstance(data, dict):
        s = str(data.get("status", "")).upper()
        if s in {"PAID", "SUCCESS", "COMPLETED"}:
            return True
        if str(data.get("success", "")).lower() in {"true", "1", "yes"}:
            return True
        if data.get("paid_at") or data.get("settlement_time"):
            return True
    return False

def _verify_signature(request: Request, raw_body: bytes) -> bool:
    """
    Prioritas:
    1) Jika WEBHOOK_SECRET kosong -> lolos (untuk debug/dev).
    2) Jika ada header GitHub-style 'X-Hub-Signature-256' atau generic 'X-Signature':
       validasi HMAC-SHA256(raw_body) pakai WEBHOOK_SECRET.
    3) Jika ada 'saweria-callback-signature':
       (sementara) terima dulu dan log-kan; nanti kita ketatkan pakai SAWERIA_STREAMKEY.
    """
    # 1) Dev mode: skip
    if not WEBHOOK_SECRET:
        return True

    # 2) Generic HMAC (GitHub-style)
    got = request.headers.get("X-Hub-Signature-256") or request.headers.get("X-Signature")
    if got:
        sig = got.split("=", 1)[-1] if "=" in got else got
        digest = hmac.new(WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(digest, sig)

    # 3) Saweria header — longgarkan dulu (accept + log)
    saw_sig = request.headers.get("saweria-callback-signature")
    if saw_sig:
        print("[webhook] saweria-callback-signature detected (accepted in relaxed mode)")
        return True

    # Jika tak ada header apapun → tolak
    return False


@app.post("/webhook/saweria")
async def webhook_saweria(request: Request):
    raw = await request.body()
    try:
        data = await request.json()
    except Exception:
        data = None

    if not _verify_signature(request, raw):
        print("[webhook] invalid signature")
        raise HTTPException(401, "invalid signature")

    inv_id = _extract_invoice_id_from_payload(data)
    print(f"[webhook] payload received. extracted invoice = {inv_id}")
    if not inv_id:
        # tetap 200 agar Saweria tidak retry agresif, tapi log-kan
        return JSONResponse({"ok": True, "message": "no invoice code found"}, status_code=200)

    inv = _storage_get(inv_id)
    if not inv:
        print(f"[webhook] invoice not found: {inv_id}")
        return JSONResponse({"ok": True, "message": "invoice not found"}, status_code=200)

    # sukses?
    success = _is_success_status(data) or True  # <- bila Saweria tidak kirim status jelas, pakai True (karena webhook dipicu setelah bayar)
    if not success:
        print(f"[webhook] not marked success, ignoring. invoice={inv_id}")
        return {"ok": True}

    # mark paid
    inv = _storage_update_status(inv_id, "PAID")
    print(f"[webhook] marked PAID for {inv_id}")

    # kirim invite
    try:
        chat_id = int(inv["user_id"])
        target_group_id = str(inv["group_id"])
        await send_invite_link(bot_app, chat_id=chat_id, target_group_id=target_group_id)
        print(f"[webhook] invite sent → user={chat_id} group={target_group_id}")
    except Exception as e:
        print(f"[webhook] FAILED to send invite: {e!r}")

    return {"ok": True, "handled": True, "invoice_id": inv_id}
