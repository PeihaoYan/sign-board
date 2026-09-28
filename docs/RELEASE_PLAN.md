# v1.0.0 版本升级与发布计划

## 1. 版本定位

`v1.0.0` 是“单场活动可部署、可回滚、可验收”的首个正式版本，不承诺多实例、高可用或通用 SaaS 能力。版本采用 SemVer：

- `MAJOR`：破坏 API、数据格式或部署契约。
- `MINOR`：向后兼容的新功能，例如多活动管理、审计日志、备份界面。
- `PATCH`：向后兼容的缺陷、安全和部署修复。

当前仓库分支是 `master`，历史没有发布标签。不要改写已有提交；本轮变更审阅通过后创建一个 annotated tag `v1.0.0`，并把发布提交与标签的 SHA 记录到部署记录中。

## 2. 本轮已完成的发布变更

- 将 FastAPI/OpenAPI 版本元数据统一到 `1.0.0`。
- 删除内置开发凭据回退；生产启动必须显式提供 `ADMIN_TOKEN`。
- 为管理员 ZIP 增加矢量笔迹 PNG 渲染，并保留旧版图片记录回退。
- 为大屏几何上报增加短期签名 Cookie、宽高范围、宽高比和总像素上限。
- 前端 `wallSync.js` 与 `wallExport.js` 对服务端或本地缓存几何做同样的异常过滤。
- 增加 `v1.0.0` 的项目分析、架构图和变更记录。
- 增加对应回归断言：版本信息、矢量 ZIP 文件、显示会话、异常几何。
- 首次活动默认状态改为 `draft`，新增 `EVENT_STATUS` 配置和启动校验。
- 监控分享改为一次性兑换码和短期签名 Cookie，管理员响应不再携带长期监控令牌。
- 增加 `schema_migrations`、SQLite 在线备份工具、MIT 许可证、社区文件和 GitHub Actions 基础门禁。
- 移除机构专属素材和线上环境信息，加入无品牌背景及素材授权说明。

## 3. 发布前门禁

### 必须通过

- [x] `.venv/Scripts/python.exe -m pytest -q`：本机结果 `26 passed`，仍有 2 条依赖弃用警告。
- [x] Python `compileall`、Node `--check` 和 `git diff --check` 通过。
- [x] `tools/prepare_git.py`：当前 128 个候选文件约 0.8 MB，没有凭据、数据库或私有素材。
- [x] 本地 Uvicorn 隔离探针：`/health`、活动接口和页面返回 200，首次状态为 `draft`。
- [x] 缺少 `ADMIN_TOKEN` 的启动校验、一次性监控码、短期监控 Cookie 和 SQLite 备份工具。
- [x] `docker build -t sign-board:v1.0.0 .` 成功；本机使用已缓存的等价 `python:3.12-slim` 基础镜像完成构建。
- [x] 使用独立 env-file 启动容器，`GET /health` 返回 `200`，首次活动为 `draft`，缺少 `ADMIN_TOKEN` 时容器退出码为 `3`。
- [x] 临时容器以 UID `10001` 运行，健康检查为 `healthy`；切换 `live` 后提交成功，重启容器后数据仍存在。
- [x] 固定本地浏览器视口完成横屏书写、PNG 导出一致性和二维码缩放检查，均 `failures=0`。
- [x] 使用测试数据库完成 `tools/backup_db.py` 备份、复制恢复和 `PRAGMA integrity_check` 演练；这不替代线上数据恢复和版本回滚。
- [x] Release Candidate 容器完成 50 条合成提交：`201:50`，5 秒内完成 `50/50`。
- [x] Release Candidate 容器完成 CSV、管理员 ZIP、监控 ZIP 完整性检查，以及监控删除后总数从 50 变为 49。
- [x] 本地浏览器在容器停止/重启后从「等待连接」恢复为「实时连接」，WebSocket 重连检查 `failures=0`。
- [ ] 在真实大屏浏览器打开 `/display`，连续提交 30–50 条签名，验证 WebSocket 断线重连。
- [ ] 在真实手机完成普通书写、横屏书写、署名校验、重复提交和活动结束流程。
- [ ] 管理员下载 CSV/ZIP，确认矢量和旧图片记录均有正确文件及清单。
- [ ] 现场监控下载 PNG/ZIP、删除当前页，确认大屏同步移除。
- [ ] 完成 SQLite 备份、恢复和上一版本回滚演练。
- [ ] 审阅候选文件，确认无 `data/*.sqlite3`、`.env`、`.secrets/`、个人签名和测试产物。

### 不应作为已完成验证的项目

本机 Python 测试通过不代表真实设备、Cloudflare/Caddy、投影分辨率、浏览器权限和公网路径已经通过。所有现场相关结论必须附带测试设备、浏览器版本、域名和时间。

## 4. 推荐 Git 操作流程

以下命令由维护者在最终验收通过后执行；本轮代理不自动提交、打标签或推送。

```powershell
# 1. 确认当前分支和差异
 git status --short --branch
 git diff --check
 git diff --stat

# 2. 运行本机门禁
 .\.venv\Scripts\python.exe -m pytest -q
 .\.venv\Scripts\python.exe tools\prepare_git.py
 .\.venv\Scripts\python.exe tools\verify_git_baseline.py

# 3. 构建并验证发布镜像
 docker build -t sign-board:v1.0.0 .
 docker run --rm --env-file .env -p 18180:8000 sign-board:v1.0.0

# 4. 审阅后暂存、提交和创建不可变发布标签
 git add -A
 git commit -m "Prepare v1.0.0 release"
 git tag -a v1.0.0 -m "科研诚信签名板 v1.0.0"

# 5. 推送前再次确认目标远端和标签
 git show --stat --oneline HEAD
 git show v1.0.0 --no-patch --format=fuller
 git push origin master
 git push origin v1.0.0
```

如果当前没有 `origin`，先由维护者配置正确的远端；不要把现场服务器凭据、SQLite 数据库或 `.env` 放进远端。部署时使用 tag 或提交 SHA，而不是直接使用可变分支。由于旧历史包含内部部署信息，公开仓库应按 [`docs/PUBLIC_RELEASE.md`](PUBLIC_RELEASE.md) 从清理后的工作树建立干净历史。

## 5. 回滚流程

1. 停止接收活动提交，将活动状态设为 `ended` 或暂停入口。
2. 备份 `/opt/sign-board/data/sign-board.sqlite3` 及 WAL 文件，记录当前提交 SHA。
3. 回到上一已验证 tag，重新安装依赖并重启服务。
4. 调用 `/health`、公开活动接口、管理接口和大屏页面做最小验证。
5. 确认 SQLite schema 与上一版本兼容；若迁移不可逆，先恢复数据库副本再启动。
6. 记录故障原因、影响范围、恢复时间和待修复项。

`git revert` 适合撤销已发布功能改动；线上紧急回退应使用已验证 tag，不应在服务器上临时编辑源文件。

## 6. 后续版本建议

### v1.0.1：发布后稳定性补丁

- 依赖升级时重新生成 runtime/dev lock，并在 Python 矩阵和容器中验证平台差异。
- 清理测试弃用警告，补充应用启动配置错误测试。
- 为导出、删除、备份和启动失败增加结构化日志与错误编号。
- 增加依赖安全扫描和发布包校验和。

### v1.1.0：可审计的单实例产品

- 为管理员和监控增加更细角色权限和操作审计；当前已有短期监控会话和一次性监控码。
- 增加操作审计表：谁在何时隐藏、拒绝、删除、导出了哪些内容。
- 增加活动数据保留、脱敏和备份恢复页面。
- 建立 CI：Python 测试、静态资源契约、浏览器 smoke、导出一致性和依赖安全扫描。
- 将 `app/main.py` 拆为配置、数据库、认证、提交、活动和导出模块。

### v1.2.0：可运营性增强

- Prometheus/OpenTelemetry 指标：提交延迟、队列长度、WebSocket 连接数、导出耗时、错误率。
- 活动彩排模式与一键清理测试数据，避免把压测记录混入真实活动。
- 发布包生成、SHA256 校验和自动部署前后探针。
- 对背景图、二维码和签名可读性做固定分辨率视觉回归。

### v2.0.0：多实例或多活动平台

只有当需求明确要求并发活动、多实例、跨主机实时同步时才考虑：

- PostgreSQL 替代 SQLite 主库。
- Redis 或消息总线承载广播、限流和任务队列。
- 对象存储承载归档和大文件，应用实例无本地状态。
- 独立身份与角色系统、租户/活动隔离、审计和数据生命周期策略。

## 7. 发布判断

当前代码可以作为 `v1.0.0` 的发布候选，但在真实设备和部署门禁完成前不要宣称“正式发布”。完成门禁后，发布提交、annotated tag、容器镜像摘要和部署 SHA 应作为同一份发布记录保存。
