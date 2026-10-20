"""Manager-only monthly summaries shared by browser preview and CSV export."""

import calendar
import csv
import datetime as dt
import io
import json
import re
from decimal import Decimal, ROUND_HALF_UP
from . import core


def decimal(value, scale=1):
    return format(
        (Decimal(value) / Decimal(scale)).quantize(
            Decimal(".01"), rounding=ROUND_HALF_UP
        ),
        ".2f",
    )


def build(db, user, month, kind):
    core.manager(user)
    if not isinstance(month, str) or not re.fullmatch(r"\d{4}-\d{2}", month):
        raise core.RuleError("请选择有效月份（YYYY-MM）")
    try:
        start = dt.date.fromisoformat(month + "-01")
        last = start.replace(day=calendar.monthrange(start.year, start.month)[1])
    except ValueError:
        raise core.RuleError("月份无效")
    today = dt.date.today()
    if start > today:
        raise core.RuleError("不能导出未来月份")
    if kind not in ("employees", "products"):
        raise core.RuleError("报表类型无效")
    end = min(last, today).isoformat()
    begin = start.isoformat()
    reports = db.execute(
        "SELECT * FROM reports WHERE date BETWEEN ? AND ? ORDER BY date,id",
        (begin, end),
    ).fetchall()
    days = {r["date"] for r in reports}
    days.update(
        r[0]
        for r in db.execute(
            "SELECT date FROM intake_counts WHERE date BETWEEN ? AND ? UNION SELECT date FROM direct_sales WHERE date BETWEEN ? AND ?",
            (begin, end, begin, end),
        )
    )
    inventory = {day: core.inventory(db, day) for day in sorted(days)}
    status_by_day = {
        day: {p["id"]: p["status"] for p in rows} for day, rows in inventory.items()
    }
    if kind == "employees":
        title = "员工月度核算"
        columns = [
            "月份",
            "员工",
            "登录账号",
            "提交天数",
            "计件工作量（分类）",
            "计件工作时长（小时）",
            "计时工作时长（小时）",
            "总工时",
            "计件产值",
            "计时产值",
            "总产值",
            "平均每小时产值",
            "待核对日报数",
        ]
        rows = []
        for u in db.execute(
            "SELECT id,name,username,role FROM users WHERE role!='checker' ORDER BY id"
        ):
            own = [r for r in reports if r["user_id"] == u["id"]]
            if u["role"] == "manager" and not own:
                continue
            piece_amount = timed_minutes = unresolved = 0
            quantities = {}
            for r in own:
                pieces = json.loads(r["pieces"])
                piece_amount += sum(p["price"] * p["quantity"] for p in pieces)
                for p in pieces:
                    key = (p.get("process") or p.get("stage", "finished"), p["unit"])
                    quantities[key] = quantities.get(key, 0) + p["quantity"]
                timed_minutes += sum(t["minutes"] for t in json.loads(r["timed"]))
                unresolved += int(
                    any(
                        status_by_day[r["date"]].get(p["product_id"]) not in ("passed", "na")
                        for p in pieces
                    )
                )
            quantity = (
                "；".join(
                    f"{dict(harvest='采摘',pack='分包',seal='封膜',semi='半成品',finished='成品')[stage]} {qty} {unit}"
                    for (stage, unit), qty in sorted(quantities.items())
                )
                or "—"
            )
            minutes = sum(r["minutes"] for r in own)
            amount = sum(r["amount"] for r in own)
            rows.append(
                [
                    month,
                    u["name"],
                    u["username"],
                    len(own),
                    quantity,
                    decimal(minutes - timed_minutes, 60),
                    decimal(timed_minutes, 60),
                    decimal(minutes, 60),
                    decimal(piece_amount, 100),
                    decimal(amount - piece_amount, 100),
                    decimal(amount, 100),
                    decimal(Decimal(amount) * 60, minutes * 100) if minutes else "",
                    unresolved,
                ]
            )
        note = "成品与半成品的计件绩效都计入；不同工序和单位的工作量分开列出，历史记录保留原分类。按员工汇总已提交日报；未提交日期不推算工时。产值沿用提交时价格，供工资核算参考，不含加班规则、扣款或其他工资项目。待核对数按日报计数。"
    else:
        title = "产品月度产量"
        columns = [
            "月份",
            "产品 / 规格",
            "单位",
            "员工报数合计",
            "实际入库合计（已填）",
            "未入库直售合计",
            "入库 + 直售（已填）",
            "净差额（仅已点货日）",
            "已点货天数",
            "待点货天数",
            "差异天数",
            "需复核天数",
            "直售未登记天数",
            "核对状态",
        ]
        groups = {}
        for day, items in inventory.items():
            for p in items:
                if p["stage"] != "finished":
                    continue
                if (
                    not p["contributors"]
                    and p["actual"] is None
                    and not p["sales_recorded"]
                    and not (p["process_check"] and p["process_check"]["packed"] and not p["process_check"]["sealed"])
                ):
                    continue
                g = groups.setdefault(
                    p["id"],
                    {
                        "name": core.finished_name(p),
                        "unit": p["unit"],
                        "expected": 0,
                        "actual": 0,
                        "sold": 0,
                        "difference": 0,
                        "counted": 0,
                        "pending": 0,
                        "mismatch": 0,
                        "stale": 0,
                        "unrecorded": 0,
                        "unresolved": 0,
                    },
                )
                g["unresolved"] += int(p["status"] != "passed")
                g["expected"] += p["expected"]
                g["sold"] += p["direct_sold"]
                g["unrecorded"] += int(not p["sales_recorded"])
                if p["actual"] is not None:
                    g["actual"] += p["actual"]
                    g["counted"] += 1
                    g["difference"] += p["difference"]
                for status in ("pending", "mismatch", "stale"):
                    g[status] += int((p["actual"] is None) if status == "pending" else p["has_difference"] if status == "mismatch" else p["needs_recount"])
        rows = []
        for g in sorted(groups.values(), key=lambda g: g["name"]):
            issues = g["unresolved"]
            rows.append(
                [
                    month,
                    g["name"],
                    g["unit"],
                    g["expected"],
                    g["actual"] if g["counted"] else "",
                    g["sold"],
                    g["actual"] + g["sold"] if g["counted"] else "",
                    g["difference"] if g["counted"] else "",
                    g["counted"],
                    g["pending"],
                    g["mismatch"],
                    g["stale"],
                    g["unrecorded"],
                    "待核对" if issues else "核对通过",
                ]
            )
        note = "所有成品计入产量，包括单工序成品与封膜成品；半成品不重复计入。实际入库与未入库直售分开统计；合计用于查看当天生产去向，不是仓库结存。有待点货时入库及合计不完整，无点货数据留空。净差额仅统计已点货日期，正负可能抵消，请同时检查差异天数。直售未登记暂按0，按有生产、点货或直售记录的日期统计。"
    # Put the figures used for monthly accounting first in both preview and CSV.
    order = (
        [1, 10, 7, 8, 9, 5, 6, 11, 3, 4, 12]
        if kind == "employees"
        else [1, 4, 5, 6, 13, 3, 7, 8, 9, 10, 11, 12, 2]
    )
    columns = [columns[i] for i in order]
    rows = [[row[i] for i in order] for row in rows]
    return {
        "month": month,
        "kind": kind,
        "title": title,
        "start": begin,
        "end": end,
        "partial": last > today,
        "columns": columns,
        "rows": rows,
        "note": note,
    }


def to_csv(report):
    stream = io.StringIO()
    writer = csv.writer(stream)

    def safe(value):
        return (
            "'" + value
            if isinstance(value, str)
            and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r"))
            else value
        )

    writer.writerow(report["columns"])
    writer.writerows([[safe(v) for v in row] for row in report["rows"]])
    return ("\ufeff" + stream.getvalue()).encode("utf-8")
