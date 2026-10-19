"""Local preview server; bind behind an IT-managed HTTPS reverse proxy for deployment."""

import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import os
import secrets
import sqlite3
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from . import core, monthly, audit_log

WEB = Path(__file__).with_name("web")


class Handler(BaseHTTPRequestHandler):
    def send(
        self,
        status,
        payload,
        content_type="application/json; charset=utf-8",
        cookie=None,
    ):
        body = (
            json.dumps(payload, ensure_ascii=False).encode()
            if isinstance(payload, (dict, list))
            else payload
        )
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def cookie(self, token, age=43200):
        return (
            f"harvest_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={age}"
            + ("; Secure" if self.server.secure else "")
        )

    def session(self, db):
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get("Cookie", ""))
            token = cookies["harvest_session"].value
        except (KeyError, ValueError):
            return None, None
        digest = hashlib.sha256(token.encode()).hexdigest()
        s = db.execute(
            "SELECT * FROM sessions WHERE token=? AND expires>?",
            (digest, int(time.time())),
        ).fetchone()
        return (
            (
                db.execute(
                    "SELECT * FROM users WHERE id=? AND deleted=0", (s["user_id"],)
                ).fetchone(),
                s,
            )
            if s
            else (None, None)
        )

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in (
            "/",
            "/app.js",
            "/style.css",
            "/favicon.svg",
            "/nebo-logo.webp",
            "/nebo-icon.png",
            "/apple-touch-icon.png",
            "/icon-192.png",
            "/icon-512.png",
            "/manifest.webmanifest",
            "/audit.js",
        ):
            name = {"/": "index.html"}.get(parsed.path, parsed.path[1:])
            mime = {
                "html": "text/html",
                "js": "text/javascript",
                "css": "text/css",
                "svg": "image/svg+xml",
                "webp": "image/webp",
                "png": "image/png",
                "webmanifest": "application/manifest+json",
            }[name.split(".")[-1]]
            return self.send(200, (WEB / name).read_bytes(), mime + "; charset=utf-8")
        if parsed.path == "/api/config":
            return self.send(200, {"demo": self.server.demo})
        with core.connect(self.server.database) as db:
            user, session = self.session(db)
            if not user:
                return self.send(401, {"error": "请先登录"})
            try:
                if parsed.path == "/api/audit":
                    db.execute("BEGIN")
                    return self.send(200, audit_log.browse(db, user,
                        {k:v[0] for k,v in parse_qs(parsed.query).items()}))
                if parsed.path in ("/api/monthly", "/api/monthly-export"):
                    query = parse_qs(parsed.query)
                    db.execute("BEGIN")
                    report = monthly.build(
                        db,
                        user,
                        query.get("month", [""])[0],
                        query.get("kind", [""])[0],
                    )
                    if parsed.path == "/api/monthly-export":
                        return self.send(
                            200, monthly.to_csv(report), "text/csv; charset=utf-8"
                        )
                    return self.send(200, report)
                day = core.date(
                    parse_qs(parsed.query).get("date", [dt.date.today().isoformat()])[0]
                )
                # All totals and reconciliation signatures must share one read snapshot.
                db.execute("BEGIN")
                data = core.state(db, user, day)
                if parsed.path == "/api/state":
                    data["csrf"] = session["csrf"]
                    return self.send(200, data)
                if parsed.path == "/api/export":
                    core.manager(user)
                    stream = io.StringIO()
                    writer = csv.writer(stream)
                    writer.writerow(
                        [
                            "日期",
                            "员工",
                            "类型",
                            "产品/备注",
                            "数量",
                            "单位",
                            "计时小时",
                            "单价/时薪",
                            "明细金额",
                            "当天总工时",
                            "当天总金额",
                            "平均每小时产值",
                            "入库核对",
                        ]
                    )

                    def safe(v):
                        return (
                            "'" + v
                            if isinstance(v, str)
                            and v.lstrip().startswith(("=", "+", "-", "@", "\t", "\r"))
                            else v
                        )

                    for r in data["reports"]:
                        suffix = [
                            r["minutes"] / 60,
                            f"{r['amount']/100:.2f}",
                            f"{r['amount']*60/r['minutes']/100:.2f}",
                            r["status"],
                        ]
                        for p in r["pieces"]:
                            writer.writerow(
                                [
                                    safe(v)
                                    for v in [
                                        day,
                                        r["name"],
                                        "计件",
                                        p["product"],
                                        p["quantity"],
                                        p["unit"],
                                        "",
                                        f"{p['price']/100:.2f}",
                                        f"{p['price']*p['quantity']/100:.2f}",
                                        *suffix,
                                    ]
                                ]
                            )
                        elapsed = 0
                        for t in r["timed"]:
                            line_amount = core.money(
                                r["rate"], elapsed + t["minutes"]
                            ) - core.money(r["rate"], elapsed)
                            elapsed += t["minutes"]
                            writer.writerow(
                                [
                                    safe(v)
                                    for v in [
                                        day,
                                        r["name"],
                                        "计时",
                                        t["memo"],
                                        "",
                                        "",
                                        t["minutes"] / 60,
                                        f"{r['rate']/100:.2f}",
                                        f"{line_amount/100:.2f}",
                                        *suffix,
                                    ]
                                ]
                            )
                    return self.send(
                        200,
                        ("\ufeff" + stream.getvalue()).encode(),
                        "text/csv; charset=utf-8",
                    )
                return self.send(404, {"error": "页面不存在"})
            except core.RuleError as e:
                return self.send(400, {"error": str(e)})

    def do_POST(self):
        # Mutations require JSON plus a session-bound CSRF token. Login also checks Origin.
        origin = self.headers.get("Origin")
        expected_origin = self.server.origin or (
            "http://" + self.headers.get("Host", "")
        )
        if origin and origin != expected_origin:
            return self.send(403, {"error": "请求来源不允许"})
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            return self.send(415, {"error": "仅接受 JSON 请求"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 100000:
                return self.send(413, {"error": "请求大小无效"})
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError()
        except (ValueError, UnicodeError):
            return self.send(400, {"error": "请求内容无效"})
        action = self.path.removeprefix("/api/")
        with core.connect(self.server.database) as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                if action == "login":
                    username = core.text(data.get("username"), "登录名", 60)
                    now = int(time.time())
                    key = self.client_address[0] + ":" + username
                    limit = db.execute(
                        "SELECT * FROM login_limits WHERE key=?", (key,)
                    ).fetchone()
                    if limit and limit["expires"] > now and limit["attempts"] >= 10:
                        return self.send(
                            429, {"error": "尝试次数过多，请 15 分钟后重试"}
                        )
                    user = db.execute(
                        "SELECT * FROM users WHERE username=? AND deleted=0", (username,)
                    ).fetchone()
                    if not user or not core.password_ok(
                        data.get("password"), user["password"]
                    ):
                        attempts = (
                            limit["attempts"] + 1
                            if limit and limit["expires"] > now
                            else 1
                        )
                        expires = (
                            limit["expires"]
                            if limit and limit["expires"] > now
                            else now + 900
                        )
                        db.execute(
                            "INSERT INTO login_limits VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET attempts=excluded.attempts,expires=excluded.expires",
                            (key, attempts, expires),
                        )
                        db.commit()
                        return self.send(401, {"error": "账号或密码不正确"})
                    db.execute("DELETE FROM login_limits WHERE key=?", (key,))
                    db.execute("DELETE FROM sessions WHERE expires<=?", (now,))
                    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                    db.execute(
                        "INSERT INTO sessions VALUES(?,?,?,?)",
                        (
                            hashlib.sha256(token.encode()).hexdigest(),
                            user["id"],
                            csrf,
                            now + 43200,
                        ),
                    )
                    db.commit()
                    return self.send(200, {"ok": True}, cookie=self.cookie(token))
                user, session = self.session(db)
                if not user:
                    return self.send(401, {"error": "请先登录"})
                if not secrets.compare_digest(
                    self.headers.get("X-CSRF-Token", ""), session["csrf"]
                ):
                    return self.send(403, {"error": "会话校验失败，请刷新后重试"})
                if action == "logout":
                    db.execute(
                        "DELETE FROM sessions WHERE token=?", (session["token"],)
                    )
                    db.commit()
                    return self.send(200, {"ok": True}, cookie=self.cookie("", 0))
                result = core.mutate(db, user, action, data)
                db.commit()
                return self.send(200, result)
            except core.RuleError as e:
                db.rollback()
                return self.send(400, {"error": str(e)})
            except sqlite3.IntegrityError:
                db.rollback()
                return self.send(
                    409, {"error": "账号、产品名称或当天日报已存在，请刷新确认"}
                )
            except Exception:
                db.rollback()
                import traceback

                traceback.print_exc()
                return self.send(
                    500, {"error": "保存失败，未写入数据。请重试或联系管理员"}
                )


def seed(path):
    with core.connect(path) as db:
        if db.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            # Existing demo accounts keep their credentials and data.
            if not db.execute(
                "SELECT 1 FROM users WHERE username='checker'"
            ).fetchone():
                db.execute(
                    "INSERT INTO users(username,name,role,rate,password) VALUES(?,?,?,?,?)",
                    (
                        "checker",
                        "李点货",
                        "checker",
                        0,
                        core.password_hash("Harvest2026!"),
                    ),
                )
            return
        for username, name, role, rate in [
            ("manager", "陈经理", "manager", 2000),
            ("employee", "林晓", "employee", 1760),
            ("employee2", "王明", "employee", 1850),
            ("checker", "李点货", "checker", 0),
        ]:
            db.execute(
                "INSERT INTO users(username,name,role,rate,password) VALUES(?,?,?,?,?)",
                (username, name, role, rate, core.password_hash("Harvest2026!")),
            )
        today = dt.date.today().isoformat()
        for product, price in [("两磅平菇", 100), ("三磅香菇", 106), ("金针菇", 85)]:
            db.execute(
                "INSERT INTO products(product,price,start_date) VALUES(?,?,?)",
                (product, price, today),
            )
        actor = db.execute("SELECT * FROM users WHERE id=3").fetchone()
        core.save_report(
            db,
            actor,
            {
                "date": today,
                "piece_hours": 6.5,
                "pieces": [
                    {"product_id": 1, "quantity": 5},
                    {"product_id": 2, "quantity": 10},
                ],
                "timed": [{"hours": 1.5, "memo": "接种、上包"}],
            },
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--init-admin", action="store_true")
    parser.add_argument("--db")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    path = args.db or ("data/demo.sqlite3" if args.demo else "data/harvest.sqlite3")
    core.initialize(path)
    if args.demo:
        seed(path)
    if args.init_admin:
        import getpass

        with core.connect(path) as db:
            if db.execute("SELECT 1 FROM users").fetchone():
                raise SystemExit(
                    "Database already has users; use manager account management."
                )
            password = os.environ.get("HARVEST_ADMIN_PASSWORD") or getpass.getpass(
                "Admin password (10+ characters): "
            )
            db.execute(
                "INSERT INTO users(username,name,role,rate,password) VALUES(?,?,?,?,?)",
                ("admin", "管理员", "manager", 0, core.password_hash(password)),
            )
        print("Created admin. Start without --init-admin.")
        return
    with core.connect(path) as db:
        if not db.execute("SELECT 1 FROM users").fetchone():
            raise SystemExit(
                "Run python3 -m harvest.server --init-admin first, or use --demo."
            )
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.database, server.demo = path, args.demo
    server.origin = os.environ.get("HARVEST_ORIGIN")
    server.secure = os.environ.get("HARVEST_SECURE_COOKIE") == "1"
    print(f"Harvest running at http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
