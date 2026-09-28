# API Overview

服务同时提供 HTML 页面、JSON API、WebSocket 和导出接口。具体字段以运行中的 `/docs` 和 `/openapi.json` 为准。

## Public

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| `GET` | `/health` | none | Health status and database availability |
| `GET` | `/api/events/{slug}` | none | Public event configuration and counters |
| `GET` | `/api/events/{slug}/display` | none | Approved signatures for the wall |
| `GET` | `/api/events/{slug}/qr.svg` | none | Event QR code |
| `GET` | `/api/events/{slug}/public-url` | none | Participant URL used by the admin UI |
| `POST` | `/api/events/{slug}/submissions` | none | Submit name and vector strokes |
| `GET` | `/api/events/{slug}/wall-geometry` | none | Last geometry reported by the wall |
| `POST` | `/api/events/{slug}/wall-geometry` | display cookie | Report bounded wall geometry |
| `GET` | `/ws/events/{slug}/display` | none | Initial snapshot and real-time wall updates |

A submission normally contains:

```json
{
  "name": "Participant",
  "strokes": [[[10, 20], [30, 40]]],
  "device_token": "client-generated-random-value"
}
```

`name` is required. A submission is accepted only while the event is `live`. The service validates request size, text length, stroke count, point count and coordinates; coordinates outside the canvas are clamped.

## Admin

Send `Authorization: Bearer <ADMIN_TOKEN>`.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/admin/login` | Validate the administrator token |
| `GET` | `/api/admin/events/{slug}` | Read editable event configuration |
| `PUT` | `/api/admin/events/{slug}` | Update title, status, display limit and QR scale |
| `POST` | `/api/admin/events/{slug}/monitor-link` | Create a short-lived one-time monitor code |
| `GET` | `/api/admin/events/{slug}/submissions` | List and filter submissions |
| `PUT` | `/api/admin/events/{slug}/submissions/{id}/status` | Approve, hide or reject a submission |
| `DELETE` | `/api/admin/events/{slug}/submissions/{id}` | Permanently delete a submission |
| `GET` | `/api/admin/events/{slug}/export.csv` | Download metadata CSV |
| `GET` | `/api/admin/events/{slug}/export.zip` | Download CSV plus rendered signatures |

## Monitor

The preferred flow is to exchange the one-time code at `POST /api/monitor/session`. The response sets a short-lived `HttpOnly` session cookie.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/monitor/session` | Exchange a monitor token or one-time code |
| `GET` | `/api/monitor/events/{slug}` | Read counters and recent submissions |
| `POST` | `/api/monitor/events/{slug}/submissions/delete` | Delete selected submissions |
| `GET` | `/api/monitor/events/{slug}/archive.zip` | Download event signature archive |
| `POST` | `/api/monitor/logout` | Remove the monitor session cookie |

Monitor deletion is intentionally destructive. Treat monitor credentials as write-capable credentials.

## Status codes

- `200`: successful read or update;
- `201`: submission created;
- `401`: missing or invalid credentials;
- `404`: event or submission does not exist;
- `409`: event is not open for submission;
- `413`: request is too large;
- `422`: invalid field, status, geometry or empty delete selection;
- `429`: submission rate limit exceeded;
- `503`: submission writer or backing database is temporarily unavailable.
