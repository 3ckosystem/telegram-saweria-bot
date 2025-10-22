# app/main.py
import os, json, re, base64, io
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ----------------- import layer project -----------------
# Pastikan modul ini sudah ada di project kamu (sesuai repo sebelumnya)
from . import payments, storage

# --------------------------------------------------------
#              APP & STATIC MINI-APP (frontend)
# --------------------------------------------------------
app = FastAPI(title="Telegram Saweria Bot API")

# Aktifkan CORS bila frontend & API beda origin (aman untuk sementara)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],           # ganti ke domain kamu kalau sudah fix
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount folder Mini App (sesuaikan path jika berbeda)
# Misal struktur: app/webapp/index.html
try:
    app.mount("/miniapp", StaticFiles(directory="app/webapp", html=True), name="miniapp")
except Exception:
    # Jika running dari cwd berbeda, coba path relatif lain (opsional)
    pass

# --------------------------------------------------------
#                   ENV (Railway Variables)
# --------------------------------------------------------
# Harga seragam (Rupiah, tanpa titik) – diambil dari Railway Variable PRICE_IDR
PRICE_IDR = int(os.getenv("PRICE_IDR", "25000"))

# Daftar grup – diambil dari Railway Variable GROUP_IDS_JSON
# Format boleh: [{"id":"-100...","label":"Group A"}, {"id":"-100...","label":"Group B"}]
# atau: ["-100...","-100..."]
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

# --------------------------------------------------------
#                      MODELS
# --------------------------------------------------------
class CreateInvoiceIn(BaseModel):
    user_id: int
    groups: List[str]

# --------------------------------------------------------
#                      ROUTES
# --------------------------------------------------------
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

    # Validasi whitelist grup dari ENV (jika ada)
    allowed = set(GROUPS or [])
    chosen = [g for g in data.groups if (not allowed or g in allowed)]
    if not chosen:
        raise HTTPException(
            status_code=422,
            detail=f"Group tidak diizinkan. Allowed={list(allowed)}; Requested={data.groups}"
        )

    # Server menghitung total (harga seragam dari Railway)
    amount = int(PRICE_IDR) * len(chosen)

    # Buat invoice via layer payments
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
    """
    Normalisasi status invoice. Mengembalikan minimal:
    { invoice_id, status, paid_at (opsional), has_qr (opsional) }
    """
    # Jika payments menyediakan helper status, gunakan; jika tidak, fallback manual.
    inv: Optional[Dict[str, Any]] = None
    status = "PENDING"
    paid_at = None
    has_qr = False

    try:
        # Try generic getter
        inv = payments.get_invoice(invoice_id)
    except Exception:
        inv = None

    if inv:
        status = (inv.get("status") or "PENDING").upper()
        paid_at = inv.get("paid_at")
        payload = inv.get("qris_payload") or inv.get("qr_payload")
        has_qr = bool(payload)

    return {"invoice_id": invoice_id, "status": status, "paid_at": paid_at, "has_qr": has_qr}

DATA_URL_RE = re.compile(r"^data:(image/[^;]+);base64,(.+)$")

@app.get("/api/qr/{raw_id}")
def qr_png(raw_id: str):
    """
    Layani PNG QR dari payload yang tersimpan.
    Mengizinkan suffix .png / .jpg pada {raw_id}.
    """
    invoice_id = re.sub(r"\.(png|jpg|jpeg)$", "", raw_id, flags=re.I)
    inv = payments.get_invoice(invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="invoice tidak ditemukan")

    data_url = inv.get("qris_payload") or inv.get("qr_payload")
    if not data_url:
        # Jika kamu ingin trigger generator QR HD di sini, kamu bisa panggil scraper dan simpan ke storage.
        # Untuk versi aman, return 404 dulu agar client bisa retry.
        raise HTTPException(status_code=404, detail="QR belum tersedia")

    m = DATA_URL_RE.match(str(data_url))
    if not m:
        raise HTTPException(status_code=500, detail="Format QR payload tidak valid")

    mime, b64 = m.group(1), m.group(2)
    try:
        raw = base64.b64decode(b64)
    except Exception:
        raise HTTPException(status_code=500, detail="Gagal decode QR payload")

    # Standarkan output sebagai PNG
    return Response(content=raw, media_type="image/png")
