"""Read the serialized NetworkX graphs shipped with the benchmark.

Schema (from the official Data page, 2026-10-20):
  {"directed": bool, "multigraph": bool, "graph": {...},
   "nodes": [{"id": <fully-qualified symbol>, "name": ..., "text": <source>}, ...],
   "edges": [{"source": ..., "target": ..., "type": ..., "key": int}, ...]}
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class GraphSummary:
    path: str
    size_bytes: int
    ok: bool = False
    error: str = ""
    directed: bool = False
    multigraph: bool = False
    node_count: int = 0
    edge_count: int = 0
    nodes_with_text: int = 0
    node_ids: set[str] = field(default_factory=set)

    @property
    def empty(self) -> bool:
        return self.error == "empty"


def summarize(path: str | Path) -> GraphSummary:
    target = Path(path)
    size = target.stat().st_size if target.exists() else 0
    summary = GraphSummary(str(target), size)

    if size == 0:
        summary.error = "empty"
        return summary

    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        summary.error = f"unreadable:{type(exc).__name__}"
        return summary

    if not isinstance(raw, dict):
        summary.error = "not-an-object"
        return summary

    nodes = raw.get("nodes")
    edges = raw.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        summary.error = "missing-nodes-or-edges"
        return summary

    summary.ok = True
    summary.directed = bool(raw.get("directed", False))
    summary.multigraph = bool(raw.get("multigraph", False))
    summary.node_count = len(nodes)
    summary.edge_count = len(edges)
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = node.get("id")
        if isinstance(node_id, str) and node_id:
            summary.node_ids.add(node_id)
        if node.get("text"):
            summary.nodes_with_text += 1
    return summary
