# v1.0.0 Release Candidate 验证报告

## 状态

已建立公开 GitHub 仓库 `PeihaoYan/sign-board`。清理后的 `public-main` 已作为远端 `main` 推送，首个公开提交为 `82eb11e`，并已创建远端 `v1.0.0` annotated tag。GitHub Release 页面对象尚未单独创建。项目边界保持为单场活动、单进程、单 SQLite 节点。

本报告记录的是当前工作树和本机验证结果，不代表真实会场、生产服务器或公网网络已经通过。

## 已通过

| 类别 | 结果 |
| --- | --- |
| Python 回归 | `26 passed`，2 条 FastAPI/Starlette/httpx 弃用警告 |
| Python/JavaScript 语法 | `compileall` 和 Node `--check` 通过 |
| 依赖一致性 | `pip check` 通过 |
| Compose/CI 配置 | YAML 解析通过 |
| 文档链接 | 20 个相对链接通过 |
| 公开内容 | 未发现旧线上 IP、用户名、私钥文件名或开发凭据字样 |
| Git 候选扫描 | 129 个候选文件，约 0.8 MB；无凭据、数据库、私有素材 |
| 默认背景 | 1920×1080；亮度超过白色笔迹风险阈值的像素为 0% |
| Docker 镜像 | 构建成功；镜像 ID `sha256:bd1a075784d4d94ea1f156cbb776225fdb69a2b30a416a1e32f24ba77704d45a` |
| Docker 安全默认 | UID `10001` 非 root，健康检查为 `healthy` |
| 首次活动 | env-file 启动后状态为 `draft` |
| 缺少管理员令牌 | 容器退出码为 `3` |
| 活动提交边界 | `draft` 返回 `409`；`live` 返回 `201` |
| 容器重启持久化 | 重启后签名仍可读取 |
| 50 条提交 | 合成负载 `201:50`，5 秒内完成 `50/50` |
| CSV/ZIP/监控归档 | 三个归档均可读取、完整性检查通过并含 `submissions.csv` |
| 监控删除 | 总数从 50 变为 49 |
| 横屏书写 | `failures=0`，包含旋转映射、提示、返回和重入 |
| 大屏 PNG 导出 | `failures=0`，大屏/导出位置差异 `0.0000` |
| 二维码缩放 | `failures=0`，覆盖 0.5×–3×和上限裁剪 |
| WebSocket 重连 | 容器停止/重启后浏览器从「等待连接」恢复为「实时连接」，`failures=0` |
| SQLite 工具 | 备份、复制恢复和 `PRAGMA integrity_check` 通过 |
| 优雅停机 | 保持大屏 WebSocket 时停止耗时 `0.00 s` |

## 尚未通过或需要维护者执行

- 真实手机和真实投影大屏彩排；
- 真实会场网络、HTTPS、反向代理和公网路径；
- 30–50 条真实现场提交，而不是合成负载；
- 真实设备上的横屏书写和浏览器兼容性；
- 生产 SQLite 备份恢复和上一版本回滚；
- 完整 Git 历史密钥扫描。当前环境没有安装 `gitleaks`；针对旧 IP、私钥文件名和开发默认值的定向扫描已经完成；
- 创建 GitHub Release 页面对象并附带现场验收状态；

## 发布入口

- 产品入口：`README.md`
- 路线图：`Roadmap.md`
- 公开历史和 GitHub Release：`docs/PUBLIC_RELEASE.md`
- 发布门禁：`docs/RELEASE_PLAN.md`
- 安全策略：`SECURITY.md`
- 素材授权：`ASSET_LICENSES.md`
