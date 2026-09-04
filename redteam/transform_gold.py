"""The transform that ran on cutover weekend: legacy billing (SQLite copy of the MySQL dump) ->
newbill (SQLite copy of the Postgres schema). Decisions, each from the code, not the column names:
  - status is authoritative; is_paid/paid_at are set at SUBMISSION (Payments.php) and never
    cleared, so they are not carried. paid_at lands ONLY on SETTLED rows (Invoice.clean()), as
    the successful payment's submission time (legacy never records settlement time).
  - archived customers migrate with is_active = 0 (PROTECT FK; every legacy screen filters them);
    the invoice-level archived flag is derived from the customer's (cron_archive.php) and dropped.
  - legacy DATETIMEs are naive America/Chicago (php.ini on legacy-app-01); destination is UTC.
  - amounts: DECIMAL(10,2) -> integer cents by exact decimal arithmetic, sign preserved.
  - ids are re-sequenced; the legacy invoice id is kept in external_ref as LEGACY-<id>.
  - balance_cents = sum of amount_cents over the customer's invoices not SETTLED/VOID
    (signals.py's formula), computed set-based after the load because the signal is bypassed.
"""
import sqlite3, sys, os, datetime, decimal, zoneinfo
src, dst = sys.argv[1], sys.argv[2]
CHI, UTC = zoneinfo.ZoneInfo("America/Chicago"), datetime.timezone.utc
def to_utc(s):
    if s is None: return None
    return datetime.datetime.fromisoformat(s).replace(tzinfo=CHI).astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S+00:00")
def cents(s): return int((decimal.Decimal(s) * 100).to_integral_value(rounding=decimal.ROUND_HALF_UP))
if os.path.exists(dst): os.unlink(dst)
S, D = sqlite3.connect(src), sqlite3.connect(dst)
D.executescript("""
CREATE TABLE billing_customer (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
  email TEXT, is_active INTEGER NOT NULL DEFAULT 1, balance_cents INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
  created_by_id INTEGER);
CREATE TABLE billing_invoice (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER NOT NULL REFERENCES billing_customer(id),
  number TEXT NOT NULL UNIQUE, external_ref TEXT UNIQUE, amount_cents INTEGER NOT NULL, status TEXT NOT NULL, paid_at TEXT,
  issued_on TEXT NOT NULL, created_at TEXT NOT NULL, created_by_id INTEGER);
""")
STATUS = {"open": "OPEN", "settled": "SETTLED", "failed": "FAILED", "void": "VOID"}
cmap = {}
for lid, code, name, email, archived, created in S.execute("SELECT id,code,name,email,archived,created_at FROM customers ORDER BY id"):
    cur = D.execute("INSERT INTO billing_customer(code,name,email,is_active,balance_cents,created_at,created_by_id) VALUES (?,?,?,?,0,?,NULL)",
                    (code, name, (email or None) or None, 0 if archived else 1, to_utc(created)))
    cmap[lid] = cur.lastrowid
settled_sub = dict(S.execute("SELECT invoice_id, MAX(created_at) FROM payments WHERE result='settled' GROUP BY invoice_id"))
for lid, cust, number, amount, status, issued, created in S.execute(
        "SELECT id,customer_id,invoice_number,amount,status,issued_on,created_at FROM invoices ORDER BY id"):
    st = STATUS[status]
    paid_at = to_utc(settled_sub[lid]) if st == "SETTLED" else None
    D.execute("INSERT INTO billing_invoice(customer_id,number,external_ref,amount_cents,status,paid_at,issued_on,created_at,created_by_id) VALUES (?,?,?,?,?,?,?,?,NULL)",
              (cmap[cust], number, "LEGACY-%d" % lid, cents(amount), st, paid_at, issued, to_utc(created)))
D.execute("""UPDATE billing_customer SET balance_cents = COALESCE((SELECT SUM(amount_cents) FROM billing_invoice i
             WHERE i.customer_id = billing_customer.id AND i.status NOT IN ('SETTLED','VOID')), 0)""")
for t in ("billing_customer", "billing_invoice"):
    D.execute("UPDATE sqlite_sequence SET seq = (SELECT MAX(id) FROM %s) WHERE name = ?" % t, (t,))
D.commit()
print("customers", D.execute("SELECT COUNT(*) FROM billing_customer").fetchone()[0], "invoices", D.execute("SELECT COUNT(*) FROM billing_invoice").fetchone()[0])
