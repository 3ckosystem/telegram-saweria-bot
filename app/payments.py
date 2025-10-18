# app/payments.py
# Buat invoice, jalankan scraper HD di background, lalu simpan PNG ke qris_payload (data URL).

import uuid, time, json, asyncio
import base64
from typing import List, Optional, Dict, Any

from . import storage
from .scraper import fetch_gopay_qr_hd_png   # gunakan HD langsung (lebih cepat & tajam)


# ------------ Helpers (passthrough ke storage) ------------
def get_invoice(invoice_id: str):
    return storage.get_invoice(invoice_id)

def list_invoices(limit: int = 20):
    return storage.list_invoices(limit)

def mark_paid(invoice_id: str):
    return storage.mark_paid(invoice_id)


# ------------ Background scraper (HD on-demand) ------------
async def _scrape_and_store(invoice_id: str, amount: int) -> None:
    """
    Ambil QR HD (PNG asli dari <img src=".../qr-code">) lalu simpan ke DB sebagai data URL.
    """
    try:
        png = await fetch_gopay_qr_hd_png(amount, f"INV:{invoice_id}")
        if not png:
            print(f"[scraper] ERROR: no HD PNG for {invoice_id}")
            return
        b64 = base64.b64encode(png).decode()
        data_url = f"data:image/png;base64,{b64}"
        storage.update_qris_payload(invoice_id, data_url)
        print(f"[scraper] ok: stored HD PNG for {invoice_id} (len={len(png)})")
    except Exception as e:
        # jangan biarkan exception membatalkan task utama
        print("[scraper] error in _scrape_and_store:", e)


# ------------ Public API ------------
async def create_invoice(user_id: int, groups: list[str], amount: int):
    inv_id = str(uuid.uuid4())
    # simpan dulu, qris_payload akan berupa URL png siap dipanggil oleh <img>
    storage.upsert_invoice({
        "invoice_id": inv_id,
        "user_id": user_id,
        "groups_json": json.dumps(groups),
        "amount": amount,
        "status": "PENDING",
        "created_at": int(time.time()),
        # langsung isi dengan URL generator (tidak perlu nunggu scraper selesai)
        "qris_payload": f"/api/qr/{inv_id}.png?amount={amount}&msg=INV:{inv_id}",
    })
    return {"invoice_id": inv_id}


def get_status(invoice_id: str):
    inv = storage.get_invoice(invoice_id)
    if not inv:
        return None
    return {
        "status": inv["status"],
        "paid_at": inv.get("paid_at"),
        "has_qr": bool(inv.get("qris_payload")),
    }