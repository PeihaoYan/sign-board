# Backup and Restore

签名、姓名和活动配置都属于现场数据。发布新版本、执行迁移或清理数据前必须先备份，并在首次上线前完成一次恢复演练。

## 在线备份

优先使用 SQLite 的在线备份能力，不要在服务运行时只复制 `*.sqlite3` 而忽略 WAL 文件。

如果宿主机安装了 `sqlite3`，可以执行：

```bash
mkdir -p backups
sqlite3 data/sign-board.sqlite3 ".backup 'backups/sign-board-$(date +%Y%m%d-%H%M%S).sqlite3'"
sqlite3 backups/<backup-file>.sqlite3 "PRAGMA integrity_check;"
```

Docker 环境也可以在停止服务后复制完整数据目录：

```bash
docker compose stop
cp -a data backups/data-$(date +%Y%m%d-%H%M%S)
docker compose start
```

停止复制会降低一致性风险，但会造成短暂不可用。仓库提供同样使用 SQLite 在线备份 API 的脚本：

```bash
python tools/backup_db.py --output backups/sign-board-$(date +%Y%m%d-%H%M%S).sqlite3
python tools/backup_db.py --database data/sign-board.sqlite3 --output backups/event.sqlite3
```

脚本会执行完整性检查，并在完成后原子替换目标文件。备份文件仍然需要由部署者加密保存，并定期执行恢复演练。

## 恢复到新目录

1. 停止服务。
2. 保留当前 `data/` 作为故障现场副本。
3. 将已验证备份恢复到新的数据目录。
4. 确认目录归属允许应用用户写入。
5. 启动服务并检查 `/health`。
6. 检查活动配置、签名数量、管理员导出和大屏展示。
7. 记录恢复时间、备份来源和数据缺口。

不要直接覆盖唯一的生产数据库。恢复前先复制当前目录，以便调查失败原因。

## 保留和删除

活动结束后由部署者根据参与者告知内容和组织隐私政策决定保留时间。删除数据库前先导出必要的归档，并确认 ZIP/CSV 不会进入 Git、公共对象存储或聊天记录。

## 回滚

应用回滚和数据库回滚必须分开处理：

- 只回滚代码时，确认旧版本能够读取当前 schema；
- 迁移不可逆时，使用迁移前的数据库副本；
- 回滚后重新检查 `/health`、公开活动接口、管理接口和导出；
- 记录部署提交、数据库备份、恢复动作和最终状态。
