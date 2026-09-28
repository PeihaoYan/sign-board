# Troubleshooting

## `/health` 不是 200

检查：

```bash
docker compose ps
docker compose logs --tail=200 sign-board
```

确认 `.env` 中存在 `ADMIN_TOKEN`，数据目录可写，端口没有被其他服务占用。缺少管理员令牌时应用应主动拒绝启动。

## 手机提交一直等待

确认：

- 活动状态为 `live`；
- 手机使用 HTTPS 地址；
- 反向代理没有限制请求体或长连接；
- 请求体没有超过服务端限制；
- 服务端日志没有 SQLite 权限或磁盘错误；
- 现场网络没有路径 MTU 或 captive portal 问题。

先用一台手机提交最小签名，再逐步增加负载。不要直接用现场真实数据做压力测试。

## 大屏没有新签名

检查浏览器中的：

- `/api/events/<slug>/display` 是否返回 200；
- `/ws/events/<slug>/display` 是否成功 Upgrade；
- 页面连接状态是否为「实时连接」；
- 浏览器是否加载了当前版本的 `display.js` 和 `signature.js`；
- 活动是否被设置为 `paused`、`ended` 或隐藏。

## 二维码地址错误

设置 `PUBLIC_BASE_URL=https://your-domain.example` 后重启服务，并确认反向代理传递了正确的 Host/Proto。用 `/api/events/<slug>/public-url` 检查最终地址。

## 导出和大屏布局不一致

PNG 导出依赖大屏上报的近期舞台几何。如果监控页提示大屏未上报布局，先在目标分辨率打开 `/display`，等待二维码加载和布局稳定后再导出。

## 公开排障信息

提交 Issue 时删除真实姓名、签名、令牌、域名、IP、数据库和活动截图中的个人数据。安全问题不要公开创建 Issue，按 `SECURITY.md` 处理。
