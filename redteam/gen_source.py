"""Generate a realistic legacy billing source (SQLite standing in for MySQL). Consistent with
the legacy code's semantics: is_paid/paid_at are set at SUBMISSION and never cleared; status
carries the outcome; archived invoices follow archived customers."""
import sqlite3, random, datetime, os, sys
random.seed(20260904)
out = sys.argv[1]
if os.path.exists(out): os.unlink(out)
db = sqlite3.connect(out); c = db.cursor()
c.executescript("""
CREATE TABLE customers (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL, name TEXT NOT NULL,
  email TEXT, archived INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE invoices (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER NOT NULL,
  invoice_number TEXT NOT NULL, amount TEXT NOT NULL, is_paid INTEGER NOT NULL DEFAULT 0, paid_at TEXT,
  status TEXT NOT NULL DEFAULT 'open', archived INTEGER NOT NULL DEFAULT 0, issued_on TEXT NOT NULL,
  created_at TEXT NOT NULL);
CREATE TABLE payments (id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_id INTEGER NOT NULL,
  processor_ref TEXT, amount TEXT NOT NULL, result TEXT, created_at TEXT NOT NULL);
""")
W1 = ["Acme","Birch","Cedar","Dune","Elm","Fjord","Grove","Harbor","Iris","Juniper","Kestrel","Lumen","Maple","Nimbus","Orchid","Pillar","Quarry","Ridge","Summit","Tundra"]
W2 = ["Supply","Tools","Freight","Paper","Logistics","Metals","Office","Electric","Textiles","Foods","Marine","Dental","Print","Glass","Timber"]
ACC = ["Caf\u00e9 Lumi\u00e8re","Gr\u00fcn Kaffee GmbH","S\u00f8rensen Marine","Jos\u00e9 Alvarez Imports","Zo\u00eb Textiles","M\u00fcller & S\u00f6hne","Ana\u00efs Papeterie"]  # accented names, kept as escapes so the file stays ASCII
def rnd_dt(start, end):
    d = start + datetime.timedelta(seconds=random.randint(0, int((end-start).total_seconds())))
    return d.strftime("%Y-%m-%d %H:%M:%S")
T0 = datetime.datetime(2023,1,1); T1 = datetime.datetime(2026,8,31,23,59,59)
codes = set(); customers = []
for i in range(4000):
    while True:
        code = "".join(random.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(4)) + "%04d" % random.randint(1, 9999)
        if code not in codes: codes.add(code); break
    name = random.choice(ACC) + " %d" % i if random.random() < 0.02 else "%s %s %d" % (random.choice(W1), random.choice(W2), i)
    r = random.random()
    email = None if r < 0.06 else ("" if r < 0.09 else "%s@example.com" % name.lower().replace(" ", ".").replace("&", "and"))
    archived = 1 if random.random() < 0.04 else 0
    customers.append((code, name, email, archived, rnd_dt(datetime.datetime(2019,1,1), T0)))
c.executemany("INSERT INTO customers(code,name,email,archived,created_at) VALUES (?,?,?,?,?)", customers)
db.commit()
inv_id = 0
for cid, (code, name, email, archived, ccreated) in enumerate(customers, start=1):
    n = random.randint(3, 25)
    for seq in range(1, n+1):
        issued = T0 + datetime.timedelta(days=random.randint(0, (T1-T0).days))
        created = issued + datetime.timedelta(seconds=random.randint(8*3600, 18*3600))
        amt = round(random.uniform(50, 9999.99), 2)
        if random.random() < 0.003: amt = -round(random.uniform(20, 800), 2)   # credit notes
        r = random.random()
        status = "settled" if r < 0.70 else "open" if r < 0.88 else "failed" if r < 0.96 else "void"
        inflight = status == "open" and random.random() < 0.08
        is_paid = 1 if status in ("settled", "failed") or inflight else 0
        sub_time = created + datetime.timedelta(days=random.randint(1, 40), seconds=random.randint(0, 86399)) if is_paid else None
        paid_at = sub_time.strftime("%Y-%m-%d %H:%M:%S") if sub_time else None
        c.execute("INSERT INTO invoices(customer_id,invoice_number,amount,is_paid,paid_at,status,archived,issued_on,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                  (cid, "%s-%04d" % (code, seq), "%.2f" % amt, is_paid, paid_at, status, archived, issued.strftime("%Y-%m-%d"), created.strftime("%Y-%m-%d %H:%M:%S")))
        inv_id += 1
        if is_paid:
            if status == "settled" and random.random() < 0.10:   # a bounce, then a successful retry
                c.execute("INSERT INTO payments(invoice_id,processor_ref,amount,result,created_at) VALUES (?,?,?,?,?)",
                          (inv_id, "PR%09d" % random.randint(1, 10**9), "%.2f" % amt, "returned", (sub_time - datetime.timedelta(days=9)).strftime("%Y-%m-%d %H:%M:%S")))
            result = "settled" if status == "settled" else (random.choice(["returned", "nsf"]) if status == "failed" else None)
            c.execute("INSERT INTO payments(invoice_id,processor_ref,amount,result,created_at) VALUES (?,?,?,?,?)",
                      (inv_id, "PR%09d" % random.randint(1, 10**9), "%.2f" % amt, result, paid_at))
db.commit()
for t in ("customers", "invoices", "payments"):
    print(t, c.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0])
print("in-flight (open + is_paid=1):", c.execute("SELECT COUNT(*) FROM invoices WHERE status='open' AND is_paid=1").fetchone()[0])
print("archived customers:", c.execute("SELECT COUNT(*) FROM customers WHERE archived=1").fetchone()[0])
db.close()
