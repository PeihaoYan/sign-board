"""Landscape writing mode: geometry matrix over real device viewports.

For every device, both phone orientations and both platform paths (`fallback` for iOS, `lock`
for Android) the page is driven through: open in portrait, enter landscape writing, draw a stroke,
submit it, and leave the mode again. The report states the writing area that the participant
actually sees, whether it and the submit button are fully inside the screen, and whether the
recorded points stay inside the canvas bitmap.

Usage:
    python tests/run_landscape_cdp.py                       # every device and case
    python tests/run_landscape_cdp.py --devices "iPhone 14"
    python tests/run_landscape_cdp.py --stages landscape,submit,exit
"""

from __future__ import annotations

import argparse
import base64
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mobile_probe import (  # noqa: E402
    DEVICES,
    ORIENTATIONS,
    DevTools,
    draw_stroke,
    enter_landscape,
    geometry,
    load_mobile_page,
    prepare_session,
    start_edge,
    submit_form,
)

OUT_DIR = Path(__file__).resolve().parent / "shots"
STAGES = ("portrait", "landscape", "submit", "exit")


def device_size(device: tuple[str, int, int], orientation: str) -> tuple[int, int]:
    _, width, height = device
    return (width, height) if orientation == "portraitPrimary" else (height, width)


def describe(label: str, data: dict) -> None:
    if not data:
        print("  geometry: unavailable")
        return
    canvas = data.get("canvas") or {}
    submit = data.get("submit") or {}
    canvas_rect = canvas.get("rect", {})
    submit_rect = submit.get("rect", {})
    shell = data.get("shell_client", {})
    print(
        f"  [{data.get('mode')}{' rotated' if data.get('rotated') else ''}]"
        f" viewport={data.get('viewport', {}).get('w')}x{data.get('viewport', {}).get('h')}"
        f" shell={shell.get('w')}x{shell.get('h')}"
        f" canvas={canvas_rect.get('w')}x{canvas_rect.get('h')} at {canvas_rect.get('l')},{canvas_rect.get('t')}"
        f" submit={submit_rect.get('w')}x{submit_rect.get('h')} at {submit_rect.get('l')},{submit_rect.get('t')}"
    )
    print(
        f"  canvas_fully_visible={data.get('canvas_fully_visible')}"
        f" visible_area={data.get('canvas_visible_area')}/{data.get('canvas_area')}"
        f" submit_fully_visible={data.get('submit_fully_visible')}"
        f" exit={data.get('exit_display')} toggle={data.get('toggle_display')}"
    )


def run_case(devtools: DevTools, device, orientation: str, mode: str, stages: list[str], shot_dir: Path | None) -> bool:
    label, _, _ = device
    width, height = device_size(device, orientation)
    ok = True
    print(f"===== {label} / {orientation} / {mode} ({width}x{height}) =====")
    prepare_session(devtools, width, height, orientation, mode)
    time.sleep(0.2)
    load_mobile_page(devtools)

    if "portrait" in stages:
        data = geometry(devtools)
        describe(label, data)

    enter_landscape(devtools)
    if "landscape" in stages:
        data = geometry(devtools)
        describe(label, data)
        if not data.get("canvas_fully_visible"):
            ok = False
            print("  FAIL: the writing area is not fully on screen")
        if data.get("mode") != "landscape":
            ok = False
            print("  FAIL: the page did not enter landscape writing mode")
        if not data.get("rotated") and orientation == "landscapePrimary":
            pass  # the browser rotated the viewport itself, nothing to correct for
        if data.get("exit_display") == "none":
            ok = False
            print("  FAIL: the exit button is not available")
        if shot_dir is not None:
            shot_dir.mkdir(exist_ok=True)
            png = devtools.call("Page.captureScreenshot", format="png").get("data", "")
            (shot_dir / f"{label.replace(' ', '')}-{orientation}-{mode}.png").write_bytes(base64.b64decode(png))

    if "submit" in stages:
        draw_stroke(devtools)
        result = submit_form(devtools)
        if not result.get("captured"):
            ok = False
            print("  FAIL: no submission was captured")
        else:
            print(
                f"  stroke: points={result.get('points')} x={result.get('x')} y={result.get('y')}"
                f" bitmap={result.get('bitmap')} spread={result.get('spread')}"
                f" in_bounds={result.get('in_bounds')}"
            )
            if not result.get("in_bounds"):
                ok = False
                print("  FAIL: recorded points leave the canvas")

    if "exit" in stages:
        # The success panel replaces the form after a submission, so the exit check starts from
        # the form again; otherwise it would measure a hidden canvas and mean nothing.
        devtools.evaluate(
            "(() => { const again = document.querySelector('#submit-another'); if (again && again.offsetParent) again.click(); })()"
        )
        time.sleep(0.6)
        devtools.evaluate("document.querySelector('#landscape-exit').click()")
        time.sleep(1.0)
        data = geometry(devtools)
        describe(label, data)
        canvas_rect = (data.get("canvas") or {}).get("rect", {})
        if data.get("mode") != "portrait":
            ok = False
            print("  FAIL: leaving the mode did not restore the portrait layout")
        if canvas_rect.get("w", 0) < 200:
            ok = False
            print("  FAIL: the portrait canvas did not return to its normal size")
        if not data.get("canvas_fully_visible"):
            ok = False
            print("  FAIL: the portrait canvas is not fully visible after leaving the mode")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--devices", default="", help="comma separated device names; default all")
    parser.add_argument("--orientations", default=",".join(ORIENTATIONS))
    parser.add_argument("--modes", default="fallback,lock")
    parser.add_argument("--stages", default="portrait,landscape,submit,exit")
    parser.add_argument("--shots", action="store_true", help="save a screenshot per case")
    arguments = parser.parse_args()

    wanted = {name.strip().lower() for name in arguments.devices.split(",") if name.strip()}
    devices = [device for device in DEVICES if not wanted or device[0].lower() in wanted]
    orientations = [item for item in arguments.orientations.split(",") if item]
    modes = [item for item in arguments.modes.split(",") if item]
    stages = [item for item in arguments.stages.split(",") if item]
    for stage in stages:
        if stage not in STAGES:
            print(f"unknown stage {stage}; known: {STAGES}")
            return 2

    port = 19222
    with tempfile.TemporaryDirectory() as profile:
        process = start_edge(port, profile)
        failures = 0
        cases = 0
        try:
            devtools = DevTools(port)
            try:
                for device in devices:
                    for orientation in orientations:
                        for mode in modes:
                            cases += 1
                            if not run_case(
                                devtools,
                                device,
                                orientation,
                                mode,
                                stages,
                                OUT_DIR if arguments.shots else None,
                            ):
                                failures += 1
            finally:
                devtools.close()
        finally:
            process.terminate()
        print(f"cases={cases} failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
