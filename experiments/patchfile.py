"""Parse git-style unified diffs into hunks and change anchors.

Standard library only, so the pipeline runs on a bare Windows Python.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")
DEV_NULL = "/dev/null"


def _clean_path(raw: str) -> str:
    """'b/foo/bar.py' -> 'foo/bar.py'; handles quotes and /dev/null."""
    path = raw.strip()
    if path.startswith('"') and path.endswith('"'):
        path = path[1:-1]
    if "\t" in path:
        path = path.split("\t", 1)[0]
    if path == DEV_NULL:
        return DEV_NULL
    if path.startswith(("a/", "b/")):
        path = path[2:]
    return path


@dataclass
class Hunk:
    old_start: int
    old_len: int
    new_start: int
    new_len: int
    section: str = ""
    # Old-side line numbers this hunk touches. A deleted line anchors itself;
    # an added line anchors the old line *after which* it is inserted.
    anchors: list[int] = field(default_factory=list)
    added: int = 0
    removed: int = 0


@dataclass
class FilePatch:
    old_path: str
    new_path: str
    hunks: list[Hunk] = field(default_factory=list)

    @property
    def path(self) -> str:
        """The path to read from the base-commit snapshot."""
        if self.old_path != DEV_NULL:
            return self.old_path
        return self.new_path

    @property
    def is_deleted(self) -> bool:
        return self.new_path == DEV_NULL

    @property
    def is_added(self) -> bool:
        return self.old_path == DEV_NULL

    @property
    def added(self) -> int:
        return sum(h.added for h in self.hunks)

    @property
    def removed(self) -> int:
        return sum(h.removed for h in self.hunks)

    def anchors(self) -> list[int]:
        seen: set[int] = set()
        for hunk in self.hunks:
            seen.update(hunk.anchors)
        return sorted(seen)


def _new_hunk(match: re.Match[str]) -> Hunk:
    old_start = int(match.group(1))
    old_len = int(match.group(2)) if match.group(2) is not None else 1
    new_start = int(match.group(3))
    new_len = int(match.group(4)) if match.group(4) is not None else 1
    return Hunk(old_start, old_len, new_start, new_len, (match.group(5) or "").strip())


def parse(text: str) -> list[FilePatch]:
    """Parse a multi-file unified diff. Unparseable regions are skipped, not fatal."""
    files: list[FilePatch] = []
    current: FilePatch | None = None
    hunk: Hunk | None = None
    old_line = new_line = 0

    for raw in text.splitlines():
        if raw.startswith("diff --git "):
            current = None
            hunk = None
            continue

        if raw.startswith("--- ") and not raw.startswith("---\t"):
            # A '---' after hunk content means a new file section.
            pending_old = _clean_path(raw[4:])
            current = FilePatch(old_path=pending_old, new_path=pending_old)
            hunk = None
            continue

        if raw.startswith("+++ ") and current is not None:
            current.new_path = _clean_path(raw[4:])
            if not current.hunks:
                files.append(current)
            continue

        if raw.startswith("@@"):
            if current is None:
                continue
            match = HUNK_RE.match(raw)
            if not match:
                hunk = None
                continue
            hunk = _new_hunk(match)
            current.hunks.append(hunk)
            old_line = hunk.old_start
            new_line = hunk.new_start
            continue

        if hunk is None or current is None:
            continue

        if raw.startswith("\\"):
            continue  # "\ No newline at end of file"

        marker, body = (raw[:1], raw[1:]) if raw else (" ", "")
        if marker == "-":
            hunk.anchors.append(old_line)
            hunk.removed += 1
            old_line += 1
        elif marker == "+":
            anchor = old_line - 1
            hunk.anchors.append(anchor if anchor >= 1 else 1)
            hunk.added += 1
            new_line += 1
        else:
            if not body and not raw:
                continue
            old_line += 1
            new_line += 1

    return [f for f in files if f.hunks]
