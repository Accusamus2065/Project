"""Domain rules. Money is stored in cents, time in minutes, quantities as integers."""

import datetime as dt
import hashlib
import hmac
import json
import os
import sqlite3
from decimal import Decimal, DecimalException, Inexact, localcontext, ROUND_HALF_UP
from pathlib import Path


class RuleError(Exception):
    pass


def connect(path):
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def initialize(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as db:
        db.executescript(Path(__file__).with_name("schema.sql").read_text())
        columns = {r["name"] for r in db.execute("PRAGMA table_info(lots)")}
        if "deleted" not in columns:
            db.execute("ALTER TABLE lots ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0")
        if "per_box" not in columns:
            db.execute("ALTER TABLE lots ADD COLUMN per_box INTEGER CHECK(per_box > 0)")
        product_columns = {r["name"] for r in db.execute("PRAGMA table_info(products)")}
        if "stage" not in product_columns:
            db.execute(
                "ALTER TABLE products ADD COLUMN stage TEXT NOT NULL DEFAULT 'finished' CHECK(stage IN ('finished','semi'))"
            )
        db.execute("PRAGMA journal_mode=WAL")
        from .migration import upgrade

        upgrade(db)
        product_columns = {r['name'] for r in db.execute('PRAGMA table_info(products)')}
        for column,definition in [('process',"TEXT CHECK(process IN ('harvest','pack','seal'))"),('parent_id','INTEGER REFERENCES products(id)'),('family_name','TEXT')]:
            if column not in product_columns:
                db.execute(f'ALTER TABLE products ADD COLUMN {column} {definition}')
        db.execute("""CREATE TABLE IF NOT EXISTS product_workflows(
            id INTEGER PRIMARY KEY, name TEXT NOT NULL,
            harvest_id INTEGER NOT NULL REFERENCES products(id),
            pack_id INTEGER NOT NULL REFERENCES products(id),
            seal_id INTEGER NOT NULL REFERENCES products(id),
            start_date TEXT NOT NULL, UNIQUE(harvest_id,pack_id,seal_id))""")
        db.execute("CREATE INDEX IF NOT EXISTS audit_at_idx ON audit(at)")
        db.execute("CREATE INDEX IF NOT EXISTS audit_actor_idx ON audit(actor,id)")
        db.execute("CREATE INDEX IF NOT EXISTS audit_action_idx ON audit(action,id)")
        # Only established links prove a process. Never guess the picking source.
        for link in db.execute('SELECT * FROM process_links').fetchall():
            db.execute("UPDATE products SET process='pack' WHERE id=? AND process IS NULL",(link['source_id'],))
            db.execute("UPDATE products SET process='seal',parent_id=? WHERE id=? AND process IS NULL",(link['source_id'],link['target_id']))


def password_hash(password, salt=None):
    if not isinstance(password, str) or not 10 <= len(password) <= 200:
        raise RuleError("密码长度需要为 10–200 个字符")
    salt = salt or os.urandom(16).hex()
    return (
        salt
        + ":"
        + hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt), 600000
        ).hex()
    )


def password_ok(password, encoded):
    try:
        return hmac.compare_digest(
            password_hash(password, encoded.split(":")[0]), encoded
        )
    except (RuleError, ValueError, AttributeError):
        return False


def text(value, label, maximum=120):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise RuleError(f"{label}不能为空，且不能超过 {maximum} 个字符")
    return value.strip()


def number(value, label, scale=1, minimum=0, maximum=10000000):
    try:
        # Never round user input into a different valid quantity or monetary value.
        with localcontext() as context:
            context.traps[Inexact] = True
            n = Decimal(str(value)) * scale
        if (
            not n.is_finite()
            or n != n.to_integral_value()
            or not minimum <= n <= maximum
        ):
            raise ValueError()
        return int(n)
    except (DecimalException, ValueError):
        raise RuleError(f"{label}格式或范围不正确")


def date(value):
    try:
        parsed = dt.date.fromisoformat(value)
        if parsed.isoformat() != value or parsed > dt.date.today():
            raise ValueError()
        return value
    except (ValueError, TypeError):
        raise RuleError("日期无效，不能填写未来日期")


def money(cents, minutes):
    return int(
        (Decimal(cents) * minutes / 60).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


def audit(db, actor, action, detail):
    detail = {
        **detail,
        "actor_name": db.execute(
            "SELECT name FROM users WHERE id=?", (actor,)
        ).fetchone()["name"],
    }
    db.execute(
        "INSERT INTO audit(at,actor,action,detail) VALUES(?,?,?,?)",
        (
            dt.datetime.now(dt.timezone.utc).isoformat(),
            actor,
            action,
            json.dumps(detail, ensure_ascii=False),
        ),
    )


def manager(user):
    if user["role"] != "manager":
        raise RuleError("此操作需要经理权限")


def _work_items(db, day):
    """Compare only this day's reported production with independently counted intake."""
    reports = db.execute(
        "SELECT r.*,u.name FROM reports r JOIN users u ON u.id=r.user_id WHERE date=? ORDER BY r.id",
        (day,),
    ).fetchall()
    # Retiring a finished item must not hide unresolved packing from prior days.
    reported_ids = {p['product_id'] for r in reports for p in json.loads(r['pieces'])}
    pending_targets = {
        target for source, target in db.execute(
            "SELECT source_id,target_id FROM process_links WHERE start_date<=? "
            "UNION SELECT pack_id,seal_id FROM product_workflows WHERE start_date<=?",
            (day, day),
        ) if source in reported_ids
    }
    result = []
    for product in db.execute(
        "SELECT * FROM products WHERE start_date<=? ORDER BY product,id", (day,)
    ):
        contributors = []
        for report in reports:
            qty = sum(
                p["quantity"]
                for p in json.loads(report["pieces"])
                if p["product_id"] == product["id"]
            )
            if qty:
                contributors.append(
                    {"report_id": report["id"], "name": report["name"], "quantity": qty}
                )
        count = db.execute(
            "SELECT c.*,u.name AS counter FROM intake_counts c JOIN users u ON u.id=c.actor WHERE product_id=? AND date=?",
            (product["id"], day),
        ).fetchone()
        sale = db.execute(
            "SELECT s.*,u.name AS recorder FROM direct_sales s JOIN users u ON u.id=s.actor WHERE product_id=? AND date=?",
            (product["id"], day),
        ).fetchone()
        if product["deleted"] and not contributors and not count and not sale and product['id'] not in pending_targets:
            continue
        expected = sum(c["quantity"] for c in contributors)
        signature = hashlib.sha256(
            json.dumps([[c["report_id"], c["quantity"]] for c in contributors]).encode()
        ).hexdigest()
        actual = count["actual"] if count else None
        sold = sale["quantity"] if sale else 0
        reconciled = None if actual is None else actual + sold
        status = (
            "pending"
            if not count
            else (
                "stale"
                if signature != count["signature"]
                else "passed" if reconciled == expected else "mismatch"
            )
        )
        result.append(
            {
                **dict(product),
                "expected": expected,
                "actual": actual,
                "direct_sold": sold,
                "sales_recorded": sale is not None,
                "sales_version": sale["version"] if sale else 0,
                "sales_recorder": sale["recorder"] if sale else None,
                "sales_updated_at": sale["updated_at"] if sale else None,
                "sales_memo": sale["memo"] if sale else "",
                "reconciled": reconciled,
                "difference": None if reconciled is None else reconciled - expected,
                "status": status,
                "signature": signature,
                "version": count["version"] if count else 0,
                "counter": count["counter"] if count else None,
                "updated_at": count["updated_at"] if count else None,
                "contributors": contributors,
            }
        )
    return result


def finished_name(product):
    name = product['product']
    return name[:-3] if product.get('process') == 'seal' and name.endswith('·封膜') else name


def inventory(db, day):
    items = _work_items(db,day)
    by_id = {p['id']:p for p in items}
    checks = process_checks(db,day,items)
    for p in items:
        p['finished_name'] = finished_name(p)
        p['process_check'] = None
        p['intake_status'] = p['status']
        p['expected_intake'] = p['expected']-p['direct_sold']
        if p['stage'] != 'finished':
            p['status'] = 'na'
    for check in checks:
        for tid in check['target_ids']:
            p = by_id.get(tid)
            if not p:
                continue
            p['process_check'] = check
            signature_data = [(i,by_id[i]['signature']) for i in check['source_ids']+check['target_ids'] if i in by_id]
            p['signature'] = hashlib.sha256(json.dumps(signature_data).encode()).hexdigest()
            count = db.execute('SELECT signature FROM intake_counts WHERE product_id=? AND date=?',(tid,day)).fetchone()
            p['intake_status'] = 'pending' if not count else 'stale' if count['signature']!=p['signature'] else 'passed' if p['difference']==0 else 'mismatch'
            # A process discrepancy is visible even before a physical count exists.
            p['status'] = 'mismatch' if check['difference'] else p['intake_status']
    for p in items:
        if p['stage'] != 'finished':
            continue
        check = p['process_check']
        p['needs_recount'] = p['intake_status'] == 'stale'
        p['has_difference'] = bool(check and check['difference']) or (p['actual'] is not None and p['sales_recorded'] and p['difference'] != 0)
        p['missing_records'] = []
        if not p['contributors']:
            p['missing_records'].append('封膜记录')
        if check and not check['packers']:
            p['missing_records'].append('分包记录')
        if p['actual'] is None:
            p['missing_records'].append('点货记录')
        if not p['sales_recorded']:
            p['missing_records'].append('直售登记')
        p['status'] = 'mismatch' if p['has_difference'] else 'stale' if p['needs_recount'] else 'pending' if p['missing_records'] else 'passed'
    for check in checks:
        relevant = [by_id[i]['status'] for i in check['target_ids'] if i in by_id and (by_id[i]['expected'] or by_id[i]['actual'] is not None or by_id[i]['sales_recorded'])]
        linked_status = 'mismatch' if check['difference'] else next((v for v in ('mismatch','stale','pending') if v in relevant),'passed' if relevant else 'pending')
        for sid in check['source_ids']:
            if sid in by_id:
                by_id[sid]['status'] = linked_status
    return items


def process_checks(db, day, inv=None):
    """Same-day employee totals; independent of physical intake checks."""
    items = {r["id"]: r for r in (_work_items(db, day) if inv is None else inv)}
    edges = [tuple(r) for r in db.execute(
        "SELECT source_id,target_id FROM process_links WHERE start_date<=? UNION SELECT pack_id,seal_id FROM product_workflows WHERE start_date<=?", (day,day))]
    # Shared work is a graph: sum each physical work item once per component.
    groups = []
    for source,target in edges:
        connected = [g for g in groups if source in g or target in g]
        group = {source,target}
        for old in connected:
            group.update(old)
            groups.remove(old)
        groups.append(group)
    result = []
    for group in groups:
        sources = sorted({a for a,b in edges if a in group})
        targets = sorted({b for a,b in edges if b in group})
        present = [items[i] for i in group if i in items]
        if not present:
            continue
        a = sum(items.get(i,{}).get('expected',0) for i in sources)
        b = sum(items.get(i,{}).get('expected',0) for i in targets)
        def names(ids):
            return ' + '.join(items.get(i,{}).get('product', db.execute('SELECT product FROM products WHERE id=?',(i,)).fetchone()[0]) for i in ids)
        result.append(dict(id=min(group),source_ids=sources,target_ids=targets,source=names(sources),target=names(targets),unit=present[0]['unit'],
            packed=a,sealed=b,difference=b-a,status='pending' if a==b==0 else 'passed' if a==b else 'mismatch',
            packers=[c for i in sources for c in items.get(i,{}).get('contributors',[])],
            sealers=[c for i in targets for c in items.get(i,{}).get('contributors',[])]))
    return result


def validate_sealer(db, day, uid, pieces, extra_target=None):
    targets = {
        r[0]
        for r in db.execute(
            "SELECT target_id FROM process_links WHERE start_date<=? UNION SELECT id FROM products WHERE process='seal' AND start_date<=?", (day,day)
        )
    }
    if extra_target is not None:
        targets.add(extra_target)
    if not any(p["product_id"] in targets for p in pieces):
        return
    for report in db.execute(
        "SELECT user_id,pieces FROM reports WHERE date=? AND user_id!=?", (day, uid)
    ):
        if any(p["product_id"] in targets for p in json.loads(report["pieces"])):
            raise RuleError(
                "当天封膜已由另一位员工登记，所有封膜项目必须由同一人完成。如登记有误，请先修正原记录。"
            )


def save_process_link(db, user, data):
    manager(user)
    sid = number(data.get("source_id"), "分装项目", minimum=1)
    tid = number(data.get("target_id"), "封膜项目", minimum=1)
    start = date(data.get("start_date"))
    source = db.execute("SELECT * FROM products WHERE id=?", (sid,)).fetchone()
    target = db.execute("SELECT * FROM products WHERE id=?", (tid,)).fetchone()
    if not source or not target or source["deleted"] or target["deleted"]:
        raise RuleError("请选择启用中的分装和封膜项目")
    if source["family_name"] or target["family_name"]:
        raise RuleError("新工序请在添加产品时选择上一道工序")
    if (
        source["stage"] != "semi"
        or target["stage"] != "finished"
        or source["unit"] != target["unit"]
    ):
        raise RuleError(
            "分装必须为半成品、封膜必须为成品，且计量单位相同；筐与盒不能直接关联"
        )
    if start < max(source["start_date"], target["start_date"]):
        raise RuleError("关联启用日期不能早于两个项目的启用日期")
    if db.execute(
        "SELECT 1 FROM process_links WHERE source_id=? OR target_id=?", (sid, tid)
    ).fetchone():
        raise RuleError("该项目已有工序关联，不能重复关联")
    for report in db.execute(
        "SELECT user_id,date,pieces FROM reports WHERE date>=?", (start,)
    ):
        validate_sealer(
            db, report["date"], report["user_id"], json.loads(report["pieces"]), tid
        )
    db.execute(
        "INSERT INTO process_links(source_id,target_id,start_date) VALUES(?,?,?)",
        (sid, tid, start),
    )
    audit(
        db,
        user["id"],
        "process_link",
        {
            "source": source["product"],
            "target": target["product"],
            "unit": source["unit"],
            "start_date": start,
        },
    )
    return {"ok": True}


def save_count(db, user, data):
    if user["role"] not in ("manager", "checker"):
        raise RuleError("此操作需要点货员或经理权限")
    day = date(data.get("date"))
    pid = number(data.get("product_id"), "产品", minimum=1)
    row = next((r for r in inventory(db, day) if r["id"] == pid), None)
    if not row:
        raise RuleError("产品或日期无效")
    if row["stage"] != "finished":
        raise RuleError("只对成品点货，采摘和分包无需单独点货")
    if data.get("version") != row["version"]:
        raise RuleError("点货记录已更新，请刷新后重试")
    if data.get("signature") != row["signature"]:
        raise RuleError("员工提交数据已变化，请刷新后重新确认当天点货数量")
    old = db.execute(
        "SELECT * FROM intake_counts WHERE product_id=? AND date=?", (pid, day)
    ).fetchone()
    reason = text(data.get("reason"), "修改原因", 500) if old else ""
    if data.get('confirm_unchanged'):
        if not old or not row['needs_recount']:
            raise RuleError('当前点货记录无需复点确认，请刷新后查看')
        actual = old['actual']
        if 'actual' in data and number(data['actual'], '当天实点数量') != actual:
            raise RuleError('数量发生变化，请使用修改点货数量')
    else:
        actual = number(data.get("actual"), "当天实点数量")
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    db.execute(
        "INSERT INTO intake_counts(product_id,date,actual,actor,updated_at,signature) VALUES(?,?,?,?,?,?) ON CONFLICT(product_id,date) DO UPDATE SET actual=excluded.actual,actor=excluded.actor,updated_at=excluded.updated_at,signature=excluded.signature,version=intake_counts.version+1",
        (pid, day, actual, user["id"], now, row["signature"]),
    )
    audit(
        db,
        user["id"],
        "intake_count",
        {
            "product": row["product"],
            "unit": row["unit"],
            "stage": row["stage"],
            "date": day,
            "reason": reason,
            "before": dict(old) if old else None,
            "after": {"actual": actual},
            "confirmed_unchanged": bool(data.get("confirm_unchanged")),
            "expected": row["expected"],
        },
    )
    return {"ok": True}


def save_direct_sale(db, user, data):
    manager(user)
    day = date(data.get("date"))
    pid = number(data.get("product_id"), "产品", minimum=1)
    row = next((r for r in inventory(db, day) if r["id"] == pid), None)
    if not row:
        raise RuleError("产品或日期无效")
    if row["stage"] != "finished":
        raise RuleError("未入库直售仅用于成品，半成品请独立点货")
    if data.get("version") != row["sales_version"]:
        raise RuleError("直售记录已更新，请刷新后重试")
    quantity = number(data.get("quantity"), "当天直接售出未入库数量")
    memo = text(data.get("memo"), "售货说明", 500)
    old = db.execute(
        "SELECT * FROM direct_sales WHERE product_id=? AND date=?", (pid, day)
    ).fetchone()
    reason = text(data.get("reason"), "修改原因", 500) if old else ""
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    db.execute(
        "INSERT INTO direct_sales(product_id,date,quantity,memo,actor,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(product_id,date) DO UPDATE SET quantity=excluded.quantity,memo=excluded.memo,actor=excluded.actor,updated_at=excluded.updated_at,version=direct_sales.version+1",
        (pid, day, quantity, memo, user["id"], now),
    )
    audit(
        db,
        user["id"],
        "direct_sale",
        {
            "product": row["product"],
            "unit": row["unit"],
            "stage": row["stage"],
            "date": day,
            "reason": reason,
            "before": dict(old) if old else None,
            "after": {"quantity": quantity, "memo": memo},
        },
    )
    return {"ok": True}


def save_report(db, actor, data):
    if actor["role"] not in ("manager", "employee"):
        raise RuleError("点货员请使用当天入库点货入口")
    day = date(data.get("date"))
    uid = number(data.get("user_id", actor["id"]), "员工", minimum=1)
    if uid != actor["id"]:
        manager(actor)
    employee = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not employee or employee["role"] == "checker":
        raise RuleError("员工不存在")
    old = db.execute(
        "SELECT * FROM reports WHERE user_id=? AND date=?", (uid, day)
    ).fetchone()
    if old:
        reason = text(data.get("reason"), "修改原因", 500)
        if data.get("version") != old["version"]:
            raise RuleError("记录已更新，请刷新后重试")
    else:
        reason = ""
    piece_minutes = (
        number(data["piece_hours"], "计件工时", 60, 0, 1440)
        if "piece_hours" in data
        else None
    )
    minutes = (
        number(data.get("hours"), "当天总工时", 60, 1, 1440)
        if piece_minutes is None
        else None
    )
    pieces, timed = data.get("pieces", []), data.get("timed", [])
    if (
        not isinstance(pieces, list)
        or not isinstance(timed, list)
        or len(pieces) + len(timed) > 100
    ):
        raise RuleError("工作明细格式错误或超过 100 项")
    if not pieces and not timed:
        raise RuleError("至少填写一项计件或计时工作")
    saved, seen, total = [], set(), 0
    historical = (
        {
            p.get("snapshot_id", str(p["product_id"])): p
            for p in json.loads(old["pieces"])
        }
        if old
        else {}
    )
    for p in pieces:
        if not isinstance(p, dict):
            raise RuleError("计件明细格式错误")
        pid = number(p.get("product_id"), "产品", minimum=1)
        product = db.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
        key = str(p.get("snapshot_id", pid))
        previous = historical.get(key)
        if previous and previous["product_id"] != pid:
            previous = None
        matches = [(k, v) for k, v in historical.items() if v["product_id"] == pid]
        if matches and previous is None:
            if len(matches) != 1:
                raise RuleError("历史产品明细不明确，请刷新后重试")
            key, previous = matches[0]
        elif not matches:
            key = str(pid)
        if (
            not product
            or day < product["start_date"]
            or (product["deleted"] and previous is None)
        ):
            raise RuleError("产品不存在、未启用或已停用")
        if key in seen or (
            any(r["product_id"] == pid for r in saved)
            and not (
                previous
                and all(
                    r.get("snapshot_id") in historical
                    for r in saved
                    if r["product_id"] == pid
                )
            )
        ):
            raise RuleError("同一产品不能重复填写")
        seen.add(key)
        qty = number(p.get("quantity"), "计件数量", minimum=1)
        snapshot = previous or dict(product)
        saved.append(
            {
                "product_id": pid,
                "snapshot_id": key,
                "product": snapshot["product"],
                "unit": snapshot["unit"],
                "stage": snapshot.get("stage", "finished"),
                "process": snapshot.get("process"),
                "price": snapshot["price"],
                "quantity": qty,
            }
        )
        total += qty * snapshot["price"]
    validate_sealer(db, day, uid, saved)
    rate = old["rate"] if old else employee["rate"]
    saved_time, timed_minutes = [], 0
    for t in timed:
        if not isinstance(t, dict):
            raise RuleError("计时明细格式错误")
        m = number(t.get("hours"), "计时工作小时数", 60, 1, 1440)
        memo = text(t.get("memo"), "计时工作备注", 500)
        saved_time.append({"minutes": m, "memo": memo})
        timed_minutes += m
    if piece_minutes is not None:
        minutes = piece_minutes + timed_minutes
        if not 1 <= minutes <= 1440:
            raise RuleError("当天总工时必须大于 0 且不超过 24 小时")
    if timed_minutes > minutes:
        raise RuleError("计时工作不能超过当天总工时（总工时需包含计件与计时工作）")
    total += money(rate, timed_minutes)
    values = (
        minutes,
        rate,
        json.dumps(saved_time, ensure_ascii=False),
        json.dumps(saved, ensure_ascii=False),
        total,
    )
    if old:
        db.execute(
            "UPDATE reports SET minutes=?,rate=?,timed=?,pieces=?,amount=?,version=version+1 WHERE id=?",
            (*values, old["id"]),
        )
    else:
        db.execute(
            "INSERT INTO reports(minutes,rate,timed,pieces,amount,user_id,date) VALUES(?,?,?,?,?,?,?)",
            (*values, uid, day),
        )
    audit(
        db,
        actor["id"],
        "修改日报" if old else "提交日报",
        {
            "user_id": uid,
            "user_name": employee["name"],
            "date": day,
            "reason": reason,
            "before": dict(old) if old else None,
            "after": {
                "minutes": minutes,
                "rate": rate,
                "timed": saved_time,
                "pieces": saved,
                "amount": total,
            },
        },
    )
    return {"amount": total, "efficiency": round(total * 60 / minutes, 2)}


def save_workflow(db, user, data):
    manager(user)
    name = text(data.get('name'), '成品名称', 80)
    start = date(data.get('start_date'))
    steps = data.get('steps')
    if not isinstance(steps, dict) or set(steps) != {'harvest','pack','seal'}:
        raise RuleError('请完整设置采摘、分包、封膜三道工序')
    chosen = {}
    db.execute('SAVEPOINT create_workflow')
    try:
        for process,label in [('harvest','采摘'),('pack','分包'),('seal','封膜')]:
            value = steps[process]
            if not isinstance(value,dict):
                raise RuleError('工序设置无效')
            if value.get('mode') == 'existing':
                if set(value) != {'mode','id'}:
                    raise RuleError('引用已有工序时不能同时创建或修改名称、单位、单价')
                row = db.execute('SELECT * FROM products WHERE id=?',(number(value.get('id'),'已有工序',minimum=1),)).fetchone()
                if not row or row['deleted'] or row['process'] != process:
                    raise RuleError('只能选择同级且启用中的已有工序')
                if row['start_date'] > start:
                    raise RuleError('流程启用日期不能早于引用的工序')
                chosen[process] = dict(row)
            elif value.get('mode') == 'new':
                if value.get('id'):
                    raise RuleError('新建和选择已有工序不能同时使用')
                base = text(value.get('name'),label+'名称',80)
                unit = text(value.get('unit'),'单位',12)
                price = number(value.get('price'),'计件单价',100)
                full = base+'·'+label
                if db.execute('SELECT 1 FROM products WHERE product=? AND unit=?',(full,unit)).fetchone():
                    raise RuleError(full+'已存在，请选择 选择已有工序 或使用不同名称')
                rid = db.execute('INSERT INTO products(product,unit,price,start_date,stage,process,family_name) VALUES(?,?,?,?,?,?,?)',
                    (full,unit,price,start,'finished' if process=='seal' else 'semi',process,name)).lastrowid
                chosen[process] = dict(db.execute('SELECT * FROM products WHERE id=?',(rid,)).fetchone())
            else:
                raise RuleError('请选择 新建工序 或 选择已有工序')
        if chosen['pack']['unit'] != chosen['seal']['unit']:
            raise RuleError('分包与封膜单位必须相同，才能按 1:1 核对')
        ids = [chosen[k]['id'] for k in ('harvest','pack','seal')]
        if db.execute('SELECT 1 FROM product_workflows WHERE harvest_id=? AND pack_id=? AND seal_id=?',ids).fetchone():
            raise RuleError('这组三道工序已经建立流程')
        rid = db.execute('INSERT INTO product_workflows(name,harvest_id,pack_id,seal_id,start_date) VALUES(?,?,?,?,?)',(name,*ids,start)).lastrowid
        audit(db,user['id'],'workflow',{'name':name,'start_date':start,'steps':list(chosen.values())})
        db.execute('RELEASE create_workflow')
        return {'ok':True,'id':rid}
    except Exception:
        db.execute('ROLLBACK TO create_workflow')
        db.execute('RELEASE create_workflow')
        raise


def mutate(db, user, action, data):
    if action == "workflow":
        return save_workflow(db,user,data)
    if action == "process_link":
        return save_process_link(db, user, data)
    if action == "report":
        return save_report(db, user, data)
    if action == "direct_sale":
        return save_direct_sale(db, user, data)
    if action == "intake_count":
        return save_count(db, user, data)
    if action in ("shipment", "shipment_void", "count", "lot", "lot_delete"):
        raise RuleError("旧库存与批次功能已停用，请使用产品和当天入库点货")
    manager(user)
    before = None
    if action in ("user", "product", "product_delete") and data.get("id"):
        table, columns = (
            ("users", "id,username,name,role,rate")
            if action == "user"
            else ("products", "*")
        )
        old = db.execute(
            f"SELECT {columns} FROM {table} WHERE id=?",
            (number(data["id"], "记录", minimum=1),),
        ).fetchone()
        before = dict(old) if old else None
    if action == "user":
        name = text(data.get("name"), "姓名")
        rate = number(data.get("rate"), "时薪", 100)
        if data.get("id"):
            uid = number(data["id"], "员工", minimum=1)
            old = db.execute(
                "SELECT id,name,rate FROM users WHERE id=?", (uid,)
            ).fetchone()
            if not old:
                raise RuleError("员工不存在")
            db.execute("UPDATE users SET name=?,rate=? WHERE id=?", (name, rate, uid))
            if data.get("password"):
                db.execute(
                    "UPDATE users SET password=? WHERE id=?",
                    (password_hash(data["password"]), uid),
                )
                db.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        else:
            username = text(data.get("username"), "登录名", 60)
            role = data.get("role", "employee")
            if role not in ("employee", "manager", "checker"):
                raise RuleError("角色无效")
            db.execute(
                "INSERT INTO users(username,name,role,rate,password) VALUES(?,?,?,?,?)",
                (username, name, role, rate, password_hash(data.get("password"))),
            )
    elif action == "product":
        price = number(data.get("price"), "计件单价", 100)
        if data.get("id"):
            if not before or before["deleted"]:
                raise RuleError("产品不存在或已停用")
            if any(
                key in data and data[key] != before[key] for key in ("stage", "unit", "process", "parent_id", "family_name")
            ):
                raise RuleError(
                    "工序、关联和单位创建后不可更改，请建立新项目以保留历史核算"
                )
            db.execute("UPDATE products SET price=? WHERE id=?", (price, before["id"]))
        else:
            process=data.get('process')
            names={'harvest':'采摘','pack':'分包','seal':'封膜'}
            if process not in names:
                raise RuleError('请选择采摘、分包或封膜工序')
            start=date(data.get('start_date'))
            parent=None
            if process!='harvest':
                parent_id=number(data.get('parent_id'),'上一道工序',minimum=1)
                parent=db.execute('SELECT * FROM products WHERE id=?',(parent_id,)).fetchone()
                expected='harvest' if process=='pack' else 'pack'
                if not parent or parent['deleted'] or parent['process']!=expected or not parent['family_name']:
                    raise RuleError('请选择有效且启用中的上一道工序；历史未整理项目请重新建立完整流程')
                if start<parent['start_date']:
                    raise RuleError('启用日期不能早于上一道工序')
                family=parent['family_name']
                if db.execute('SELECT 1 FROM products WHERE parent_id=?',(parent_id,)).fetchone():
                    raise RuleError('上一道工序已经有后续项目，请勿重复创建；不同规格请建立独立流程')
            else:
                if data.get('parent_id'):
                    raise RuleError('采摘没有上一道工序')
                family=text(data.get('product'),'蘑菇名称与规格',80)
            unit=text(data.get('unit','筐' if process=='harvest' else '盒'),'计量单位',12)
            if process=='seal' and unit!=parent['unit']:
                raise RuleError('封膜单位必须与分包相同，才能按 1:1 核对')
            stage='finished' if process=='seal' else 'semi'
            if 'stage' in data and data['stage']!=stage:
                raise RuleError('类型由工序决定，不能手动修改')
            rid=db.execute('INSERT INTO products(product,price,start_date,stage,unit,process,parent_id,family_name) VALUES(?,?,?,?,?,?,?,?)',
                (family+'·'+names[process],price,start,stage,unit,process,parent['id'] if parent else None,family)).lastrowid
            if process=='seal':
                db.execute('INSERT INTO process_links(source_id,target_id,start_date) VALUES(?,?,?)',(parent['id'],rid,start))
            # Explicit id: adding a link also changes SQLite last_insert_rowid().
            data={**data,'id':rid}
    elif action == "product_delete":
        if not before or before["deleted"]:
            raise RuleError("产品不存在或已停用")
        if data.get('confirm_name') != before['product']:
            raise RuleError('请输入完整项目名称以确认停用')
        if db.execute('SELECT 1 FROM products WHERE parent_id=? AND deleted=0',(before['id'],)).fetchone():
            raise RuleError('请先停用下一道工序，再停用此项目')
        if db.execute("""SELECT 1 FROM product_workflows w JOIN products p ON
            (w.harvest_id=? AND p.id IN (w.pack_id,w.seal_id)) OR (w.pack_id=? AND p.id=w.seal_id)
            WHERE p.deleted=0""",(before['id'],before['id'])).fetchone():
            raise RuleError('该工序仍有启用中的后续项目，请先停用所有相关后续工序')
        db.execute("UPDATE products SET deleted=1 WHERE id=?", (before["id"],))
    else:
        raise RuleError("未知操作")
    table, columns = (
        ("users", "id,username,name,role,rate")
        if action == "user"
        else ("products", "*")
    )
    rid = data.get("id") or db.execute("SELECT last_insert_rowid()").fetchone()[0]
    after = dict(
        db.execute(f"SELECT {columns} FROM {table} WHERE id=?", (rid,)).fetchone()
    )
    audit(
        db,
        user["id"],
        action,
        {
            "format": 2,
            "before": before,
            "after": after,
            "password_reset": bool(data.get("password")) and before is not None,
        },
    )
    return {"ok": True}


def state(db, user, day):
    is_manager = user["role"] == "manager"
    inv = inventory(db, day)
    public_user = {k: user[k] for k in ("id", "name", "username", "role", "rate")}
    if user["role"] == "checker":
        public_user.pop("rate")
        return {
            "user": public_user,
            "date": day,
            "products": [],
            "reports": [],
            "users": [],
            "audit": [],
            "inventory": [
                {
                    k: r[k]
                    for k in (
                        "id",
                        "product",
                        "unit",
                        "stage",
                        "process",
                        "actual",
                        "signature",
                        "version",
                        "counter",
                        "updated_at",
                    )
                }
                | {
                    "product": r["finished_name"],
                    "status": (
                        "pending"
                        if r["actual"] is None
                        else "stale" if r["intake_status"] == "stale" else "recorded"
                    )
                }
                for r in inv if r["stage"] == "finished"
            ],
        }
    query = (
        "SELECT r.*,u.name FROM reports r JOIN users u ON u.id=r.user_id WHERE r.date=?"
    )
    params = [day]
    if not is_manager:
        query += " AND r.user_id=?"
        params.append(user["id"])
    reports = []
    for r in db.execute(query + " ORDER BY r.id", params):
        r = dict(r)
        r["pieces"], r["timed"] = json.loads(r["pieces"]), json.loads(r["timed"])
        for p in r["pieces"]:
            p.pop("code", None)
            p.pop("lot_id", None)
        statuses = [
            i["status"]
            for i in inv
            if i["id"] in [p["product_id"] for p in r["pieces"]]
        ]
        r["status"] = (
            next(
                (s for s in ("mismatch", "stale", "pending") if s in statuses), "passed"
            )
            if any(status != "na" for status in statuses)
            else "na"
        )
        reports.append(r)
    return {
        "workflows": [dict(r) for r in db.execute("SELECT * FROM product_workflows ORDER BY id")] if is_manager else [],
        "process_checks": process_checks(db, day, inv) if is_manager else [],
        "process_links": (
            [
                dict(r)
                for r in db.execute(
                    "SELECT l.*,s.product AS source,t.product AS target,s.unit FROM process_links l JOIN products s ON s.id=l.source_id JOIN products t ON t.id=l.target_id"
                )
            ]
            if is_manager
            else []
        ),
        "user": public_user,
        "date": day,
        "products": [
            dict(r) for r in db.execute("SELECT * FROM products ORDER BY product,id")
        ],
        "reports": reports,
        "inventory": [{**p,"product":p["finished_name"]} for p in inv if p["stage"]=="finished"] if is_manager else [],
        "users": (
            [
                dict(r)
                for r in db.execute(
                    "SELECT id,name,username,role,rate FROM users ORDER BY id"
                )
            ]
            if is_manager
            else []
        ),
        "audit": (
            [
                dict(r)
                for r in db.execute(
                    "SELECT a.*,u.name FROM audit a JOIN users u ON u.id=a.actor ORDER BY a.id DESC LIMIT 100"
                )
            ]
            if is_manager
            else []
        ),
    }
