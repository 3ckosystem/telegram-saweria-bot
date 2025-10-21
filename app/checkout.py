# app/checkout.py
import os, uuid, base64
from pathlib import Path
from typing import List, Dict

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

# Import fungsi scraper kamu
# Pastikan ini sesuai dengan nama modul & fungsi di project
from .scraper import fetch_gopay_qr_hd_png  # TODO: sesuaikan jika namanya berbeda

# ===== Konfigurasi dasar =====
BASE_URL = os.environ.get("BASE_URL", "").rstrip("/")
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
QRIS_DIR = STATIC_DIR / "qris"
QRIS_DIR.mkdir(parents=True, exist_ok=True)

router = APIRouter()

# ===== Model =====
class InvoiceItem(BaseModel):
    id: str
    name: str
    qty: int = Field(ge=1)
    price: int = Field(ge=0)
    subtotal: int = Field(ge=0)

class InvoiceCreateReq(BaseModel):
    items: List[InvoiceItem]
    total: int

class InvoiceCreateRes(BaseModel):
    invoice_id: str
    amount: int

class QrisRes(BaseModel):
    qr_png_url: str
    payment_code: str
    saweria_payment_url: str = "https://saweria.co/payments"

# ===== Penyimpanan sementara (in-memory) =====
INVOICE_DB: Dict[str, Dict] = {}

# ===== Helper =====
def _fmt_id() -> str:
    return "INV:" + uuid.uuid4().hex

# ===== Endpoint =====
@router.post("/invoice", response_model=InvoiceCreateRes)
async def create_invoice(payload: InvoiceCreateReq):
    # Anti-tamper sederhana: hitung ulang total dari items
    calc_total = sum(i.qty * i.price for i in payload.items)
    if calc_total != payload.total:
        # tetap kita izinkan, tapi pada real-case bisa ditolak
        # raise HTTPException(status_code=400, detail="Total tidak valid.")
        pass

    inv_id = _fmt_id()
    INVOICE_DB[inv_id] = {
        "items": [i.model_dump() for i in payload.items],
        "amount": payload.total,
        "status": "created",
    }
    return InvoiceCreateRes(invoice_id=inv_id, amount=payload.total)

@router.get("/qris", response_model=QrisRes)
async def get_qris(invoice_id: str = Query(..., alias="invoice_id")):
    inv = INVOICE_DB.get(invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice tidak ditemukan.")

    amount = int(inv["amount"])

    # ===== Panggil scraper kamu untuk ambil PNG QR & payment code =====
    # Harapan output: (png_bytes, payment_code)
    # TODO: sesuaikan signature fungsi berikut dengan milikmu.
    # Contoh alternatif jika fungsi kamu butuh parameter berbeda:
    # png_bytes, payment_code = await fetch_gopay_qr_hd_png(invoice_id=invoice_id, nominal=amount)
    png_bytes, payment_code = await fetch_gopay_qr_hd_png(invoice_id, amount)  # <— SESUAIKAN jika perlu

    # Simpan PNG ke /static/qris/{invoice_id}.png
    out_path = QRIS_DIR / f"{invoice_id}.png"
    with open(out_path, "wb") as f:
        f.write(png_bytes)

    if not BASE_URL:
        # fallback: relative path
        qr_url = f"/static/qris/{invoice_id}.png"
    else:
        qr_url = f"{BASE_URL}/static/qris/{invoice_id}.png"

    # Update status invoice (opsional)
    inv["status"] = "qris_ready"
    inv["payment_code"] = payment_code

    return QrisRes(
        qr_png_url=qr_url,
        payment_code=payment_code,
        saweria_payment_url="https://saweria.co/payments",
    )
