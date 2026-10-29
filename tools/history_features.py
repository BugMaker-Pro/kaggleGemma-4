"""The repository's own fix history as a retrieval prior.

Everything in the paper so far reads the *issue* or the *code*. This reads a third
thing the repository states: where earlier fixes to similar issues landed. It is
available to any agent with a checkout, it costs one patch parse, and it is the
only signal left for the 74% of tasks whose issue names no file and quotes no
source.

Ordering is by pull-request number, which is monotone in time inside a repository
(`django__django-11099` was opened before `django__django-12345`), so a task only
ever sees fixes that came before it. The dataset we keep has no timestamps, and
this is the honest substitute.

Output: data/history_scores.jsonl, one row per task:

    {"instance_id": ..., "files": {"path": weight, ...}, "seen": 12}

`weight` is the similarity-weighted count of past fixes that touched the file,
normalised to [0, 1] per task. `seen` is how many past issues were close enough
to count, so a task with no history is distinguishable from one whose history
disagreed.

    python tools/history_features.py --tasks data/swebench_full.jsonl
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from experiments.retrieve import tokenize  # noqa: E402

DIFF = re.compile(r"^diff --git a/(\S+) b/(\S+)$", re.M)
TOP_K = 25
MIN_SIM = 0.08
RECENCY = 0.00004  # per PR number of distance; a 5,000-PR gap halves the weight


def patch_files(patch: str) -> list[str]:
    return [match.group(2) for match in DIFF.finditer(patch or "")]


def pr_number(instance_id: str) -> int:
    try:
        return int(instance_id.rsplit("-", 1)[1])
    except (IndexError, ValueError):
        return 0


class BM25:
    def __init__(self, docs: list[set[str]], k1: float = 1.2, b: float = 0.75) -> None:
        self.docs = docs
        self.k1, self.b = k1, b
        self.lengths = [len(doc) for doc in docs]
        self.average = statistics.fmean(self.lengths) if docs else 0.0
        df: dict[str, int] = defaultdict(int)
        for doc in docs:
            for token in doc:
                df[token] += 1
        total = len(docs)
        self.idf = {token: math.log(1 + (total - n + 0.5) / (n + 0.5))
                    for token, n in df.items()}

    def score(self, query: set[str], index: int) -> float:
        doc, length = self.docs[index], self.lengths[index]
        total = 0.0
        for token in query & doc:
            tf = 1.0  # sets, not bags: presence is enough at this scale
            total += self.idf.get(token, 0.0) * tf * (self.k1 + 1) / (
                tf + self.k1 * (1 - self.b + self.b * length / max(self.average, 1e-9)))
        return total


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default=str(ROOT / "data" / "swebench_full.jsonl"))
    ap.add_argument("--out", default=str(ROOT / "data" / "history_scores.jsonl"))
    args = ap.parse_args(argv)

    tasks = [json.loads(line) for line in Path(args.tasks).open(encoding="utf-8") if line.strip()]
    for task in tasks:
        task["_files"] = patch_files(task.get("patch") or "")
        task["_text"] = set(tokenize(task.get("problem_statement") or ""))
        task["_pr"] = pr_number(task["instance_id"])

    by_repo: dict[str, list[dict]] = defaultdict(list)
    for task in tasks:
        if task["_files"]:
            by_repo[task["repo"]].append(task)

    out = Path(args.out)
    coverage = with_files = 0
    with out.open("w", encoding="utf-8") as fh:
        for repo, group in by_repo.items():
            group.sort(key=lambda task: task["_pr"])
            index = BM25([task["_text"] for task in group])
            for position, task in enumerate(group):
                past = group[:position]
                weights: dict[str, float] = defaultdict(float)
                seen = 0
                if past and task["_text"]:
                    scores = [(index.score(task["_text"], i), past[i]) for i in range(len(past))]
                    scores.sort(key=lambda pair: -pair[0])
                    top = scores[: TOP_K]
                    best = top[0][0] if top else 0.0
                    if best > 0:
                        for value, other in top:
                            similarity = value / best
                            if similarity < MIN_SIM:
                                continue
                            seen += 1
                            decay = math.exp(-RECENCY * (task["_pr"] - other["_pr"]))
                            for path in other["_files"]:
                                weights[path] += similarity * similarity * decay
                if weights:
                    peak = max(weights.values())
                    weights = {path: value / peak for path, value in weights.items()}
                    coverage += 1
                with_files += 1
                fh.write(json.dumps({
                    "instance_id": task["instance_id"],
                    "files": weights,
                    "seen": seen,
                }) + "\n")

    print(f"tasks with a usable history: {coverage}/{with_files} "
          f"({coverage / max(with_files, 1):.1%}) -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
