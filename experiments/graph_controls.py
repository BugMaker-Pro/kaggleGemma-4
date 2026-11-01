"""Label-free topology controls for pool-internal, fixed-slot retrieval.

See docs/graph-control-protocol.md. All rankings and randomization operate on
candidate indices, files, and graph edges; they never accept gold labels.
"""
from __future__ import annotations

import hashlib
import math
import random
from collections import Counter, defaultdict
from collections.abc import Iterable

from experiments.retrieve import tokenize

SEEDS = (11, 23, 37, 51, 71)
ATTEMPTS_PER_EDGE = 20


def edge(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


def projection(graph_edges: Iterable[dict], candidate_ids: list[str]) -> list[tuple[int, int]]:
    position = {name: i for i, name in enumerate(candidate_ids)}
    kept = set()
    for row in graph_edges:
        if row.get('type') not in ('calls', 'inherits'):
            continue
        a = position.get(row.get('source'))
        b = position.get(row.get('target'))
        if a is not None and b is not None and a != b:
            kept.add(edge(a, b))
    return sorted(kept)


def adjacency(edges: Iterable[tuple[int, int]]) -> dict[int, set[int]]:
    out = defaultdict(set)
    for a, b in edges:
        out[a].add(b)
        out[b].add(a)
    return out


def reachable(order: list[int], neighbours: dict[int, set[int]], seeds: int = 5) -> set[int]:
    out = set()
    for candidate in order[:seeds]:
        out.update(neighbours.get(candidate, ()))
    return out - set(order[:seeds])


def promote(order: list[int], marked: set[int], seeds: int = 5, k: int = 10) -> list[int]:
    """Retain seeds, then promote marked tail candidates with stable base order."""
    tail = order[seeds:]
    return (order[:seeds] + [i for i in tail if i in marked]
            + [i for i in tail if i not in marked])[:k]


def file_marked(order: list[int], files: list[str], seeds: int = 5) -> set[int]:
    selected = {files[i] for i in order[:seeds] if files[i]}
    return {i for i, name in enumerate(files) if name in selected}


def degree_signature(edges: Iterable[tuple[int, int]], files: list[str], pair: bool = False) -> Counter:
    """Per-node within/cross degree, or the stricter degree to each partner file."""
    signature = Counter()
    for a, b in edges:
        for source, target in ((a, b), (b, a)):
            kind = files[target] if pair else ('within' if files[source] == files[target] else 'cross')
            signature[(source, kind)] += 1
    return signature


def rewire(edges: Iterable[tuple[int, int]], files: list[str], task_id: str, seed: int,
           pair: bool = False, attempts_per_edge: int = ATTEMPTS_PER_EDGE) -> tuple[list[tuple[int, int]], dict]:
    """Constrained simple-graph double-edge swaps; no uniformity/mixing claim."""
    original = set(edges)
    if any(a >= b for a, b in original):
        raise ValueError('Input must have canonical, non-self edges')
    salt = f'{task_id}|{seed}|{int(pair)}'.encode()
    rng = random.Random(int.from_bytes(hashlib.sha256(salt).digest()[:8], 'big'))
    buckets = defaultdict(list)
    for a, b in sorted(original):
        fa, fb = files[a], files[b]
        if fa == fb:
            key = ('within', fa, fa)
        elif pair:
            key = ('cross_pair', *sorted((fa, fb)))
        else:
            key = ('cross', '', '')
        buckets[key].append((a, b))
    current = set(original)
    attempted = accepted = 0
    for key in sorted(buckets):
        entries = buckets[key]
        if len(entries) < 2:
            continue
        for _ in range(attempts_per_edge * len(entries)):
            attempted += 1
            first, second = rng.sample(range(len(entries)), 2)
            a, b = entries[first]
            c, d = entries[second]
            if key[0] == 'cross_pair':
                if files[a] != key[1]:
                    a, b = b, a
                if files[c] != key[1]:
                    c, d = d, c
            else:
                if rng.getrandbits(1):
                    a, b = b, a
                if rng.getrandbits(1):
                    c, d = d, c
            if len({a, b, c, d}) != 4:
                continue
            if key[0] != 'within' and (files[a] == files[d] or files[c] == files[b]):
                continue
            new_first, new_second = edge(a, d), edge(c, b)
            if new_first in current or new_second in current or new_first == new_second:
                continue
            current.remove(entries[first])
            current.remove(entries[second])
            current.update((new_first, new_second))
            entries[first], entries[second] = new_first, new_second
            accepted += 1
    if len(current) != len(original) or degree_signature(current, files) != degree_signature(original, files):
        raise AssertionError('Rewiring changed a per-node within/cross degree')
    if pair and degree_signature(current, files, True) != degree_signature(original, files, True):
        raise AssertionError('Strict rewiring changed a per-node partner-file degree')
    changed = len(original - current)
    return sorted(current), {'seed': seed, 'attempts': attempted, 'accepted': accepted,
                             'edges': len(original), 'changed_edges': changed,
                             'changed_fraction': changed / len(original) if original else 0.0}


def body_documents(nodes: dict[str, dict], files: dict[str, str], body_lines: int = 80):
    from experiments.retrieve import document_text
    lines_of = {}
    for node_id, node in nodes.items():
        path = node.get('file', '')
        if path not in lines_of:
            lines_of[path] = (files.get(path) or '').splitlines()
        start = max(node.get('lineno', 1) - 1, 0)
        end = min(node.get('end_lineno') or start + 1, start + body_lines)
        yield node_id, document_text(node) + '\n' + '\n'.join(lines_of[path][start:end])


def bm25_subset(documents: Iterable[tuple[str, str]], query: str, wanted: list[str],
                k1: float = 1.2, b: float = 0.75) -> list[float]:
    """Exact corpus-statistic BM25 scores for selected IDs, without a full index."""
    terms = sorted(set(tokenize(query)))
    term_set, selected = set(terms), set(wanted)
    df = Counter()
    selected_counts = {}
    total_length = n = 0
    for doc_id, text in documents:
        counts = Counter(tokenize(text))
        length = sum(counts.values())
        total_length += length
        n += 1
        present = term_set.intersection(counts)
        df.update(present)
        if doc_id in selected:
            selected_counts[doc_id] = (length, {term: counts[term] for term in present})
    missing = selected - selected_counts.keys()
    if missing:
        raise ValueError(f'{len(missing)} candidate documents absent from corpus')
    avgdl = total_length / n if n else 1.0
    idf = {term: math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5)) for term in terms}
    out = []
    for doc_id in wanted:
        length, counts = selected_counts[doc_id]
        value = 0.0
        for term in terms:
            tf = counts.get(term, 0)
            if tf:
                value += idf[term] * tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / (avgdl or 1)))
        out.append(value)
    return out


def metrics(order: list[int], labels: list[int], total: int, files: list[str], gold_files: list[str],
            base: list[int]) -> dict:
    chosen, baseline = set(order[:10]), set(base[:10])
    hits = sum(labels[i] for i in chosen)
    file_hits = len({files[i] for i in chosen} & set(gold_files))
    gained = sum(labels[i] for i in chosen - baseline)
    lost = sum(labels[i] for i in baseline - chosen)
    return {'symbol': hits / total, 'file': file_hits / len(set(gold_files)) if gold_files else 0.0,
            'gained': gained, 'lost': lost, 'top10': order[:10]}


def evaluate(context: dict) -> dict:
    files, edges = context['files'], [tuple(e) for e in context['edges']]
    true_adj = adjacency(edges)
    randomized = {}
    diagnostics = {}
    for name, pair in (('rewired', False), ('rewired_pair', True)):
        randomized[name] = []
        diagnostics[name] = []
        for seed in SEEDS:
            randomized_edges, diag = rewire(edges, files, context['instance_id'], seed, pair)
            randomized[name].append(adjacency(randomized_edges))
            diagnostics[name].append(diag)
    representations = {}
    for name, order in context['orders'].items():
        mark = reachable(order, true_adj)
        ranked = {'base': order[:10], 'real': promote(order, mark),
                  'file': promote(order, file_marked(order, files))}
        for family, graphs in randomized.items():
            for seed, graph, diag in zip(SEEDS, graphs, diagnostics[family]):
                other_mark = reachable(order, graph)
                ranked[f'{family}_{seed}'] = promote(order, other_mark)
                diag.setdefault('reach_changed', {})[name] = len(mark.symmetric_difference(other_mark))
        representations[name] = {
            'marked_candidates': len(mark),
            'arms': {arm: metrics(top, context['labels'], context['gold_total'], files,
                                  context['gold_files'], order) for arm, top in ranked.items()}}
    return {'instance_id': context['instance_id'], 'repo': context['repo'],
            'pool_size': len(files), 'pool_gold': sum(context['labels']),
            'gold_total': context['gold_total'], 'graph_edges': len(edges),
            'seconds': context.get('seconds', 0), 'rewiring': diagnostics,
            'representations': representations}
