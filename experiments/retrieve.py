"""Symbol-level localisation, with and without a graph, at a fixed context budget.

The question the experiment has to answer is not "does the graph help" but
"does the graph help *more than spending the same context on plain text*".
So every arm reports both what it found and how many characters it took to say
it -- a graph that wins by stuffing three times as much context into the prompt
has not shown anything.

Arms:
  text_k     BM25 over symbol text, top k                        (baseline)
  text_3k    BM25 over symbol text, top 3k                       (budget control)
  graph_k    BM25 top k, then one hop along call edges, same k   (treatment)
"""

from __future__ import annotations

import heapq
import math
import re
from collections import Counter, defaultdict

TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+")
STOPWORDS = frozenset(
    """a an and are as at be because been but by can could did do does for from had has
    have how i if in into is it its may might more most of on or our should so some such
    than that the their them then there these they this to was we were what when where
    which while why will with would you your""".split()
)


def tokenize(text: str) -> list[str]:
    """Identifier-aware tokens: `read_csv_file` and `readCsvFile` both *read csv file*."""
    out: list[str] = []
    for raw in TOKEN_RE.findall(text or ""):
        parts = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", raw).replace("_", " ").split()
        for part in parts:
            lowered = part.lower()
            if len(lowered) > 1 and lowered not in STOPWORDS:
                out.append(lowered)
    return out


def document_text(node: dict) -> str:
    return " ".join(
        part for part in (
            node.get("file", ""),
            (node.get("qualname") or "").replace(".", " "),
            node.get("name", ""),
            node.get("signature", ""),
            node.get("doc", ""),
        ) if part
    )


class BM25:
    def __init__(self, docs: dict[str, str], k1: float = 1.2, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.ids = list(docs)
        self.tfs: list[Counter] = []
        self.lens: list[int] = []
        self.df: Counter = Counter()
        for doc_id in self.ids:
            tokens = tokenize(docs[doc_id])
            counts = Counter(tokens)
            self.tfs.append(counts)
            self.lens.append(len(tokens))
            self.df.update(counts.keys())
        self.n = len(self.ids)
        self.avgdl = (sum(self.lens) / self.n) if self.n else 0.0
        self._postings = None

    def _index(self) -> dict[str, list[int]]:
        if self._postings is None:
            postings: dict[str, list[int]] = defaultdict(list)
            for i, counts in enumerate(self.tfs):
                for term in counts:
                    postings[term].append(i)
            self._postings = dict(postings)
        return self._postings

    def _idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log(1 + (self.n - df + 0.5) / (df + 0.5))

    def search(self, query: str, k: int) -> list[tuple[str, float]]:
        if not self.n or k <= 0:
            return []
        postings = self._index()
        scores: dict[int, float] = defaultdict(float)
        for term in set(tokenize(query)):
            rows = postings.get(term)
            if not rows:
                continue
            idf = self._idf(term)
            for i in rows:
                tf = self.tfs[i][term]
                denom = tf + self.k1 * (1 - self.b + self.b * self.lens[i] / (self.avgdl or 1))
                scores[i] += idf * tf * (self.k1 + 1) / denom
        if not scores:
            return []
        best = heapq.nlargest(k, scores.items(), key=lambda kv: kv[1])
        return [(self.ids[i], score) for i, score in best]


def adjacency(graph: dict) -> dict[str, set[str]]:
    """Undirected call/inheritance neighbourhood, used for one-hop expansion."""
    neighbours: dict[str, set[str]] = defaultdict(set)
    for edge in graph.get("edges", []):
        if edge.get("type") not in ("calls", "inherits"):
            continue
        src, dst = edge.get("source"), edge.get("target")
        if not src or not dst:
            continue
        neighbours[src].add(dst)
        neighbours[dst].add(src)
    return neighbours


def expand(seeds: list[str], neighbours: dict[str, set[str]], limit: int) -> list[str]:
    """One hop out from the seeds, breadth-first, deduplicated, capped."""
    seen = list(seeds)
    known = set(seeds)
    for seed in seeds:
        for neighbour in sorted(neighbours.get(seed, ())):
            if neighbour in known:
                continue
            known.add(neighbour)
            seen.append(neighbour)
            if len(seen) >= limit:
                return seen
    return seen


def context_chars(ids: list[str], nodes: dict[str, dict], cap: int = 400) -> int:
    total = 0
    for node_id in ids:
        node = nodes.get(node_id, {})
        text = document_text(node)[:cap]
        total += len(text) + 1
    return total


def recall_at(ranked: list[str], targets: set[str], k: int) -> float:
    if not targets:
        return float("nan")
    return len(set(ranked[:k]) & targets) / len(targets)


def any_hit_at(ranked: list[str], targets: set[str], k: int) -> float:
    return 1.0 if set(ranked[:k]) & targets else 0.0
