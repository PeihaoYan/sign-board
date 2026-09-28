# Deployment

首版推荐 Docker Compose。Ubuntu/systemd 和 Caddy 适合已经有服务器运维经验的部署者。

## Docker Compose

```bash
cp .env.example .env
# 编辑 .env，设置随机 ADMIN_TOKEN 和公开地址
mkdir -p data
docker compose up --build -d
docker compose ps
curl --fail http://127.0.0.1:18180/health
```

Docker 镜像以 UID/GID `10001` 的非 root 用户运行。Linux bind mount 使用 `./data:/app/data` 时，如果宿主机权限阻止写入，请在确认目录只用于本项目后执行：

```bash
sudo chown -R 10001:10001 data
```

不要把 `18180` 直接暴露到公网。推荐让 Caddy、Nginx 或其他反向代理在 HTTPS 终止后转发到 `127.0.0.1:18180`，并确保 WebSocket 路径 `/ws/` 被转发。

## HTTPS 和公开地址

在 `.env` 中设置：

```text
PUBLIC_BASE_URL=https://wall.example.com
```

代理需要支持：

- HTTPS；
- `/api/`、页面和 `/assets/` 的普通 HTTP 转发；
- `/ws/` 的 WebSocket Upgrade；
- 不缓存活动 API 和 WebSocket；
- 正确传递 `X-Forwarded-Proto` 和 `X-Forwarded-Host`。

手机端和大屏都应通过同一个 HTTPS 源访问。活动前用手机扫描大屏二维码，确认地址、书写、提交和实时显示完整可用。

## Ubuntu systemd

将源代码放到自定义的应用目录后，从项目根目录执行：

```bash
sudo bash deploy/setup-ubuntu.sh
```

脚本会优先读取 `ADMIN_TOKEN` 或 `ADMIN_TOKEN_FILE`，交互式运行时也可以使用隐藏输入。不要把令牌作为命令行参数传入，不要把脚本输出粘贴到公开日志。

脚本默认使用 systemd 用户 `signboard`、数据目录 `/opt/sign-board/data` 和端口 80。若使用 Caddy，应让应用监听 loopback 非特权端口，再由 Caddy 负责 80/443 和 TLS。具体服务文件在 `deploy/sign-board.service`，上线前应根据实际 `APP_DIR`、端口和反向代理审阅它。

## 上线检查

```bash
curl --fail https://wall.example.com/health
curl --fail https://wall.example.com/api/events/<slug>
```

然后依次验证：

1. `/admin` 可以登录；
2. 活动仍处于 `draft` 或 `paused`；
3. 配置标题、公开地址和背景；
4. 大屏二维码可以被两种手机网络扫描；
5. 切换为 `live` 后完成一次真实签名；
6. 监控、审核、导出和备份均可用；
7. 活动结束后切回 `ended`，并停止或限制外部访问。
