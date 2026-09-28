# 系统架构图

本文描述 `v1.0.0` 的运行时架构、数据流、信任边界和持久化模型。图表使用 Mermaid，可在支持 Mermaid 的 Markdown 阅读器中直接渲染。

## 1. 系统上下文

```mermaid
flowchart LR
    Participant[参会者手机\n/mobile] -->|HTTPS POST 矢量笔迹| Gateway[反向代理或 Uvicorn\n同源入口]
    Display[会场大屏浏览器\n/display] <-->|HTTP 快照 + WebSocket| Gateway
    Admin[管理员浏览器\n/admin] -->|Bearer 管理员令牌| Gateway
    Monitor[现场监控浏览器\n/monitor] -->|短期监控会话| Gateway
    Gateway --> App[FastAPI 单体应用\napp/main.py]
    App --> DB[(SQLite WAL\nsign-board.sqlite3)]
    App --> Assets[静态页面与背景图\nstatic/]
    App --> QR[二维码生成器\nqrcode]
    Operator[Ubuntu systemd / Docker Compose] -.部署与重启.-> App
    Proxy[Caddy / HTTPS] -.可选 TLS 终止.-> Gateway
```

边界说明：四类浏览器都访问同一个源，服务端没有独立前端构建产物。WebSocket 只服务于大屏实时更新；监控页使用定时轮询，管理员页使用请求-响应。

## 2. 服务内部组件

```mermaid
flowchart TB
    subgraph FastAPI[FastAPI 单进程]
        Pages[页面与静态资源\nrender_page / NoCacheStaticFiles]
        PublicAPI[公开活动 API\n活动配置 / 二维码 / 提交]
        WallAPI[大屏 API\n快照 / 几何 / WebSocket]
        AdminAPI[管理员 API\n配置 / 审核 / 导出]
        MonitorAPI[监控 API\n统计 / 删除 / 归档]
        Auth[鉴权与会话\nAdmin Bearer / Monitor token / Display cookie]
        Writer[批量提交写入协程\nasyncio.Queue]
        Render[服务端签名 PNG 渲染\nrender_strokes_png]
    end

    subgraph Browser[前端脚本]
        Mobile[mobile.js\nCanvas + 横屏映射]
        Display[display.js\nWebSocket + 动画]
        Layout[wallLayout.js\n确定性落位与尺寸]
        Signature[signature.js\n矢量笔迹渲染]
        Sync[wallSync.js\n几何同步]
        Export[wallExport.js\n大屏 PNG 重绘]
        AdminUI[admin.js\n活动与审核]
        MonitorUI[monitor.js\n轮询与下载]
    end

    DB[(SQLite\nevents / submissions / wall_geometry)]
    Files[static/assets/background.png\n无品牌默认背景]

    Pages --> Browser
    PublicAPI --> Auth
    WallAPI --> Auth
    AdminAPI --> Auth
    MonitorAPI --> Auth
    PublicAPI --> Writer
    Writer --> DB
    WallAPI --> DB
    AdminAPI --> DB
    MonitorAPI --> DB
    MonitorAPI --> Render
    Render --> DB
    Display --> Layout
    Display --> Signature
    Display --> Sync
    Export --> Layout
    Export --> Signature
    AdminUI --> Signature
    MonitorUI --> Signature
    Display --> Files
    Export --> Files
```

## 3. 提交与实时展示时序

```mermaid
sequenceDiagram
    participant U as 参会者手机
    participant A as FastAPI
    participant Q as 批量写入队列
    participant D as SQLite WAL
    participant W as 大屏 WebSocket

    U->>A: POST /api/events/{slug}/submissions\nname + strokes + device_token
    A->>A: 状态、署名、限流、笔迹和请求大小校验
    A->>Q: 入队并等待 future
    Q->>D: 批量 INSERT submissions
    D-->>Q: 返回 row
    Q-->>A: 完成 future
    A->>W: broadcast(type=submission, item)
    A-->>U: 201 Created
    W-->>W: 更新 Map、重新计算布局、绘制 Canvas
```

失败路径：写入超时返回 `503`，参与者可以重试；批次异常只影响当前批次，写入协程继续存活。活动不是 `live` 时在进入队列前返回 `409`。

## 4. 大屏布局与 PNG 导出时序

```mermaid
sequenceDiagram
    participant B as /display 浏览器
    participant A as FastAPI
    participant M as /monitor 浏览器
    participant L as wallLayout.js
    participant E as wallExport.js

    B->>A: GET /display
    A-->>B: HTML + HttpOnly sign_board_display Cookie
    B->>A: GET /api/events/{slug}/display
    A-->>B: event + approved items
    B->>L: stage size + QR bounds + item count
    L-->>B: positions + metrics
    B->>A: POST /api/events/{slug}/wall-geometry\n同源 Cookie + bounded geometry
    A-->>B: 200 OK

    M->>A: GET /api/monitor/events/{slug}\nmonitor token/session
    A-->>M: recent items + stats
    M->>A: GET /api/events/{slug}/wall-geometry
    A-->>M: last wall geometry
    M->>E: renderWallPng(items, geometry)
    E->>L: 同一布局函数与逻辑舞台尺寸
    L-->>E: 与大屏一致的位置
    E->>E: 加载背景图，重绘矢量笔迹和姓名
    E-->>M: PNG Blob 下载
```

几何写入只允许近期打开过 `/display` 的同源浏览器会话。Cookie 是范围受限的显示能力，不是管理员凭据；严格的宽高、比例和像素限制是第二道防线。

## 5. 数据模型

```mermaid
erDiagram
    EVENTS ||--o{ SUBMISSIONS : contains
    EVENTS ||--o| WALL_GEOMETRY : reports

    EVENTS {
        integer id PK
        text slug UK
        text title
        text subtitle
        text organization
        text welcome_text
        text theme
        text status
        integer display_limit
        real qr_scale
        text created_at
        text updated_at
    }

    SUBMISSIONS {
        integer id PK
        integer event_id FK
        text name
        text organization
        text message
        text signature_data "legacy PNG/JPEG DataURL"
        text stroke_data "primary JSON coordinates"
        text device_hash
        text status
        text created_at
        text approved_at
        text displayed_at
    }

    WALL_GEOMETRY {
        integer event_id PK,FK
        integer stage_width
        integer stage_height
        real qr_left
        real qr_right
        real qr_top
        real qr_bottom
        integer signature_count
        text updated_at
    }
```

当前数据库是单文件 SQLite，启用 WAL、外键和 busy timeout。`init_db()` 会在启动时补充历史列；这能支持当前部署升级，但还不是可审计的迁移系统。

## 6. 信任边界

```mermaid
flowchart LR
    Public[公开输入\n姓名 / strokes / display geometry]
    Operator[受保护输入\nAdmin Bearer / Monitor token]
    Server[服务端校验与清理]
    Store[(SQLite)]
    Wall[公开输出\napproved display snapshot]
    Archive[受保护输出\nCSV / ZIP / PNG]

    Public --> Server
    Operator --> Server
    Server --> Store
    Store --> Wall
    Store --> Archive
```

- 公开提交只允许读取公开活动配置和写入自己的签名；文本长度、控制字符、笔迹点数和状态由服务端约束。
- 管理员令牌以 Bearer 形式发送，管理员配置和审核接口不会被公开页面调用。
- 监控令牌允许下载和删除，因此必须按可写凭据管理，不应公开转发。
- 大屏快照只返回 `approved` 记录；`hidden`、`rejected` 不进入展示数据。
- 导出数据包含姓名和签名，属于个人数据，应在活动结束后按保留策略处理。
