
# app/payments.py
# ------------------------------------------------------------
# Abstraksi tipis di atas storage + integrasi scraper.
# - create_invoice(user_id, groups, amount)
# - get_invoice(invoice_id)
# - get_status(invoice_id)
# - mark_paid(invoice_id)
# - list_invoices(limit=50)
# - (opsional) _bg_generate_qr(...) untuk prewarm QR HD dan cache ke DB
# ------------------------------------------------------------

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any, Dict, List, Optional, Callable

from . import storage  # wajib ada modul storage
from .scraper import fetch_gopay_qr_hd_png

# ---------- Helper compat ke beragam nama fungsi di storage ----------
def _resolve(name: str, *alts: str) -> Callable:
    for n in (name, *alts):
        fn = getattr(storage, n, None)
        if callable(fn):
            return fn
    raise AttributeError(f"Function not found in storage: {name} / {alts}")

# Map beberapa kemungkinan nama (biar tahan beda versi storage.py)
_storage_create_invoice     = _resolve("create_invoice", "new_invoice", "add_invoice")
_storage_get_invoice        = _resolve("get_invoice", "read_invoice", "fetch_invoice")
_storage_get_status         = _resolve("get_status", "read_status", "status_of")
_storage_mark_paid          = _resolve("mark_paid", "set_paid", "update_status_paid")
_storage_update_qr_payload  = _resolve("update_qris_payload", "update_qr_payload", "cache_qr_payload")
_storage_list_invoices      = _resolve("list_invoices", "all_invoices", "fetch_invoices")

# ---------- Public API ----------
async def create_invoice(user_id: int, groups: List[str], amount: int) -> Dict[str, Any]:
    """
    Buat invoice baru di storage. Mengembalikan dict minimal:
    {"invoice_id": "...", "user_id": int, "groups_json": "[]", "amount": int, "status": "PENDING"}
    """
    inv = _storage_create_invoice(user_id, groups, amount)
    # Prewarm QR (tanpa blocking)
    try:
        asyncio.create_task(_bg_generate_qr(inv["invoice_id"], amount))
    except Exception:
        pass
    return inv

def get_invoice(invoice_id: str) -> Optional[Dict[str, Any]]:
    return _storage_get_invoice(invoice_id)

def get_status(invoice_id: str) -> Optional[Dict[str, Any]]:
    return _storage_get_status(invoice_id)

def mark_paid(invoice_id: str) -> Optional[Dict[str, Any]]:
    """
    Tandai invoice sebagai PAID di storage, kembalikan row terbaru.
    """
    _storage_mark_paid(invoice_id)
    return _storage_get_invoice(invoice_id)

def list_invoices(limit: int = 50) -> List[Dict[str, Any]]:
    try:
        return _storage_list_invoices(limit)
    except TypeError:
        # beberapa implementasi tidak menerima limit
        return _storage_list_invoices()

# ---------- Background QR prewarm ----------
async def _bg_generate_qr(invoice_id: str, amount: int) -> None:
    """
    Ambil QR HD via scraper dan simpan sebagai data URL ke DB.
    Supaya /api/qr/{id} bisa cepat melayani request berikutnya.
    """
    try:
        message = f"INV:{invoice_id}"
        png = await fetch_gopay_qr_hd_png(amount, message)
        if not png:
            return
        b64 = base64.b64encode(png).decode()
        _storage_update_qr_payload(invoice_id, f"data:image/png;base64,{b64}")
    except Exception:
        # diamkan; logging sudah cukup dari layer scraper
        return
