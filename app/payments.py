# app/payments.py
# Buat invoice, jalankan scraper HD di background, lalu simpan PNG ke qris_payload (data URL).

import uuid
import time
import json
import asyncio
import base64
from typing import List, Optional, Dict, Any

from . import storage
from .s1 import fetch_gopay_qr_hd_png   # gunakan HD langsung (lebih cepat & tajam)

# hindari double-scrape untuk invoice yang sama
_inflight: dict[str, asyncio.Task] = {}

def get_invoice(invoice_id: str) -> Optional[Dict[str, Any]]:
    return storage.get_invoice(invoice_id)

def list_invoices(limit: int = 20) -> List[Dict[str, Any]]:
    return storage.list_invoices(limit)

def mark_paid(invoice_id: str) -> Optional[Dict[str, Any]]:
    return storage.mark_paid(invoice_id)

async def _scrape_and_store(invoice_id: str, amount: int) -> None:
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
        print("[scraper] error in _scrape_and_store:", e)

async def ensure_qr_scraped(invoice_id: str, amount: int) -> None:
    """Pastikan hanya ada satu task scrape per invoice; tunggu jika sudah berjalan."""
    t = _inflight.get(invoice_id)
    if t and not t.done():
        await t
        return
    t = asyncio.create_task(_scrape_and_store(invoice_id, amount))
    _inflight[invoice_id] = t
    try:
        await t
    finally:
        _inflight.pop(invoice_id, None)

async def create_invoice(user_id: int, groups: List[str], amount: int) -> Dict[str, str]:
    try:
        amount = int(amount)
    except Exception:
        amount = 0
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
        "qris_payload": None,
    })

    # background scrape (non-blocking)
    try:
        asyncio.create_task(ensure_qr_scraped(inv_id, amount))
    except Exception as e:
        print("[payments] create_task failed, running inline:", e)
        await ensure_qr_scraped(inv_id, amount)

    return {"invoice_id": inv_id}

def get_status(invoice_id: str) -> Optional[Dict[str, Any]]:
    inv = storage.get_invoice(invoice_id)
    if not inv:
        return None
    return {
        "status": inv["status"],
        "paid_at": inv.get("paid_at"),
        "has_qr": bool(inv.get("qris_payload")),
    }
 