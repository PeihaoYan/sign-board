# Asset Licensing

公共代码仓库只应包含来源和授权范围明确的运行时素材。

## Current review status

`static/assets/background.png` 由 `tools/create_default_background.py` 生成，使用无品牌几何图形，不含文字、校徽、人物或第三方素材，可随代码按软件许可证分发。对应的 `static/assets/background.svg` 是同一设计的可读源文件。原机构专属素材已移到本地 `.private-assets/`，不属于通用 Release。

公开发布前必须完成以下一项：

- 替换为自行创作且允许再分发的无品牌背景；
- 获得书面授权并记录授权范围；
- 将机构专属素材移出通用发布包，并在单独目录提供说明；
- 为每一项图片记录来源、作者、许可证、修改方式和商标限制。

运行时背景应保持可替换，使用者可以通过部署文档配置自己的活动背景，而不需要修改业务代码。
