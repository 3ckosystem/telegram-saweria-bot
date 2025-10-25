# app/storage.py
# ------------------------------------------------------------
# Penyimpanan sederhana pakai SQLite.
# Table:
# - invoices(invoice_id, user_id, amount, groups_json, status, qris_payload, paid_at, created_at)
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

def _conn():
    return sqlite3.connect(DB_PATH)

def _table_has_column(conn, table: str, col: str) -> bool:
    cur = conn.execute(f'PRAGMA table_info("{table}")')
    return any((r[1] == col) for r in cur.fetchall())

def init_db():
    conn = _conn()
    cur = conn.cursor()

    # invoices (biarkan seperti yang sudah ada di projectmu)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS invoices (
      invoice_id TEXT PRIMARY KEY,
      user_id    INTEGER,
      amount     INTEGER,
      status     TEXT,
      groups_json TEXT,
      qris_payload TEXT
      -- jangan paksa created_at di sini kalau skema lama belum ada
    )
    """)

    # invite_logs
    cur.execute("""
    CREATE TABLE IF NOT EXISTS invite_logs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      invoice_id TEXT,
      group_id   TEXT,
      invite_link TEXT,
      error      TEXT
      -- kolom created_at opsional
    )
    """)

    # 🔧 migrasi ringan: tambahkan created_at bila belum ada (opsional)
    if not _table_has_column(conn, "invite_logs", "created_at"):
        try:
            cur.execute('ALTER TABLE invite_logs ADD COLUMN created_at INTEGER')
        except Exception:
            pass  # abaikan kalau SQLite lama tidak bisa; fungsi add_invite_log akan menyesuaikan

    conn.commit()
    conn.close()


# ---------- helpers ----------
def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {k: row[k] for k in row.keys()}

# ---------- invoices ----------
def create_invoice(user_id: int, groups: List[str], amount: int) -> Dict[str, Any]:
    invoice_id = str(uuid.uuid4())
    groups_json = json.dumps(groups, ensure_ascii=False)
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
    return _row_to_dict(row)

def get_invoice(invoice_id: str) -> Optional[Dict[str, Any]]:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM invoices WHERE invoice_id = ?", (invoice_id,))
    row = cur.fetchone()
    conn.close()
    return _row_to_dict(row) if row else None

def list_invoices(limit: int = 20) -> List[Dict[str, Any]]:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM invoices ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    conn.close()
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
def add_invite_log(invoice_id: str, group_id: str, invite_link: str | None, error: str | None):
    conn = _conn()
    cur  = conn.cursor()
    has_created = _table_has_column(conn, "invite_logs", "created_at")
    now = int(time.time())

    if has_created:
        cur.execute("""
            INSERT INTO invite_logs (invoice_id, group_id, invite_link, error, created_at)
            VALUES (?,?,?,?,?)
        """, (invoice_id, str(group_id), invite_link, error, now))
    else:
        cur.execute("""
            INSERT INTO invite_logs (invoice_id, group_id, invite_link, error)
            VALUES (?,?,?,?)
        """, (invoice_id, str(group_id), invite_link, error))
    conn.commit()
    conn.close()


def list_invite_logs(invoice_id: str):
    conn = _conn()
    cur  = conn.cursor()
    # pilih kolom secara defensif (created_at mungkin tidak ada)
    has_created = _table_has_column(conn, "invite_logs", "created_at")
    if has_created:
        cur.execute("""SELECT invoice_id, group_id, invite_link, error, created_at
                       FROM invite_logs WHERE invoice_id=? ORDER BY id ASC""", (invoice_id,))
    else:
        cur.execute("""SELECT invoice_id, group_id, invite_link, error
                       FROM invite_logs WHERE invoice_id=? ORDER BY id ASC""", (invoice_id,))
    rows = cur.fetchall()
    conn.close()

    items = []
    for r in rows:
        item = {
            "invoice_id": r[0],
            "group_id":   r[1],
            "invite_link": r[2],
            "error":       r[3],
        }
        if has_created:
            item["created_at"] = r[4]
        items.append(item)
    return items
