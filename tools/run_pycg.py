"""Run PyCG over one snapshot and dump its call graph, for timing and sanity.

    python tools/run_pycg.py --snapshot data/repos/astropy__astropy@....tar.gz --out data/pycg/x.json

PyCG is run in-process rather than through its CLI: the PyPI wheel ships a
`PyCG/` directory while the code imports `pycg`, so the console script cannot
start on a case-sensitive install. Point PYTHONPATH at the GitHub checkout.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tarfile
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _warm_imports() -> None:
    """Import the stdlib modules that are otherwise pulled in lazily.

    PyCG's import hook fires for every module loaded after it is installed, and
    it asserts that an edge can only be added between nodes it already knows.
    The first `importlib.invalidate_caches()` then tries to import zipfile and
    importlib.metadata, and the run dies before it reaches the user's code.
    """
    import importlib
    import importlib.metadata  # noqa: F401
    import importlib.resources  # noqa: F401
    import zipfile  # noqa: F401
    import email  # noqa: F401
    import http.client  # noqa: F401
    import dataclasses  # noqa: F401
    import typing  # noqa: F401
    import json  # noqa: F401
    import logging  # noqa: F401
    import warnings  # noqa: F401
    import collections.abc  # noqa: F401
    import encodings.idna  # noqa: F401

    importlib.invalidate_caches()


def extract(tar_path: str | Path, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path, "r:gz") as tf:
        tf.extractall(dest)
    tops = [p for p in dest.iterdir() if p.is_dir()]
    return tops[0] if len(tops) == 1 else dest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--entry", default=None, help="entry point file, relative to repo root")
    ap.add_argument("--max-iter", type=int, default=-1, help="-1 = iterate to a fixpoint")
    args = ap.parse_args(argv)

    # PyCG installs a metapath finder that records every import. Any stdlib
    # module imported *after* that point makes it add an edge to a node it never
    # created (importlib.metadata, zipfile, ...), so warm the lazy ones first.
    _warm_imports()

    from pycg.pycg import CallGraphGenerator
    from pycg.utils.constants import CALL_GRAPH_OP

    work = Path(tempfile.mkdtemp(prefix="pycg-"))
    try:
        repo = extract(args.snapshot, work)
        if args.entry:
            entry = repo / args.entry
        else:
            candidates = sorted(p for p in repo.glob("*.py"))
            entry = candidates[0] if candidates else next(iter(sorted(repo.rglob("*.py"))))

        started = time.time()
        generator = CallGraphGenerator([str(entry)], str(repo), args.max_iter, CALL_GRAPH_OP)
        generator.analyze()
        graph = generator.output()
        elapsed = time.time() - started

        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "nodes": list(graph.keys()),
            "edges": [[src, dst[0], dst[1]] for src, dsts in graph.items() for dst in dsts],
            "seconds": round(elapsed, 2),
            "entry": str(entry.relative_to(repo)),
        }), encoding="utf-8")
        print(json.dumps({
            "nodes": len(graph),
            "edges": sum(len(v) for v in graph.values()),
            "seconds": round(elapsed, 2),
            "entry": str(entry.relative_to(repo)),
            "sample": list(graph)[:5],
        }, indent=2))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
