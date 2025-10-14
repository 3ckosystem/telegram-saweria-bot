import uuid, time
from typing import Dict, Optional

# NOTE: Untuk simplicity, pakai memori. Ganti ke DB di produksi.
_invoices: Dict[str, dict] = {}

def create_invoice(user_id: int, groups: list, amount: int) -> dict:
    inv_id = str(uuid.uuid4())
    # Di produksi: panggil integrasi Saweria (resmi webhook / lib tidak resmi) untuk generate QR
    # Di sini kita mock-kan QR string (ganti dengan data dari Saweria)
    qr_payload = f"QRIS:SAWERIA:{inv_id}:AMT:{amount}"
    _invoices[inv_id] = {
        "invoice_id": inv_id,
        "user_id": user_id,
        "groups": groups,
        "amount": amount,
        "status": "PENDING",
        "created_at": int(time.time())
    }
    return {"invoice_id": inv_id, "qr": qr_payload}

def mark_paid(invoice_id: str) -> Optional[dict]:
    inv = _invoices.get(invoice_id)
    if not inv: return None
    inv["status"] = "PAID"
    inv["paid_at"] = int(time.time())
    return inv

def get_invoice(invoice_id: str) -> Optional[dict]:
    return _invoices.get(invoice_id)
