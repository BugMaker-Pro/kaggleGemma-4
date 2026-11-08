"""Gold-free candidate membership control over already retrieved rankings."""
from __future__ import annotations

from experiments.query_pilot import ACTIONS, merge_actions


def round_robin_pool(results, selected, cap):
    """Each list contributes its next unseen ID per turn; no rank/label lookahead.

    Original list goes first, supplemental lists follow the frozen ACTIONS order.
    Duplicates consume no slot or turn: skip to the next unseen ID in that list.
    """
    if cap < 0 or len(selected) != len(set(selected)) or any(a not in ACTIONS for a in selected):
        raise ValueError("Invalid candidate cap or actions")
    actions = ("original", *(a for a in ACTIONS if a in selected))
    lists = [[row["id"] for row in results[a]["candidates"]] for a in actions]
    if any(len(ids) != len(set(ids)) for ids in lists):
        raise ValueError("Duplicate candidate within an action")
    positions = [0] * len(lists)
    chosen = []
    seen = set()
    while len(chosen) < cap:
        progressed = False
        for i, ids in enumerate(lists):
            while positions[i] < len(ids) and ids[positions[i]] in seen:
                positions[i] += 1
            if positions[i] == len(ids):
                continue
            node_id = ids[positions[i]]
            positions[i] += 1
            chosen.append(node_id)
            seen.add(node_id)
            progressed = True
            if len(chosen) == cap:
                break
        if not progressed:
            break
    return chosen


def retain_candidates(results, selected, cap, rrf_k):
    """Change membership only; rank retained IDs by the SAME full-union RRF."""
    union_size = sum(len(results[a]["candidates"]) for a in ("original", *selected))
    full_rrf = merge_actions(results, selected, union_size, rrf_k)
    membership = round_robin_pool(results, selected, cap)
    keep = set(membership)
    return {"rrf": full_rrf[:cap], "round_robin": [x for x in full_rrf if x in keep],
            "round_robin_admission": membership, "full_rrf": full_rrf}
