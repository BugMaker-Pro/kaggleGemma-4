"""Read files out of a base-commit snapshot without extracting 22 GB.

A snapshot is either a `.tgz` or an already-extracted tree. Two access patterns
matter and they are not interchangeable:

  read_text / read_bytes   a handful of files, random access. Cheap on a
                           directory, expensive on a gzip stream.
  read_all_text            the whole tree, one decompression pass. This is what
                           a graph build wants, and it is the only sane way to
                           touch hundreds of members of one archive.
"""

from __future__ import annotations

import tarfile
from pathlib import Path


def _strip_dot(name: str) -> str:
    return name[2:] if name.startswith("./") else name


def _decode(data: bytes | None) -> str | None:
    """Bytes -> text with \\n line endings; None for binary or undecodable."""
    if data is None or b"\x00" in data[:4096]:
        return None
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        return None
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _common_prefix(names: list[str]) -> str:
    """'repo-sha/' when every member sits under one top-level directory."""
    firsts = {name.split("/", 1)[0] for name in names}
    if len(firsts) == 1:
        only = next(iter(firsts))
        if all(name.startswith(only + "/") for name in names):
            return only + "/"
    return ""


class Snapshot:
    """Uniform read access over a .tgz snapshot or an already-extracted tree."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._tar: tarfile.TarFile | None = None
        self._members: dict[str, tarfile.TarInfo] | None = None
        self._prefix = ""
        if not self.path.exists():
            raise FileNotFoundError(self.path)
        self._kind = "dir" if self.path.is_dir() else "tar"

    # -- random access ---------------------------------------------------
    def _ensure_index(self) -> None:
        """Index the archive on first random access, not on construction.

        `read_all_text` never needs the index, and building it costs one full
        decompression of the archive -- a third of the cost of a rebuild for a
        caller that only reads a few members or reads them all in one pass.
        """
        if self._kind != "tar" or self._members is not None:
            return
        self._tar = tarfile.open(self.path, "r:gz")
        members: dict[str, tarfile.TarInfo] = {}
        for info in self._tar.getmembers():
            if info.isfile():
                members[_strip_dot(info.name)] = info
        self._members = members
        self._prefix = _common_prefix(list(members))

    def _rel(self, path: str) -> str:
        return path.replace("\\", "/").lstrip("./")

    def exists(self, path: str) -> bool:
        rel = self._rel(path)
        if self._kind == "dir":
            return (self.path / rel).is_file()
        self._ensure_index()
        assert self._members is not None
        return (self._prefix + rel) in self._members

    def read_bytes(self, path: str) -> bytes | None:
        rel = self._rel(path)
        if self._kind == "dir":
            target = self.path / rel
            return target.read_bytes() if target.is_file() else None
        self._ensure_index()
        assert self._members is not None and self._tar is not None
        info = self._members.get(self._prefix + rel)
        if info is None:
            return None
        handle = self._tar.extractfile(info)
        return handle.read() if handle is not None else None

    def read_text(self, path: str) -> str | None:
        """Decoded source with line endings normalised to \\n.

        Repositories are checked out on Linux upstream but copied around on
        Windows, so normalising here keeps every line number platform-stable.
        """
        return _decode(self.read_bytes(path))

    # -- bulk access -----------------------------------------------------
    def read_all_text(self, name_filter=None) -> dict[str, str]:
        """Every matching file as {repo-relative path: text}, in one pass."""
        out: dict[str, str] = {}
        if self._kind == "dir":
            for path in sorted(self.path.rglob("*")):
                if not path.is_file():
                    continue
                rel = path.relative_to(self.path).as_posix()
                if name_filter is not None and not name_filter(rel):
                    continue
                text = self.read_text(rel)
                if text is not None:
                    out[rel] = text
            return out

        raw: dict[str, str] = {}
        with tarfile.open(self.path, "r:gz") as tf:
            for info in tf:
                if not info.isfile():
                    continue
                handle = tf.extractfile(info)
                if handle is None:
                    continue
                text = _decode(handle.read())
                if text is not None:
                    raw[_strip_dot(info.name)] = text

        prefix = _common_prefix(list(raw))
        for name, text in raw.items():
            rel = name[len(prefix):] if prefix and name.startswith(prefix) else name
            if name_filter is not None and not name_filter(rel):
                continue
            out[rel] = text
        return out

    def subset_text(self, paths) -> dict[str, str]:
        """Only the named files, still in a single pass."""
        wanted = {path.replace("\\", "/").lstrip("./") for path in paths}
        return self.read_all_text(lambda name: name in wanted)

    def names(self) -> list[str]:
        if self._kind == "dir":
            return [
                p.relative_to(self.path).as_posix()
                for p in self.path.rglob("*")
                if p.is_file()
            ]
        self._ensure_index()
        assert self._members is not None
        return sorted(k[len(self._prefix):] for k in self._members)

    def close(self) -> None:
        if self._tar is not None:
            self._tar.close()
            self._tar = None

    def __enter__(self) -> "Snapshot":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
