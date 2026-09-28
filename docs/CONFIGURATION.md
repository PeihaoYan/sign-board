# Configuration

复制 `.env.example` 为 `.env`。不要把 `.env` 提交到 Git。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DATA_DIR` | `./data` | SQLite 数据和运行时签名目录 |
| `EVENT_SLUG` | `integrity-2026` | 首次创建的默认活动 slug |
| `EVENT_TITLE` | 中文示例标题 | 首次创建的活动标题 |
| `EVENT_SUBTITLE` | 中文示例副标题 | 首次创建的活动副标题 |
| `EVENT_ORGANIZATION` | 中文示例主办方 | 首次创建的主办方 |
| `EVENT_STATUS` | `draft` | 首次创建状态，推荐保持 `draft` |
| `ADMIN_TOKEN` | 无 | 必填，管理员凭据 |
| `MONITOR_TOKEN` | 回退到 `ADMIN_TOKEN` | 可选，现场监控凭据 |
| `PUBLIC_BASE_URL` | 空 | 二维码和公开链接使用的 HTTPS 基地址 |
| `SUBMISSION_BATCH_MAX` | `200` | 服务端批量写入上限 |
| `SUBMISSION_BATCH_INTERVAL` | `0.03` | 批量写入等待窗口，单位秒 |
| `SUBMISSION_TIMEOUT` | `20` | 单次提交等待写入的上限，单位秒 |
| `DB_OPEN_RETRIES` | `4` | SQLite 打开失败重试次数 |

## 令牌

使用随机长令牌，不要使用活动名称、短密码或示例值。Linux/macOS：

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

PowerShell：

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

生产环境通过 HTTPS 使用管理员和监控页面。令牌轮换时先准备备份，再修改环境文件并重启服务。

## 活动状态

- `draft`：配置阶段，不接受提交；
- `live`：接受提交并展示已通过的签名；
- `paused`：暂时关闭提交；
- `ended`：活动结束，不接受提交。

首次启动默认使用 `draft`。已有数据库中的状态不会被新的环境变量覆盖。

## 背景图

运行时默认背景位于 `static/assets/background.png`，可替换为有明确授权的 PNG。`tools/create_default_background.py` 可以重新生成无品牌默认图。背景图应保持大屏宽高比，并确保白色笔迹和二维码具有足够对比度。不要把含有个人数据、未授权校徽或活动专属信息的背景提交到通用仓库。
