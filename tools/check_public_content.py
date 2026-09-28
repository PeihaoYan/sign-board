"""Reject known private deployment strings from the public candidate tree."""

from __future__ import annotations

import re
from pathlib import Path

from prepare_git import included_files


FORBIDDEN_TEXT = (
    re.compile(r"104\.208\.74\.71"),
    re.compile(r"whitedwarf@"),
    re.compile(r"azureserver_key"),
    re.compile(r"dev-admin-token"),
)


def main() -> int:
    failures: list[str] = []
    scanner = Path(__file__).resolve()
    for path in included_files():
        if path.resolve() == scanner:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pattern in FORBIDDEN_TEXT:
            if pattern.search(text):
                failures.append(f"{path.relative_to(Path(__file__).resolve().parent.parent)} matches {pattern.pattern}")

    if failures:
        print("private deployment strings found in the public candidate:")
        print("\n".join(f"  {failure}" for failure in failures))
        return 1
    print("public content scan ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
