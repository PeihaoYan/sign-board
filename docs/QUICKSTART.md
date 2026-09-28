# Quickstart

本页用于在一台干净机器上启动一个本地测试活动。生产环境还需要 HTTPS、备份和隐私告知，见 `DEPLOYMENT.md`、`BACKUP-RESTORE.md` 和 `PRIVACY.md`。

## Docker

```bash
cp .env.example .env
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
# 将上一步生成的值写入 .env 的 ADMIN_TOKEN
docker compose up --build -d
curl --fail http://127.0.0.1:18180/health
```

PowerShell：

```powershell
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(32))"
# 将生成值写入 .env 的 ADMIN_TOKEN
docker compose up --build -d
Invoke-WebRequest http://127.0.0.1:18180/health
```

打开 `http://127.0.0.1:18180/admin`，使用 `ADMIN_TOKEN` 登录。活动首次为 `draft`，先保存活动配置，再切换为 `live`。

## 本地 Python

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
export ADMIN_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export EVENT_STATUS=live
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 18180
```

Windows 使用 `.venv\Scripts\python.exe` 和 PowerShell 环境变量即可，完整命令见根目录 README。

## 验证流程

1. 打开 `/display`，确认二维码和「连接中/实时连接」状态。
2. 打开 `/mobile?event=integrity-2026`，写入签名并填写署名。
3. 提交后确认大屏出现签名。
4. 打开 `/admin?event=integrity-2026`，验证审核和导出。
5. 从管理后台生成一次性监控链接，验证 `/monitor`、PNG、ZIP 和当前页删除。
6. 将活动状态切换回 `ended`，确认新提交被拒绝。

## 停止和清理

```bash
docker compose logs --tail=200 sign-board
docker compose down
```

如果使用了真实姓名或签名，请删除本地 `data/` 前先确认是否需要导出或备份。不要把 `.env`、`data/` 或导出文件提交到 Git。
