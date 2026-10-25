"""Map a task to its source snapshot on disk.

Two layouts are supported, because the corpus depends on where it came from:

  <instance_id>.tgz                     the competition's shipped snapshots/
  <owner>__<repo>@<sha12>.tar.gz        what tools/fetch_repos.py writes

Everything downstream asks the index for a task and never builds a path itself.
"""

from __future__ import annotations

from pathlib import Path

try:
    from .snapshot import Snapshot
except ImportError:  # running as a script
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from experiments.snapshot import Snapshot


def repo_key(repo: str, base_commit: str) -> str:
    return f"{repo.replace('/', '__')}@{base_commit[:12]}.tar.gz"


class SnapshotIndex:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.missing: list[str] = []

    def path_for(self, task: dict) -> Path | None:
        instance_id = task.get("instance_id", "")
        candidates = [
            self.root / repo_key(task.get("repo", ""), task.get("base_commit", "")),
            self.root / f"{instance_id}.tgz",
            self.root / instance_id,
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def open(self, task: dict) -> Snapshot | None:
        path = self.path_for(task)
        if path is None:
            self.missing.append(task.get("instance_id", "?"))
            return None
        return Snapshot(path)
