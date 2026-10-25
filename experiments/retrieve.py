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


def adjacency(graph: dict, resolutions: set[str] | None = None) -> dict[str, set[str]]:
    """Undirected call/inheritance neighbourhood, used for one-hop expansion.

    `resolutions` restricts the edges used: passing the high-precision set is how
    the paper separates "the graph is useless" from "this graph's edges are half
    unresolved noise".
    """
    neighbours: dict[str, set[str]] = defaultdict(set)
    for edge in graph.get("edges", []):
        if edge.get("type") not in ("calls", "inherits"):
            continue
        if resolutions is not None and edge.get("resolution") not in resolutions:
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


def expand_round_robin(pool_ids: list[str], neighbours: dict[str, set[str]],
                       k: int, seeds: int = 5) -> list[str]:
    """Keep the strongest text hits, then fill the remaining slots with neighbours.

    This is the arm that can actually add something new: a gold symbol whose name
    has nothing to do with the issue, but which is one hop from a strong seed,
    enters the shortlist even though BM25 never ranked it inside the pool.

    Neighbours are taken round-robin across the seeds so a single hub seed with
    forty neighbours cannot take every slot, and anything left over is padded
    from the untouched tail of the text ranking -- so both arms always return
    the same number of symbols and the context budget stays comparable.
    """
    if k <= 0:
        return []
    head = list(pool_ids[:seeds])
    out = list(head)
    seen = set(out)

    queues = [sorted(neighbours.get(node, ())) for node in head]
    cursor = [0] * len(queues)
    while len(out) < k:
        progressed = False
        for i, queue in enumerate(queues):
            if len(out) >= k:
                break
            while cursor[i] < len(queue):
                candidate = queue[cursor[i]]
                cursor[i] += 1
                if candidate in seen:
                    continue
                out.append(candidate)
                seen.add(candidate)
                progressed = True
                break
        if not progressed:
            break

    for node_id in pool_ids[seeds:]:
        if len(out) >= k:
            break
        if node_id in seen:
            continue
        out.append(node_id)
        seen.add(node_id)
    return out[:k]


def fuse(pool: list[tuple[str, float]], neighbours: dict[str, set[str]],
         k: int = 10, seeds: int = 5, weight: float = 0.5) -> list[str]:
    """Text score plus a discounted score inherited from adjacent strong seeds.

    This is the standard graph-augmented ranking, kept deliberately simple so the
    weight means something: a candidate that BM25 never ranked can still enter the
    shortlist, and a candidate that BM25 ranked highly is not thrown away just
    because it happens to have no neighbours.

    `weight` is the fraction of the score a candidate can inherit from its best
    adjacent seed, so 0 degenerates to plain text ranking and 1 lets a neighbour
    of the top hit outrank the top hit itself.
    """
    if not pool or k <= 0:
        return []
    top = max(score for _, score in pool) or 1.0
    base = {node_id: score / top for node_id, score in pool}
    seed_ids = [node_id for node_id, _ in pool[:seeds]]
    seed_score = {node_id: base.get(node_id, 0.0) for node_id in seed_ids}

    candidates = dict(base)
    for seed in seed_ids:
        for neighbour in neighbours.get(seed, ()):
            inherited = weight * seed_score[seed]
            if inherited > candidates.get(neighbour, 0.0):
                candidates[neighbour] = inherited

    ranked = sorted(candidates.items(), key=lambda kv: (-kv[1], kv[0]))
    return [node_id for node_id, _ in ranked[:k]]


def ball(seeds: list[str], neighbours: dict[str, set[str]],
         hops: int = 1) -> list[tuple[str, int]]:
    """Every node within `hops` of the seeds, as (node_id, distance), distance first.

    Used both for the headroom diagnostic and for the multi-hop expansion arm:
    the question "is the gold symbol reachable in k hops" is exactly this
    function applied to the targets.
    """
    if hops <= 0:
        return []
    seen = {node_id: 0 for node_id in seeds}
    frontier = list(seeds)
    for distance in range(1, hops + 1):
        next_frontier: list[str] = []
        for node_id in frontier:
            for neighbour in sorted(neighbours.get(node_id, ())):
                if neighbour in seen:
                    continue
                seen[neighbour] = distance
                next_frontier.append(neighbour)
        frontier = next_frontier
        if not frontier:
            break
    return [(node_id, distance) for node_id, distance in seen.items() if distance > 0]


def expand_ball(seeds: list[str], neighbours: dict[str, set[str]], k: int,
                hops: int = 2) -> list[str]:
    """Seeds first, then the k-hop ball in distance order, padded from nothing.

    Unlike `expand_round_robin` this does not fall back to the text tail: it is
    the "how far can the graph alone get you" arm.
    """
    out = list(seeds[:k])
    seen = set(out)
    for node_id, _distance in sorted(ball(seeds, neighbours, hops), key=lambda kv: kv[1]):
        if len(out) >= k:
            break
        if node_id in seen:
            continue
        out.append(node_id)
        seen.add(node_id)
    return out[:k]


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
