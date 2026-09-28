import os
import sqlite3

db = "/opt/sign-board/data/sign-board.sqlite3"
connection = sqlite3.connect(db)
connection.execute("DELETE FROM submissions")
connection.commit()
remaining = connection.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]
connection.close()
print("remaining_submissions", remaining)
