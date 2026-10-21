# 自行部署与维护说明

本文供项目维护者自行部署和维护使用。服务器账号、域名配置、HTTPS、备份和运行费用由项目负责人管理，不再依赖原 IT 团队。当前尚未完成正式上线；以下是运行与数据维护说明，不代表服务器已经配置完成。

当前操作手册见 [README](../README.md)，当前技术与迁移说明见 [技术说明](TECHNICAL-README.md)。

## 运行环境

Python 3.11+；正式入口使用 requirements.txt 固定版本的 Waitress，业务逻辑仍使用标准库。SQLite 适用于当前小团队单实例场景，数据必须存放在本机持久磁盘；不要放到网络共享盘或运行多个独立数据库副本。本地预览可使用 harvest.server；Render 使用 harvest.production，由 Waitress 处理 HTTP、Render 终结 HTTPS。正式接收业务数据前仍需配置异地自动备份并完成恢复验收。

## Render 配置

- Language：Python 3；Branch：main；Root Directory：留空。
- Build Command：`pip install -r requirements.txt`
- Start Command：`python -m harvest.production`
- Health Check Path：`/healthz`
- Pre-Deploy Command：留空，磁盘仅在运行时可访问；初始化在启动入口执行。
- Auto-Deploy：初次上线先关闭，验证代码后手动部署。
- 正式实例：付费 Compute，磁盘 Mount Path `/var/data`，数据库路径 `/var/data/harvest.sqlite3`。仅一个实例。
- 环境变量 `TZ`：工厂实际业务时区（多伦多为 `America/Toronto`）。
- 环境变量 `HARVEST_ADMIN_PASSWORD`：首次启动的管理员密码，至少 10 位，单独生成并保存；账号为 `admin`。已有用户时不会覆盖密码，首次成功后删除此变量并重新部署。
- `HARVEST_ORIGIN`：使用 Render 默认网址时不必填写，自动读取 `RENDER_EXTERNAL_URL`；使用自定义域名后填写完整 HTTPS 来源，不带路径。
- Secure Cookie 在正式入口中自动启用。不能用 HTTP 浏览器地址验收登录会话。

免费临时试用必须显式设置 `HARVEST_ALLOW_EPHEMERAL=1` 和 `HARVEST_DB=/tmp/nebo-trial.sqlite3`，不添加磁盘；重启、休眠、重新部署可能丢失全部数据，只能用于非正式测试。试用期间保留初始化密码变量，以便临时数据库丢失后重新创建管理员。升级正式服务时删除临时存储开关，把数据库路径改为持久化目录，按全新正式数据库初始化；不要假设试用数据会自动迁移。

已在本地测试实际 Waitress 启动、健康检查、登录、首次初始化及删除初始化密码后的重启；尚未完成 Render 线上验收与自动异地备份。

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

经理可以重设密码，重设后该账号所有会话失效。当前支持删除账号并保留业务历史；尚未实现 MFA、自动密码找回、全局登录限流清理或外部 SSO；应结合实际访问范围确定正式版本所需措施。

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

## R2 每日异地备份

正式启动入口 `python -m harvest.production` 在完整配置以下环境变量后启动后台备份线程：
`R2_BUCKET`、`R2_ENDPOINT_URL`、`R2_ACCESS_KEY_ID`、`R2_SECRET_ACCESS_KEY`。
Endpoint 使用 Cloudflare 的 HTTPS S3 地址，不带桶名。令牌仅授予备份桶 Object Read & Write。
使用 Standard 私有桶；为 `daily/` 前缀设置上传后 7 天删除的生命周期规则。

首次启动立即尝试；之后按服务器 TZ（建议 America/Toronto）每天凌晨 3 点后每小时检查一次。
SQLite 在线快照经完整性检查、gzip 压缩后上传，并回读 SHA-256 校验。经理「备份状态」可查看状态；普通员工不可查看。
同一天最多尝试一次，重启不重复上传。状态和预算记录保存在数据库旁的 `.backup-status.json`，不要删除或编辑。

程序的保守保护上限：原数据库 250 MB、单份压缩文件 200 MB、桶内合计 4 GB、每月上传 2 GB、每月预留请求 500 次。
超过桶容量等待旧对象清理后次日重试；月度预算到下月重置；网络或权限失败次日重试。
程序不自动删除远端备份，也不会补传错过日期。7 天持续失败可能导致生命周期规则删除全部旧备份，因此应及时处理状态异常。
这些限制不是 Cloudflare 账户级费用硬上限；同账户其他操作、计价变化及平台流量费用不受此程序控制。
`HARVEST_BACKUP_ENABLED=0` 可暂停自动备份。

上线验收：部署后检查经理状态为「备份已验证」，并在 R2 Objects 确认 `daily/harvest-日期.sqlite3.gz`。
下载一份到隔离目录，解压后执行 SQLite `PRAGMA integrity_check;` 并核对数据；不要直接覆盖正在运行的正式数据库。
恢复须先停止写入、保留当前数据库和 WAL 文件，再用核验后的快照替换数据库；恢复前应演练。
