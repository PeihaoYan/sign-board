"""Prepare the working tree for version control, and check what a first commit would contain.

Read-only by default: it lists what Git would pick up, flags anything that must never be committed
(credentials, keys, databases, generated pictures), and verifies that the ignore rules actually cover
them. With `--write-ignore` it appends the missing ignore patterns — the one file this script may
change, and only because a wrong ignore file is how a token or a 200 MB database ends up in history.

Usage:
    python tools/prepare_git.py
    python tools/prepare_git.py --write-ignore
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Patterns a project like this needs. Each one is justified in the listing it produces.
REQUIRED_IGNORES = {
    ".secrets/": "the admin and monitor tokens and the SSH key for the server",
    ".private-assets/": "local institution-specific assets excluded from the public release",
    ".venv/": "the local virtual environment (about 48 MB)",
    ".env": "a local deployment environment file, which carries the same secrets",
    "data/*": "the running database, which is data rather than source",
    "__pycache__/": "byte-compiled Python",
    ".pytest_cache/": "pytest's own cache",
    "*.pyc": "byte-compiled Python",
    "tests/.test-data/": "the database the test suite writes",
    "tests/.probe-data/": "the database the browser test harness writes (tens of megabytes)",
    "tests/.release-probe-data*/": "local release probe databases",
    "tests/.shutdown-data/": "the database the shutdown test writes",
    "tests/.shutdown-profile/": "a browser profile left by the shutdown test",
    "tests/shots/": "pictures the checks produce for a human to look at",
    "tests/*.log": "logs from a locally started server",
    "tests/.*-profile/": "browser profiles from the test harness",
    "backups/": "SQLite backups containing activity data",
    ".coverage": "coverage output",
    "htmlcov/": "HTML coverage output",
}

# Files that must never be committed, whatever else changes.
FORBIDDEN = [
    (re.compile(r"^\.secrets/"), "credentials and keys"),
    (re.compile(r"\.pem$"), "a private key"),
    (re.compile(r"\.sqlite3$|\.sqlite$|\.db$"), "a database"),
    (re.compile(r"^\.env$|/\.env$"), "an environment file"),
    (re.compile(r"^\.venv/"), "a virtual environment"),
]


def included_files() -> list[Path]:
    """Every existing file Git would pick up, using Git's native candidate list."""
    completed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=str(ROOT),
        check=True,
        capture_output=True,
    )
    found: list[Path] = []
    for raw_path in completed.stdout.split(b"\0"):
        if not raw_path:
            continue
        path = ROOT / raw_path.decode("utf-8")
        if path.is_file():
            found.append(path)
    return sorted(found)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-ignore", action="store_true")
    arguments = parser.parse_args()

    ignore_file = ROOT / ".gitignore"
    current = ignore_file.read_text(encoding="utf-8") if ignore_file.exists() else ""
    # Compare the patterns, not the raw text: a pattern can be followed by an explanatory comment,
    # which a plain substring search would then fail to recognise.
    existing = {
        line.split("#", 1)[0].strip()
        for line in current.splitlines()
        if line.split("#", 1)[0].strip()
    }
    missing = [pattern for pattern in REQUIRED_IGNORES if pattern not in existing]
    if arguments.write_ignore and missing:
        lines = [line.rstrip() for line in current.splitlines()]
        lines.append("")
        lines.append("# Local run artifacts and credentials, listed by tools/prepare_git.py. Git reads")
        lines.append("# everything after a `#` on a pattern line as part of the pattern, so the reasons")
        lines.append("# for these rules live here rather than beside them:")
        for pattern in missing:
            lines.append(f"#   {pattern}  {REQUIRED_IGNORES[pattern]}")
        for pattern in missing:
            lines.append(pattern)
        ignore_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"updated {ignore_file.name} with {len(missing)} pattern(s): {', '.join(missing)}")
        current = ignore_file.read_text(encoding="utf-8")
        existing = {
            line.split("#", 1)[0].strip()
            for line in current.splitlines()
            if line.split("#", 1)[0].strip()
        }
        missing = [pattern for pattern in REQUIRED_IGNORES if pattern not in existing]

    files = included_files()
    total = sum(path.stat().st_size for path in files)
    print(f"\na first commit would take {len(files)} files, {total / 1024 / 1024:.1f} MB")
    by_folder: dict[str, tuple[int, int]] = {}
    for path in files:
        relative = path.relative_to(ROOT)
        folder = relative.parts[0] if len(relative.parts) > 1 else "(root)"
        count, size = by_folder.get(folder, (0, 0))
        by_folder[folder] = (count + 1, size + path.stat().st_size)
    for folder, (count, size) in sorted(by_folder.items(), key=lambda item: -item[1][1]):
        print(f"  {folder:<16} {count:>4} files  {size / 1024 / 1024:>7.2f} MB")

    print("\nlargest files included:")
    for path in sorted(files, key=lambda item: -item.stat().st_size)[:8]:
        print(f"  {path.stat().st_size / 1024 / 1024:>7.2f} MB  {path.relative_to(ROOT).as_posix()}")

    leaked = []
    for path in files:
        relative = path.relative_to(ROOT).as_posix()
        for regex, reason in FORBIDDEN:
            if regex.search(relative):
                leaked.append((relative, reason))
    print()
    if leaked:
        print("MUST NOT BE COMMITTED:")
        for relative, reason in leaked:
            print(f"  {relative}  ({reason})")
    else:
        print("nothing that looks like a credential or a database is included")

    if missing:
        print(f"\nignore patterns still missing: {', '.join(missing)}")
        print("run again with --write-ignore to add them")
    return 1 if leaked or missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
