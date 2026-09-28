# Operations

## 活动流程

1. 配置 `.env` 和管理员令牌。
2. 启动服务，确认活动状态为 `draft`。
3. 在 `/admin` 配置标题、副标题、主办方、二维码大小和展示数量。
4. 打开 `/display`，检查背景、二维码和连接状态。
5. 用真实手机测试普通和横屏书写。
6. 将活动状态切换为 `live`。
7. 使用 `/monitor` 观察提交和异常内容。
8. 活动结束后切换为 `ended`，导出数据并按政策清理。

## 健康检查

```bash
curl --fail http://127.0.0.1:18180/health
```

`200` 只表示服务和默认活动可以读取；它不等于 WebSocket、HTTPS、二维码、浏览器渲染和备份全部正常。现场验收必须覆盖完整用户流程。

## Docker 常用命令

```bash
docker compose logs --tail=200 sign-board
docker compose ps
docker compose restart sign-board
docker compose stop
docker compose up --build -d
```

日志中不要发布管理员令牌、监控令牌、导出内容或包含姓名的完整请求。

## 令牌管理

`ADMIN_TOKEN` 和 `MONITOR_TOKEN` 都是敏感凭据。发生泄露时：

1. 暂停活动；
2. 备份数据库；
3. 修改环境文件中的令牌；
4. 重启服务；
5. 使旧的监控链接失效；
6. 检查访问日志和导出记录。

首版监控令牌可以删除提交，因此不能作为只读凭据分发。
