"""Create a consistent SQLite backup using the SQLite online backup API.

Usage:
    python tools/backup_db.py --output backups/sign-board.sqlite3
    python tools/backup_db.py --database data/sign-board.sqlite3 --output backups/event.sqlite3
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def default_database() -> Path:
    return Path(os.getenv("DATA_DIR", ROOT / "data")) / "sign-board.sqlite3"


def backup_database(source: Path, target: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(f"source database does not exist: {source}")
    if source.resolve() == target.resolve():
        raise ValueError("backup output must be different from the source database")

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    if temporary.exists():
        temporary.unlink()

    source_connection = sqlite3.connect(source)
    target_connection = sqlite3.connect(temporary)
    try:
        source_connection.backup(target_connection)
        result = target_connection.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise RuntimeError(f"backup integrity check failed: {result!r}")
        target_connection.commit()
    finally:
        target_connection.close()
        source_connection.close()

    temporary.replace(target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=default_database())
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    backup_database(arguments.database, arguments.output)
    print(f"backup created: {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
