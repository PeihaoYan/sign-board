from __future__ import annotations

import asyncio
import base64
import binascii
import csv
import hashlib
import hmac
import io
import json
import os
import secrets
import sqlite3
import struct
import time
import zipfile
import zlib
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote

from app import __version__
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

try:
    import qrcode
    from qrcode.image.svg import SvgPathImage
except ImportError:  # pragma: no cover - dependency is installed in the runtime image
    qrcode = None
    SvgPathImage = None


ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "static"
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data"))
DB_PATH = DATA_DIR / "sign-board.sqlite3"
SIGNATURE_DIR = DATA_DIR / "signatures"
DEFAULT_SLUG = os.getenv("EVENT_SLUG", "integrity-2026")
EVENT_STATUSES = {"draft", "live", "paused", "ended"}
# New deployments start closed until an operator explicitly opens the event. Existing databases keep
# their stored status, so this only changes the status of an event created for the first time.
DEFAULT_EVENT_STATUS = os.getenv("EVENT_STATUS", "draft").strip().lower() or "draft"
# There is no safe built-in administrator credential. The service refuses to start until
# deployment supplies one explicitly, so a copied compose file cannot expose the admin API.
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "").strip()
# Read-only credential for the on-site monitor page. Falls back to the admin token
# so a single-credential deployment keeps working unchanged.
MONITOR_TOKEN = os.getenv("MONITOR_TOKEN", "").strip() or ADMIN_TOKEN
MONITOR_COOKIE = "sign_board_monitor"
DISPLAY_COOKIE = "sign_board_display"
MONITOR_SESSION_TTL = 8 * 60 * 60
MONITOR_LINK_TTL = 10 * 60
DISPLAY_SESSION_TTL = 2 * 60 * 60
# Public address used in generated QR codes, for example https://wall.example.com.
# Falls back to the request's own Host header when it is not set.
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip()
MAX_SIGNATURE_BYTES = 420_000
PNG_HEADER = b"\x89PNG\r\n\x1a\n"
JPEG_HEADER = b"\xff\xd8\xff"
SIGNATURE_PREFIXES = ("data:image/png;base64,", "data:image/jpeg;base64,")
MAX_STROKES = 60
MAX_STROKE_POINTS = 6000
MAX_STROKE_COORDINATE = 4000
MAX_REQUEST_BYTES = 512_000
# Geometry is reported by a public display page, so bound it before it can influence
# the monitor's canvas allocation or the persisted export layout.
MIN_WALL_STAGE_WIDTH = 320
MAX_WALL_STAGE_WIDTH = 7680
MIN_WALL_STAGE_HEIGHT = 180
MAX_WALL_STAGE_HEIGHT = 4320
MAX_WALL_STAGE_PIXELS = 16_777_216
MIN_WALL_ASPECT = 1.25
MAX_WALL_ASPECT = 2.4
# Fixed size for the PNG rendered out of stroke coordinates (used by the archive export).
STROKE_PNG_WIDTH = 600
STROKE_PNG_HEIGHT = 300
STROKE_PNG_LINE = 7
STROKE_PNG_PAD = 14


def render_strokes_png(strokes: list[Any], width: int = STROKE_PNG_WIDTH, height: int = STROKE_PNG_HEIGHT) -> bytes | None:
    """Draw stroke points as white lines on a transparent RGBA PNG.

    Signatures are stored as coordinates, so the archive has to rasterise them here.
    Drawing them white keeps the same look as the wall, where the ink sits directly on
    the venue background with nothing behind it.
    """
    points = [point for stroke in strokes if isinstance(stroke, list) for point in stroke if isinstance(point, list) and len(point) == 2]
    if not points:
        return None

    min_x = min(point[0] for point in points)
    max_x = max(point[0] for point in points)
    min_y = min(point[1] for point in points)
    max_y = max(point[1] for point in points)
    span_x = max(max_x - min_x, 1)
    span_y = max(max_y - min_y, 1)
    drawable_width = max(width - STROKE_PNG_PAD * 2, 1)
    drawable_height = max(height - STROKE_PNG_PAD * 2, 1)
    # Preserve the aspect ratio and centre the ink inside the canvas.
    scale = min(drawable_width / span_x, drawable_height / span_y)
    offset_x = (width - span_x * scale) / 2 - min_x * scale
    offset_y = (height - span_y * scale) / 2 - min_y * scale

    pixels = bytearray(width * height * 4)

    def paint(cx: int, cy: int) -> None:
        radius = STROKE_PNG_LINE // 2
        for dy in range(-radius, radius + 1):
            y = cy + dy
            if y < 0 or y >= height:
                continue
            for dx in range(-radius, radius + 1):
                x = cx + dx
                if x < 0 or x >= width or dx * dx + dy * dy > radius * radius + radius:
                    continue
                offset = (y * width + x) * 4
                pixels[offset] = 255
                pixels[offset + 1] = 255
                pixels[offset + 2] = 255
                pixels[offset + 3] = 255

    for stroke in strokes:
        if not isinstance(stroke, list) or not stroke:
            continue
        scaled = [
            (point[0] * scale + offset_x, point[1] * scale + offset_y)
            for point in stroke
            if isinstance(point, list) and len(point) == 2
        ]
        if not scaled:
            continue
        if len(scaled) == 1:
            paint(int(round(scaled[0][0])), int(round(scaled[0][1])))
            continue
        for index in range(1, len(scaled)):
            x0, y0 = scaled[index - 1]
            x1, y1 = scaled[index]
            steps = max(abs(x1 - x0), abs(y1 - y0), 1)
            for step in range(int(steps) + 1):
                ratio = step / steps
                paint(int(round(x0 + (x1 - x0) * ratio)), int(round(y0 + (y1 - y0) * ratio)))

    rows = bytearray()
    for y in range(height):
        rows.append(0)  # filter type: none
        start = y * width * 4
        rows.extend(pixels[start : start + width * 4])

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return len(payload).to_bytes(4, "big") + tag + payload + zlib.crc32(tag + payload).to_bytes(4, "big")

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        PNG_HEADER
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(rows), 6))
        + chunk(b"IEND", b"")
    )



class NoCacheStaticFiles(StaticFiles):
    """Serve the frontend without client caching.

    A browser holding an older copy of display.js or mobile.js keeps running stale
    logic (for example looking for a rendered signature image while the server now
    sends stroke points), which shows up as blank signatures on the wall. These files
    are small and come from the same hosts that already fetch the event data, so
    revalidating on every load is the safer trade.
    """

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


def validate_configuration() -> None:
    if not ADMIN_TOKEN:
        raise RuntimeError("ADMIN_TOKEN must be set before starting sign-board")
    if DEFAULT_EVENT_STATUS not in EVENT_STATUSES:
        allowed = ", ".join(sorted(EVENT_STATUSES))
        raise RuntimeError(f"EVENT_STATUS must be one of: {allowed}")


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_configuration()
    init_db()
    install_shutdown_signal_handlers()
    yield


def install_shutdown_signal_handlers() -> None:
    """Close the display sockets when the service is asked to stop.

    Uvicorn's graceful shutdown waits for every open connection to finish, and the wall's WebSocket
    is open by design — it stays open for the whole event. Without this, `systemctl restart
    sign-board` sits in "deactivating" until systemd's 90 second stop timeout kills the process
    (measured), which is a bad thing to discover while deploying before an event. Closing each socket
    with code 1001 lets the shutdown finish in about a second; the wall then reconnects on its own.
    """
    import signal

    loop = asyncio.get_running_loop()
    for name in ("SIGTERM", "SIGINT"):
        number = getattr(signal, name, None)
        if number is None:
            continue
        try:
            loop.add_signal_handler(number, lambda: asyncio.ensure_future(close_all_sockets()))
        except (NotImplementedError, RuntimeError):  # pragma: no cover - Windows/test loops
            # Windows event loops do not support signal handlers; the process is stopped outright
            # there, so there is nothing to close.
            continue


async def close_all_sockets() -> None:
    """Ask every connected display to disconnect, so uvicorn can finish shutting down."""
    async with _connections_lock:
        sockets = [socket for group in _connections.values() for socket in group]
        _connections.clear()
    for socket in sockets:
        try:
            await socket.close(code=1001)
        except Exception:  # noqa: BLE001 - a socket that is already gone is not a problem
            continue


app = FastAPI(title="科研诚信签名板", version=__version__, lifespan=lifespan)
app.mount("/assets", NoCacheStaticFiles(directory=STATIC_DIR), name="assets")


@app.middleware("http")
async def disable_page_caching(request: Request, call_next):
    """Keep the HTML entry points fresh, for the same reason as the static files."""
    response = await call_next(request)
    if request.url.path in ("/", "/display", "/mobile", "/admin", "/monitor"):
        response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response


def asset_version() -> str:
    """Content hash of the frontend files, injected into the page asset URLs.

    The version changes whenever any asset changes, so a browser that somehow kept an
    older copy still fetches the new file instead of silently running stale code.
    """
    digest = hashlib.sha256()
    for path in sorted(STATIC_DIR.glob("*.js")) + sorted(STATIC_DIR.glob("*.css")):
        try:
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
        except OSError:  # pragma: no cover - file removed mid-flight
            continue
    return digest.hexdigest()[:12]


def render_page(filename: str) -> HTMLResponse:
    html = (STATIC_DIR / filename).read_text(encoding="utf-8")
    default_event_script = (
        "<script>window.__SIGN_BOARD_DEFAULT_EVENT__ = "
        f"{json.dumps(DEFAULT_SLUG)};"
        "</script>"
    )
    rendered = html.replace("__ASSET_VERSION__", asset_version())
    rendered = rendered.replace("</head>", f"{default_event_script}\n</head>", 1)
    return HTMLResponse(
        rendered,
        headers={"Cache-Control": "no-store, must-revalidate"},
    )


def render_display_page(request: Request) -> HTMLResponse:
    response = render_page("display.html")
    response.set_cookie(
        DISPLAY_COOKIE,
        display_session_value(),
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=DISPLAY_SESSION_TTL,
        path="/",
    )
    return response


_db_lock = asyncio.Lock()
_connections: dict[str, set[WebSocket]] = {}
_connections_lock = asyncio.Lock()
_rate_state: dict[str, list[float]] = {}
_rate_lock = asyncio.Lock()
_monitor_grants: dict[str, float] = {}


class SubmissionCreate(BaseModel):
    name: str = Field(default="", max_length=60)
    organization: str = Field(default="", max_length=120)
    message: str = Field(default="", max_length=180)
    # Preferred form: raw stroke points rendered on the display, so the wall shows ink
    # only, with no background image of any kind.
    strokes: list[list[list[int]]] = Field(default_factory=list)
    # Fallback for older clients that can only send a rendered image.
    signature_data: str = Field(default="", max_length=120_000)
    device_token: str = Field(default="", max_length=100)


class EventUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=80)
    subtitle: str | None = Field(default=None, max_length=160)
    organization: str | None = Field(default=None, max_length=120)
    welcome_text: str | None = Field(default=None, max_length=220)
    theme: str | None = Field(default=None, max_length=40)
    status: str | None = Field(default=None, max_length=20)
    display_limit: int | None = Field(default=None, ge=12, le=500)
    # How large the floating QR card is drawn on the big screen, as a multiple of its default size.
    # The upper bound is what still leaves room for signatures: at 3.0 the card covers a third of
    # the stage's width and the placement has very little left to work with.
    qr_scale: float | None = Field(default=None, ge=0.5, le=3.0)


class StatusUpdate(BaseModel):
    status: str = Field(max_length=20)


class QrBox(BaseModel):
    """Box of the floating QR card, in percentages of the stage."""

    left: float = Field(ge=-100, le=200)
    right: float = Field(ge=-100, le=200)
    top: float = Field(ge=-100, le=200)
    bottom: float = Field(ge=-100, le=200)


class WallGeometryUpdate(BaseModel):
    """Size of the wall's stage and where the QR card sits inside it.

    Reported by the display page after it lays the signatures out. The display session and
    conservative bounds protect the monitor export from forged or pathological geometry.
    """

    stageWidth: int = Field(ge=MIN_WALL_STAGE_WIDTH, le=MAX_WALL_STAGE_WIDTH)
    stageHeight: int = Field(ge=MIN_WALL_STAGE_HEIGHT, le=MAX_WALL_STAGE_HEIGHT)
    qr: QrBox | None = None
    # How many signatures the wall was showing. It decides how large each one is drawn, so the
    # monitor needs it to reproduce the arrangement.
    count: int | None = Field(default=None, ge=0, le=20000)


SCHEMA = """
PRAGMA journal_mode = WAL;
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    subtitle TEXT NOT NULL DEFAULT '',
    organization TEXT NOT NULL DEFAULT '',
    welcome_text TEXT NOT NULL DEFAULT '',
    theme TEXT NOT NULL DEFAULT 'integrity',
    status TEXT NOT NULL DEFAULT 'draft',
    display_limit INTEGER NOT NULL DEFAULT 42,
    qr_scale REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    name TEXT NOT NULL DEFAULT '',
    organization TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    signature_data TEXT NOT NULL,
    stroke_data TEXT NOT NULL DEFAULT '',
    device_hash TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'approved',
    created_at TEXT NOT NULL,
    approved_at TEXT,
    displayed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_submissions_event_status ON submissions(event_id, status, id DESC);
CREATE INDEX IF NOT EXISTS idx_submissions_device ON submissions(event_id, device_hash, created_at);
CREATE TABLE IF NOT EXISTS wall_geometry (
    event_id INTEGER PRIMARY KEY REFERENCES events(id) ON DELETE CASCADE,
    stage_width INTEGER NOT NULL,
    stage_height INTEGER NOT NULL,
    qr_left REAL,
    qr_right REAL,
    qr_top REAL,
    qr_bottom REAL,
    signature_count INTEGER,
    updated_at TEXT NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def db_connection() -> Iterator[sqlite3.Connection]:
    """Open a short-lived connection, commit on success and always close it.

    sqlite3's own context manager only commits; it never closes, so relying on it
    would leak one file descriptor per request. Closing explicitly keeps the file
    descriptor count flat, which is what matters when a burst of a thousand
    participants arrives at once.

    WAL is enabled on every connection: in the default rollback-journal mode each
    write transaction creates and removes a journal file and locks the whole
    database, and at high concurrency that is what makes SQLite report
    "unable to open database file". Opening can transiently fail under that
    pressure, so it is retried briefly before giving up.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SIGNATURE_DIR.mkdir(parents=True, exist_ok=True)

    last_error: Exception | None = None
    for attempt in range(DB_OPEN_RETRIES):
        try:
            connection = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
            break
        except sqlite3.OperationalError as error:
            last_error = error
            time.sleep(0.05 * (attempt + 1))
    else:
        assert last_error is not None
        raise last_error

    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA journal_mode = WAL")
    except sqlite3.OperationalError:
        # A read-only or exotic filesystem may refuse WAL; the app still works.
        pass
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def clean_text(value: str, limit: int) -> str:
    value = "".join(char for char in str(value).strip() if char in "\n\t" or ord(char) >= 32)
    return value[:limit]


MIGRATIONS = (
    (1, "submissions", "stroke_data", "TEXT NOT NULL DEFAULT ''"),
    (2, "events", "qr_scale", "REAL NOT NULL DEFAULT 1.0"),
    (3, "wall_geometry", "signature_count", "INTEGER"),
)


def apply_migrations(connection: sqlite3.Connection) -> None:
    """Apply small, idempotent schema changes and record each version.

    The base schema contains the current columns so a new database is created in one pass. The
    versioned checks keep upgrades from older deployments auditable and make future migrations
    explicit instead of accumulating anonymous ALTER TABLE calls in startup code.
    """
    applied = {
        row["version"]
        for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
    }
    for version, table, column, definition in MIGRATIONS:
        if version not in applied:
            columns = {
                row["name"] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if column not in columns:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            connection.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, utc_now()),
            )


def init_db() -> None:
    now = utc_now()
    with db_connection() as connection:
        connection.executescript(SCHEMA)
        apply_migrations(connection)
        existing = connection.execute("SELECT id FROM events WHERE slug = ?", (DEFAULT_SLUG,)).fetchone()
        if existing is None:
            connection.execute(
                """
                INSERT INTO events
                    (slug, title, subtitle, organization, welcome_text, theme, status, display_limit, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 42, ?, ?)
                """,
                (
                    DEFAULT_SLUG,
                    os.getenv("EVENT_TITLE", "科研诚信研讨会"),
                    os.getenv("EVENT_SUBTITLE", "以诚立身，以实求真"),
                    os.getenv("EVENT_ORGANIZATION", "科研诚信主题活动"),
                    "留下您的签名，共同守护诚实、严谨、可复现的科研环境。",
                    "integrity",
                    DEFAULT_EVENT_STATUS,
                    now,
                    now,
                ),
            )


def fetch_event(slug: str) -> sqlite3.Row | None:
    with db_connection() as connection:
        return connection.execute("SELECT * FROM events WHERE slug = ?", (slug,)).fetchone()


# ---------------------------------------------------------------------------
# Write path
#
# SQLite durably commits with one fsync per transaction. Under a burst (500
# participants submitting at once) that becomes the bottleneck: every request
# waits for its own fsync and for the write lock. Submissions are therefore
# funnelled through a single writer coroutine that commits whole batches at
# once, which keeps a burst fast while only ever having one writer in flight.
# ---------------------------------------------------------------------------
SUBMISSION_BATCH_MAX = int(os.getenv("SUBMISSION_BATCH_MAX", "200"))
SUBMISSION_BATCH_INTERVAL = float(os.getenv("SUBMISSION_BATCH_INTERVAL", "0.03"))
SUBMISSION_TIMEOUT = float(os.getenv("SUBMISSION_TIMEOUT", "20"))
DB_OPEN_RETRIES = int(os.getenv("DB_OPEN_RETRIES", "4"))

# State is kept per event loop. A running server uses exactly one loop, while the
# test client creates a fresh loop per test, and a writer bound to a dead loop
# would otherwise leave requests waiting forever.
_pending_by_loop: dict[asyncio.AbstractEventLoop, asyncio.Queue] = {}
_writer_by_loop: dict[asyncio.AbstractEventLoop, asyncio.Task] = {}


async def _submission_writer(queue: asyncio.Queue) -> None:
    """Consume the submission queue and commit in batches.

    The whole body is wrapped in try/except: if an exception escaped this task the
    writer would silently die, leaving every later request waiting on a future that
    nobody ever resolves (the submission endpoint would hang forever). A failed
    batch therefore fails only its own requests and the loop keeps running.
    """
    while True:
        first = await queue.get()
        batch = [first]
        deadline = time.monotonic() + SUBMISSION_BATCH_INTERVAL
        while len(batch) < SUBMISSION_BATCH_MAX:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                batch.append(await asyncio.wait_for(queue.get(), timeout=remaining))
            except asyncio.TimeoutError:
                break

        try:
            inserted: list[tuple[asyncio.Future, sqlite3.Row]] = []
            error: Exception | None = None
            try:
                with db_connection() as connection:
                    for event_id, record, future in batch:
                        cursor = connection.execute(
                            """
                            INSERT INTO submissions
                                (event_id, name, organization, message, signature_data, stroke_data, device_hash, status, created_at, approved_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, 'approved', ?, ?)
                            """,
                            (
                                event_id,
                                record["name"],
                                record["organization"],
                                record["message"],
                                record["signature_data"],
                                record.get("stroke_data", ""),
                                record["device_hash"],
                                record["created_at"],
                                record["created_at"],
                            ),
                        )
                        row = connection.execute(
                            "SELECT * FROM submissions WHERE id = ?", (cursor.lastrowid,)
                        ).fetchone()
                        inserted.append((future, row))
            except Exception as caught:
                error = caught

            if error is not None:
                for _, _, future in batch:
                    if not future.done():
                        future.set_exception(error)
            else:
                for future, row in inserted:
                    if not future.done():
                        future.set_result(row)
        except Exception:  # pragma: no cover - the writer must never die
            continue


def _writer_state() -> tuple[asyncio.Queue, asyncio.Task]:
    loop = asyncio.get_running_loop()
    queue = _pending_by_loop.get(loop)
    task = _writer_by_loop.get(loop)
    if queue is None:
        queue = asyncio.Queue()
        _pending_by_loop[loop] = queue
    if task is None or task.done():
        task = loop.create_task(_submission_writer(queue))
        _writer_by_loop[loop] = task
    return queue, task


async def store_submission(event_id: int, record: dict[str, Any]) -> sqlite3.Row:
    queue, _ = _writer_state()
    future: asyncio.Future = asyncio.get_running_loop().create_future()
    await queue.put((event_id, record, future))
    try:
        # A bounded wait turns an unexpected stall into a fast 503 that the
        # participant can retry, instead of a request that hangs forever.
        return await asyncio.wait_for(future, timeout=SUBMISSION_TIMEOUT)
    except asyncio.TimeoutError as error:
        raise HTTPException(status_code=503, detail="服务繁忙，请稍后重试") from error


def event_or_404(slug: str) -> sqlite3.Row:
    event = fetch_event(slug)
    if event is None:
        raise HTTPException(status_code=404, detail="活动不存在")
    return event


def event_payload(event: sqlite3.Row) -> dict[str, Any]:
    with db_connection() as connection:
        total = connection.execute(
            "SELECT COUNT(*) AS count FROM submissions WHERE event_id = ? AND status != 'rejected'",
            (event["id"],),
        ).fetchone()["count"]
        approved = connection.execute(
            "SELECT COUNT(*) AS count FROM submissions WHERE event_id = ? AND status = 'approved'",
            (event["id"],),
        ).fetchone()["count"]
    return {
        "slug": event["slug"],
        "title": event["title"],
        "subtitle": event["subtitle"],
        "organization": event["organization"],
        "welcome_text": event["welcome_text"],
        "theme": event["theme"],
        "status": event["status"],
        "display_limit": event["display_limit"],
        "qr_scale": event["qr_scale"] if "qr_scale" in event.keys() else 1.0,
        "stats": {"total": total, "approved": approved},
    }


def submission_payload(row: sqlite3.Row) -> dict[str, Any]:
    keys = row.keys()
    strokes: Any = []
    raw_strokes = row["stroke_data"] if "stroke_data" in keys else ""
    if raw_strokes:
        try:
            strokes = json.loads(raw_strokes)
        except ValueError:
            strokes = []
    return {
        "id": row["id"],
        "name": row["name"],
        "organization": row["organization"],
        "message": row["message"],
        "signature_data": row["signature_data"],
        "strokes": strokes,
        "status": row["status"],
        "created_at": row["created_at"],
    }


def get_submission(submission_id: int, slug: str) -> sqlite3.Row | None:
    with db_connection() as connection:
        return connection.execute(
            """
            SELECT submissions.* FROM submissions
            JOIN events ON events.id = submissions.event_id
            WHERE submissions.id = ? AND events.slug = ?
            """,
            (submission_id, slug),
        ).fetchone()


def clean_strokes(strokes: list[list[list[int]]]) -> str:
    """Validate stroke points and return them as compact JSON.

    Points are canvas pixel coordinates. They are the primary representation because
    drawing them on the display produces pure ink: a rendered image would always
    carry its own background behind the white stroke.

    Out-of-range coordinates are clamped rather than rejected: a stroke that started
    at the edge of the canvas, or a client rounding artifact, must never cost the
    participant their submission. The display crops whatever falls outside its own box.
    """
    if len(strokes) > MAX_STROKES:
        raise HTTPException(status_code=422, detail="笔迹数据过大")
    cleaned: list[list[list[int]]] = []
    total = 0
    for stroke in strokes:
        if not stroke:
            continue
        points: list[list[int]] = []
        for point in stroke:
            if len(point) != 2:
                raise HTTPException(status_code=422, detail="笔迹数据格式无效")
            x, y = point
            clamped_x = min(max(int(x), 0), MAX_STROKE_COORDINATE)
            clamped_y = min(max(int(y), 0), MAX_STROKE_COORDINATE)
            points.append([clamped_x, clamped_y])
        total += len(points)
        if total > MAX_STROKE_POINTS:
            raise HTTPException(status_code=422, detail="笔迹数据过大")
        cleaned.append(points)
    if not cleaned:
        return ""
    return json.dumps(cleaned, separators=(",", ":"))


def decode_signature(signature_data: str) -> bytes:
    prefix = next((item for item in SIGNATURE_PREFIXES if signature_data.startswith(item)), None)
    if prefix is None:
        raise HTTPException(status_code=422, detail="签名必须为 PNG 或 JPEG 图片")
    encoded = signature_data[len(prefix):]
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise HTTPException(status_code=422, detail="签名图片格式无效") from error
    valid_header = raw.startswith(PNG_HEADER) if prefix.endswith("png;base64,") else raw.startswith(JPEG_HEADER)
    if len(raw) > MAX_SIGNATURE_BYTES or not valid_header:
        raise HTTPException(status_code=422, detail="签名图片过大或格式无效")
    return raw


async def allow_submission(key: str) -> bool:
    now = time.monotonic()
    async with _rate_lock:
        recent = [stamp for stamp in _rate_state.get(key, []) if now - stamp < 60]
        # A shared venue Wi-Fi means many participants can appear as one client IP,
        # so the per-minute budget stays generous while still stopping scripted floods.
        if len(recent) >= 30:
            _rate_state[key] = recent
            return False
        recent.append(now)
        _rate_state[key] = recent
        if len(_rate_state) > 2500:
            for old_key, stamps in list(_rate_state.items()):
                if not stamps or now - stamps[-1] > 300:
                    _rate_state.pop(old_key, None)
        return True


def admin_token_from_request(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "):
        return ""
    return authorization[7:].strip()


def require_admin(request: Request) -> bool:
    token = admin_token_from_request(request)
    if not token or not hmac.compare_digest(token, ADMIN_TOKEN):
        raise HTTPException(status_code=401, detail="管理员凭据无效")
    return True


def monitor_session_value(timestamp: int | None = None) -> str:
    """Create a short-lived signed session without placing the long-lived token in a cookie."""
    issued_at = int(time.time()) if timestamp is None else timestamp
    nonce = secrets.token_urlsafe(24)
    payload = f"{issued_at}.{nonce}"
    signature = hmac.new(MONITOR_TOKEN.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def valid_monitor_session(value: str) -> bool:
    try:
        issued_at_text, nonce, signature = value.split(".", 2)
        issued_at = int(issued_at_text)
        if not nonce:
            return False
    except (AttributeError, ValueError):
        return False
    now = int(time.time())
    if issued_at > now + 60 or now - issued_at > MONITOR_SESSION_TTL:
        return False
    payload = f"{issued_at_text}.{nonce}"
    expected = hmac.new(MONITOR_TOKEN.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def issue_monitor_link() -> str:
    now = time.time()
    for key, expires_at in list(_monitor_grants.items()):
        if expires_at <= now:
            _monitor_grants.pop(key, None)
    key = secrets.token_urlsafe(32)
    _monitor_grants[key] = now + MONITOR_LINK_TTL
    return key


def redeem_monitor_link(key: str) -> bool:
    expires_at = _monitor_grants.pop(key, None)
    return expires_at is not None and expires_at > time.time()


def monitor_token_from_request(request: Request) -> str:
    """Accept a bearer/query credential or resolve a signed short-lived monitor session."""
    direct = admin_token_from_request(request) or request.query_params.get("key", "")
    if direct:
        return direct
    if valid_monitor_session(request.cookies.get(MONITOR_COOKIE, "")):
        return MONITOR_TOKEN
    return ""


def require_monitor(request: Request) -> bool:
    """Access for the on-site monitor page."""
    token = monitor_token_from_request(request)
    if not token or not hmac.compare_digest(token, MONITOR_TOKEN):
        raise HTTPException(status_code=401, detail="监控凭据无效")
    return True


def require_monitor_or_admin(request: Request) -> bool:
    """Monitor endpoints used by on-site staff and the admin console."""
    token = monitor_token_from_request(request)
    if not token:
        raise HTTPException(status_code=401, detail="凭据无效")
    if hmac.compare_digest(token, MONITOR_TOKEN) or hmac.compare_digest(token, ADMIN_TOKEN):
        return True
    raise HTTPException(status_code=401, detail="凭据无效")


def display_session_value(timestamp: int | None = None) -> str:
    """Create a short-lived, signed capability for a browser that loaded /display."""
    issued_at = int(time.time()) if timestamp is None else timestamp
    payload = str(issued_at)
    signature = hmac.new(ADMIN_TOKEN.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def valid_display_session(value: str) -> bool:
    try:
        payload, signature = value.split(".", 1)
        issued_at = int(payload)
    except (AttributeError, ValueError):
        return False
    now = int(time.time())
    if issued_at > now + 60 or now - issued_at > DISPLAY_SESSION_TTL:
        return False
    expected = hmac.new(ADMIN_TOKEN.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def require_display_session(request: Request) -> bool:
    """Allow geometry writes only from a recently loaded display session.

    The display is intentionally public, so this is a scoped capability and CSRF boundary rather
    than an administrator credential. It prevents arbitrary cross-site POSTs while strict geometry
    bounds below limit the impact of a client that can open the display itself.
    """
    if not valid_display_session(request.cookies.get(DISPLAY_COOKIE, "")):
        raise HTTPException(status_code=401, detail="大屏会话无效或已过期")
    return True


async def broadcast(slug: str, message: dict[str, Any]) -> None:
    async with _connections_lock:
        sockets = list(_connections.get(slug, set()))
    stale: list[WebSocket] = []
    for socket in sockets:
        try:
            await socket.send_json(message)
        except Exception:
            stale.append(socket)
    if stale:
        async with _connections_lock:
            current = _connections.get(slug, set())
            for socket in stale:
                current.discard(socket)


@app.get("/health")
async def health() -> dict[str, Any]:
    try:
        event = await asyncio.to_thread(fetch_event, DEFAULT_SLUG)
        return {"status": "ok", "service": "sign-board", "event": DEFAULT_SLUG, "database": event is not None}
    except Exception as error:  # pragma: no cover - operational fallback
        return JSONResponse(status_code=503, content={"status": "error", "detail": str(error)})


@app.get("/api/events/{slug}")
async def public_event(slug: str) -> dict[str, Any]:
    event = event_or_404(slug)
    return event_payload(event)


@app.get("/api/events/{slug}/display")
async def public_display(slug: str) -> dict[str, Any]:
    event = event_or_404(slug)
    with db_connection() as connection:
        rows = connection.execute(
            """
            SELECT * FROM submissions
            WHERE event_id = ? AND status = 'approved'
            ORDER BY id DESC LIMIT ?
            """,
            (event["id"], event["display_limit"]),
        ).fetchall()
    return {"event": event_payload(event), "items": [submission_payload(row) for row in reversed(rows)]}


def wall_geometry_payload(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    qr = None
    if row["qr_left"] is not None:
        qr = {
            "left": row["qr_left"],
            "right": row["qr_right"],
            "top": row["qr_top"],
            "bottom": row["qr_bottom"],
        }
    return {
        "stageWidth": row["stage_width"],
        "stageHeight": row["stage_height"],
        "qr": qr,
        "count": row["signature_count"],
        "updated_at": row["updated_at"],
        "source": "wall",
    }


@app.get("/api/events/{slug}/wall-geometry")
async def public_wall_geometry(slug: str) -> dict[str, Any]:
    """The geometry the big screen last laid its signatures out with.

    The wall places every signature in percentages of its own stage and the placement rule weighs
    candidates in pixels of that stage, so a picture laid out on another size would not be the
    arrangement the audience is looking at. The display page reports what it used; the monitor
    page reads it back before building its PNG export.
    """
    event = event_or_404(slug)
    with db_connection() as connection:
        row = connection.execute(
            "SELECT * FROM wall_geometry WHERE event_id = ?",
            (event["id"],),
        ).fetchone()
    return {"event_slug": slug, "geometry": wall_geometry_payload(row)}


@app.post("/api/events/{slug}/wall-geometry")
async def report_wall_geometry(
    slug: str,
    payload: WallGeometryUpdate,
    _: bool = Depends(require_display_session),
) -> dict[str, Any]:
    """Called by the big screen after every layout, so the monitor's export can match it."""
    aspect = payload.stageWidth / payload.stageHeight
    if not MIN_WALL_ASPECT <= aspect <= MAX_WALL_ASPECT:
        raise HTTPException(status_code=422, detail="大屏尺寸比例无效")
    if payload.stageWidth * payload.stageHeight > MAX_WALL_STAGE_PIXELS:
        raise HTTPException(status_code=422, detail="大屏像素尺寸过大")
    event = event_or_404(slug)
    now = utc_now()
    with db_connection() as connection:
        connection.execute(
            """
            INSERT INTO wall_geometry
                (event_id, stage_width, stage_height, qr_left, qr_right, qr_top, qr_bottom,
                 signature_count, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                stage_width = excluded.stage_width,
                stage_height = excluded.stage_height,
                qr_left = excluded.qr_left,
                qr_right = excluded.qr_right,
                qr_top = excluded.qr_top,
                qr_bottom = excluded.qr_bottom,
                signature_count = excluded.signature_count,
                updated_at = excluded.updated_at
            """,
            (
                event["id"],
                payload.stageWidth,
                payload.stageHeight,
                payload.qr.left if payload.qr else None,
                payload.qr.right if payload.qr else None,
                payload.qr.top if payload.qr else None,
                payload.qr.bottom if payload.qr else None,
                payload.count,
                now,
            ),
        )
    return {"ok": True, "updated_at": now}


@app.get("/api/events/{slug}/qr.svg")
async def event_qr(request: Request, slug: str) -> Response:
    event_or_404(slug)
    if qrcode is None or SvgPathImage is None:
        raise HTTPException(status_code=503, detail="二维码组件尚未安装")
    if PUBLIC_BASE_URL:
        # An explicit public address wins: the QR code must keep working when the page is
        # opened through a reverse proxy or a temporary tunnel whose Host header differs.
        base = PUBLIC_BASE_URL.rstrip("/")
    else:
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
        host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc)).split(",")[0].strip()
        base = f"{scheme}://{host}"
    target = f"{base}/mobile?event={quote(slug)}"
    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=2)
    code.add_data(target)
    code.make(fit=True)
    image = code.make_image(image_factory=SvgPathImage)
    svg = image.to_string()
    if isinstance(svg, str):
        svg = svg.encode("utf-8")
    return Response(content=svg, media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


@app.get("/api/events/{slug}/public-url")
async def event_public_url(request: Request, slug: str) -> dict[str, Any]:
    """The address participants should open; used by the admin console to show the QR link."""
    event_or_404(slug)
    if PUBLIC_BASE_URL:
        base = PUBLIC_BASE_URL.rstrip("/")
    else:
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
        host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc)).split(",")[0].strip()
        base = f"{scheme}://{host}"
    return {"base_url": base, "mobile_url": f"{base}/mobile?event={quote(slug)}", "configured": bool(PUBLIC_BASE_URL)}


@app.post("/api/events/{slug}/submissions", status_code=201)
async def create_submission(slug: str, payload: SubmissionCreate, request: Request) -> dict[str, Any]:
    event = event_or_404(slug)
    if event["status"] != "live":
        raise HTTPException(status_code=409, detail="当前活动暂未开放提交")
    declared_length = request.headers.get("content-length")
    if declared_length and declared_length.isdigit() and int(declared_length) > MAX_REQUEST_BYTES:
        raise HTTPException(status_code=413, detail="提交内容过大")
    client_ip = request.client.host if request.client else "unknown"
    device_token = clean_text(payload.device_token, 100) or secrets.token_urlsafe(18)
    rate_key = hashlib.sha256(f"{slug}:{client_ip}:{device_token}".encode()).hexdigest()
    if not await allow_submission(rate_key):
        raise HTTPException(status_code=429, detail="提交过于频繁，请稍后再试")
    stroke_data = clean_strokes(payload.strokes)
    if stroke_data:
        # Vector strokes are the primary representation; no rendered image is needed.
        signature_data = ""
    else:
        decode_signature(payload.signature_data)
        signature_data = payload.signature_data
    # The name is required: the wall credits every signature to a participant. Records made
    # before this was enforced may still carry an empty name and are shown as anonymous.
    name = clean_text(payload.name, 60)
    if not name:
        raise HTTPException(status_code=422, detail="请填写署名")
    now = utc_now()
    device_hash = hashlib.sha256(device_token.encode()).hexdigest()
    row = await store_submission(
        event["id"],
        {
            "name": name,
            "organization": "",
            "message": "",
            "signature_data": signature_data,
            "stroke_data": stroke_data,
            "device_hash": device_hash,
            "created_at": now,
        },
    )
    item = submission_payload(row)
    await broadcast(slug, {"type": "submission", "item": item})
    return {"ok": True, "item": item}


@app.websocket("/ws/events/{slug}/display")
async def display_socket(websocket: WebSocket, slug: str) -> None:
    event = fetch_event(slug)
    if event is None:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    async with _connections_lock:
        _connections.setdefault(slug, set()).add(websocket)
    try:
        snapshot = await public_display(slug)
        await websocket.send_json({"type": "snapshot", **snapshot})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        async with _connections_lock:
            _connections.get(slug, set()).discard(websocket)


@app.post("/api/admin/login")
async def admin_login(request: Request) -> dict[str, Any]:
    if not hmac.compare_digest(admin_token_from_request(request), ADMIN_TOKEN):
        raise HTTPException(status_code=401, detail="管理员凭据无效")
    return {"ok": True}


@app.get("/api/monitor/events/{slug}")
async def monitor_snapshot(slug: str, response: Response, _: bool = Depends(require_monitor_or_admin)) -> dict[str, Any]:
    """Read-only operations view: counters, recent activity and connection health."""
    event = event_or_404(slug)
    now = datetime.now(timezone.utc)
    with db_connection() as connection:
        rows = connection.execute(
            "SELECT id, name, organization, message, signature_data, stroke_data, status, created_at FROM submissions WHERE event_id = ? ORDER BY id DESC",
            (event["id"],),
        ).fetchall()

    def age_seconds(row: sqlite3.Row) -> float:
        try:
            created = datetime.fromisoformat(row["created_at"])
        except ValueError:
            return float("inf")
        return (now - created).total_seconds()

    counted = [row for row in rows if row["status"] != "rejected"]
    approved = [row for row in rows if row["status"] == "approved"]
    last_minute = [row for row in counted if age_seconds(row) <= 60]
    last_ten = [row for row in counted if age_seconds(row) <= 600]

    response.headers["Cache-Control"] = "no-store"
    return {
        "server_time": now.isoformat(timespec="seconds"),
        "event": event_payload(event),
        "stats": {
            "total": len(counted),
            "approved": len(approved),
            "hidden": len([row for row in rows if row["status"] == "hidden"]),
            "rejected": len([row for row in rows if row["status"] == "rejected"]),
            "last_minute": len(last_minute),
            "last_ten_minutes": len(last_ten),
            "last_submission": counted[0]["created_at"] if counted else None,
        },
        # Reuse the shared payload builder so the monitor feed can never drift from
        # what the wall and the admin console receive.
        "recent": [submission_payload(row) for row in rows[:15]],
    }


class MonitorDeleteRequest(BaseModel):
    ids: list[int] = Field(default_factory=list, max_length=300)


class MonitorSessionRequest(BaseModel):
    key: str = Field(default="", max_length=200)


@app.post("/api/monitor/events/{slug}/submissions/delete")
async def monitor_delete_submissions(
    slug: str,
    payload: MonitorDeleteRequest,
    _: bool = Depends(require_monitor_or_admin),
) -> dict[str, Any]:
    """Delete the given submissions from the on-site monitor page.

    This is a deliberate write capability for the duty operator: the monitor credential
    is meant to be usable by on-site staff, so it must be treated as sensitive.
    """
    event = event_or_404(slug)
    if not payload.ids:
        raise HTTPException(status_code=422, detail="没有选择要删除的签名")
    deleted = await delete_submissions_by_id(event, payload.ids)
    return {"ok": True, "deleted": deleted, "requested": len(payload.ids)}


def render_submission_signature(row: sqlite3.Row) -> bytes | None:
    """Render vector strokes and fall back to legacy image data for an archive entry."""
    stroke_data = row["stroke_data"] if "stroke_data" in row.keys() else ""
    if stroke_data:
        try:
            rendered = render_strokes_png(json.loads(stroke_data))
        except (TypeError, ValueError):
            rendered = None
        if rendered is not None:
            return rendered
    if row["signature_data"]:
        try:
            return decode_signature(row["signature_data"])
        except HTTPException:
            return None
    return None


@app.get("/api/monitor/events/{slug}/archive.zip")
async def monitor_archive(slug: str, _: bool = Depends(require_monitor_or_admin)) -> StreamingResponse:
    """Download every submission of the event, with each signature rendered to PNG."""
    event = event_or_404(slug)
    with db_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM submissions WHERE event_id = ? ORDER BY id",
            (event["id"],),
        ).fetchall()

    archive = io.BytesIO()
    manifest = io.StringIO(newline="")
    writer = csv.writer(manifest)
    writer.writerow(["id", "name", "organization", "message", "status", "created_at", "signature_file"])
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for row in rows:
            signature_file = f"signatures/{row['id']}.png"
            rendered = render_submission_signature(row)
            if rendered is not None:
                bundle.writestr(signature_file, rendered)
            writer.writerow([
                row["id"], row["name"], row["organization"], row["message"], row["status"],
                row["created_at"], signature_file if rendered is not None else "",
            ])
        bundle.writestr("submissions.csv", manifest.getvalue().encode("utf-8-sig"))
    archive.seek(0)
    return StreamingResponse(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{slug}-signatures.zip"'},
    )


@app.post("/api/monitor/session")
async def monitor_session(request: Request, payload: MonitorSessionRequest, response: Response) -> dict[str, Any]:
    """Exchange a monitor token or one-time link for a short-lived httpOnly session."""
    valid_key = (
        payload.key
        and (
            hmac.compare_digest(payload.key, MONITOR_TOKEN)
            or hmac.compare_digest(payload.key, ADMIN_TOKEN)
            or redeem_monitor_link(payload.key)
        )
    )
    if not valid_key:
        raise HTTPException(status_code=401, detail="监控凭据无效")
    response.set_cookie(
        MONITOR_COOKIE,
        monitor_session_value(),
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=MONITOR_SESSION_TTL,
        path="/",
    )
    return {"ok": True, "expires_in": MONITOR_SESSION_TTL}


@app.post("/api/monitor/logout")
async def monitor_logout(response: Response) -> dict[str, Any]:
    response.delete_cookie(MONITOR_COOKIE, path="/")
    return {"ok": True}


@app.post("/api/admin/logout")
async def admin_logout() -> dict[str, Any]:
    return {"ok": True}


@app.get("/api/admin/events/{slug}")
async def admin_event(slug: str, _: bool = Depends(require_admin)) -> dict[str, Any]:
    event = event_or_404(slug)
    return event_payload(event)


@app.post("/api/admin/events/{slug}/monitor-link")
async def admin_monitor_link(slug: str, _: bool = Depends(require_admin)) -> dict[str, Any]:
    """Create a short-lived one-time code for the on-site monitor page."""
    event_or_404(slug)
    return {"key": issue_monitor_link(), "expires_in": MONITOR_LINK_TTL}


@app.put("/api/admin/events/{slug}")
async def update_event(slug: str, payload: EventUpdate, _: bool = Depends(require_admin)) -> dict[str, Any]:
    event = event_or_404(slug)
    updates: dict[str, Any] = {}
    for field in ("title", "subtitle", "organization", "welcome_text", "theme", "status", "display_limit", "qr_scale"):
        value = getattr(payload, field)
        if value is not None:
            if isinstance(value, str):
                value = clean_text(value, 220)
            if field == "status" and value not in EVENT_STATUSES:
                raise HTTPException(status_code=422, detail="活动状态无效")
            updates[field] = value
    if not updates:
        return event_payload(event)
    updates["updated_at"] = utc_now()
    assignments = ", ".join(f"{column} = ?" for column in updates)
    async with _db_lock:
        def update() -> None:
            with db_connection() as connection:
                connection.execute(
                    f"UPDATE events SET {assignments} WHERE id = ?",
                    (*updates.values(), event["id"]),
                )
        await asyncio.to_thread(update)
    updated = event_or_404(slug)
    await broadcast(slug, {"type": "event", "event": event_payload(updated)})
    return event_payload(updated)


@app.get("/api/admin/events/{slug}/submissions")
async def admin_submissions(slug: str, status: str = "all", _: bool = Depends(require_admin)) -> dict[str, Any]:
    event = event_or_404(slug)
    allowed = {"all", "pending", "approved", "hidden", "rejected"}
    if status not in allowed:
        raise HTTPException(status_code=422, detail="筛选状态无效")
    query = "SELECT * FROM submissions WHERE event_id = ?"
    params: list[Any] = [event["id"]]
    if status != "all":
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY id DESC LIMIT 500"
    with db_connection() as connection:
        rows = connection.execute(query, params).fetchall()
    return {"items": [submission_payload(row) for row in rows]}


@app.put("/api/admin/events/{slug}/submissions/{submission_id}/status")
async def update_submission_status(
    slug: str,
    submission_id: int,
    payload: StatusUpdate,
    _: bool = Depends(require_admin),
) -> dict[str, Any]:
    event = event_or_404(slug)
    allowed = {"pending", "approved", "hidden", "rejected"}
    if payload.status not in allowed:
        raise HTTPException(status_code=422, detail="签名状态无效")
    row = get_submission(submission_id, slug)
    if row is None:
        raise HTTPException(status_code=404, detail="签名不存在")
    now = utc_now()
    approved_at = now if payload.status == "approved" else row["approved_at"]
    async with _db_lock:
        def update() -> None:
            with db_connection() as connection:
                connection.execute(
                    "UPDATE submissions SET status = ?, approved_at = ? WHERE id = ? AND event_id = ?",
                    (payload.status, approved_at, submission_id, event["id"]),
                )
        await asyncio.to_thread(update)
    updated = get_submission(submission_id, slug)
    assert updated is not None
    item = submission_payload(updated)
    if payload.status == "approved":
        await broadcast(slug, {"type": "submission", "item": item})
    else:
        await broadcast(slug, {"type": "remove", "id": submission_id})
    return {"ok": True, "item": item}


@app.delete("/api/admin/events/{slug}/submissions/{submission_id}")
async def delete_submission(slug: str, submission_id: int, _: bool = Depends(require_admin)) -> dict[str, Any]:
    event = event_or_404(slug)
    deleted = await delete_submissions_by_id(event, [submission_id])
    if not deleted:
        raise HTTPException(status_code=404, detail="签名不存在")
    return {"ok": True}


async def delete_submissions_by_id(event: sqlite3.Row, ids: list[int]) -> int:
    """Delete submissions belonging to the event and tell every wall to drop them."""
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    async with _db_lock:
        def delete() -> int:
            with db_connection() as connection:
                cursor = connection.execute(
                    f"DELETE FROM submissions WHERE event_id = ? AND id IN ({placeholders})",
                    (event["id"], *ids),
                )
                return cursor.rowcount
        deleted = await asyncio.to_thread(delete)
    if deleted:
        for submission_id in ids:
            await broadcast(event["slug"], {"type": "remove", "id": submission_id})
    return deleted


def fetch_submissions_by_ids(event: sqlite3.Row, ids: list[int]) -> list[sqlite3.Row]:
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    with db_connection() as connection:
        return connection.execute(
            f"SELECT * FROM submissions WHERE event_id = ? AND id IN ({placeholders}) ORDER BY id",
            (event["id"], *ids),
        ).fetchall()


@app.get("/api/admin/events/{slug}/export.csv")
async def export_csv(slug: str, _: bool = Depends(require_admin)) -> StreamingResponse:
    event = event_or_404(slug)
    with db_connection() as connection:
        rows = connection.execute(
            "SELECT id, name, organization, message, status, created_at, approved_at FROM submissions WHERE event_id = ? ORDER BY id",
            (event["id"],),
        ).fetchall()
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["id", "name", "organization", "message", "status", "created_at", "approved_at"])
    for row in rows:
        writer.writerow([row[key] for key in ("id", "name", "organization", "message", "status", "created_at", "approved_at")])
    content = output.getvalue().encode("utf-8-sig")
    return StreamingResponse(
        io.BytesIO(content),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{slug}-submissions.csv"'},
    )


@app.get("/api/admin/events/{slug}/export.zip")
async def export_zip(slug: str, _: bool = Depends(require_admin)) -> StreamingResponse:
    event = event_or_404(slug)
    with db_connection() as connection:
        rows = connection.execute("SELECT * FROM submissions WHERE event_id = ? ORDER BY id", (event["id"],)).fetchall()
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        manifest = io.StringIO(newline="")
        writer = csv.writer(manifest)
        writer.writerow(["id", "name", "organization", "message", "status", "created_at", "approved_at", "signature_file"])
        for row in rows:
            rendered = render_submission_signature(row)
            signature_file = f"signatures/{row['id']}.png" if rendered is not None else ""
            if rendered is not None:
                bundle.writestr(signature_file, rendered)
            writer.writerow([
                row["id"], row["name"], row["organization"], row["message"], row["status"],
                row["created_at"], row["approved_at"], signature_file,
            ])
        bundle.writestr("submissions.csv", manifest.getvalue().encode("utf-8-sig"))
    archive.seek(0)
    return StreamingResponse(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{slug}-archive.zip"'},
    )


@app.get("/", include_in_schema=False)
async def root_page(request: Request) -> HTMLResponse:
    return render_display_page(request)


@app.get("/display", include_in_schema=False)
async def display_page(request: Request) -> HTMLResponse:
    return render_display_page(request)


@app.get("/mobile", include_in_schema=False)
async def mobile_page() -> HTMLResponse:
    return render_page("mobile.html")


@app.get("/admin", include_in_schema=False)
async def admin_page() -> HTMLResponse:
    return render_page("admin.html")


@app.get("/monitor", include_in_schema=False)
async def monitor_page() -> HTMLResponse:
    return render_page("monitor.html")
