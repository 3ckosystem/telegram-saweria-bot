# app/main.py
import os, json, re, hmac, hashlib
from typing import Optional, List, Dict, Any
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from telegram import Update
from telegram.ext import Application

from .bot import build_app, register_handlers, send_invite_link
from . import storage

# ===================== ENV =====================
BOT_TOKEN       = os.environ["BOT_TOKEN"]
BASE_URL        = os.environ["BASE_URL"].strip()
WEBHOOK_SECRET  = os.environ.get("WEBHOOK_SECRET", "")
ENV             = os.getenv("ENV", "dev")

# >>> HARGA GLOBAL dari PRICE_IDR (fallback 25000)
PRICE_IDR       = int(os.getenv("PRICE_IDR", "25000"))
DEFAULT_PRICE   = PRICE_IDR

# ==== GROUPS ====
GROUPS_ENV = (os.environ.get("GROUP_IDS_JSON") or "").strip()

def parse_groups(env_val: str) -> List[Dict[str, Any]]:
    """
    Normalisasi berbagai format GROUP_IDS_JSON.
    Menambahkan field:
      - price (int)    → dari item.price / item.price_idr / PRICE_IDR
      - price_idr (int) alias price
      - title/label untuk kemudahan FE
    """
    groups: List[Dict[str, Any]] = []
    if not env_val:
        return groups
    try:
        data = json.loads(env_val)
    except Exception:
        data = env_val

    def _build(
        gid: str,
        name: Optional[str] = None,
        initial: Optional[str] = None,
        price: Optional[int] = None,
    ):
        gid = str(gid).strip()
        if not gid:
            return
        nm = (name or gid).strip()
        p = int(price if (price is not None and str(price).isdigit()) else DEFAULT_PRICE)
        obj: Dict[str, Any] = {
            "id": gid,
            "name": nm,
            "title": nm,
            "label": nm,
            "price": p,
            "price_idr": p,
        }
        if initial:
            obj["initial"] = str(initial).strip()
        groups.append(obj)

    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, dict):
                _build(
                    v.get("id") or k,
                    v.get("name") or v.get("label") or v.get("text") or str(k),
                    v.get("initial") or v.get("abbr"),
                    v.get("price") or v.get("price_idr"),
                )
            else:
                _build(k, str(v))
    elif isinstance(data, list):
        for it in data:
            if isinstance(it, dict):
                _build(
                    it.get("id") or it.get("group_id") or it.get("value"),
                    it.get("name") or it.get("label") or it.get("text"),
                    it.get("initial") or it.get("abbr"),
                    it.get("price") or it.get("price_idr"),
                )
            else:
                _build(str(it))
    else:
        _build(str(data).strip())

    return groups

GROUPS = parse_groups(GROUPS_ENV)

# Fallback 1 var agar tak kosong sama sekali
if not GROUPS:
    fallback_gid = os.getenv("GROUP_ID") or os.getenv("TELEGRAM_GROUP_ID")
    if fallback_gid:
        GROUPS = [{
            "id": fallback_gid.strip(),
            "name": "Default Group",
            "title": "Default Group",
            "label": "Default Group",
            "price": DEFAULT_PRICE,
            "price_idr": DEFAULT_PRICE,
        }]

# ===================== FastAPI =====================
app = FastAPI(title="Telegram × Saweria Bot")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Static mounts ----------
def _resolve_dir(*candidates: Path) -> Optional[Path]:
    for p in candidates:
        if p and p.is_dir():
            return p.resolve()
    return None

def _resolve_webapp_dir() -> Optional[Path]:
    envp = os.getenv("WEBAPP_DIR")
    if envp:
        p = Path(envp).resolve()
        if p.is_dir():
            return p
    here = Path(__file__).resolve().parent
    repo_root = here.parent
    return _resolve_dir(
        here / "webapp",
        repo_root / "webapp",
        Path.cwd() / "webapp",
        Path.cwd() / "app" / "webapp",
    )

# /public (opsional)
public_dir = _resolve_dir(
    Path(__file__).resolve().parent / "public",
    Path.cwd() / "public"
)
if public_dir:
    print(f"[static] Mounting /public -> {public_dir}")
    app.mount("/public", StaticFiles(directory=str(public_dir)), name="public")

# /webapp (Mini App)
WEBAPP_DIR = _resolve_webapp_dir()
if WEBAPP_DIR:
    print(f"[static] Mounting /webapp -> {WEBAPP_DIR}")
    app.mount("/webapp", StaticFiles(directory=str(WEBAPP_DIR), html=True), name="webapp")
else:
    print("[static] WARNING: folder 'webapp' tidak ditemukan. /webapp akan 404")

# root: redirect ke /webapp/ bila ada
@app.get("/")
def root():
    if WEBAPP_DIR:
        return RedirectResponse(url="/webapp/")
    return {"ok": True, "message": "Service is running. Put your front-end in a 'webapp/' folder."}

# ---------- ENDPOINT CONFIG/GRUPS UNTUK FRONT-END ----------
def _groups_payload():
    return {
        "ok": True,
        "count": len(GROUPS),
        "groups": GROUPS,
        "items": GROUPS,
        "options": GROUPS,
        "env": ENV,
        "baseUrl": BASE_URL,
        # expose harga global juga
        "price": PRICE_IDR,
        "price_idr": PRICE_IDR,
        "defaultPrice": DEFAULT_PRICE,
    }

# Aliases di /api/*
@app.get("/api/groups")
def api_groups():
    return _groups_payload()

@app.get("/api/items")
def api_items():
    return _groups_payload()

@app.get("/api/options")
def api_options():
    return _groups_payload()

@app.get("/api/config")
def api_config():
    return _groups_payload()

# Aliases di bawah /webapp (untuk fetch relatif dari index.html)
@app.get("/webapp/config.json")
def webapp_config():
    return _groups_payload()

@app.get("/webapp/groups.json")
def webapp_groups_json():
    return _groups_payload()

# Aliases di ROOT (untuk fetch('/groups.json') atau fetch('/config.json'))
@app.get("/config.json")
def root_config_json():
    return _groups_payload()

@app.get("/groups.json")
def root_groups_json():
    return _groups_payload()

# ---------- Telegram Bot lifecycle ----------
bot_app: Application = build_app()
register_handlers(bot_app)

@app.on_event("startup")
async def on_start():
    print("[startup] init DB…")
    storage.init_db()
    print(f"[startup] GROUPS loaded: {len(GROUPS)} item(s); PRICE_IDR={PRICE_IDR}")

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
    # storage.create_invoice(user_id, groups: List[str], amount)
    if hasattr(storage, "create_invoice"):
        try:
            inv = storage.create_invoice(user_id, [group_id], amount)  # type: ignore
        except TypeError:
            inv = storage.create_invoice(user_id, group_id, amount)   # type: ignore
    else:
        inv = {
            "invoice_id": os.urandom(16).hex(),
            "user_id": user_id,
            "group_id": group_id,
            "amount": amount,
            "status": "PENDING",
        }
        if hasattr(storage, "save_invoice"):
            storage.save_invoice(inv)  # type: ignore

    inv_id = str(inv.get("invoice_id", ""))
    short = inv_id.replace("INV:", "").replace("inv:", "").replace("-", "")[:8].upper()
    code = f"INV:{short}" if short else f"INV:{os.urandom(4).hex().upper()}"
    inv["code"] = code
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

# === Ekstraksi key/kode invoice dari payload webhook ===
INV_KEY_RE = re.compile(r"(INV[:：]?\s*([A-Za-z0-9]{4,16}))", re.I)
UUID_RE    = re.compile(r"\b[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}\b", re.I)

def _extract_invoice_key(data: Any) -> Optional[str]:
    candidates: List[str] = []
    if isinstance(data, dict):
        for k in ["message","pesan","note","notes","comment","payload","metadata","data","custom_field","custom","order_id","invoice_id","id"]:
            v = data.get(k)
            if isinstance(v, str):
                candidates.append(v)
            elif isinstance(v, (dict, list)):
                candidates.append(json.dumps(v))
        candidates.append(json.dumps(data))
    elif isinstance(data, list):
        candidates.append(json.dumps(data))
    elif isinstance(data, str):
        candidates.append(data)

    for text in candidates:
        if not text:
            continue
        m = INV_KEY_RE.search(text)
        if m:
            return m.group(2).upper()
        m2 = UUID_RE.search(text)
        if m2:
            return m2.group(0).replace("-", "").upper()[:8]
    return None

@app.post("/api/invoice")
async def api_create_invoice(payload: CreateInvoiceIn):
    inv = _storage_create(payload.user_id, payload.group_id, payload.amount)
    return {
        "ok": True,
        "invoice_id": inv["invoice_id"],
        "code": inv.get("code"),
        "amount": inv["amount"],
        "howto": [
            "Jika ada kolom 'pesan' sebelum bayar, tempelkan kode ini.",
            "Setelah bayar, bot akan kirim link undangan ke DM kamu."
        ],
    }

def _storage_find_by_code_prefix(prefix: str):
    prefix = prefix.strip().upper().replace("INV:", "")
    if hasattr(storage, "list_invoices"):
        invoices = storage.list_invoices()  # type: ignore
        if isinstance(invoices, list):
            for it in invoices:
                code = str(it.get("code", "")).upper().replace("INV:", "")
                inv_id = str(it.get("invoice_id", "")).replace("-", "").upper()
                if code.startswith(prefix) or inv_id.startswith(prefix):
                    return it
    return None

def _storage_get_pending_only():
    if hasattr(storage, "list_invoices"):
        invoices = storage.list_invoices()  # type: ignore
        if isinstance(invoices, list):
            pendings = [it for it in invoices if str(it.get("status","")).upper()=="PENDING"]
            if len(pendings) == 1:
                return pendings[0]
    return None

@app.get("/api/status/{invoice_id}")
async def api_status(invoice_id: str):
    inv = _storage_get(invoice_id)
    if not inv:
        raise HTTPException(404, "invoice not found")
    return {"ok": True, "status": inv.get("status", "PENDING")}

# ==================================================
# ===============  SAWERIA WEBHOOK  ================
# ==================================================
def _is_success_status(data: Any) -> bool:
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
    if not WEBHOOK_SECRET:
        return True
    got = request.headers.get("X-Hub-Signature-256") or request.headers.get("X-Signature")
    if got:
        sig = got.split("=", 1)[-1] if "=" in got else got
        digest = hmac.new(WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(digest, sig)
    saw_sig = request.headers.get("saweria-callback-signature")
    if saw_sig:
        print("[webhook] saweria-callback-signature detected (accepted in relaxed mode)")
        return True
    return False

@app.post("/webhook/saweria")
async def webhook_saweria(request: Request):
    raw = await request.body()
    try:
        data = await request.json()
    except Exception:
        data = None

    if not _verify_signature(request, raw):
        raise HTTPException(401, "invalid signature")

    key = _extract_invoice_key(data)
    print(f"[webhook] payload received. extracted key = {key}")

    inv = None
    if key:
        inv = _storage_find_by_code_prefix(key)
        if not inv:
            inv = _storage_get(key)

    if not inv:
        inv = _storage_get_pending_only()
        if inv:
            print("[webhook] fallback to single PENDING invoice")

    if not inv:
        return JSONResponse({"ok": True, "message": "invoice not found"}, status_code=200)

    inv_id = str(inv.get("invoice_id"))
    inv = _storage_update_status(inv_id, "PAID")
    print(f"[webhook] marked PAID for {inv_id}")

    try:
        chat_id = int(inv["user_id"])
        target_group_id = str(inv.get("group_id") or (inv.get("groups") or [""])[0])
        await send_invite_link(bot_app, chat_id, target_group_id)
        print(f"[webhook] invite sent → user={chat_id} group={target_group_id}")
    except Exception as e:
        print(f"[webhook] FAILED to send invite: {e!r}")

    return {"ok": True, "handled": True, "invoice_id": inv_id}
