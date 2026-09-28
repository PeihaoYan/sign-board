"""Check relative Markdown links in the public documentation."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def markdown_files() -> list[Path]:
    candidates = [ROOT / "README.md", ROOT / "Roadmap.md", ROOT / "CHANGELOG.md"]
    candidates.extend((ROOT / "docs").glob("*.md"))
    candidates.extend((ROOT / ".github").rglob("*.md"))
    candidates.extend([ROOT / "CONTRIBUTING.md", ROOT / "SECURITY.md", ROOT / "CODE_OF_CONDUCT.md"])
    return sorted({path for path in candidates if path.is_file()})


def main() -> int:
    link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    failures: list[str] = []
    checked = 0
    for source in markdown_files():
        text = source.read_text(encoding="utf-8")
        for target in link_pattern.findall(text):
            target = target.strip().split("#", 1)[0]
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            checked += 1
            resolved = (source.parent / target).resolve()
            try:
                resolved.relative_to(ROOT.resolve())
            except ValueError:
                failures.append(f"{source.relative_to(ROOT)} -> outside repository: {target}")
                continue
            if not resolved.exists():
                failures.append(f"{source.relative_to(ROOT)} -> missing: {target}")

    if failures:
        print("broken documentation links:")
        print("\n".join(f"  {failure}" for failure in failures))
        return 1
    print(f"documentation links ok: {checked} relative links")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
