"""Per-repository recall@10 for every arm, from a localisation JSONL.

    python tools/per_repo.py data/experiment.jsonl
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

ARMS = ("text", "graph_rerank", "graph_open", "graph_fuse", "graph_fuse_precise")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    path = Path(argv[0] if argv else "data/experiment.jsonl")
    rows = [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]
    scored = [row for row in rows if row.get("arms")]

    by_repo: dict[str, list[dict]] = collections.defaultdict(list)
    for row in scored:
        by_repo[row.get("repo", "?")].append(row)

    arms = [arm for arm in ARMS if all(arm in row["arms"] for row in scored)]
    header = f"{'repository':24s}{'n':>4s}" + "".join(f"{arm:>16s}" for arm in arms)
    header += f"{'file r@10':>11s}{'1-hop':>8s}"
    print(header)
    print("-" * len(header))
    for repo, entries in sorted(by_repo.items(), key=lambda kv: -len(kv[1])):
        line = f"{repo:24s}{len(entries):4d}"
        for arm in arms:
            mean = sum(row["arms"][arm]["recall@10"] for row in entries) / len(entries)
            line += f"{mean:16.3f}"
        files = sum(row["arms"]["text"]["file_recall@10"] for row in entries) / len(entries)
        reach = sum(row.get("graph_headroom") or 0.0 for row in entries) / len(entries)
        line += f"{files:11.3f}{reach:8.3f}"
        print(line)

    line = f"{'all':24s}{len(scored):4d}"
    for arm in arms:
        line += f"{sum(row['arms'][arm]['recall@10'] for row in scored) / len(scored):16.3f}"
    files = sum(row["arms"]["text"]["file_recall@10"] for row in scored) / len(scored)
    reach = sum(row.get("graph_headroom") or 0.0 for row in scored) / len(scored)
    line += f"{files:11.3f}{reach:8.3f}"
    print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
