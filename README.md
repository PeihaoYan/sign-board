# sign-board

自托管的实时手写签名墙。参与者用手机扫码手写签名，大屏通过 WebSocket 实时展示，管理员可以审核内容并导出活动数据。

本项目面向高校、实验室、公益组织和活动组织者，目标是提供一套不依赖付费 SaaS 的可部署方案。

> 当前状态：`v1.0.0` Release Candidate 准备中。首个正式 GitHub Release 还需要完成素材授权、容器/浏览器验收、备份恢复和发布审阅。

## 功能

- 手机端 Canvas 手写签名、重写、署名校验和横屏书写
- 大屏实时展示、二维码入口、断线重连和拥挤度自适应布局
- 管理员活动配置、状态控制、签名审核、隐藏、拒绝和删除
- 现场监控、当前页清理、大屏 PNG 导出、CSV/ZIP 导出
- 矢量笔迹存储，避免签名携带背景图片
- SQLite WAL 持久化，无需外部数据库
- Docker Compose、Ubuntu systemd 和 Caddy 部署路径
- `/health` 健康检查和 OpenAPI 文档

大屏签名会随同屏数量缩小，并按舞台尺寸同步缩放。参考舞台为 1920×1080：

| 同屏签名数 | 缩放 | 气泡 | 笔迹画布 | 姓名字号 |
| --- | --- | --- | --- | --- |
| ≤40 | 1 | 152×118 | 101×65 | 12px |
| ≤90 | 0.8 | 122×94 | 81×52 | 10px |
| ≤160 | 0.7 | 106×83 | 70×46 | 8px |
| ≤260 | 0.6 | 91×71 | 60×39 | 8px |
| ≤400 | 0.5 | 76×59 | 50×33 | 8px |
| >400 | 0.45 | 68×53 | 45×29 | 8px |

## 首次运行

需要 Python 3.11+ 或 Docker。推荐先用 Docker Compose：

```bash
cp .env.example .env
# 编辑 .env，至少设置一个随机的 ADMIN_TOKEN
# 例如：python -c "import secrets; print(secrets.token_urlsafe(32))"
docker compose up --build -d
curl http://127.0.0.1:18180/health
```

Windows PowerShell：

```powershell
Copy-Item .env.example .env
# 编辑 .env 后启动
docker compose up --build -d
Invoke-WebRequest http://127.0.0.1:18180/health
```

首次部署默认活动状态是 `draft`，不会接受公开提交。打开 `/admin` 登录后，配置活动并将状态改为「现场开放」。

默认页面：

| 页面 | 地址 |
| --- | --- |
| 大屏 | `/display` |
| 手机 | `/mobile?event=integrity-2026` |
| 管理后台 | `/admin?event=integrity-2026` |
| 现场监控 | `/monitor?event=integrity-2026` |
| 健康检查 | `/health` |
| OpenAPI | `/docs` |

如果通过反向代理或正式域名访问，设置 `PUBLIC_BASE_URL`，让二维码始终指向正确的 HTTPS 地址。

## 本地开发

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
$env:ADMIN_TOKEN='local-development-token'
$env:EVENT_STATUS='live'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 18180
.\.venv\Scripts\python.exe -m pytest -q
```

Linux/macOS：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
export ADMIN_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export EVENT_STATUS=live
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 18180
.venv/bin/python -m pytest -q
```

## 配置

完整配置说明见 [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md)。最重要的变量：

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `ADMIN_TOKEN` | 是 | 管理员令牌，必须是随机长令牌 |
| `MONITOR_TOKEN` | 否 | 现场监控令牌；未设置时回退到管理员令牌 |
| `EVENT_SLUG` | 否 | 默认活动标识 |
| `EVENT_STATUS` | 否 | 首次创建活动的状态，默认 `draft` |
| `DATA_DIR` | 否 | SQLite 数据和签名数据目录 |
| `PUBLIC_BASE_URL` | 生产建议 | 二维码使用的公开 HTTPS 地址 |
| `EVENT_TITLE` | 否 | 首次创建活动的标题 |
| `EVENT_SUBTITLE` | 否 | 首次创建活动的副标题 |
| `EVENT_ORGANIZATION` | 否 | 首次创建活动的主办方 |

环境变量只用于初始化或运行配置；活动内容应在管理后台调整。当前版本的数据模型支持多个活动记录，但默认界面和启动配置仍以单场活动为中心。

## 部署和运维

- 快速启动：[`docs/QUICKSTART.md`](docs/QUICKSTART.md)
- API 概览：[`docs/API.md`](docs/API.md)
- Docker 生产部署：[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)
- Ubuntu/systemd/Caddy：[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)
- 备份、恢复和升级：[`docs/BACKUP-RESTORE.md`](docs/BACKUP-RESTORE.md)
- 运行维护：[`docs/OPERATIONS.md`](docs/OPERATIONS.md)
- 安全策略：[`SECURITY.md`](SECURITY.md)
- 隐私和数据处理：[`docs/PRIVACY.md`](docs/PRIVACY.md)
- 故障排查：[`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md)
- 系统架构：[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- 当前路线图：[`Roadmap.md`](Roadmap.md)
- 干净公开历史和 GitHub Release：[`docs/PUBLIC_RELEASE.md`](docs/PUBLIC_RELEASE.md)
- 当前验证报告：[`docs/RELEASE_REPORT.md`](docs/RELEASE_REPORT.md)

生产环境应使用 HTTPS。监控凭据具备删除签名的能力，不能当作普通只读链接公开转发。活动结束后应按组织的数据保留政策导出并删除个人数据。

## 系统边界

首个版本明确支持：

- 单节点、单进程 Uvicorn/FastAPI 服务
- 单个 SQLite WAL 数据库
- 单场活动的现场展示
- 几百人级别的突发提交，具体容量取决于 CPU、磁盘、网络和浏览器

首个版本不承诺：

- 多 worker 或多实例实时广播
- 跨节点共享限流和任务队列
- PostgreSQL/Redis 高可用架构
- 多租户 SaaS、云端托管或自动证书服务

不要把仓库中的单机压测数字理解为所有服务器和网络环境下的 SLA。

## 数据和隐私

提交数据包含署名和手写轨迹。签名会显示在活动大屏上，并可能进入 CSV、PNG 或 ZIP 导出。部署者必须在活动现场告知参与者用途，限制管理员和监控凭据的访问范围，并制定删除和保留周期。

签名笔迹以坐标保存，服务端会校验点数、坐标、文本长度和请求体大小。管理接口和导出接口需要鉴权；公开大屏只展示已允许展示的记录。

## 开发和发布

安装开发依赖并运行测试：

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

GitHub Actions 会运行 Python 测试、编译检查和 Docker 健康检查。浏览器横屏、布局、导出和压力脚本位于 `tests/`，其中部分需要固定浏览器、运行中的服务或专用测试数据，详见脚本顶部说明。

发布流程和未完成门禁见 [`docs/RELEASE_PLAN.md`](docs/RELEASE_PLAN.md)。项目当前没有正式发布标签；维护者应在所有门禁通过、授权核对和差异审阅后再创建 `v1.0.0`。

## 许可证和素材

代码以 MIT License 发布，详见根目录 [`LICENSE`](LICENSE)。图片、校徽、活动背景、字体和其他非代码素材不自动继承软件许可证，来源和再分发限制见 [`ASSET_LICENSES.md`](ASSET_LICENSES.md)。

通用发布包不得包含未授权的机构专属背景、校徽、校名、个人签名、数据库或部署凭据。

## 贡献

代码贡献、测试、文档和问题报告请先阅读 [`CONTRIBUTING.md`](CONTRIBUTING.md)。安全漏洞不要公开创建 Issue，处理方式见 [`SECURITY.md`](SECURITY.md)。
