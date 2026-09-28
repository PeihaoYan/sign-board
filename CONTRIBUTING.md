# Contributing

感谢你为 sign-board 提交改进。项目首版目标是让没有本地开发环境的组织者也能通过 Docker 自行部署一场活动。

## 开始之前

1. Fork 仓库并创建功能分支。
2. 创建虚拟环境并安装开发依赖：

   ```bash
   python -m venv .venv
   .venv/bin/python -m pip install -r requirements-dev.txt
   ```

3. 运行测试：

   ```bash
   python -m pytest -q
   ```

## 提交要求

- 说明用户问题、行为变化和测试方式。
- 新增接口时同步更新 API 或配置文档。
- 不提交 `.env`、`.secrets/`、SQLite 数据库、真实签名、令牌和未授权素材。
- 修改前端布局、Canvas 或 WebSocket 行为时，补充对应的浏览器验证或静态契约测试。
- 性能数据必须注明浏览器、机器、分辨率、负载和测试时间；不要把单机结果宣传为通用容量保证。
- 保持首版的单场活动、单进程、SQLite 边界，扩展多实例前先讨论部署模型变化。

## Pull Request

Pull Request 应包含：

- 变更目的；
- 影响的页面、接口或数据表；
- 测试命令和结果；
- 配置、迁移、隐私或安全影响；
- 文档和变更记录是否同步。
