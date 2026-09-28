# Public GitHub Release

当前仓库历史包含旧的内部部署地址、部署私钥文件名和开发环境默认值。它们不应随公开 Git 历史发布。当前工作树已经完成脱敏和候选扫描，但本项目不自动改写现有 `master`，也不自动推送。

## 发布前检查

在确认当前目录是清理后的工作树后运行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe tools\prepare_git.py
git diff --check
git status --short --branch
```

确认：

- `tools/prepare_git.py` 不报告凭据、数据库或私有素材；
- `.env`、`.secrets/`、`data/*.sqlite3` 和 `.private-assets/` 不在候选文件中；
- `static/assets/background.png` 是无品牌默认背景；
- `LICENSE`、`ASSET_LICENSES.md`、`SECURITY.md` 和社区文件存在；
- Docker、真实设备、备份恢复和回滚门禁已经由维护者完成。

## 建立干净公开历史

推荐在新的公开仓库或临时克隆中操作，不要直接重写本地 `master`：

```powershell
# 在清理后的工作树中确认没有需要保留的未提交用户改动
 git status --short

# 建立不继承旧提交的公开分支；以下命令会改变当前 Git 工作树，先确认已备份
 git switch --orphan public-main
 git rm -rf --cached .
 git add -A
 git status --short
 git commit -m "Initial open-source release"
 git tag -a v1.0.0 -m "sign-board v1.0.0"
```

`git rm --cached` 不删除已经存在于工作目录的文件，但执行前仍应由维护者确认工作树和备份。若使用新的空目录/新仓库，则可以直接将 `tools/prepare_git.py` 的候选文件复制进去后初始化 Git，避免触碰现有仓库。

## 推送前

先在 GitHub 创建空仓库，并核对远端地址：

```powershell
git remote add origin https://github.com/<owner>/<repository>.git
git remote -v
git show --stat --oneline HEAD
git show v1.0.0 --no-patch --format=fuller
git push -u origin public-main:main
git push origin v1.0.0
```

创建 GitHub Release 时附带：

- `v1.0.0` 版本号；
- Docker/本地启动方式；
- 单进程 SQLite 的系统边界；
- 已完成和未完成的验收项；
- 备份、隐私和监控凭据警告；
- MIT License 和素材授权说明。

不要把当前现场服务器作为公开演示环境，不要把 `.env`、SQLite、导出 ZIP、真实签名或私有背景上传到 GitHub。
