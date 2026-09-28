# sign-board 开源发布路线图

## 目标

将本项目发布为首个可复现、可自托管、可审阅的 GitHub Release：

> 面向高校、实验室、公益组织和活动组织者的单场实时手写签名墙。
>
> 手机扫码提交手写签名，大屏实时展示，管理员审核并导出活动数据。

首个版本的产品边界是：**单场活动、单进程、单 SQLite 数据库、单节点部署**。它不承诺多租户、多实例、高可用或通用 SaaS 能力。服务器、域名、HTTPS 和备份存储仍由部署者自行提供。

## 发布目标

- 版本：`v1.0.0`
- 发布类型：自托管开源应用，不提供必须依赖的付费 SaaS 服务
- 首选部署：Docker Compose
- 备选部署：Ubuntu + systemd + Caddy
- 数据库：SQLite WAL
- 主要容量目标：单场活动、约 500 人级突发提交
- 代码许可证：`MIT License`，已写入 `LICENSE`；若后续要要求网络服务修改保持开源，再单独评估 `AGPL-3.0-or-later`
- Git 操作边界：本路线图不自动提交、打标签或推送；由维护者在验收后执行

## 当前基线

- 后端和接口测试：`26 passed`，另有 2 条依赖弃用警告
- 当前实现已经覆盖手机端、大屏端、管理端、现场监控、审核、导出、WebSocket、SQLite 和基础部署
- 当前实现仍是单体应用，`app/main.py` 约 1400 行
- 已加入 runtime/dev lock 文件和直接依赖约束；依赖升级仍需重新生成并通过完整门禁
- 已加入 `schema_migrations`、SQLite 在线备份工具和恢复文档
- 已加入 MIT 许可证、社区文件和 GitHub Actions 基础门禁
- 公开源码中的内部 IP、用户名、私有素材和失效脚本引用已清理
- 默认背景已替换为无品牌、可复现生成的 PNG/SVG
- Docker Release Candidate 镜像已构建并完成临时容器健康、非 root、draft/live、重启持久化验证
- 本地浏览器已通过横屏书写、PNG 导出一致性和二维码缩放检查，均 `failures=0`
- `tools/backup_db.py` 已完成本地 SQLite 备份、复制恢复和 `PRAGMA integrity_check` 演练；线上数据恢复和版本回滚仍待维护者执行
- Release Candidate 容器完成 50 条合成提交、CSV/ZIP、监控删除和持久化验证；5 秒内 50/50 成功
- 容器停止/重启后的浏览器 WebSocket 自动重连检查通过，`failures=0`
- 历史扫描发现旧提交包含线上 IP、部署私钥文件名和开发凭据默认值；正式公开前仍需完成全历史密钥扫描，并决定是否以干净基线发布

## 阶段 0：公开仓库清理

状态：`in_progress`

交付物：

- `LICENSE`
- `ASSET_LICENSES.md`
- 脱敏后的 `README.md`
- 不含真实 IP、用户名、SSH 信息、代理端口和线上数据的部署文档
- 无个人签名、数据库、密钥和内部运行产物的候选提交
- 机构专属背景、校徽和校名从通用默认发布包中移除或明确隔离
- 全 Git 历史的密钥和个人数据扫描记录

验收：

- `git grep` 不再发现真实服务器地址、内部用户名或本机代理配置
- `gitleaks` 或等效工具扫描历史无有效密钥
- 默认背景具有可核验授权，或使用自行创作的无品牌背景
- `tools/prepare_git.py` 通过

## 阶段 1：安全默认和配置契约

状态：`completed`

交付物：

- 缺少 `ADMIN_TOKEN` 时服务启动失败
- 首次创建活动默认为 `draft` 或 `paused`，不会自动向公网开放提交
- 默认活动 slug、标题、说明、公开地址和数据目录集中配置
- 部署脚本不再通过命令行参数传递或打印长期凭据
- 监控凭据使用短期会话或一次性兑换码，不直接把长期令牌作为 Cookie
- 生产环境支持 HTTPS 安全 Cookie，并文档化令牌轮换
- 增加隐私说明、数据保留、导出和删除策略
- 公开接口、管理接口和监控接口的权限边界写入文档

验收：

- 无管理员令牌无法启动
- 非 `live` 活动拒绝提交
- 令牌不会出现在进程参数、默认日志或共享 URL 中
- 未授权请求统一返回预期的 `401/403`
- 监控删除操作有明确警告和审计边界

## 阶段 2：可复现安装和运行

状态：`in_progress`

交付物：

- `pyproject.toml` 或明确的 runtime/dev 依赖文件
- 锁定或约束依赖版本，并固定 Python 支持范围
- 非 root Docker 镜像
- Docker `HEALTHCHECK`
- Compose 健康检查、数据卷和 `.env.example` 使用说明
- 干净机器上的 Docker 快速启动文档
- Ubuntu/systemd/Caddy 文档与 Docker 路径一致，不依赖当前维护者的服务器环境
- `/health`、启动失败和基本升级命令的自动验证

验收：

- 在没有本地虚拟环境和本地数据库的机器上可以构建镜像
- `docker compose up --build` 后健康检查通过
- 重启容器后 SQLite 数据仍然存在
- 空配置或缺失密钥时失败原因清晰

## 阶段 3：数据库迁移、备份和回滚

状态：`in_progress`

交付物：

- `schema_migrations` 表
- 按版本组织的幂等迁移
- SQLite 在线备份命令
- 数据库完整性检查命令
- 恢复到新目录的演练文档
- 活动结束后的保留和清理命令
- 上一版本回滚说明

验收：

- 从空数据库可以初始化
- 从当前基线数据库可以升级
- 升级失败不会静默破坏原数据库
- 备份恢复后活动、签名、状态和导出结果一致
- 至少完成一次版本升级和一次回滚演练

## 阶段 4：测试和 GitHub CI

状态：`in_progress`

交付物：

- `.github/workflows/ci.yml`
- 后端 API、鉴权、导出和迁移测试
- Docker 构建与健康检查 job
- 桌面端大屏/管理/监控 smoke test
- 移动端普通书写、署名校验和横屏书写 smoke test
- PNG/ZIP/CSV 导出一致性测试
- 500 条布局和有限并发测试作为非阻塞性能门禁
- 依赖漏洞扫描和敏感文件扫描

验收：

- Pull Request 至少通过 Python 测试、静态检查和 Docker 构建
- 浏览器测试使用固定版本或明确的支持范围
- 性能数据标注测试机器、浏览器、版本和负载，不宣传为通用保证
- 测试脚本区分 CI、真实浏览器和线上运维用途

## 阶段 5：文档和社区入口

状态：`in_progress`

交付物：

- 精简后的 `README.md`
- `docs/QUICKSTART.md`
- `docs/CONFIGURATION.md`
- `docs/DEPLOYMENT.md`
- `docs/OPERATIONS.md`
- `docs/BACKUP-RESTORE.md`
- `docs/PRIVACY.md`
- `docs/API.md`
- `docs/TROUBLESHOOTING.md`
- `docs/PUBLIC_RELEASE.md`
- `docs/RELEASE_REPORT.md`
- `CONTRIBUTING.md`
- `CODE_OF_CONDUCT.md`
- `SECURITY.md`
- GitHub issue/PR 模板
- 无个人数据的截图或演示素材

验收：

- 新用户只读 README 和 Quickstart 即可启动一个测试活动
- 文档不包含维护者个人服务器信息
- 每个公开环境变量都有用途、默认值、是否必填和安全说明
- 公开限制包括容量、单节点模型、备份责任和隐私责任

## 阶段 6：发布候选和 GitHub Release

状态：`in_progress`

公开历史策略已确定为从清理后的工作树建立 `public-main`，但实际 Git 分支、提交、标签和推送由维护者执行。

发布前必须通过：

- `pytest -q`
- 静态检查和文档链接检查
- `tools/prepare_git.py`
- 全历史密钥扫描
- Docker 构建和容器 `/health` 检查
- 新环境启动、提交、展示、审核、导出和停止流程
- 真实手机普通/横屏书写验证
- WebSocket 断线重连验证
- PNG/CSV/ZIP 导出验证
- SQLite 备份恢复验证
- 上一版本回滚验证
- `git diff --check`
- 确认未包含 `.env`、`.secrets/`、数据库、个人数据和未授权素材

维护者随后再执行：

1. 审阅候选文件和完整差异。
2. 提交发布变更。
3. 创建 annotated tag：`v1.0.0`。
4. 创建 GitHub Release，附带变更说明、部署限制和已知问题。
5. 推送分支和标签。

## 发布后的 v1.1 方向

首版发布后再考虑：

- 可审计的管理员/监控操作日志
- 多活动创建与管理
- 更短的监控登录码和令牌轮换界面
- 数据保留策略界面
- `app/main.py` 模块拆分
- Prometheus/OpenTelemetry 指标
- 活动彩排模式和测试数据清理
- 更完整的 Playwright 浏览器回归

## 暂不纳入 v1.0

- 多实例实时广播
- PostgreSQL/Redis 迁移
- 多租户 SaaS
- 跨节点高可用
- 云端托管服务
- 为支持多个数据库而引入复杂 ORM

这些能力会改变部署边界和运维成本，不应阻塞首个可用的自托管开源版本。
