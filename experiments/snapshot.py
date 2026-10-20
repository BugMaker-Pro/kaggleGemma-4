"""Read files out of a base-commit snapshot without extracting 22 GB.

`snapshots/<instance_id>.tgz` holds the repository at `base_commit`. We index
the tar lazily and read individual members, which keeps the pipeline usable on
a laptop and avoids a second copy of the corpus on disk.
"""

from __future__ import annotations

import tarfile
from pathlib import Path


def _strip_dot(name: str) -> str:
    return name[2:] if name.startswith("./") else name


class Snapshot:
    """Uniform read access over a .tgz snapshot or an already-extracted tree."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._tar: tarfile.TarFile | None = None
        self._members: dict[str, tarfile.TarInfo] | None = None
        self._prefix = ""
        if not self.path.exists():
            raise FileNotFoundError(self.path)
        if self.path.is_dir():
            self._kind = "dir"
        else:
            self._kind = "tar"
            self._index()

    # -- indexing -------------------------------------------------------
    def _index(self) -> None:
        assert self._kind == "tar"
        self._tar = tarfile.open(self.path, "r:gz")
        members: dict[str, tarfile.TarInfo] = {}
        for info in self._tar.getmembers():
            if not info.isfile():
                continue
            members[_strip_dot(info.name)] = info
        self._members = members

        firsts = {name.split("/", 1)[0] for name in members}
        if len(firsts) == 1:
            only = next(iter(firsts))
            if all(name.startswith(only + "/") for name in members):
                self._prefix = only + "/"

    # -- reading --------------------------------------------------------
    def _rel(self, path: str) -> str:
        return path.replace("\\", "/").lstrip("./")

    def exists(self, path: str) -> bool:
        rel = self._rel(path)
        if self._kind == "dir":
            return (self.path / rel).is_file()
        assert self._members is not None
        return (self._prefix + rel) in self._members

    def read_bytes(self, path: str) -> bytes | None:
        rel = self._rel(path)
        if self._kind == "dir":
            target = self.path / rel
            return target.read_bytes() if target.is_file() else None
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
        data = self.read_bytes(path)
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

    def names(self) -> list[str]:
        if self._kind == "dir":
            return [
                p.relative_to(self.path).as_posix()
                for p in self.path.rglob("*")
                if p.is_file()
            ]
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
