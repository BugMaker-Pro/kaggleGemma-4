"""Fetch the reranker checkpoint into models/ -- never into git.

The weights are 2.12 GB, so they are downloaded rather than tracked. The default
endpoint is the mirror that actually works from this network; pass
`--endpoint https://huggingface.co` when the direct route is available.

    python tools/fetch_model.py
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="BAAI/bge-reranker-v2-m3")
    ap.add_argument("--dest", default=str(ROOT / "models"))
    ap.add_argument("--endpoint", default="https://hf-mirror.com")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args(argv)

    # huggingface_hub reads HF_ENDPOINT at import time, so set it first.
    os.environ.setdefault("HF_ENDPOINT", args.endpoint)
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("huggingface_hub is missing: uv sync --frozen", file=sys.stderr)
        return 2

    target = Path(args.dest) / args.model.split("/")[-1]
    local = snapshot_download(repo_id=args.model, local_dir=target, max_workers=args.workers)
    total = sum(path.stat().st_size for path in Path(local).rglob("*") if path.is_file())
    print(f"{local}  ({total / 1024 ** 3:.2f} GB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
