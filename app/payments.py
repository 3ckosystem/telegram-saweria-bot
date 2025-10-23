
# app/payments.py — SAFE WRAPPER (no crash on import)
# ------------------------------------------------------------
# Fungsi publik:
#   - create_invoice(user_id, groups, amount)  -> dict invoice
#   - get_invoice(invoice_id)                  -> dict|None
#   - get_status(invoice_id)                   -> dict|None
#   - mark_paid(invoice_id)                    -> dict|None
#   - list_invoices(limit=50)                  -> list[dict]
#   - (bg) _bg_generate_qr(invoice_id, amount) -> None
# Catatan: tidak me-raise error saat import meski storage beda nama.
# ------------------------------------------------------------

from __future__ import annotations
import asyncio, base64
from typing import Any, Dict, List, Optional

from . import storage
from .scraper import fetch_gopay_qr_hd_png

# ---------- util pemanggil aman ----------
def _call_storage(names: list[str], *args, **kwargs):
    """
    Coba panggil storage.<name> dari daftar 'names' secara berurutan.
    Tidak me-raise saat import; hanya raise saat dipanggil dan tak satupun ditemukan.
    """
    for n in names:
        fn = getattr(storage, n, None)
        if callable(fn):
            return fn(*args, **kwargs)
    raise RuntimeError(f"Storage function not found. Tried: {', '.join(names)}")

# ---------- API ----------
async def create_invoice(user_id: int, groups: List[str], amount: int) -> Dict[str, Any]:
    inv = _call_storage(
        ["create_invoice", "new_invoice", "add_invoice"],
        user_id, groups, amount
    )
    # prewarm QR (non-blocking)
    try:
        asyncio.create_task(_bg_generate_qr(inv["invoice_id"], amount))
    except Exception:
        pass
    return inv

def get_invoice(invoice_id: str) -> Optional[Dict[str, Any]]:
    return _call_storage(["get_invoice", "read_invoice", "fetch_invoice"], invoice_id)

def get_status(invoice_id: str) -> Optional[Dict[str, Any]]:
    return _call_storage(["get_status", "read_status", "status_of"], invoice_id)

def mark_paid(invoice_id: str) -> Optional[Dict[str, Any]]:
    _call_storage(["mark_paid", "set_paid", "update_status_paid"], invoice_id)
    return get_invoice(invoice_id)

def list_invoices(limit: int = 50) -> List[Dict[str, Any]]:
    try:
        return _call_storage(["list_invoices", "all_invoices", "fetch_invoices"], limit)
    except TypeError:
        return _call_storage(["list_invoices", "all_invoices", "fetch_invoices"])

# ---------- background prewarm ----------
async def _bg_generate_qr(invoice_id: str, amount: int) -> None:
    try:
        message = f"INV:{invoice_id}"
        png = await fetch_gopay_qr_hd_png(int(amount), message)
        if not png:
            return
        b64 = base64.b64encode(png).decode()
        _call_storage(
            ["update_qris_payload", "update_qr_payload", "cache_qr_payload"],
            invoice_id, f"data:image/png;base64,{b64}"
        )
    except Exception:
        return
