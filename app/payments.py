# app/payments.py
# Buat invoice, jalankan scraper simple capture di background, simpan PNG ke qris_payload (data URL).

import uuid, time, json, asyncio, base64
from . import storage
from .scraper import fetch_gopay_qr_hd_png   # <-- gunakan HD

def get_invoice(invoice_id: str):
    return storage.get_invoice(invoice_id)

def list_invoices(limit: int = 20):
    return storage.list_invoices(limit)

def mark_paid(invoice_id: str):
    return storage.mark_paid(invoice_id)

async def _scrape_and_store(invoice_id: str, amount: int):
    try:
        # ambil QR HD (langsung unduh PNG asli dari <img src=".../qr-code">)
        png = await fetch_gopay_qr_hd_png(amount, f"INV:{invoice_id}")
        if not png:
            print(f"[scraper] ERROR: no HD PNG for {invoice_id}")
            return
        b64 = base64.b64encode(png).decode()
        data_url = f"data:image/png;base64,{b64}"
        storage.update_qris_payload(invoice_id, data_url)
        print(f"[scraper] ok: stored HD PNG for {invoice_id} (len={len(png)})")
    except Exception as e:
        print("[scraper] error:", e)

async def create_invoice(user_id: int, groups: list[str], amount: int):
    inv_id = str(uuid.uuid4())
    storage.upsert_invoice({
        "invoice_id": inv_id,
        "user_id": user_id,
        "groups_json": json.dumps(groups),
        "amount": amount,
        "status": "PENDING",
        "created_at": int(time.time()),
        "qris_payload": None,   # akan terisi oleh scraper
    })
    # trigger background capture segera
    asyncio.create_task(_scrape_and_store(inv_id, amount))
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
