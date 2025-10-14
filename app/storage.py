import sqlite3, time, os
DB_PATH = os.getenv("DB_PATH", "data.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn(); cur = conn.cursor()
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS invoices (
        invoice_id TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        groups_json TEXT NOT NULL,
        amount INTEGER NOT NULL,
        status TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        paid_at INTEGER,
        qris_payload TEXT
    );
    CREATE TABLE IF NOT EXISTS invite_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id TEXT NOT NULL,
        group_id TEXT NOT NULL,
        invite_link TEXT,
        sent_at INTEGER,
        error TEXT
    );
    """)
    # migrasi ringan: tambah kolom jika belum ada
    try: cur.execute("ALTER TABLE invoices ADD COLUMN qris_payload TEXT;")
    except Exception: pass
    conn.commit(); conn.close()


def upsert_invoice(data: dict):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO invoices(invoice_id, user_id, groups_json, amount, status, created_at)
    VALUES(?,?,?,?,?,?)
    ON CONFLICT(invoice_id) DO UPDATE SET
        user_id=excluded.user_id,
        groups_json=excluded.groups_json,
        amount=excluded.amount,
        status=excluded.status
    """, (data["invoice_id"], data["user_id"], data["groups_json"], data["amount"], data["status"], data["created_at"]))
    conn.commit(); conn.close()

def mark_paid(invoice_id: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE invoices SET status='PAID', paid_at=? WHERE invoice_id=?", (int(time.time()), invoice_id))
    conn.commit(); conn.close()

def get_invoice(invoice_id: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM invoices WHERE invoice_id=?", (invoice_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None

def add_invite_log(invoice_id: str, group_id: str, invite_link: str|None, error: str|None):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO invite_logs(invoice_id, group_id, invite_link, sent_at, error) VALUES(?,?,?,?,?)",
                (invoice_id, group_id, invite_link, int(time.time()), error))
    conn.commit(); conn.close()

def list_invite_logs(invoice_id: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT invoice_id, group_id, invite_link, sent_at, error FROM invite_logs WHERE invoice_id=? ORDER BY id DESC", (invoice_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def update_qris_payload(invoice_id: str, payload: str):
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("ALTER TABLE invoices ADD COLUMN qris_payload TEXT;")
    except Exception:
        pass
    cur.execute("UPDATE invoices SET qris_payload=? WHERE invoice_id=?", (payload, invoice_id))
    conn.commit(); conn.close()

