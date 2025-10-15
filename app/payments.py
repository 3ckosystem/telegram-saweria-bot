# app/payments.py
import uuid, time, json, os, base64, asyncio
import httpx
from . import storage
from .scraper import fetch_qr_png

BASE_URL = os.getenv("BASE_URL", "")
SAWERIA_CREATE_URL = os.getenv("SAWERIA_CREATE_URL")  # e.g., https://api.saweria.id/v1/invoices
SAWERIA_API_KEY = os.getenv("SAWERIA_API_KEY", "")

def _callback_url(invoice_id: str) -> str:
    # Saweria akan menembak webhookmu; pastikan mereka bisa kirim invoice_id ini
    return f"{BASE_URL}/api/saweria/webhook"

async def _create_invoice_via_saweria(user_id: int, groups: list[str], amount: int, invoice_id: str) -> dict:
    """
    Contoh adapter GENERIK.
    - Ubah 'payload' & cara ambil 'qr_string' sesuai dokumen Saweria kamu.
    - Header Authorization biasanya 'Bearer <API_KEY>'.
    Return: dict(qr_string=<string untuk di-QR>, provider_invoice_id=<id di Saweria>)
    """
    if not SAWERIA_CREATE_URL or not SAWERIA_API_KEY:
        raise RuntimeError("SAWERIA env not set")

    payload = {
        "amount": amount,
        "external_id": invoice_id,              # biar gampang cocokkan saat webhook
        "description": f"Join groups {','.join(groups)}",
        "callback_url": _callback_url(invoice_id),
        # tambahkan field lain sesuai API (mis: customer name/email, expiry, dsb)
    }
    headers = {"Authorization": f"Bearer {SAWERIA_API_KEY}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(SAWERIA_CREATE_URL, headers=headers, json=payload)
    r.raise_for_status()
    data = r.json()

    # >>>>> EDIT BAGIAN INI sesuai respons nyata Saweria kamu <<<<<
    # Misal respons:
    # { "id":"inv_abc", "qr_string":"000201010212..." }  atau  { "qr_url":"https://..." }
    provider_invoice_id = data.get("id") or data.get("invoice_id") or invoice_id
    qr_string = data.get("qr_string") or data.get("qr") or data.get("qr_url")
    if not qr_string:
        raise RuntimeError(f"Unexpected Saweria response: {data}")

    return {"provider_invoice_id": provider_invoice_id, "qr_string": qr_string}

async def _scrape_and_store(invoice_id: str, amount: int):
    try:
        # method dibaca dari ENV di dalam scraper
        png = await fetch_qr_png(amount, f"INV:{invoice_id}")
        if not png: return
        import base64
        b64 = base64.b64encode(png).decode()
        data_url = f"data:image/png;base64,{b64}"
        storage.update_qris_payload(invoice_id, data_url)
    except Exception as e:
        print("[scraper] error:", e)

async def create_invoice(user_id: int, groups: list[str], amount: int):
    inv_id = str(uuid.uuid4())
    storage.upsert_invoice({
        "invoice_id": inv_id, "user_id": user_id,
        "groups_json": json.dumps(groups), "amount": amount,
        "status": "PENDING", "created_at": int(time.time()),
    })
    asyncio.create_task(_scrape_and_store(inv_id, amount))
    return {"invoice_id": inv_id, "qr": "pending"}

def mark_paid(invoice_id: str):
    storage.mark_paid(invoice_id)
    return storage.get_invoice(invoice_id)

def get_invoice(invoice_id: str):
    return storage.get_invoice(invoice_id)

