import sqlite3

from tools.backup_db import backup_database


def test_backup_uses_sqlite_online_backup(tmp_path):
    source = tmp_path / "source.sqlite3"
    target = tmp_path / "backups" / "copy.sqlite3"

    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE entries (value TEXT NOT NULL)")
        connection.execute("INSERT INTO entries VALUES (?)", ("preserved",))

    backup_database(source, target)

    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT value FROM entries").fetchone() == ("preserved",)
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
