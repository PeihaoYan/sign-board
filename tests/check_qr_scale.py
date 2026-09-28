"""Check the QR size setting on the wall: does the card scale, and does the placement still fit?

Drives the admin API to set a scale, opens /display at a projector size, and measures the card and
the signatures: the card's share of the stage (which must stay the same as the scale changes), and
whether any signature ends up underneath the card (which is what the setting would break if the card
grew past the room the placement keeps free).

Usage:
    python tests/check_qr_scale.py [--base http://127.0.0.1:18195] [--key probe-token]
                                   [--scales 0.5,1,1.5,2.5,3]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mobile_probe import DevTools, start_edge  # noqa: E402

PROBE = """
(() => {
  const stage = document.querySelector('#wall-stage');
  const card = document.querySelector('.qr-card');
  const bubbles = [...document.querySelectorAll('.signature-bubble')];
  const stageRect = stage.getBoundingClientRect();
  const cardRect = card.getBoundingClientRect();
  // A bubble is rotated by up to 9 degrees and floats up and down, so its bounding box is bigger
  // than the signature inside it and its corners can reach into the card without covering anything.
  // What matters is whether the drawn content — the ink canvas and the name — lands on the card.
  let contentOverlaps = 0;
  let deepest = 0;
  const centresInside = [];
  bubbles.forEach((bubble) => {
    const parts = [...bubble.querySelectorAll('canvas, .signature-name')];
    let overlap = 0;
    parts.forEach((part) => {
      const box = part.getBoundingClientRect();
      const width = Math.min(box.right, cardRect.right) - Math.max(box.left, cardRect.left);
      const height = Math.min(box.bottom, cardRect.bottom) - Math.max(box.top, cardRect.top);
      if (width > 0 && height > 0) overlap += width * height;
    });
    if (overlap > 0) {
      contentOverlaps += 1;
      const box = bubble.getBoundingClientRect();
      deepest = Math.max(deepest, Math.round(box.width * box.height ? overlap / (box.width * box.height) * 100 : 0));
    }
    const centre = bubble.getBoundingClientRect();
    const x = centre.left + centre.width / 2;
    const y = centre.top + centre.height / 2;
    if (x > cardRect.left && x < cardRect.right && y > cardRect.top && y < cardRect.bottom) {
      centresInside.push(String(bubble.dataset.id));
    }
  });
  return JSON.stringify({
    stage: [stage.clientWidth, stage.clientHeight],
    card: [Math.round(cardRect.width), Math.round(cardRect.height)],
    cardShareWidth: Number((cardRect.width / stageRect.width * 100).toFixed(2)),
    cardShareHeight: Number((cardRect.height / stageRect.height * 100).toFixed(2)),
    cardBox: [Math.round(cardRect.left - stageRect.left), Math.round(cardRect.top - stageRect.top)],
    qrScale: getComputedStyle(document.documentElement).getPropertyValue('--qr-scale').trim(),
    bubbles: bubbles.length,
    contentOverlaps: contentOverlaps,
    deepestOverlapPercent: deepest,
    centresInside: centresInside.length,
    firstBubble: bubbles.length ? [
      Math.round(bubbles[0].getBoundingClientRect().width),
      Math.round(bubbles[0].getBoundingClientRect().height),
    ] : null,
  });
})()"""


def set_scale(base: str, slug: str, token: str, value: float) -> dict:
    request = urllib.request.Request(
        f"{base}/api/admin/events/{slug}",
        data=json.dumps({"qr_scale": value}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="PUT",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:18195")
    parser.add_argument("--slug", default="integrity-2026")
    parser.add_argument("--key", default="probe-token")
    parser.add_argument("--scales", default="0.5,1,1.5,2.5,3")
    parser.add_argument("--stage", default="1920x1080")
    parser.add_argument("--skip-admin", action="store_true", help="only exercise the wall")
    arguments = parser.parse_args()

    scales = [float(part) for part in arguments.scales.split(",")]
    width_text, height_text = arguments.stage.lower().split("x")
    port = 19321
    profile = Path(tempfile.mkdtemp(prefix="edge-qr-"))
    process = start_edge(port, profile)
    failures: list[str] = []
    rows = []
    try:
        devtools = DevTools(port)
        devtools.call("Page.enable")
        devtools.call("Runtime.enable")
        devtools.call("Network.enable")
        devtools.call("Network.setCacheDisabled", cacheDisabled=True)
        devtools.call(
            "Emulation.setDeviceMetricsOverride",
            width=int(width_text),
            height=int(height_text),
            deviceScaleFactor=1,
            mobile=False,
        )
        for scale in scales:
            saved = set_scale(arguments.base, arguments.slug, arguments.key, scale)
            devtools.call("Page.navigate", url=f"{arguments.base}/display?event={arguments.slug}")
            time.sleep(3.5)
            value = json.loads(devtools.evaluate(PROBE))
            rows.append({"requested": scale, "saved": saved.get("qr_scale"), **value})
            print(
                f"scale {scale:<4} -> applied {value['qrScale']:<5}"
                f" card {value['card'][0]}x{value['card'][1]}"
                f" = {value['cardShareWidth']}% x {value['cardShareHeight']}% of the stage"
                f" at {value['cardBox']}"
                f" | bubbles {value['bubbles']} first {value['firstBubble']}"
                f" drawn on the card: {value['contentOverlaps']}"
                f" (deepest {value['deepestOverlapPercent']}%), centres under it: {value['centresInside']}"
            )
            # Bubbles are rotated and animated, so a corner reaching into the card is tolerated;
            # a signature whose centre sits under the card would be hidden by it.
            if value["centresInside"]:
                failures.append(f"scale {scale}: {value['centresInside']} signatures are centred under the QR card")
            if value["cardShareWidth"] > 34:
                failures.append(f"scale {scale}: the card takes {value['cardShareWidth']}% of the stage width")
            if value["cardShareHeight"] > 90:
                failures.append(f"scale {scale}: the card takes {value['cardShareHeight']}% of the stage height")

        # The admin page itself: the slider must drive the label and the preview, and saving must
        # reach the wall's setting.
        if not arguments.skip_admin:
            print("--- admin page ---")
            devtools.call("Page.navigate", url=f"{arguments.base}/admin?event={arguments.slug}")
            time.sleep(1.5)
            devtools.evaluate(
                f"window.sessionStorage.setItem('sign-board-admin-token', {json.dumps(arguments.key)})"
            )
            devtools.call("Page.navigate", url=f"{arguments.base}/admin?event={arguments.slug}")
            time.sleep(3.0)
            admin_state = json.loads(
                devtools.evaluate(
                    """(() => {
                      const slider = document.querySelector('#qr-scale-input');
                      const label = document.querySelector('#qr-scale-value');
                      const preview = document.querySelector('#admin-qr');
                      const note = document.querySelector('#qr-preview-note');
                      // Start from a known value so the comparison means something: the page may
                      // well have loaded with the very value the test is about to set.
                      slider.value = '1';
                      slider.dispatchEvent(new Event('input', { bubbles: true }));
                      const before = { value: slider.value, label: label.textContent, width: preview.style.width };
                      slider.value = '2';
                      slider.dispatchEvent(new Event('input', { bubbles: true }));
                      const after = { value: slider.value, label: label.textContent, width: preview.style.width, note: note.textContent };
                      return JSON.stringify({
                        visible: !document.querySelector('#admin-shell').classList.contains('admin-hidden'),
                        before,
                        after,
                      });
                    })()"""
                )
            )
            print(f"  admin visible: {admin_state['visible']}")
            print(f"  before: {admin_state['before']}")
            print(f"  after moving the slider to 2: {admin_state['after']}")
            if not admin_state["visible"]:
                failures.append("the admin page did not show the console, so the QR size control is unreachable")
            if admin_state["after"]["label"] == admin_state["before"]["label"]:
                failures.append("moving the QR size slider did not change the shown value")
            if admin_state["after"]["width"] == admin_state["before"]["width"]:
                failures.append("moving the QR size slider did not resize the QR preview")
            if "大屏" not in admin_state["after"]["note"]:
                failures.append("the admin page does not explain what the size means on the wall")

            # Saving from the admin form must be what the wall then reads.
            saved = json.loads(
                devtools.evaluate(
                    """(async () => {
                      document.querySelector('#event-form').dispatchEvent(new Event('submit', { cancelable: true }));
                      await new Promise((resolve) => setTimeout(resolve, 1200));
                      return JSON.stringify({
                        notice: document.querySelector('#event-notice').textContent,
                        slider: document.querySelector('#qr-scale-input').value,
                      });
                    })()"""
                )
            )
            print(f"  after saving: {saved}")
            stored = urllib.request.urlopen(
                f"{arguments.base}/api/events/{arguments.slug}/display", timeout=15
            )
            qr_scale = json.load(stored)["event"]["qr_scale"]
            print(f"  the event now reports qr_scale={qr_scale}")
            if abs(qr_scale - 2) > 0.01:
                failures.append(f"saving the admin form stored qr_scale={qr_scale}, not 2")

        # The card must grow with the setting until the stage's own safety cap stops it, and the
        # signatures must not shrink away as it does.
        by_scale = {row["requested"]: row for row in rows}
        if 1 in by_scale and 2.5 in by_scale:
            grew = by_scale[2.5]["card"][0] / by_scale[1]["card"][0]
            print(
                f"card width at 2.5x against 1x: {grew:.2f}"
                f" (the stage caps the card at a third of its width)"
            )
            if grew < 1.5:
                failures.append(f"the card only grew {grew:.2f}x when the setting went from 1 to 2.5")
            if by_scale[2.5]["cardShareWidth"] > 34:
                failures.append(
                    f"the capped card still takes {by_scale[2.5]['cardShareWidth']}% of the stage width"
                )
        for row in rows:
            # A request the stage refused must have been refused for the documented reason: the card
            # would have taken more than a third of the stage. The card is not square (it carries a
            # title and a line of copy), so the scale is compared against the height it implies.
            applied = float(row["qrScale"])
            if applied + 0.01 < row["requested"]:
                unclamped_height = row["card"][1] / applied * row["requested"]
                allowed = row["stage"][1] / 3
                print(
                    f"  scale {row['requested']} was capped to {applied}: the card would have been"
                    f" {round(unclamped_height)} px tall against the {round(allowed)} px limit"
                )
                if unclamped_height < allowed * 0.85:
                    failures.append(
                        f"scale {row['requested']}: capped at {applied} although the card would only"
                        f" have been {round(unclamped_height)} px of the {round(allowed)} px limit"
                    )
    finally:
        try:
            devtools.close()
        except Exception:
            pass
        process.terminate()
        set_scale(arguments.base, arguments.slug, arguments.key, 1.0)

    print(f"failures={len(failures)}")
    for failure in failures:
        print("FAIL:", failure)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
