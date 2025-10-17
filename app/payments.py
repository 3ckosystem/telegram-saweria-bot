# app/payments.py
# Buat invoice, jalankan scraper HD di background, lalu simpan PNG ke qris_payload (data URL).

import uuid
import time
import json
import asyncio
import base64
from typing import List, Optional, Dict, Any

from . import storage
from .scraper import fetch_gopay_qr_hd_png   # gunakan HD langsung (lebih cepat & tajam)


# ------------ Helpers (passthrough ke storage) ------------
def get_invoice(invoice_id: str) -> Optional[Dict[str, Any]]:
    return storage.get_invoice(invoice_id)

def list_invoices(limit: int = 20) -> List[Dict[str, Any]]:
    return storage.list_invoices(limit)

def mark_paid(invoice_id: str) -> Optional[Dict[str, Any]]:
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
async def create_invoice(user_id: int, groups: List[str], amount: int) -> Dict[str, str]:
    """
    Membuat invoice PENDING dan langsung memicu pengambilan QR HD di background.
    """
    # Validasi ringan (tidak kaku, agar UX tetap mulus)
    try:
        amount = int(amount)
    except Exception:
        amount = 0
    if amount <= 0:
        # tetap buat invoice untuk konsistensi flow, tapi log agar mudah dilacak
        print(f"[payments] WARN: amount <= 0 for user={user_id}")

    if not isinstance(groups, list):
        groups = []

    inv_id = str(uuid.uuid4())
    storage.upsert_invoice({
        "invoice_id": inv_id,
        "user_id": user_id,
        "groups_json": json.dumps(groups),
        "amount": amount,
        "status": "PENDING",
        "created_at": int(time.time()),
        "qris_payload": None,   # akan terisi oleh scraper async
    })

    # Trigger background capture segera (non-blocking)
    try:
        asyncio.create_task(_scrape_and_store(inv_id, amount))
    except Exception as e:
        # fallback: jalankan langsung (blocking) agar tetap ada QR (jarang terjadi)
        print("[payments] create_task failed, running inline:", e)
        await _scrape_and_store(inv_id, amount)

    return {"invoice_id": inv_id}


def get_status(invoice_id: str) -> Optional[Dict[str, Any]]:
    """
    Mengembalikan status ringkas untuk polling MiniApp.
    Contoh: {"status":"PENDING"|"PAID","paid_at":..., "has_qr": true|false}
    """
    inv = storage.get_invoice(invoice_id)
    if not inv:
        return None
    return {
        "status": inv["status"],
        "paid_at": inv.get("paid_at"),
        "has_qr": bool(inv.get("qris_payload")),
    }
