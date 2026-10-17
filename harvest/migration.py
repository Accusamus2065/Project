"""Idempotent migration from lot/closing-stock reports to product/day intake."""

import json


def upgrade(db):
    sql = db.execute("SELECT sql FROM sqlite_master WHERE name='users'").fetchone()[0]
    if "'checker'" not in sql:
        db.commit()
        db.execute("PRAGMA foreign_keys=OFF")
        try:
            with db:
                db.execute("BEGIN")
                db.execute(
                    "CREATE TABLE users_new(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('manager','employee','checker')), rate INTEGER NOT NULL CHECK(rate >= 0), password TEXT NOT NULL)"
                )
                db.execute("INSERT INTO users_new SELECT * FROM users")
                db.execute("DROP TABLE users")
                db.execute("ALTER TABLE users_new RENAME TO users")
        finally:
            db.execute("PRAGMA foreign_keys=ON")
    with db:
        for lot in db.execute("SELECT * FROM lots ORDER BY start_date,id").fetchall():
            if db.execute(
                "SELECT 1 FROM legacy_products WHERE lot_id=?", (lot["id"],)
            ).fetchone():
                continue
            product = db.execute(
                "SELECT * FROM products WHERE product=? AND unit=?",
                (lot["product"], lot["unit"]),
            ).fetchone()
            if product:
                pid = product["id"]
                # The latest active legacy lot supplies the initial current price.
                if not lot["deleted"]:
                    db.execute(
                        "UPDATE products SET price=?,deleted=0,start_date=MIN(start_date,?) WHERE id=?",
                        (lot["price"], lot["start_date"], pid),
                    )
            else:
                pid = db.execute(
                    "INSERT INTO products(product,unit,price,start_date,deleted) VALUES(?,?,?,?,?)",
                    (
                        lot["product"],
                        lot["unit"],
                        lot["price"],
                        lot["start_date"],
                        lot["deleted"],
                    ),
                ).lastrowid
            db.execute(
                "INSERT INTO legacy_products(lot_id,product_id) VALUES(?,?)",
                (lot["id"], pid),
            )
        mapping = dict(
            db.execute("SELECT lot_id,product_id FROM legacy_products").fetchall()
        )
        for report in db.execute("SELECT id,pieces FROM reports").fetchall():
            pieces = json.loads(report["pieces"])
            changed = False
            for p in pieces:
                if "product_id" not in p:
                    p["product_id"] = mapping[p["lot_id"]]
                    p["snapshot_id"] = "legacy-" + str(p["lot_id"])
                    changed = True
            if changed:
                db.execute(
                    "UPDATE reports SET pieces=? WHERE id=?",
                    (json.dumps(pieces, ensure_ascii=False), report["id"]),
                )
        if db.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("数据库关联检查失败，迁移已停止")
