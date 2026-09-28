"""Check the keepsake picture against the server: same signatures, nothing altered, nothing dropped.

The picture is drawn from a JSON sidecar of strokes fetched from the event, so the thing worth proving
is that the sidecar is the event's own data — same ids, same names, same points, in the same order —
and that no signature in the event is missing from it. This compares them point by point.

Usage:
    python tools/verify_wall_sheet.py [--sheet deliverables/signature-wall-1920x1080.strokes.json]
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sheet", default="deliverables/signature-wall-1920x1080.strokes.json")
    parser.add_argument("--base", default="http://127.0.0.1:18180")
    parser.add_argument("--slug", default="integrity-2026")
    arguments = parser.parse_args()

    sheet_path = ROOT / arguments.sheet
    if not sheet_path.exists():
        print(f"{sheet_path} does not exist yet; run tools/export_wall_sheet.py first")
        return 1
    sheet = json.loads(sheet_path.read_text(encoding="utf-8"))
    saved = {item["id"]: item for item in sheet["signatures"]}

    token = (ROOT / ".secrets" / "admin-token.txt").read_text(encoding="utf-8").strip()
    request = urllib.request.Request(
        f"{arguments.base}/api/admin/events/{arguments.slug}/submissions",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        rows = json.load(response).get("items", [])
    approved = {row["id"]: row for row in rows if row.get("status") == "approved" and row.get("strokes")}

    print(f"sheet: {len(saved)} signatures, drawn {sheet['exported_at']} from {sheet['source']}")
    print(f"event: {len(approved)} approved signatures with strokes")

    missing = sorted(set(approved) - set(saved))
    extra = sorted(set(saved) - set(approved))
    altered_names = [key for key in saved if key in approved and saved[key]["name"] != approved[key]["name"]]
    altered_points = []
    for key, item in saved.items():
        if key not in approved:
            continue
        mine = [[[round(x, 3), round(y, 3)] for x, y in stroke] for stroke in item["strokes"]]
        theirs = [[[round(x, 3), round(y, 3)] for x, y in stroke] for stroke in approved[key]["strokes"]]
        if mine != theirs:
            altered_points.append(key)

    if missing:
        print(f"FAIL: {len(missing)} signatures in the event are not in the picture: {missing[:8]}")
    if extra:
        print(f"FAIL: the picture holds {len(extra)} signatures the event does not: {extra[:8]}")
    if altered_names:
        print(f"FAIL: {len(altered_names)} names differ from the event: {altered_names[:8]}")
    if altered_points:
        print(f"FAIL: {len(altered_points)} signatures have altered points: {altered_points[:8]}")
    if not (missing or extra or altered_names or altered_points):
        total_points = sum(len(stroke) for item in saved.values() for stroke in item["strokes"])
        print(f"every signature matches the event point for point ({total_points} points preserved)")
    layout = sheet["layout"]
    where = (f"{layout['columns']}x{layout['rows']} cells" if layout.get("columns")
             else f"random spread, clearance {layout.get('scatter_gap')}")
    print(f"layout: {layout.get('style', 'grid')} style, {where}"
          f" {layout['cell'][0]}x{layout['cell'][1]} px,"
          f" shared scale {layout['shared_scale']}, pen {layout['pen_px']} px")
    names = [item["name"] for item in sheet["signatures"]]
    print(f"signers ({len(names)}, in the order they signed): {'、'.join(names)}")
    return 1 if (missing or extra or altered_names or altered_points) else 0


if __name__ == "__main__":
    raise SystemExit(main())
