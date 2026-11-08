"""Gold-free, deterministic fixed-query pilot. No model or repair execution."""
from __future__ import annotations

import hashlib
import itertools
import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from experiments.retrieve import BM25, tokenize

TASK_FIELDS = frozenset({"instance_id", "repo", "base_commit", "problem_statement"})
ACTIONS = ("identifiers", "code", "prose", "traceback")
FENCE = re.compile(r"\x60{3}[^\n]*\n([\s\S]*?)\x60{3}")
INLINE = re.compile(r"(?<!\x60)\x60([^\x60\n]+)\x60(?!\x60)")
PATH = re.compile(r"[\w./\\-]+\.py\b")
FRAME = re.compile(r'File ["\x27]([^"\x27]+)["\x27], line (\d+)(?:, in ([^\n]+))?')
DOTTED = re.compile(r"\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+\b")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class TaskInput:
    instance_id: str
    repo: str
    base_commit: str
    problem_statement: str

    @classmethod
    def from_mapping(cls, row):
        if set(row) != TASK_FIELDS:
            raise ValueError("Online task must contain exactly the four allowed input fields")
        if not all(isinstance(row[key], str) for key in TASK_FIELDS):
            raise ValueError("Online task fields must be strings")
        if not all(row[key] for key in TASK_FIELDS - {"problem_statement"}):
            raise ValueError("Task identity fields must not be empty")
        return cls(**row)


def sanitize_task(row):
    """Boundary adapter only: discard patches, tests and all other source fields."""
    return asdict(TaskInput.from_mapping({key: row[key] for key in sorted(TASK_FIELDS)}))


def extract_actions(task, issue_char_limit=20000, query_char_limit=4000):
    if not isinstance(task, TaskInput):
        raise TypeError("Expected sanitized TaskInput")
    issue = task.problem_statement[:issue_char_limit]
    spans = []
    code_ranges = [(m.start(), m.end()) for m in FENCE.finditer(issue)]
    for kind, pattern, group in (("code", FENCE, 1), ("inline", INLINE, 1),
                                  ("path", PATH, 0), ("dotted", DOTTED, 0),
                                  ("traceback", FRAME, 0)):
        for match in pattern.finditer(issue):
            start, end = match.span(group)
            if kind == "inline" and any(a <= start < b for a, b in code_ranges):
                continue
            spans.append({"kind": kind, "start": start, "end": end,
                          "text": issue[start:end], "status": "issue_span_only"})
    spans.sort(key=lambda item: (item["start"], item["end"], item["kind"]))
    kinds = {"identifiers": {"inline", "path", "dotted"}, "code": {"code"},
             "traceback": {"traceback"}}
    result = {"original": {"query": issue, "evidence_indices": []}}
    for action in ACTIONS:
        indices = [i for i, span in enumerate(spans) if span["kind"] in kinds.get(action, set())]
        if action == "prose":
            query = FENCE.sub(" ", issue)
            query = FRAME.sub(" ", query)
        else:
            query = "\n".join(dict.fromkeys(spans[i]["text"] for i in indices))
        query = query[:query_char_limit]
        result[action] = {"query": query, "evidence_indices": indices,
                          "available": bool(tokenize(query))}
    return {"issue_chars_seen": len(issue), "issue_truncated": len(issue) < len(task.problem_statement),
            "evidence": spans, "actions": result}


def stable_search(index: BM25, query: str, k: int):
    """Same BM25 formula as the baseline, with sorted terms and explicit ID ties."""
    scores = defaultdict(float)
    postings = index._index()
    for term in sorted(set(tokenize(query))):
        for i in postings.get(term, []):
            tf = index.tfs[i][term]
            denom = tf + index.k1 * (1 - index.b + index.b * index.lens[i] / (index.avgdl or 1))
            scores[i] += index._idf(term) * tf * (index.k1 + 1) / denom
    order = sorted(scores, key=lambda i: (-scores[i], index.ids[i]))[:k]
    return [{"id": index.ids[i], "score": scores[i]} for i in order], len(scores)


def merge_actions(results, selected, cap, rrf_k):
    """Gold-independent fusion and truncation, shared by fixed arms and oracle."""
    if len(selected) != len(set(selected)):
        raise ValueError("Duplicate selected action")
    scores = defaultdict(float)
    for action in ("original", *selected):
        seen = set()
        for rank, candidate in enumerate(results[action]["candidates"], 1):
            node_id = candidate["id"]
            if node_id in seen:
                raise ValueError("Duplicate candidate in action")
            seen.add(node_id)
            scores[node_id] += 1.0 / (rrf_k + rank)
    return sorted(scores, key=lambda node_id: (-scores[node_id], node_id))[:cap]


def arm_cost(results, selected):
    rows = [results[key] for key in ("original", *selected)]
    return {"retrieval_calls": sum(row["cost"]["retrieval_calls"] for row in rows),
            "query_chars": sum(row["cost"]["query_chars"] for row in rows),
            "scored_documents": sum(row["cost"]["scored_documents"] for row in rows),
            "returned_candidates": sum(len(row["candidates"]) for row in rows),
            "unique_candidates": len({x["id"] for row in rows for x in row["candidates"]}),
            "search_seconds": sum(row["cost"]["search_seconds"] for row in rows),
            "model_calls": 0, "model_input_tokens": 0, "model_output_tokens": 0}


def allowed_sequences(results, config):
    available = [key for key in ACTIONS if results[key]["available"]]
    for count in range(config["max_supplemental_actions"] + 1):
        for selected in itertools.combinations(available, count):
            cost = arm_cost(results, selected)
            if (cost["retrieval_calls"] <= config["max_retrieval_calls"]
                    and cost["scored_documents"] <= config["max_scored_documents"]
                    and cost["query_chars"] <= config["max_total_query_chars"]):
                yield selected


def load_manifest(directory):
    manifest = json.loads((Path(directory) / "manifest.json").read_text(encoding="utf-8"))
    fingerprint = manifest.pop("manifest_sha256")
    if digest(manifest) != fingerprint:
        raise ValueError("Manifest fingerprint mismatch")
    manifest["manifest_sha256"] = fingerprint
    if file_hash(Path(directory) / "tasks.jsonl") != manifest["tasks_sha256"]:
        raise ValueError("Sanitized task file changed")
    return manifest
