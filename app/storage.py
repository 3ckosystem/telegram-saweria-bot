# app/storage.py
# ------------------------------------------------------------
# Penyimpanan sederhana pakai SQLite.
# Table:
# - invoices(invoice_id, user_id, amount, groups_json, status, qris_payload, paid_at, created_at, code)
# - invite_logs(id, invoice_id, group_id, invite_link, error, created_at)
# ------------------------------------------------------------

from __future__ import annotations

import os
import sqlite3
import json
import uuid
import time
from typing import Any, Dict, List, Optional

DB_PATH = os.getenv("DB_PATH", "/data/app.db")

# ---------- koneksi ----------
def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def _ensure_column(conn: sqlite3.Connection, table: str, col: str, coltype: str) -> None:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    cols = {r[1] for r in cur.fetchall()}
    if col not in cols:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
        conn.commit()

def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS invoices (
        invoice_id   TEXT PRIMARY KEY,
        user_id      INTEGER NOT NULL,
        amount       INTEGER NOT NULL,
        groups_json  TEXT NOT NULL,
        status       TEXT NOT NULL DEFAULT 'PENDING',
        qris_payload TEXT,
        paid_at      INTEGER,
        created_at   INTEGER NOT NULL
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS invite_logs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id  TEXT NOT NULL,
        group_id    TEXT,
        invite_link TEXT,
        error       TEXT,
        created_at  INTEGER NOT NULL
    )
    """)
    # migrasi ringan: tambahkan kolom code bila belum ada
    _ensure_column(conn, "invoices", "code", "TEXT")
    conn.commit()
    conn.close()

# ---------- helpers ----------
def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    d = {k: row[k] for k in row.keys()}
    # turunkan group_id dari groups_json jika belum ada
    if "group_id" not in d:
        try:
            groups = json.loads(d.get("groups_json") or "[]")
            if isinstance(groups, list) and groups:
                d["group_id"] = str(groups[0])
        except Exception:
            d["group_id"] = None
    return d

# ---------- invoices ----------
def create_invoice(user_id: int, group_id: str, amount: int) -> Dict[str, Any]:
    """
    Diselaraskan dgn main.py: terima single group_id.
    Tetap simpan ke groups_json sebagai list satu elemen.
    """
    invoice_id = str(uuid.uuid4())
    groups_json = json.dumps([group_id], ensure_ascii=False)
    now = int(time.time())
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO invoices (invoice_id, user_id, amount, groups_json, status, created_at)
        VALUES (?, ?, ?, ?, 'PENDING', ?)
    """, (invoice_id, user_id, amount, groups_json, now))
    conn.commit()
    cur.execute("SELECT * FROM invoices WHERE invoice_id = ?", (invoice_id,))
    row = cur.fetchone()
    conn.close()
    d = _row_to_dict(row)
    return d

def save_invoice(inv: Dict[str, Any]) -> None:
    """
    Upsert ringan: update kolom yang relevan berdasarkan invoice_id.
    Menyimpan field 'code' agar _storage_find_by_code_prefix bisa bekerja.
    """
    invoice_id = inv["invoice_id"]
    # sinkronkan groups_json jika ada group_id
    groups_json = inv.get("groups_json")
    if not groups_json and inv.get("group_id"):
        groups_json = json.dumps([inv["group_id"]], ensure_ascii=False)

    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE invoices
           SET user_id      = COALESCE(?, user_id),
               amount       = COALESCE(?, amount),
               groups_json  = COALESCE(?, groups_json),
               status       = COALESCE(?, status),
               qris_payload = COALESCE(?, qris_payload),
               paid_at      = COALESCE(?, paid_at),
               code         = COALESCE(?, code)
         WHERE invoice_id   = ?
    """, (
        inv.get("user_id"),
        inv.get("amount"),
        groups_json,
        inv.get("status"),
        inv.get("qris_payload"),
        inv.get("paid_at"),
        inv.get("code"),
        invoice_id,
    ))
    conn.commit()
    conn.close()

def get_invoice(invoice_id: str) -> Optional[Dict[str, Any]]:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM invoices WHERE invoice_id = ?", (invoice_id,))
    row = cur.fetchone()
    conn.close()
    return _row_to_dict(row) if row else None

def list_invoices(limit: int = 200) -> List[Dict[str, Any]]:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM invoices ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    conn.close
    return [_row_to_dict(r) for r in rows]

def update_invoice_status(invoice_id: str, status: str) -> Optional[Dict[str, Any]]:
    status = status.upper()
    now = int(time.time()) if status == "PAID" else None
    conn = _get_conn()
    cur = conn.cursor()
    if status == "PAID":
        cur.execute("UPDATE invoices SET status='PAID', paid_at=? WHERE invoice_id=?", (now, invoice_id))
    else:
        cur.execute("UPDATE invoices SET status=? WHERE invoice_id=?", (status, invoice_id))
    conn.commit()
    cur.execute("SELECT * FROM invoices WHERE invoice_id = ?", (invoice_id,))
    row = cur.fetchone()
    conn.close()
    return _row_to_dict(row) if row else None

def mark_paid(invoice_id: str) -> Optional[Dict[str, Any]]:
    return update_invoice_status(invoice_id, "PAID")

def update_qris_payload(invoice_id: str, data_url: str) -> None:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE invoices SET qris_payload=? WHERE invoice_id=?", (data_url, invoice_id))
    conn.commit()
    conn.close()

# ---------- invite logs ----------
def add_invite_log(invoice_id: str, group_id: str, invite_link: Optional[str], error: Optional[str]) -> None:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO invite_logs(invoice_id, group_id, invite_link, error, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (invoice_id, group_id, invite_link, error, int(time.time())))
    conn.commit()
    conn.close()

def list_invite_logs(invoice_id: str) -> List[Dict[str, Any]]:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM invite_logs WHERE invoice_id=? ORDER BY created_at ASC", (invoice_id,))
    rows = cur.fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]
