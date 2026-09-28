"""Check that the committed baseline really matches the working tree, file by file.

Git compares content hashes, not timestamps, so this proves the property a rollback depends on: every
tracked file in the working tree is byte-identical to the one in the commit, and therefore
`git checkout` would restore exactly what is deployed today.

Usage:
    python tools/verify_git_baseline.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def git(*arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments], cwd=str(ROOT), capture_output=True, text=True, check=False
    )
    if completed.returncode != 0:
        raise SystemExit(f"git {' '.join(arguments)} failed: {completed.stderr.strip()}")
    return completed.stdout


def main() -> int:
    if not (ROOT / ".git").exists():
        print("no repository at the project root")
        return 1

    head = git("rev-parse", "HEAD").strip()
    subject = git("log", "-1", "--format=%s").strip()
    # Compare the *index*, not the last commit: `git restore` and `git checkout --` restore from the
    # index, so that is the baseline a rollback actually uses. Reading HEAD instead reports a file that
    # was staged as removed — and is genuinely gone from the index — as "tracked but absent", which
    # sent this checker into a false alarm over a temporary commit-message file.
    entries = {}
    for line in git("ls-files", "-s").splitlines():
        metadata, path = line.split("\t", 1)
        mode, blob, _stage = metadata.split()
        entries[path] = (mode, blob)
    print(f"HEAD {head[:12]}  {subject}")
    print(f"tracked files in the index: {len(entries)}")

    differences: list[str] = []
    missing: list[str] = []
    for path, (mode, blob) in entries.items():
        target = ROOT / path
        if not target.exists():
            missing.append(path)
            continue
        current = git("hash-object", path).strip()
        if current != blob:
            differences.append(path)

    untracked = [line for line in git("status", "--porcelain").splitlines() if line]

    print()
    if missing:
        print(f"tracked but absent from the working tree ({len(missing)}):")
        for path in missing[:10]:
            print(f"  {path}")
    if differences:
        print(f"tracked but changed in the working tree ({len(differences)}):")
        for path in differences[:10]:
            print(f"  {path}")
    if not missing and not differences:
        print("every tracked file is byte-identical to the committed baseline")

    # Ignored paths must stay ignored: this is what keeps the tokens and the database out of history.
    must_be_ignored = [
        ".secrets/admin-token.txt",
        ".secrets/monitor-token.txt",
        ".secrets/deploy.env",
        ".secrets/deploy_key.pem",
        ".private-assets/ustcblue.jpg",
        ".venv/pyvenv.cfg",
        "data/sign-board.sqlite3",
    ]
    not_ignored = []
    for path in must_be_ignored:
        completed = subprocess.run(
            ["git", "check-ignore", "-q", path], cwd=str(ROOT), check=False
        )
        if completed.returncode != 0:
            not_ignored.append(path)
    print()
    if not_ignored:
        print("THESE ARE NOT IGNORED AND MUST NOT BE COMMITTED:")
        for path in not_ignored:
            print(f"  {path}")
    else:
        print(f"credentials and databases stay out of history ({len(must_be_ignored)} paths checked)")

    if untracked:
        print(f"\nnew or changed files not in the commit ({len(untracked)}):")
        for line in untracked[:12]:
            print(f"  {line}")
    print()
    print("rollback: git restore <path>  |  git checkout -- .  |  git reset --hard " + head[:12])
    return 1 if (missing or differences or not_ignored) else 0


if __name__ == "__main__":
    sys.exit(main())
