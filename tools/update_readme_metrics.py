"""Write the signature size table in README.md from the values the code actually computes.

The table used to be maintained by hand, and it drifted: it listed 9 px names for three tiers where
`metricsFor` clamps to 8 px, and it still listed the old ink sizes after the ink was made a share of
the bubble. A table nobody regenerates is a table that lies, so this rewrites it and the size line
under it from `static/wallLayout.js` itself.

Usage:
    python tools/update_readme_metrics.py            # show what would change
    python tools/update_readme_metrics.py --write    # rewrite the table
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"

# The tiers the README documents, as (the highest count the row covers, the label to print).
TIERS = [
    (40, "≤40"),
    (90, "≤90"),
    (160, "≤160"),
    (260, "≤260"),
    (400, "≤400"),
    (100000, ">400"),
]

NODE = """
const fs = require('fs'); const vm = require('vm');
const sandbox = { window: {} }; vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('static/wallLayout.js', 'utf8'), sandbox);
const L = sandbox.window.wallLayout;
const tiers = %TIERS%;
const stage = { stageWidth: 1920, stageHeight: 1080 };
console.log(JSON.stringify(tiers.map(([count, label]) => {
  const m = L.metricsFor(count, stage);
  return { label, crowdScale: m.crowdScale, bubble: [m.width, m.height], ink: [m.inkWidth, m.inkHeight], name: m.nameSize };
})));
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    arguments = parser.parse_args()

    program = NODE.replace("%TIERS%", json.dumps(TIERS))
    completed = subprocess.run(
        ["node", "-e", program],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        print("node failed:", completed.stderr.strip()[:300])
        return 1
    rows = json.loads(completed.stdout)

    header = "| 同屏签名数 | 缩放 | 气泡 | 笔迹画布 | 姓名字号 |"
    separator = "| --- | --- | --- | --- | --- |"
    table = [header, separator]
    for row in rows:
        table.append(
            f"| {row['label']} | {row['crowdScale']:g} | {row['bubble'][0]}×{row['bubble'][1]}"
            f" | {row['ink'][0]}×{row['ink'][1]} | {row['name']}px |"
        )
    table_text = "\n".join(table)

    readme = README.read_text(encoding="utf-8")
    pattern = re.compile(
        r"\| 同屏签名数 \| 缩放 \| 气泡 \| 笔迹画布 \| 姓名字号 \|\n(\| --- \| --- \| --- \| --- \| --- \|\n)((?:\|[^\n]*\|\n)+)"
    )
    match = pattern.search(readme)
    if not match:
        print("the size table was not found in README.md; nothing changed")
        return 1
    current = match.group(0).rstrip("\n")
    if current == table_text:
        print("README.md already matches the code:")
        print(table_text)
        return 0

    print("the table in README.md does not match static/wallLayout.js")
    print("--- currently in the file ---")
    print(current)
    print("--- what the code computes ---")
    print(table_text)
    if not arguments.write:
        print("\nrun again with --write to update the file")
        return 1

    updated = pattern.sub(table_text.replace("\\", "\\\\") + "\n", readme, count=1)
    README.write_text(updated, encoding="utf-8")
    print("\nREADME.md updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
