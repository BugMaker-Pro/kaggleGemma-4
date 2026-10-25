"""One-off: pull SWE-bench Lite metadata from the HF mirror and normalise it to JSONL.

This is tooling, not part of the experiment code. `experiments/` stays stdlib-only
and testable; everything that touches the network or a third-party parser lives here.

    python tools/fetch_swebench.py            # download + convert
    python tools/fetch_swebench.py --stats    # convert cache only, print stats

Output: data/swebench_lite.jsonl, one instance per line, with the same field names
the competition's tasks.jsonl uses where they overlap (instance_id / repo /
base_commit / problem_statement / patch / test_patch), so the downstream
experiment code never has to care which corpus it is running on.
"""

import argparse
import json
import os
import sys
import urllib.request

MIRROR = "https://hf-mirror.com"
DATASET = "princeton-nlp/SWE-bench_Lite"
SPLIT = "test"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
OUT = os.path.join(ROOT, "data", "swebench_lite.jsonl")


def _download(url, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    print("GET", url, flush=True)
    with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
        total = 0
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
            total += len(chunk)
    os.replace(tmp, dest)
    print("  ->", dest, f"{total / 1e6:.1f} MB", flush=True)
    return dest


def _parquet_path(split):
    return os.path.join(RAW, f"{split}.parquet")


_DROP = {"text", "hints_text", "created_at", "version", "environment_setup_commit"}


def _normalise(row):
    out = {}
    for k, v in row.items():
        if k in _DROP:
            continue
        if k in ("FAIL_TO_PASS", "PASS_TO_PASS"):
            # stored as a JSON-encoded string ("['a','b']") or a real list
            if isinstance(v, str):
                try:
                    v = json.loads(v)
                except json.JSONDecodeError:
                    v = [s.strip() for s in v.strip("[]").split(",") if s.strip()]
            out[k] = list(v)
        else:
            out[k] = v
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default=SPLIT)
    ap.add_argument("--stats", action="store_true", help="skip download, rebuild from cache")
    args = ap.parse_args(argv)

    src = _parquet_path(args.split)
    if not args.stats or not os.path.exists(src):
        _download(f"{MIRROR}/datasets/{DATASET}/resolve/main/data/{args.split}-00000-of-00001.parquet", src)

    import pyarrow.parquet as pq

    table = pq.read_table(src)
    rows = [_normalise(r) for r in table.to_pylist()]

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    by_repo = {}
    for r in rows:
        by_repo[r["repo"]] = by_repo.get(r["repo"], 0) + 1
    ftp = sum(len(r.get("FAIL_TO_PASS") or []) for r in rows)
    patch_lines = sum((r.get("patch") or "").count("\n") for r in rows)

    print(f"\n{len(rows)} instances -> {OUT}")
    print(f"columns: {', '.join(sorted(rows[0]))}")
    print(f"{len(by_repo)} repos, {ftp} fail-to-pass tests, {patch_lines} patch lines")
    for repo, n in sorted(by_repo.items(), key=lambda kv: -kv[1]):
        print(f"  {n:4d}  {repo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
