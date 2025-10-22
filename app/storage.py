# app/storage.py
import os, sqlite3, json
from datetime import datetime

DB_PATH = os.getenv("DB_PATH", "data/app.db")

def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # Buat tabel invoices
    cur.execute("""
    CREATE TABLE IF NOT EXISTS invoices (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        groups TEXT,
        amount REAL,
        message TEXT,
        qris_payload TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Buat tabel invite logs
    cur.execute("""
    CREATE TABLE IF NOT EXISTS invite_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id TEXT,
        user_id TEXT,
        group_id TEXT,
        status TEXT,
        error TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Pastikan kolom message ada
    cur.execute("PRAGMA table_info(invoices)")
    cols = [r[1] for r in cur.fetchall()]
    if "message" not in cols:
        cur.execute("ALTER TABLE invoices ADD COLUMN message TEXT")

    conn.commit()
    conn.close()


# ---------- Fungsi CRUD ----------
def create_invoice(invoice_id, user_id, groups, amount, message=""):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO invoices (id, user_id, groups, amount, message, status)
        VALUES (?, ?, ?, ?, ?, 'pending')
    """, (invoice_id, user_id, json.dumps(groups), amount, message))
    conn.commit()
    conn.close()


def get_invoice(invoice_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0],
        "user_id": row[1],
        "groups": json.loads(row[2]) if row[2] else [],
        "amount": row[3],
        "message": row[4],
        "qris_payload": row[5],
        "status": row[6],
        "created_at": row[7]
    }


def update_invoice_status(invoice_id, status):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE invoices SET status=? WHERE id=?", (status, invoice_id))
    conn.commit()
    conn.close()


def mark_paid(invoice_id):
    update_invoice_status(invoice_id, "paid")


def update_qris_payload(invoice_id, payload):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE invoices SET qris_payload=? WHERE id=?", (payload, invoice_id))
    conn.commit()
    conn.close()


def list_invoices(limit=50):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, user_id, amount, status, created_at FROM invoices ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    conn.close()
    return [
        {"id": r[0], "user_id": r[1], "amount": r[2], "status": r[3], "created_at": r[4]}
        for r in rows
    ]


# ---------- Log group invite ----------
def log_invite_result(invoice_id, user_id, group_id, status, error=None):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO invite_logs (invoice_id, user_id, group_id, status, error)
        VALUES (?, ?, ?, ?, ?)
    """, (invoice_id, user_id, group_id, status, error))
    conn.commit()
    conn.close()


def list_invite_logs(limit=50):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT invoice_id, user_id, group_id, status, error, created_at
        FROM invite_logs
        ORDER BY created_at DESC
        LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    conn.close()
    return [
        {"invoice_id": r[0], "user_id": r[1], "group_id": r[2], "status": r[3], "error": r[4], "created_at": r[5]}
        for r in rows
    ]
