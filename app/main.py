# app/main.py
import os, json, re, base64
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ====== project modules (sudah ada di project kamu) ======
from . import payments, storage
from .bot import build_app, register_handlers, send_invite_link

app = FastAPI(title="Telegram Saweria Bot API")

# --- CORS (nyalain kalau front-end & API beda origin) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # ganti ke domain kamu kalau sudah fix
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Serve Mini App statis (ubah path bila perlu) ---
try:
    app.mount("/miniapp", StaticFiles(directory="app/webapp", html=True), name="miniapp")
except Exception:
    # abaikan kalau direktori tidak ada di kontainer tertentu
    pass

# --- Root ke Mini App (opsional, biar gampang test) ---
@app.get("/")
def root_index():
    return PlainTextResponse("OK. Buka /miniapp/ untuk Mini App, atau panggil /api/config /api/invoice dsb.")

# ================== ENV (Railway Variables) ==================
PRICE_IDR = int(os.getenv("PRICE_IDR", "25000"))

try:
    raw_groups = json.loads(os.getenv("GROUP_IDS_JSON", "[]"))
    GROUPS: List[str] = [
        (g["id"] if isinstance(g, dict) and "id" in g else str(g))
        for g in raw_groups
    ]
    GROUP_LABELS: Dict[str, str] = {
        (g.get("id") if isinstance(g, dict) else str(g)): (g.get("label") if isinstance(g, dict) else str(g))
        for g in raw_groups
    }
except Exception:
    GROUPS, GROUP_LABELS = [], {}

# ================== MODELS ==================
class CreateInvoiceIn(BaseModel):
    user_id: int
    groups: List[str]


tg_app = None

@app.on_event("startup")
async def _startup():
    global tg_app
    # init DB
    try:
        storage.init_db()
    except Exception as e:
        print("[startup] storage.init_db error:", e)
    # init telegram app for sending messages
    try:
        tg_app = build_app()
        register_handlers(tg_app)
        await tg_app.initialize()
        print("[startup] telegram app initialized")
    except Exception as e:
        print("[startup] telegram app init error:", e)

@app.on_event("shutdown")
async def _shutdown():
    global tg_app
    if tg_app:
        try:
            await tg_app.shutdown()
        except Exception as e:
            print("[shutdown] telegram app shutdown error:", e)

# ================== ROUTES ==================
@app.get("/health")
def health():
    return {"ok": True, "price_idr": PRICE_IDR, "groups_count": len(GROUPS)}

@app.get("/api/config")
def api_config():
    """Dipanggil Mini App untuk ambil daftar grup & harga dari Railway."""
    items = [{"id": gid, "label": GROUP_LABELS.get(gid, gid)} for gid in GROUPS]
    return {"price_idr": PRICE_IDR, "groups": items}

@app.post("/api/invoice")
def create_invoice(data: CreateInvoiceIn):
    # Validasi dasar
    if not data.user_id or data.user_id <= 0:
        raise HTTPException(status_code=422, detail="user_id tidak valid / tidak terbaca dari Telegram")
    if not data.groups:
        raise HTTPException(status_code=422, detail="groups kosong")

    # Validasi whitelist ENV
    allowed = set(GROUPS or [])
    chosen = [g for g in data.groups if (not allowed or g in allowed)]
    if not chosen:
        raise HTTPException(
            status_code=422,
            detail=f"Group tidak diizinkan. Allowed={list(allowed)}; Requested={data.groups}"
        )

    # Server hitung total (harga seragam dari Railway)
    amount = int(PRICE_IDR) * len(chosen)

    # Buat invoice
    try:
        inv = payments.create_invoice(user_id=int(data.user_id), groups=chosen, amount=int(amount))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal membuat invoice (server): {e}")

    if not inv or not inv.get("invoice_id"):
        raise HTTPException(status_code=500, detail="create_invoice tidak mengembalikan invoice_id")

    return {
        "invoice_id": inv["invoice_id"],
        "amount": inv.get("amount", amount),
        "groups": chosen,
        "price_idr": PRICE_IDR,
        "status": inv.get("status", "PENDING"),
    }

@app.get("/api/invoice/{invoice_id}/status")
def invoice_status(invoice_id: str):
    inv: Optional[Dict[str, Any]] = None
    status = "PENDING"
    paid_at = None
    has_qr = False

    try:
        inv = payments.get_invoice(invoice_id)
    except Exception:
        inv = None

    if inv:
        status = (inv.get("status") or "PENDING").upper()
        paid_at = inv.get("paid_at")
        payload = inv.get("qris_payload") or inv.get("qr_payload")
        has_qr = bool(payload)

    return {"invoice_id": invoice_id, "status": status, "paid_at": paid_at, "has_qr": has_qr}

# ----- QR payload → PNG -----
DATA_URL_RE = re.compile(r"^data:(image/[^;]+);base64,(.+)$")

@app.get("/api/qr/{raw_id}")
def qr_png(raw_id: str):
    """
    Layani PNG QR dari payload yang tersimpan. Izinkan suffix .png/.jpg pada {raw_id}.
    """
    invoice_id = re.sub(r"\.(png|jpg|jpeg)$", "", raw_id, flags=re.I)
    inv = payments.get_invoice(invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="invoice tidak ditemukan")

    data_url = inv.get("qris_payload") or inv.get("qr_payload")
    if not data_url:
        # Bisa dibuat auto-generate di sini kalau kamu ingin.
        raise HTTPException(status_code=404, detail="QR belum tersedia")

    m = DATA_URL_RE.match(str(data_url))
    if not m:
        raise HTTPException(status_code=500, detail="Format QR payload tidak valid")

    mime, b64 = m.group(1), m.group(2)
    try:
        raw = base64.b64decode(b64)
    except Exception:
        raise HTTPException(status_code=500, detail="Gagal decode QR payload")

    return Response(content=raw, media_type="image/png")

# ================== BACK-COMPAT / STUBS ==================
@app.get("/debug/saweria-qr-hd")
def debug_saweria_qr_hd(amount: Optional[int] = None, msg: Optional[str] = None):
    """
    Endpoint lama: sekarang tidak dipakai. Balikkan 410 agar jelas.
    """
    raise HTTPException(status_code=410, detail="Endpoint debug/saweria-qr-hd sudah tidak digunakan. Pakai alur: /api/invoice -> /api/qr/{invoice_id}.png")

@app.post("/telegram/webhook")
async def telegram_webhook_stub(req: Request):
    """
    Stub agar tidak 404 ketika webhook lama masih aktif.
    Kalau ingin hidupkan handler bot sesungguhnya, sambungkan di sini.
    """
    _ = await req.body()
    return {"ok": True, "note": "stub webhook aktif - sambungkan ke handler bot bila diperlukan"}


@app.post("/api/saweria/webhook")
async def saweria_webhook(request: Request):
    

@app.get("/api/invite-logs/{invoice_id}")
def invite_logs(invoice_id: str):
    try:
        logs = storage.list_invite_logs(invoice_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"invoice_id": invoice_id, "logs": logs}
