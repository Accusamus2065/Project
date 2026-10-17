# 自行部署与维护说明

本文供项目维护者自行部署和维护使用。服务器账号、域名配置、HTTPS、备份和运行费用由项目负责人管理，不再依赖原 IT 团队。当前尚未完成正式上线；以下是运行与数据维护说明，不代表服务器已经配置完成。

当前操作手册见 [README](../README.md)，业务演进与迁移记录见 [技术说明](INCOMING-V2.md)。

## 运行环境

Python 3.11+，标准库，无第三方包。SQLite 适用于当前小团队单实例场景，数据必须存放在本机持久磁盘；不要放到网络共享盘或运行多个独立数据库副本。当前 HTTP 服务使用 Python 标准库，作为 MVP/本地验证入口；正式上线前应评估受控内网规模及生产服务适配、反向代理和进程监管，不应直接暴露该端口到公网。

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

域名是占位示例，替换为自己配置的正式地址。由反向代理终结 HTTPS 并转发到 loopback 端口；不要从客户端信任任意代理头。通过进程管理器设置工作目录、重启策略、日志轮转和最小权限账号。操作系统时区设为公司的业务时区，页面日期使用访问设备本地时间，应保持一致。

现有保护：PBKDF2-SHA256（600,000 次）随机盐密码哈希；数据库仅保存会话 token 的哈希；12 小时会话；HttpOnly/SameSite Cookie；HTTPS 模式 Secure Cookie；Origin 校验；写接口 CSRF；登录尝试限流；服务端角色权限；参数化 SQL；输出转义；CSV 公式注入防护；请求大小限制；同源 CSP。

经理可以重设密码，重设后该账号所有会话失效。当前未实现 MFA、账号停用、自动密码找回、全局登录限流清理、外部 SSO 或完整的账户生命周期；应结合实际访问范围确定正式版本所需措施。

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

示例使用默认正式数据库；如自定义 `--db`，修改备份源路径。自行配置备份周期、异地保存、访问控制和保留期限。恢复演练：停止服务，将备份还原到一个新的文件路径，运行 `PRAGMA integrity_check`，使用新的 `--db` 启动，验证员工、日报与库存。不要直接在运行中的数据库路径覆盖文件。

## 上线检查

1. 使用新的正式数据库和正式账号，不使用演示模式或演示密码。
2. 验证员工、点货员、经理各自的权限及手机操作。
3. 验证分包合计等于封膜合计，封膜减未入库直售等于点货数量；产量只统计成品。
4. 使用两台设备验证并发提交、重复提交、旧版本修正被拒绝，以及服务重启后数据仍在。
5. 检查员工月度核算与成品月度产量导出。
6. 配置 HTTPS、进程自动重启、日志轮转和磁盘监测；实际执行一次数据库备份恢复。

## 容量与后续维护

当前采用单实例 SQLite，数据库应保存在服务器持久磁盘中。操作记录完整保留，页面分页查询；分页不会删除历史。扩大使用规模前应以实际数据量和同时提交人数进行压测，再决定是否需要升级服务器或数据库。定期检查磁盘容量、备份可用性及系统更新，给备份设置保留期限。
