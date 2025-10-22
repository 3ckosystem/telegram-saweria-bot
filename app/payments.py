# app/payments.py
# ------------------------------------------------------------
# Lapisan kecil di atas storage untuk:
# - membuat invoice
# - membaca status
# - menandai PAID
# - (opsional) generate QR HD di background dan cache ke DB
# ------------------------------------------------------------

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any, Dict, List, Optional

from . import storage
from .scraper import fetch_gopay_qr_hd_png


# ---------- util: panggil fungsi storage yang mungkin beda nama ----------
def _storage_create_invoice(user_id: int, groups: List[str], amount: int) -> Dict[str, Any]:
    """
    Coba beberapa kemungkinan nama fungsi di storage agar fleksibel.
    Return: dict invoice (harus mengandung invoice_id / amount / groups_json / status, dsb.)
    """
    if hasattr(storage, "create_invoice"):
        return storage.create_invoice(user_id, groups, amount)  # type: ignore[attr-defined]
    if hasattr(storage, "add_invoice"):
        return storage.add_invoice(user_id, groups, amount)  # type: ignore[attr-defined]
    # fallback terakhir: bikin lewat API yang umum kalau ada
    raise RuntimeError("storage.create_invoice / add_invoice tidak ditemukan")


def _storage_get_invoice(invoice_id: str) -> Optional[Dict[str, Any]]:
    if hasattr(storage, "get_invoice"):
        return storage.get_invoice(invoice_id)  # type: ignore[attr-defined]
    if hasattr(storage, "find_invoice"):
        return storage.find_invoice(invoice_id)  # type: ignore[attr-defined]
    return None


def _storage_update_status(invoice_id: str, status: str) -> Optional[Dict[str, Any]]:
    if hasattr(storage, "update_invoice_status"):
        return storage.update_invoice_status(invoice_id, status)  # type: ignore[attr-defined]
    if hasattr(storage, "mark_paid") and status.upper() == "PAID":
        return storage.mark_paid(invoice_id)  # type: ignore[attr-defined]
    # kalau tidak ada API khusus, biarkan caller yang handle None
    return None


def _storage_update_qr_payload(invoice_id: str, data_url: str) -> None:
    if hasattr(storage, "update_qris_payload"):
        storage.update_qris_payload(invoice_id, data_url)  # type: ignore[attr-defined]
        return
    if hasattr(storage, "save_qr_payload"):
        storage.save_qr_payload(invoice_id, data_url)  # type: ignore[attr-defined]
        return
    # jika tidak ada, diamkan saja.


def _storage_list_invoices(limit: int = 20) -> List[Dict[str, Any]]:
    if hasattr(storage, "list_invoices"):
        return storage.list_invoices(limit)  # type: ignore[attr-defined]
    return []


# ---------- API yang dipakai main.py ----------
async def create_invoice(user_id: int, groups: List[str], amount: int, message: str = "") -> Dict[str, Any]:
    inv = _storage_create_invoice(user_id, groups, amount)  # message handled at QR time  # <— simpan di DB/in-memory

    # jika kamu ada proses ambil QR HD di background, teruskan juga message ke fetcher:
    # asyncio.create_task(_bg_fetch_qr_hd(inv["invoice_id"], message))

    return inv


def get_invoice(invoice_id: str) -> Optional[Dict[str, Any]]:
    return _storage_get_invoice(invoice_id)


def get_status(invoice_id: str) -> Optional[Dict[str, Any]]:
    inv = _storage_get_invoice(invoice_id)
    if not inv:
        return None

    # Normalisasi field agar stabil untuk API /api/invoice/{id}/status
    status = (inv.get("status") or "PENDING").upper()
    payload = inv.get("qris_payload") or inv.get("qr_payload")

    return {
        "invoice_id": inv.get("invoice_id") or invoice_id,
        "status": status,
        "paid_at": inv.get("paid_at"),
        "has_qr": bool(payload),
    }


def mark_paid(invoice_id: str) -> Optional[Dict[str, Any]]:
    updated = _storage_update_status(invoice_id, "PAID")
    # kalau storage tidak mengembalikan row terbaru, coba ambil lagi
    return updated or _storage_get_invoice(invoice_id)


def list_invoices(limit: int = 20) -> List[Dict[str, Any]]:
    return _storage_list_invoices(limit)


# ---------- background QR prewarm ----------
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
