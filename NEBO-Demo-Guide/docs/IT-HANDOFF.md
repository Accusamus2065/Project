> 2026-10-07 更新：当前业务为员工按产品报产量、点货员登记当天实际入库、经理核对。旧出库和库存结存功能已停用；升级步骤及角色说明见 [入库版技术说明](INCOMING-V2.md)。下文中旧业务验收项以新说明为准。

# IT 交接说明（MVP）

## 交付范围

提供源码、数据库结构、测试、运行与交接说明。公司 IT 负责正式部署、HTTPS、服务器/操作系统维护、账户运行管理、备份恢复和运行费用。本地演示并不代表生产部署验收完成。

## 运行环境

Python 3.11+，标准库，无第三方包。SQLite 适用于当前小团队单实例场景，数据必须存放在本机持久磁盘；不要放到网络共享盘或运行多个独立数据库副本。当前 HTTP 服务使用 Python 标准库，作为 MVP/本地验证入口；正式上线前 IT 应评估受控内网规模及生产服务适配、反向代理和进程监管，不应直接暴露该端口到公网。

## 正式数据库初始化

在项目工作目录：

```sh
python3 -m harvest.server --init-admin
```

按提示设置 10 位以上管理员密码，账号为 `admin`。密码不会回显；已有账号的数据库不会重新初始化管理员。也可通过部署系统注入 `HARVEST_ADMIN_PASSWORD` 完成首次初始化，之后删除该环境变量。请不要把密码写入源码、命令行参数或 Git。

```sh
python3 -m harvest.server --db /absolute/persistent/path/harvest.sqlite3 --init-admin
```

为自定义路径初始化后，后续启动使用同一个 `--db` 路径。默认正式数据库为 `data/harvest.sqlite3`；演示数据库为 `data/demo.sqlite3`。正式实例不要使用 `--demo`。

## 服务与反向代理

```sh
HARVEST_ORIGIN=https://harvest.company.example HARVEST_SECURE_COOKIE=1 \
python3 -m harvest.server --db /absolute/persistent/path/harvest.sqlite3 --host 127.0.0.1 --port 8765
```

域名是占位示例，替换为 IT 管理的正式地址。由反向代理终结 HTTPS 并转发到 loopback 端口；不要从客户端信任任意代理头。通过进程管理器设置工作目录、重启策略、日志轮转和最小权限账号。操作系统时区设为公司的业务时区，页面日期使用访问设备本地时间，应保持一致。

现有保护：PBKDF2-SHA256（600,000 次）随机盐密码哈希；数据库仅保存会话 token 的哈希；12 小时会话；HttpOnly/SameSite Cookie；HTTPS 模式 Secure Cookie；Origin 校验；写接口 CSRF；登录尝试限流；服务端角色权限；参数化 SQL；输出转义；CSV 公式注入防护；请求大小限制；同源 CSP。

经理可以重设密码，重设后该账号所有会话失效。当前未实现 MFA、账号停用、自动密码找回、全局登录限流清理、外部 SSO 或完整的账户生命周期；IT 应结合实际访问范围确定正式版本所需措施。

## 备份与恢复

使用 SQLite 在线备份接口，而不是在服务运行时只复制主数据库文件（WAL 模式还有附属文件）。例如：

```sh
python3 - <<'PY'
import sqlite3
from pathlib import Path
from datetime import datetime
Path('backups').mkdir(exist_ok=True)
source = sqlite3.connect('data/harvest.sqlite3')
target = sqlite3.connect('backups/harvest-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.sqlite3')
source.backup(target)
target.close()
source.close()
PY
```

示例使用默认正式数据库；如自定义 `--db`，修改备份源路径。IT 配置备份周期、异地保存、访问控制和保留期限。恢复演练：停止服务，将备份还原到一个新的文件路径，运行 `PRAGMA integrity_check`，使用新的 `--db` 启动，验证员工、日报与库存。不要直接在运行中的数据库路径覆盖文件。

## 上线验收

1. 用实际样本验证单价、计量单位、个人时薪、取整规则和总工时。
2. 核对起始库存日期与数量；确认按 Lot 对账符合现场流程。
3. 两个员工账号各自只能看到本人日报；经理可查看所有人员、盘点与导出。
4. 使用两台设备验证并发提交、重复提交、旧版本修正被拒绝，以及重启后数据仍在。
5. 核对输出报表模板；业务方确认 CSV 能满足当前阶段要求。
6. 完成正式 HTTPS、日志监控、备份恢复演练及故障联系人交接。

## 已知容量边界

当前库存统计从日报与出库流水重算，历史修正会检查全部业务日期。适用于初期小团队验证，尚未进行多年数据、大并发压测。扩大规模前需要基于实测优化库存流水/汇总查询，并建立数据库迁移版本机制。审计日志保留在同一数据库中，页面展示最近 100 条，不是不可篡改的外部审计系统。
