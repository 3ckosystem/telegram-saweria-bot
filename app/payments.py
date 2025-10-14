import uuid, time, json
from . import storage

def create_invoice(user_id: int, groups: list[str], amount: int):
    inv_id = str(uuid.uuid4())
    qr_payload = f"QRIS:SAWERIA:{inv_id}:AMT:{amount}"  # TODO: ganti ke QRIS Saweria asli
    storage.upsert_invoice({
        "invoice_id": inv_id,
        "user_id": user_id,
        "groups_json": json.dumps(groups),
        "amount": amount,
        "status": "PENDING",
        "created_at": int(time.time())
    })
    return {"invoice_id": inv_id, "qr": qr_payload}

def mark_paid(invoice_id: str):
    storage.mark_paid(invoice_id)
    return storage.get_invoice(invoice_id)

def get_invoice(invoice_id: str):
    return storage.get_invoice(invoice_id)
