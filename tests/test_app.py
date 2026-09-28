import base64
import io
import os
import re
import shutil
import sqlite3
import struct
import sys
import zipfile
from pathlib import Path

# Each run starts from an empty database. Without this the suite reads whatever the previous run left
# behind — submissions still approved, a wall geometry still reported — and a handful of assertions
# that expect a fresh event then fail for reasons that have nothing to do with the code. The data
# directory is this file's own scratch folder, so nothing a person or the live service cares about is
# ever touched.
DATA_DIR = Path(__file__).parent / ".test-data"
if DATA_DIR.exists():
    shutil.rmtree(DATA_DIR, ignore_errors=True)

os.environ["DATA_DIR"] = str(DATA_DIR)
os.environ["ADMIN_TOKEN"] = "test-admin-token"
os.environ["EVENT_SLUG"] = "test-event"
os.environ["EVENT_TITLE"] = "测试签名墙"
os.environ["EVENT_STATUS"] = "live"

from fastapi.testclient import TestClient

from app.main import app

# The static files are checked directly as well as through the app.
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


# Tiny valid PNG used to exercise the upload validation without external fixtures.
PNG_DATA = "data:image/png;base64," + base64.b64encode(
    bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d49444154789c6360f8cf00000003000100c9fe92ef0000000049454e44ae426082"
    )
).decode()


def test_public_flow_and_exports():
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
        assert client.get("/openapi.json").json()["info"]["version"] == "1.0.0"

        event = client.get("/api/events/test-event")
        assert event.status_code == 200
        assert event.json()["title"] == "测试签名墙"

        qr = client.get("/api/events/test-event/qr.svg")
        assert qr.status_code == 200
        assert "svg" in qr.headers["content-type"]

        submission = client.post(
            "/api/events/test-event/submissions",
            json={
                "name": "测试参与者",
                "organization": "测试课题组",
                "message": "以真实数据支撑每一个结论",
                "signature_data": PNG_DATA,
                "device_token": "test-device",
            },
        )
        assert submission.status_code == 201
        submission_id = submission.json()["item"]["id"]

        display = client.get("/api/events/test-event/display")
        assert display.status_code == 200
        assert display.json()["items"][0]["id"] == submission_id

        vector = client.post(
            "/api/events/test-event/submissions",
            json={
                "name": "矢量导出",
                "strokes": [[[10, 20], [80, 45], [150, 30]]],
                "device_token": "vector-export",
            },
        )
        assert vector.status_code == 201
        vector_id = vector.json()["item"]["id"]

        admin_headers = {"Authorization": "Bearer test-admin-token"}
        rows = client.get("/api/admin/events/test-event/submissions", headers=admin_headers)
        assert rows.status_code == 200
        listed_names = {item["name"] for item in rows.json()["items"]}
        assert {"测试参与者", "矢量导出"} <= listed_names

        hidden = client.put(
            f"/api/admin/events/test-event/submissions/{submission_id}/status",
            headers=admin_headers,
            json={"status": "hidden"},
        )
        assert hidden.status_code == 200
        visible_ids = [item["id"] for item in client.get("/api/events/test-event/display").json()["items"]]
        assert submission_id not in visible_ids
        assert vector_id in visible_ids

        csv_export = client.get("/api/admin/events/test-event/export.csv", headers=admin_headers)
        assert csv_export.status_code == 200
        assert "测试参与者" in csv_export.content.decode("utf-8-sig")

        zip_export = client.get("/api/admin/events/test-event/export.zip", headers=admin_headers)
        assert zip_export.status_code == 200
        assert zip_export.content[:2] == b"PK"
        with zipfile.ZipFile(io.BytesIO(zip_export.content)) as bundle:
            assert f"signatures/{vector_id}.png" in bundle.namelist()
            assert "矢量导出" in bundle.read("submissions.csv").decode("utf-8-sig")


def test_schema_migrations_are_recorded():
    database = DATA_DIR / "sign-board.sqlite3"
    with sqlite3.connect(database) as connection:
        versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")]
    assert versions == [1, 2, 3]


def test_realtime_snapshot_and_authentication():
    with TestClient(app) as client:
        assert client.get("/api/admin/events/test-event").status_code == 401
        with client.websocket_connect("/ws/events/test-event/display") as socket:
            snapshot = socket.receive_json()
            assert snapshot["type"] == "snapshot"
            assert snapshot["event"]["slug"] == "test-event"


def test_monitor_page_exposes_download_and_clear():
    with TestClient(app) as client:
        page = client.get("/monitor")
        assert page.status_code == 200
        # The monitor page can download the wall and clear the page it shows. The PNG is the big
        # screen, not this page's table, so it loads the wall's layout and export modules.
        assert "下载大屏 PNG" in page.text
        assert "下载签名 ZIP" in page.text
        assert "清空当前页" in page.text
        for asset in ("wallLayout.js", "wallExport.js", "wallSync.js"):
            assert asset in page.text, asset

        # Without a credential the monitor API refuses access.
        assert client.get("/api/monitor/events/test-event").status_code == 401
        assert client.get("/api/monitor/events/test-event?key=wrong-token").status_code == 401

        client.post(
            "/api/events/test-event/submissions",
            json={
                "name": "监控测试",
                "message": "只读监控",
                "signature_data": PNG_DATA,
                "device_token": "monitor-device",
            },
        )

        authorized = client.get("/api/monitor/events/test-event?key=test-admin-token")
        assert authorized.status_code == 200
        payload = authorized.json()
        assert payload["stats"]["total"] >= 1
        assert payload["stats"]["hidden"] >= 0
        assert payload["recent"][0]["name"] == "监控测试"
        assert "server_time" in payload
        assert authorized.headers.get("cache-control") == "no-store"

        # Read-only: the monitor surface exposes no way to change data.
        assert client.delete("/api/monitor/events/test-event").status_code == 405
        assert client.put("/api/monitor/events/test-event", json={"status": "paused"}).status_code == 405


def test_monitor_link_uses_one_time_code_and_signed_cookie():
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer test-admin-token"}
        grant = client.post("/api/admin/events/test-event/monitor-link", headers=headers)
        assert grant.status_code == 200
        key = grant.json()["key"]
        assert key and key != "test-admin-token"

        exchanged = client.post("/api/monitor/session", json={"key": key})
        assert exchanged.status_code == 200
        cookie = client.cookies.get("sign_board_monitor")
        assert cookie and cookie != "test-admin-token"
        assert client.get("/api/monitor/events/test-event").status_code == 200

        # A monitor link cannot be replayed after it has created a session.
        assert client.post("/api/monitor/session", json={"key": key}).status_code == 401


def test_wall_geometry_round_trip():
    """The big screen reports the geometry it laid out with, so the monitor's PNG can match it."""
    with TestClient(app) as client:
        empty = client.get("/api/events/test-event/wall-geometry")
        assert empty.status_code == 200
        assert empty.json()["geometry"] is None

        unauthorised = client.post(
            "/api/events/test-event/wall-geometry",
            json={"stageWidth": 1920, "stageHeight": 1044, "qr": None, "count": 12},
        )
        assert unauthorised.status_code == 401
        display_page = client.get("/display")
        assert display_page.status_code == 200
        set_cookie = display_page.headers.get("set-cookie", "")
        assert "sign_board_display=" in set_cookie
        assert "HttpOnly" in set_cookie and "SameSite=lax" in set_cookie

        reported = client.post(
            "/api/events/test-event/wall-geometry",
            json={
                "stageWidth": 1920,
                "stageHeight": 1044,
                "qr": {"left": 76.2, "right": 99.1, "top": 58.4, "bottom": 92.7},
                "count": 200,
            },
        )
        assert reported.status_code == 200
        assert reported.json()["ok"] is True

        stored = client.get("/api/events/test-event/wall-geometry").json()["geometry"]
        assert stored["stageWidth"] == 1920
        assert stored["stageHeight"] == 1044
        assert stored["qr"]["left"] == 76.2
        # The crowd size travels with the geometry: it decides how large each signature is drawn.
        assert stored["count"] == 200
        assert stored["source"] == "wall"

        # A later report replaces the earlier one: only the current arrangement matters.
        client.post(
            "/api/events/test-event/wall-geometry",
            json={"stageWidth": 1600, "stageHeight": 900, "qr": None, "count": 12},
        )
        replaced = client.get("/api/events/test-event/wall-geometry").json()["geometry"]
        assert replaced["stageWidth"] == 1600
        assert replaced["qr"] is None
        assert replaced["count"] == 12

        # Nonsense is rejected instead of being stored and breaking the monitor's export.
        assert client.post(
            "/api/events/test-event/wall-geometry",
            json={"stageWidth": 0, "stageHeight": 900, "qr": None},
        ).status_code == 422
        assert client.post(
            "/api/events/test-event/wall-geometry",
            json={"stageWidth": 200, "stageHeight": 20000, "qr": None},
        ).status_code == 422
        assert client.post(
            "/api/events/test-event/wall-geometry",
            json={"stageWidth": 1920, "stageHeight": 1920, "qr": None},
        ).status_code == 422
        assert client.get("/api/events/does-not-exist/wall-geometry").status_code == 404


def test_signature_size_shrinks_with_the_crowd():
    """A busy wall draws smaller signatures, and no size may be written twice.

    The bubble size, the placement grid and the exported PNG all have to agree, so the sizes are
    derived from the signature count in one place (`wallLayout.metricsFor`) and the stylesheet
    reads them from CSS variables instead of hard-coding them.
    """
    layout_js = (STATIC_DIR / "wallLayout.js").read_text(encoding="utf-8")
    display_js = (STATIC_DIR / "display.js").read_text(encoding="utf-8")
    export_js = (STATIC_DIR / "wallExport.js").read_text(encoding="utf-8")
    styles = re.sub(r"/\*.*?\*/", "", (STATIC_DIR / "styles.css").read_text(encoding="utf-8"), flags=re.S)

    # The ladder is ordered and ends in a floor, so a huge crowd still gets a usable size.
    ladder = layout_js.split("const SCALE_LADDER = [", 1)[1].split("];", 1)[0]
    thresholds = [int(match) for match in re.findall(r"upTo: (\d+)", ladder)]
    scales = [float(match) for match in re.findall(r"scale: ([0-9.]+)", ladder)]
    assert thresholds == sorted(thresholds) and len(set(thresholds)) == len(thresholds)
    assert scales == sorted(scales, reverse=True), "a bigger crowd must not get bigger signatures"
    assert min(scales) >= 0.4, "below this the ink stops being legible on a projector"
    assert "0.6" in ladder, "the round 200-signature case keeps the measured scale"

    # The grid step trails the bubble, so neighbours never touch.
    metrics = layout_js.split("function metricsFor(count, options) {", 1)[1].split("\n  }", 1)[0]
    assert "stepWidth" in metrics and "stepHeight" in metrics
    assert "BUBBLE_GAP" in metrics
    # The handwriting occupies part of the bubble rather than almost all of it, and the same share
    # thins the pen: shrinking the ink without thinning the line turns a signature into a row of bars.
    assert "INK_SIZE_FACTOR" in layout_js, "the ink size is a named constant, so it can be tuned"
    factor = float(re.search(r"const INK_SIZE_FACTOR = ([0-9.]+)", layout_js).group(1))
    assert 0.4 <= factor <= 0.95, f"the ink share is out of the range a wall can read: {factor}"
    assert "inkScale" in metrics, "the renderer needs the same factor to thin the pen"
    display_js = (STATIC_DIR / "display.js").read_text(encoding="utf-8")
    export_js = (STATIC_DIR / "wallExport.js").read_text(encoding="utf-8")
    assert "metrics.inkScale" in display_js, "the wall must thin the pen with the ink"
    assert "metrics.inkScale" in export_js, "the exported picture must match the wall's pen"
    # The signature size is a share of the stage, so it follows the screen instead of staying at a
    # fixed number of pixels; the crowd only decides the rest of it.
    assert "REFERENCE_STAGE" in layout_js
    assert "stageScaleFor" in layout_js
    assert "stageWidth" in metrics and "stageHeight" in metrics, "the metrics must know the stage"
    compute = layout_js.split("function computeWallLayout(items, options) {", 1)[1].split("\n  }", 1)[0]
    assert "stageWidth," in compute or "stageWidth" in compute, "the stage must reach the metrics"

    # A crowded wall is spread out with a minimum spacing, a sparse one keeps the sequential
    # placement. The crowded rule must keep the spacing (the ladder) and must not fall back to a
    # lattice: a lattice is what made the wall look mechanical.
    assert "SCATTER_FROM" in layout_js
    assert "scatterLayout" in layout_js
    assert "SCATTER_RADII" in layout_js, "the spacing ladder is what keeps a crowd from overlapping"
    assert "latticeLayout" not in layout_js, "a lattice puts every signature within a pixel of its cell"

    # Both surfaces read the metrics: the wall through CSS variables, the export through the
    # shared metrics object.
    assert "applyBubbleMetrics" in display_js
    assert "metrics.inkWidth" in display_js
    assert "layout.metrics" in export_js
    assert "metrics.width" in export_js

    # The stylesheet must not pin the sizes it is told about.
    for selector in (".signature-bubble {", ".signature-ink {", ".signature-name {"):
        block = styles.split(selector, 1)[1].split("}", 1)[0]
        assert "px" not in block or "var(" in block, selector
    assert "var(--bubble-width)" in styles
    assert "var(--ink-width)" in styles
    assert "var(--name-size)" in styles


def test_export_draws_ink_and_leaves_the_qr_card_out():
    """The PNG export must draw stroke ink and must not draw the QR card.

    Both were reported from the field: the ink came out shrunk and misplaced because the transform
    chain in signature.js was wrong, and the QR card was drawn into a picture that is meant to be
    shown or forwarded.
    """
    signature_js = (STATIC_DIR / "signature.js").read_text(encoding="utf-8")
    export_js = (STATIC_DIR / "wallExport.js").read_text(encoding="utf-8")

    strokes = signature_js.split("function drawStrokes", 1)[1].split("\n  }", 1)[0]
    # The caller's transform is composed with, not replaced: `setTransform` alone threw away the
    # bubble's translation, rotation and scale.
    assert "context.transform(outer.a" in strokes
    assert "outer" in strokes
    # And the device-pixel ratio must not be folded into the ink transform a second time.
    assert "scale * ratio" not in strokes
    assert "lineWidth.width / scale" in strokes

    # The device-pixel scale is passed in, and the box that is drawn is the caller's transform.
    ink = signature_js.split("function drawInk", 1)[1].split("\n  }", 1)[0]
    assert "settings.dpr" in ink
    assert "outerTransform" in ink
    # A caller that has already scaled the context must not hand the same scale over again: the two
    # multiply, which is how the ink became stretched and clipped on denser screens.
    assert "context.resetTransform()" in signature_js, "the ink transform must compose, not replace"
    render = signature_js.split("function render(canvas, item, options)", 1)[1].split("\n  }", 1)[0]
    assert "dpr: 1" in render, "the scaled context already covers the bitmap ratio"

    # No QR card in the picture.
    assert "drawQrCard" not in export_js
    assert "qr.svg" not in export_js
    assert "The QR card is deliberately not drawn" in export_js


def test_writing_board_is_dark_with_white_ink():
    """The phone's writing board is dark, because the ink is white.

    On a pale board the stroke is the low-contrast element; a dark board makes the phone look like
    the wall and keeps the gold hints legible. The contrast is checked rather than the colour alone,
    since a "dark" board with dark hints would pass a colour test and still be unreadable.
    """
    styles = re.sub(r"/\*.*?\*/", "", (STATIC_DIR / "styles.css").read_text(encoding="utf-8"), flags=re.S)

    def rule(selector: str) -> str:
        match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", styles)
        assert match, f"no rule for {selector}"
        return match.group(1)

    board = rule(".canvas-wrap")
    assert "background: var(--board)" in board, "the board must use the dark surface variable"
    assert "var(--paper-deep)" not in board, "the pale board is gone"

    root = styles.split(":root {", 1)[1].split("}", 1)[0]
    match = re.search(r"--board:\s*(#[0-9a-fA-F]{6})", root)
    assert match, "the dark board colour must be defined once"
    red, green, blue = (int(match.group(1)[index:index + 2], 16) for index in (1, 3, 5))

    def luminance(colour: tuple[int, int, int]) -> float:
        def channel(value: int) -> float:
            share = value / 255
            return share / 12.92 if share <= 0.03928 else ((share + 0.055) / 1.055) ** 2.4

        parts = [channel(value) for value in colour]
        return 0.2126 * parts[0] + 0.7152 * parts[1] + 0.0722 * parts[2]

    def contrast(first: tuple[int, int, int], second: tuple[int, int, int]) -> float:
        lighter, darker = sorted((luminance(first), luminance(second)), reverse=True)
        return (lighter + 0.05) / (darker + 0.05)

    surface = (red, green, blue)
    assert luminance(surface) <= 0.1, "the board is not dark"
    assert contrast((255, 255, 255), surface) >= 7, "white ink must stand out on the board"

    # The placeholder hint must still be legible on the dark board.
    hint = re.search(r"--board-hint:\s*rgba\((\d+),\s*(\d+),\s*(\d+),\s*([0-9.]+)\)", root)
    assert hint, "the placeholder colour must be defined once"
    hint_colour = tuple(int(hint.group(index)) for index in (1, 2, 3))
    assert contrast(hint_colour, surface) >= 4.5, "the placeholder is too faint on the dark board"


def test_static_files_and_pages_are_not_cached():
    """Stale frontend files made the wall render blank signatures, so nothing is cached."""
    with TestClient(app) as client:
        for path in ("/display", "/mobile", "/admin", "/monitor", "/assets/styles.css", "/assets/display.js"):
            response = client.get(path)
            assert response.status_code == 200, path
            assert "no-store" in response.headers.get("cache-control", ""), path


def test_pages_inject_the_configured_default_event():
    with TestClient(app) as client:
        page = client.get("/display")
        assert page.status_code == 200
        assert 'window.__SIGN_BOARD_DEFAULT_EVENT__ = "test-event";' in page.text


def test_pages_carry_a_content_asset_version():
    """Asset URLs include a content hash so a stale copy can never be reused silently."""
    with TestClient(app) as client:
        page = client.get("/monitor")
        assert page.status_code == 200
        assert "__ASSET_VERSION__" not in page.text
        versions = set(re.findall(r"/assets/[a-zA-Z0-9_.]+\.(?:js|css)\?v=([0-9a-f]+)", page.text))
        assert versions, page.text[:300]
        assert len(versions) == 1
        version = versions.pop()
        assert re.fullmatch(r"[0-9a-f]{12}", version)

        # The stylesheet is reachable with that version query.
        assert client.get(f"/assets/styles.css?v={version}").status_code == 200


def test_submission_accepts_vector_strokes():
    """Strokes are the primary representation: they render as ink with no background."""
    with TestClient(app) as client:
        strokes = [
            [[10, 20], [40, 44], [90, 30]],
            [[120, 25], [160, 60]],
        ]
        created = client.post(
            "/api/events/test-event/submissions",
            json={
                "name": "矢量签名",
                "message": "",
                "strokes": strokes,
                "signature_data": "",
                "device_token": "vector-device",
            },
        )
        assert created.status_code == 201
        item = created.json()["item"]
        assert item["strokes"] == strokes
        # No rendered image is stored for stroke submissions, so nothing can carry a background.
        assert item["signature_data"] == ""

        display = client.get("/api/events/test-event/display")
        assert display.status_code == 200
        listed = [row for row in display.json()["items"] if row["name"] == "矢量签名"]
        assert listed and listed[0]["strokes"] == strokes

        monitor = client.get("/api/monitor/events/test-event?key=test-admin-token")
        assert monitor.status_code == 200
        recent = [row for row in monitor.json()["recent"] if row["name"] == "矢量签名"]
        assert recent and recent[0]["strokes"] == strokes


def test_submission_rejects_invalid_strokes():
    with TestClient(app, raise_server_exceptions=False) as client:
        too_many = [[[index, index] for index in range(7000)]]
        rejected = client.post(
            "/api/events/test-event/submissions",
            json={"name": "超限", "message": "", "strokes": too_many, "signature_data": "", "device_token": "too-many"},
        )
        assert rejected.status_code == 422

        malformed = client.post(
            "/api/events/test-event/submissions",
            json={"name": "坏点", "message": "", "strokes": [[[1, 2, 3]]], "signature_data": "", "device_token": "bad-point"},
        )
        assert malformed.status_code == 422

        empty = client.post(
            "/api/events/test-event/submissions",
            json={"name": "空", "message": "", "strokes": [], "signature_data": "", "device_token": "empty"},
        )
        assert empty.status_code == 422


def test_name_only_submission():
    """The participant page collects only a name, and that name is required."""
    with TestClient(app) as client:
        named = client.post(
            "/api/events/test-event/submissions",
            json={"name": "只有姓名", "strokes": [[[1, 2], [3, 4]]], "device_token": "name-only"},
        )
        assert named.status_code == 201
        assert named.json()["item"]["name"] == "只有姓名"


def test_signature_requires_a_name():
    """The mobile form asks for a name and the server refuses a submission without one."""
    with TestClient(app, raise_server_exceptions=False) as client:
        for payload in (
            {"name": "", "strokes": [[[1, 2], [3, 4]]], "device_token": "no-name"},
            {"name": "   ", "strokes": [[[1, 2], [3, 4]]], "device_token": "blank-name"},
            {"strokes": [[[1, 2], [3, 4]]], "device_token": "missing-name"},
        ):
            refused = client.post("/api/events/test-event/submissions", json=payload)
            assert refused.status_code == 422, payload
            assert "署名" in refused.json()["detail"]

        # A padded name is stored trimmed, not rejected.
        accepted = client.post(
            "/api/events/test-event/submissions",
            json={"name": "  署名必填  ", "strokes": [[[1, 2], [3, 4]]], "device_token": "padded-name"},
        )
        assert accepted.status_code == 201
        assert accepted.json()["item"]["name"] == "署名必填"


def test_strokes_outside_the_canvas_are_clamped_not_rejected():
    """A stroke that leaves the canvas must still be accepted, with points clamped."""
    with TestClient(app) as client:
        created = client.post(
            "/api/events/test-event/submissions",
            json={
                "name": "越界",
                "strokes": [[[-40, -5], [10, 20], [99999, 99999]]],
                "device_token": "out-of-range",
            },
        )
        assert created.status_code == 201
        assert created.json()["item"]["strokes"] == [[[0, 0], [10, 20], [4000, 4000]]]


def test_monitor_can_delete_and_download():
    """The monitor page may clear the page it shows and download signatures."""
    with TestClient(app) as client:
        created = []
        for index in range(3):
            response = client.post(
                "/api/events/test-event/submissions",
                json={
                    "name": f"监控删除{index}",
                    "strokes": [[[10, 20], [60, 40 + index * 10], [120, 30]]],
                    "device_token": f"monitor-delete-{index}",
                },
            )
            assert response.status_code == 201
            created.append(response.json()["item"]["id"])

        # No credential: neither surface is reachable.
        assert client.post("/api/monitor/events/test-event/submissions/delete", json={"ids": created}).status_code == 401
        assert client.get("/api/monitor/events/test-event/archive.zip").status_code == 401

        # Archive: one PNG per signature plus a manifest.
        with TestClient(app) as authorized:
            authorized.post("/api/monitor/session", json={"key": "test-admin-token"})
            archive = authorized.get("/api/monitor/events/test-event/archive.zip")
            assert archive.status_code == 200
            buffer = io.BytesIO(archive.content)
            with zipfile.ZipFile(buffer) as bundle:
                names = bundle.namelist()
                assert "submissions.csv" in names
                signature_files = [name for name in names if name.startswith("signatures/")]
                # The archive covers the whole event, so it must contain at least these.
                for submission_id in created:
                    assert f"signatures/{submission_id}.png" in signature_files
                png = bundle.read(f"signatures/{created[0]}.png")
                assert png.startswith(b"\x89PNG\r\n\x1a\n")
                assert len(png) > 100

            # Delete two of the three through the monitor credential, sent as a bearer
            # token (not the cookie) so the auth path used by the page itself is covered.
            deleted = client.post(
                "/api/monitor/events/test-event/submissions/delete",
                json={"ids": created[:2]},
                headers={"Authorization": "Bearer test-admin-token"},
            )
            assert deleted.status_code == 200
            assert deleted.json()["deleted"] == 2

            # The admin credential also works here, because the same operator often
            # signs in to the admin console; both tokens are equally sensitive.
            assert client.get(
                "/api/monitor/events/test-event",
                headers={"Authorization": "Bearer test-admin-token"},
            ).status_code == 200
            assert client.post(
                "/api/monitor/events/test-event/submissions/delete",
                json={"ids": []},
                headers={"Authorization": "Bearer test-admin-token"},
            ).status_code == 422

            # A wrong credential is still refused.
            assert client.post(
                "/api/monitor/events/test-event/submissions/delete",
                json={"ids": created[2:]},
                headers={"Authorization": "Bearer wrong-token"},
            ).status_code == 401

            remaining = authorized.get("/api/monitor/events/test-event?key=test-admin-token").json()["recent"]
            remaining_ids = [row["id"] for row in remaining]
            assert created[0] not in remaining_ids
            assert created[1] not in remaining_ids
            assert created[2] in remaining_ids

            # An empty selection is rejected rather than wiping the event.
            assert authorized.post(
                "/api/monitor/events/test-event/submissions/delete", json={"ids": []}
            ).status_code == 422


def test_render_strokes_png_draws_ink_on_transparent_background():
    from app import main as app_main

    png = app_main.render_strokes_png([[[0, 0], [100, 50]]])
    assert png is not None
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    width, height = struct.unpack(">II", png[16:24])
    assert (width, height) == (app_main.STROKE_PNG_WIDTH, app_main.STROKE_PNG_HEIGHT)
    # A stroke with no points cannot produce an image.
    assert app_main.render_strokes_png([]) is None


def test_display_limit_accepts_up_to_500():
    """The wall must be able to show 500 signatures at once."""
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer test-admin-token"}
        accepted = client.put("/api/admin/events/test-event", headers=headers, json={"display_limit": 500})
        assert accepted.status_code == 200
        assert accepted.json()["display_limit"] == 500

        too_many = client.put("/api/admin/events/test-event", headers=headers, json={"display_limit": 501})
        assert too_many.status_code == 422

        too_few = client.put("/api/admin/events/test-event", headers=headers, json={"display_limit": 11})
        assert too_few.status_code == 422


def test_qr_size_setting_round_trip():
    """The QR card's size is an event setting: saved, validated, and published to the wall."""
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer test-admin-token"}

        # Every event carries a scale, so the wall never has to guess one.
        initial = client.get("/api/admin/events/test-event", headers=headers)
        assert initial.status_code == 200
        assert initial.json()["qr_scale"] == 1.0

        enlarged = client.put("/api/admin/events/test-event", headers=headers, json={"qr_scale": 2.5})
        assert enlarged.status_code == 200
        assert enlarged.json()["qr_scale"] == 2.5

        # The public display payload carries it too: that is how the wall learns the new size.
        public = client.get("/api/events/test-event/display")
        assert public.status_code == 200
        assert public.json()["event"]["qr_scale"] == 2.5

        # Out-of-range values are refused rather than drawn.
        assert client.put("/api/admin/events/test-event", headers=headers, json={"qr_scale": 0.2}).status_code == 422
        assert client.put("/api/admin/events/test-event", headers=headers, json={"qr_scale": 4}).status_code == 422

        # The admin page offers the control and the wall reads the setting.
        admin_page = client.get("/admin")
        assert admin_page.status_code == 200
        assert 'id="qr-scale-input"' in admin_page.text
        display_script = client.get("/assets/display.js")
        assert "--qr-scale" in display_script.text
        assert "qr_scale" in display_script.text

        restored = client.put("/api/admin/events/test-event", headers=headers, json={"qr_scale": 1.0})
        assert restored.status_code == 200
        assert restored.json()["qr_scale"] == 1.0


def test_public_url_and_qr_follow_the_configured_domain():
    """A configured public address must drive the QR code, not the request's Host header."""
    from app import main as app_main

    with TestClient(app) as client:
        default_url = client.get("/api/events/test-event/public-url")
        assert default_url.status_code == 200
        assert default_url.json()["configured"] is False
        assert default_url.json()["mobile_url"].endswith("/mobile?event=test-event")

        original = app_main.PUBLIC_BASE_URL
        try:
            app_main.PUBLIC_BASE_URL = "https://wall.example.com/"
            configured = client.get("/api/events/test-event/public-url").json()
            assert configured["configured"] is True
            assert configured["base_url"] == "https://wall.example.com"
            assert configured["mobile_url"] == "https://wall.example.com/mobile?event=test-event"
        finally:
            app_main.PUBLIC_BASE_URL = original


def test_writer_survives_a_failed_batch(monkeypatch):
    """A failing batch must not kill the writer coroutine.

    Regression test: db_connection() can raise while opening the database, which
    used to escape the writer task entirely. The writer then died, and every later
    submission waited on a future nobody resolved, so the submission endpoint hung
    forever (observed at 1000+ concurrent submissions during load testing).
    """
    from app import main as app_main

    with TestClient(app, raise_server_exceptions=False) as client:
        real_connection = app_main.db_connection
        calls = {"count": 0}

        def flaky_connection():
            calls["count"] += 1
            # The first call resolves the event; the second is the writer opening
            # its connection, which is the failure that used to kill the writer.
            if calls["count"] == 2:
                raise sqlite3.OperationalError("unable to open database file")
            return real_connection()

        monkeypatch.setattr(app_main, "db_connection", flaky_connection)

        failed = client.post(
            "/api/events/test-event/submissions",
            json={
                "name": "失败批次",
                "message": "",
                "signature_data": PNG_DATA,
                "device_token": "failing-batch",
            },
        )
        assert failed.status_code == 500

        # The writer must still be alive: this submission has to be stored normally.
        recovered = client.post(
            "/api/events/test-event/submissions",
            json={
                "name": "恢复成功",
                "message": "",
                "signature_data": PNG_DATA,
                "device_token": "recovered-batch",
            },
        )
        assert recovered.status_code == 201
        assert recovered.json()["item"]["name"] == "恢复成功"


def test_readme_size_table_matches_the_code():
    """The README's size table must be the values the module computes, not a hand-kept copy.

    It had already drifted — three tiers claimed a 9 px name where `metricsFor` clamps to 8 px, and the
    ink column still held the sizes from before the ink became a share of the bubble. A table nobody
    regenerates is a table that lies, so `tools/update_readme_metrics.py` rewrites it and this test
    fails if it is out of date.
    """
    import subprocess

    root = Path(__file__).resolve().parent.parent
    completed = subprocess.run(
        [sys.executable, str(root / "tools" / "update_readme_metrics.py")],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert "already matches" in completed.stdout, completed.stdout + completed.stderr


def test_landscape_writing_mode_is_a_turned_canvas_in_a_tall_box():
    """The landscape mode must turn the drawing, not the page.

    The design that was asked for: the phone stays upright, the writing box is a tall rectangle, and
    only the canvas content is rotated 90°. Everything that made earlier attempts fail is checked
    here, because each one came back as a bug report: rotating the page (fullscreen, orientation
    lock, viewport surgery), a stylesheet rule fighting the size the layout sets, and a pointer
    mapping that does not invert the rotation.
    """
    raw_styles = (STATIC_DIR / "styles.css").read_text(encoding="utf-8")
    # Comments discuss the traps that were removed, so only declarations are inspected.
    styles = re.sub(r"/\*.*?\*/", "", raw_styles, flags=re.S)
    script = (STATIC_DIR / "mobile.js").read_text(encoding="utf-8")
    markup = (STATIC_DIR / "mobile.html").read_text(encoding="utf-8")

    # The page itself must not be rotated or locked: the canvas is the only thing that turns.
    for forbidden in ("requestFullscreen", "screen.orientation", "fullscreenchange", "applyRotatedLayout"):
        assert forbidden not in script, forbidden
    assert "is-rotated" not in styles, "the page must not be rotated as a whole"
    assert "rotate(90deg)" in script, "the canvas is turned 90°"
    assert "matrixTransform" not in script, "pointer mapping no longer goes through a page transform"

    # The box is tall, and the canvas inside it is turned about its own corner.
    def rule(selector: str) -> str:
        match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", styles)
        assert match, f"no rule for {selector}"
        return match.group(1)

    wrapper_block = rule("body.landscape-mode .canvas-wrap")
    assert "min-height" not in wrapper_block, "the box height comes from measureLandscapeBox()"
    assert "position: relative" in wrapper_block
    assert "position: absolute" in rule("body.landscape-mode #signature-canvas")

    # The two hints are shown in this mode only, and the return button too. The writing guide is
    # turned with the canvas, so its writing line and its text read horizontally once the phone is
    # turned — that is what makes the mode self-explanatory.
    assert "landscape-only" in styles and "landscape-only" in markup
    assert "display: block" in rule("body.landscape-mode .landscape-only")
    guide = rule("body.landscape-mode .canvas-guide")
    assert "rotate(90deg)" in guide, "the guide must be turned with the canvas"
    assert "pointer-events: none" in guide, "the guide must not swallow the touches"
    assert "canvas-guide" in markup, "the guide is a layer over the canvas"
    # Its contents are built in the strip's own coordinate space, because the strip's shape changes
    # with the screen: a fixed viewBox clipped the prompt on one phone and lost it in the middle on
    # the next, which is what the redesign fixed. Nothing about the layout may live in the markup.
    assert "<line" not in markup, "the guide's geometry must be laid out for the strip, not hardcoded"
    assert "<text" not in markup
    for marker in ("buildLandscapeGuide", "setAttribute('viewBox'", "guide-prompt", "guide-mark"):
        assert marker in script, marker
    assert "沿虚线从左到右书写" in script, "the prompt is the guide's first line of text"
    assert "display: block" in rule("body.landscape-mode .landscape-exit")
    assert '>返回<' in markup

    # The name field and the submit button share one row under the box.
    assert "flex-direction: row" in rule("body.landscape-mode .form-side")
    assert "grid-template-columns: minmax(0, 1fr) 200px" not in styles

    # A viewport that is already landscape must not rely on 100vh either: on a phone that is the
    # height without the browser chrome.
    landscape_media = styles.split("@media (orientation: landscape) {", 1)[1]
    assert "body .mobile-shell { min-height: 0; }" in landscape_media

    # The mapping inverts the rotation: a box position (u, v) is the strip position (v, H − u).
    mapping = script.split("function landscapeStripPoint", 1)[1].split("\n  }", 1)[0]
    assert "canvasWrap.getBoundingClientRect()" in mapping, "measure the wrapper, not the turned canvas"
    assert "stripHeight - u" in mapping
    assert "stripWidth" in mapping
    # The canvas's own bounding rectangle is the axis-aligned box of a turned element, so it may
    # only be used when the canvas is not turned.
    rotated_use = script.split("function pointInCanvasSpace", 1)[1].split("function bitmapPoint", 1)[0]
    assert "landscapeStripPoint(event)" in rotated_use
    assert rotated_use.count("getBoundingClientRect") == 1, "only the portrait branch may use the rect"
