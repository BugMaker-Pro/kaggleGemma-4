"""Personalised PageRank over the call graph, as the strongest graph ranking we try.

The paper's negative result is only interesting if the graph is given a *good*
chance. Uniform one-hop expansion is easy to dismiss: it ignores edge direction,
gives every neighbour the same weight, and cannot rank two hops away without
also filling the list with two-hop noise. Diffusion is the standard answer to
all three objections, so it is the fairest test we can run without a model.

Mass starts on the lexical seeds and spreads along undirected call/inheritance
edges; a node's score is how much restart probability it captures, i.e. how
often a random walk that keeps snapping back to the issue's vocabulary lands on
it. Everything stays stdlib and sparse: the visited set is small even when the
repository has 18k symbols.
"""

from __future__ import annotations


def ppr(neighbours: dict[str, set[str]], seeds: list[str], restart: float = 0.15,
        iterations: int = 30, tolerance: float = 1e-8) -> dict[str, float]:
    """Stationary distribution of a random walk restarted uniformly on `seeds`.

    `restart` is the probability of teleporting back to the seeds at each step
    (0.15 is the value PageRank made conventional); lower values let mass travel
    further, which is the knob that trades reach against precision.
    """
    seeds = [seed for seed in dict.fromkeys(seeds) if seed]
    if not seeds:
        return {}
    share = (1.0 - restart) / len(seeds)

    scores: dict[str, float] = {seed: share for seed in seeds}
    for _ in range(iterations):
        nxt: dict[str, float] = {}
        dangling = 0.0
        for node, mass in scores.items():
            if not mass:
                continue
            adjacent = neighbours.get(node)
            if not adjacent:
                dangling += mass
                continue
            spread = restart * mass / len(adjacent)
            for neighbour in adjacent:
                nxt[neighbour] = nxt.get(neighbour, 0.0) + spread

        # Mass that fell off dead ends is given back to the seeds, so the
        # distribution stays normalised and comparable across repositories.
        total = sum(nxt.values())
        scale = (1.0 + dangling) / total if total else 0.0
        for seed in seeds:
            nxt[seed] = nxt.get(seed, 0.0) * scale + share + dangling * share

        delta = sum(abs(nxt.get(k, 0.0) - v) for k, v in scores.items())
        scores = nxt
        if delta < tolerance:
            break
    return scores


def ranked(scores: dict[str, float], limit: int | None = None) -> list[str]:
    """Highest mass first; ties broken by id so the order is deterministic."""
    order = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    ids = [node_id for node_id, _ in order]
    return ids[:limit] if limit else ids


def blend(text: list[tuple[str, float]], scores: dict[str, float],
          weight: float = 0.5, limit: int = 50) -> list[str]:
    """Text score (normalised to its own maximum) plus `weight` times diffusion mass.

    Unlike `retrieve.fuse` this can promote a symbol that BM25 never put in the
    pool at all, because diffusion is computed over the whole graph rather than
    the pool. That is deliberate: it is the arm with the best chance of winning.
    """
    top = max((score for _, score in text), default=0.0) or 1.0
    combined: dict[str, float] = {}
    for node_id, score in text:
        combined[node_id] = 1.0 - weight + weight * (score / top)
    peak = max(scores.values(), default=0.0) or 1.0
    for node_id, mass in scores.items():
        normalised = mass / peak
        if normalised > combined.get(node_id, 0.0):
            combined[node_id] = max(normalised * weight, combined.get(node_id, 0.0))
    order = sorted(combined.items(), key=lambda kv: (-kv[1], kv[0]))
    return [node_id for node_id, _ in order[:limit]]
