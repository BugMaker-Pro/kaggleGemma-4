"""Paired single-round feedback pilot. Inputs can be prepared without a generator.

prepare-inputs -> freeze --model-dir LOCAL_CHAT_MODEL -> generate -> retrieve -> evaluate
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from experiments.buildgraph import build_graph, read_snapshot
from experiments.feedback_pilot import (ARMS, CONFIG, code_excerpts, paired_requests, parse_queries,
                                       rank_queries, validate_pair_order)
from experiments.query_pilot import TaskInput, canonical, digest, file_hash, stable_search
from experiments.retrieve import BM25, document_text
from experiments.snapindex import SnapshotIndex
from tools.analyse_candidate_retention import read_parent, read_rows

SOURCES = ["experiments/feedback_pilot.py", "tools/run_feedback_pilot.py",
           "tools/analyse_candidate_retention.py", "experiments/candidate_retention.py"]


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2)+"\n")


def prepare_inputs(args):
    parent, traces = read_parent(args.parent)
    tasks = [TaskInput.from_mapping(r) for r in read_rows(args.parent / "tasks.jsonl")]
    requests, contexts = [], []
    for task, trace in zip(tasks, traces):
        if trace["status"] != "ok":
            raise ValueError("Parent retrieval failure: cannot silently drop a paired task")
        start = time.perf_counter()
        path = SnapshotIndex(args.repos).path_for({"instance_id": task.instance_id, "repo": task.repo, "base_commit": task.base_commit})
        if path is None:
            raise FileNotFoundError(task.instance_id)
        files = read_snapshot(path)
        if digest(sorted(files.items())) != trace["snapshot_content_sha256"]:
            raise ValueError("Snapshot differs from parent")
        excerpts = code_excerpts(files, trace["actions"]["original"]["candidates"])
        requests.extend(paired_requests(task, excerpts))
        contexts.append({"instance_id": task.instance_id, "snapshot_content_sha256": trace["snapshot_content_sha256"],
                         "excerpts": excerpts, "source_chars_read": sum(map(len, files.values())),
                         "preparation_seconds": time.perf_counter()-start})
        print(f"prepared {task.instance_id}", flush=True)
    validate_pair_order(requests, parent["task_ids"])
    args.out.mkdir(parents=True, exist_ok=False)
    for name, rows in (("requests.jsonl", requests), ("contexts.jsonl", contexts)):
        with (args.out / name).open("x", encoding="utf-8") as stream:
            for row in rows:
                stream.write(canonical(row)+"\n")
    manifest = {"schema": 1, "date": "2026-11-02", "stage": "paired_inputs_awaiting_generator",
                "parent_manifest_sha256": parent["manifest_sha256"],
                "parent_trace_sha256": file_hash(args.parent / "trace.jsonl"), "task_ids": parent["task_ids"],
                "source_hashes": {name: file_hash(ROOT/name) for name in SOURCES},
                "requests_sha256": file_hash(args.out / "requests.jsonl"),
                "contexts_sha256": file_hash(args.out / "contexts.jsonl"), "config": CONFIG,
                "model": None, "formal_run_frozen": False,
                "primary": "feedback minus preplanned macro symbol recall@10; coverage secondary",
                "continuation_delta": 0.02, "automatic_expansion": False,
                "limits": ["Historically used tasks; exploratory only, not unseen confirmation",
                           "One model call and two generated queries per arm; no evidence-state controller",
                           "Only feedback sees the original query's first five code windows",
                           "Same token ceilings, different actual input tokens; no equal-cost claim",
                           "Invalid JSON, budget failure or generation error falls back to original ranking",
                           "No retries; no query repair; no gold-guided selection",
                           "RRF final ranking; strongest learned ranker comparison pending",
                           "Original candidates may include module nodes",
                           "Full snapshot IO for preparation logged separately from model-exposed code"]}
    manifest["manifest_sha256"] = digest(manifest)
    write_json(args.out / "manifest.json", manifest)
    print(canonical({"inputs": len(requests), "model_status": "not_configured", "path": str(args.out)}))


def load_bundle(directory, parent_dir):
    m = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    fingerprint = m.pop("manifest_sha256")
    if digest(m) != fingerprint:
        raise ValueError("Input manifest changed")
    m["manifest_sha256"] = fingerprint
    parent, traces = read_parent(parent_dir)
    if m["parent_manifest_sha256"] != parent["manifest_sha256"] or m["parent_trace_sha256"] != file_hash(parent_dir/"trace.jsonl"):
        raise ValueError("Parent changed")
    if m["task_ids"] != parent["task_ids"]:
        raise ValueError("Task IDs changed")
    for name, expected in m["source_hashes"].items():
        if file_hash(ROOT/name) != expected:
            raise ValueError(f"Input source changed: {name}")
    for name in ("requests", "contexts"):
        if file_hash(directory / f"{name}.jsonl") != m[f"{name}_sha256"]:
            raise ValueError("Paired input changed")
    requests = read_rows(directory / "requests.jsonl")
    validate_pair_order(requests, m["task_ids"])
    return m, requests, traces


def model_files(directory):
    config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
    if not any("ForCausalLM" in name or name.endswith("LMHeadModel") for name in config.get("architectures", [])):
        raise ValueError("This runner requires a local causal chat language model; encoders/rerankers are not supported")
    if not any(directory.glob("*.safetensors")) and not any(directory.glob("pytorch_model*.bin")):
        raise ValueError("Local model weights missing")
    return {p.relative_to(directory).as_posix(): file_hash(p) for p in sorted(directory.rglob("*"))
            if p.is_file() and not any(part.startswith(".") for part in p.relative_to(directory).parts)}


def token_ids(tokenizer, request):
    rendered = tokenizer.apply_chat_template(request["messages"], tokenize=False, add_generation_prompt=True)
    return tokenizer(rendered, add_special_tokens=False)["input_ids"]


def freeze(args):
    m, requests, _ = load_bundle(args.bundle, args.parent)
    weights = model_files(args.model_dir)
    import importlib.metadata
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(str(args.model_dir), local_files_only=True, trust_remote_code=False)
    if not tokenizer.chat_template:
        raise ValueError("Model has no chat template")
    counts = {r["request_sha256"]: len(token_ids(tokenizer, r)) for r in requests}
    # Do not silently shorten prompts after observing the model or outputs.
    if any(n > CONFIG["max_input_tokens"] for n in counts.values()):
        raise ValueError("A request exceeds the input token cap; prepare a separately versioned protocol")
    args.out.mkdir(parents=True, exist_ok=False)
    manifest = {"schema": 1, "stage": "frozen_single_round_generation", "bundle_sha256": m["manifest_sha256"],
                "config": CONFIG, "model_files": weights, "model_sha256": digest(weights),
                "model_label": args.model_dir.name, "input_token_counts": counts,
                "packages": {p: importlib.metadata.version(p) for p in ("torch", "transformers", "tokenizers")},
                "generation": {"do_sample": False, "max_new_tokens": CONFIG["max_output_tokens"],
                               "device": args.device, "dtype": "float16" if args.device == "cuda" else "float32"},
                "evaluation": {"primary": m["primary"], "minimum_worthwhile_delta": .02,
                               "bootstrap_seed": 20261102, "bootstrap_replicates": 2000,
                               "failure_policy": "original-only fallback; retained in denominator",
                               "automatic_expansion": False}}
    manifest["manifest_sha256"] = digest(manifest)
    write_json(args.out / "manifest.json", manifest)
    print(canonical({"frozen": str(args.out), "model_sha256": manifest["model_sha256"]}))


def load_run(args):
    bundle, requests, traces = load_bundle(args.bundle, args.parent)
    m = json.loads((args.run_dir / "manifest.json").read_text(encoding="utf-8"))
    expected = m.pop("manifest_sha256")
    if digest(m) != expected or m["bundle_sha256"] != bundle["manifest_sha256"]:
        raise ValueError("Generation manifest changed")
    m["manifest_sha256"] = expected
    return m, requests, traces


def generate(args):
    m, requests, _ = load_run(args)
    if model_files(args.model_dir) != m["model_files"]:
        raise ValueError("Local model differs from frozen version")
    import importlib.metadata
    if any(importlib.metadata.version(p) != v for p, v in m["packages"].items()):
        raise ValueError("Inference packages changed")
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(str(args.model_dir), local_files_only=True, trust_remote_code=False)
    device = m["generation"]["device"]
    dtype = torch.float16 if device == "cuda" else torch.float32
    model = AutoModelForCausalLM.from_pretrained(str(args.model_dir), local_files_only=True,
                                               trust_remote_code=False, dtype=dtype).to(device).eval()
    required_context = max(m["input_token_counts"].values()) + CONFIG["max_output_tokens"]
    if getattr(model.config, "max_position_embeddings", 0) < required_context:
        raise ValueError("Model context limit is smaller than the longest frozen prompt plus output cap")
    with (args.run_dir / "responses.jsonl").open("x", encoding="utf-8") as output:
        for request in requests:
            ids = token_ids(tokenizer, request)
            if len(ids) != m["input_token_counts"][request["request_sha256"]]:
                raise ValueError("Tokenizer input count changed")
            row = {"instance_id": request["instance_id"], "arm": request["arm"],
                   "request_sha256": request["request_sha256"], "manifest_sha256": m["manifest_sha256"],
                   "model_sha256": m["model_sha256"], "input_tokens": len(ids), "output_tokens": None,
                   "model_calls": 1, "status": "generation_error", "raw_output": "", "queries": []}
            start = time.perf_counter()
            try:
                inputs = torch.tensor([ids], device=device)
                with torch.inference_mode():
                    generated = model.generate(input_ids=inputs, attention_mask=torch.ones_like(inputs),
                                               do_sample=False, max_new_tokens=CONFIG["max_output_tokens"],
                                               pad_token_id=tokenizer.pad_token_id if tokenizer.pad_token_id is not None else tokenizer.eos_token_id)
                continuation = generated[0, len(ids):].tolist()
                row["output_tokens"] = len(continuation)
                row["raw_output"] = tokenizer.decode(continuation, skip_special_tokens=True)
                row["queries"] = parse_queries(row["raw_output"])
                row["status"] = "ok"
            except (ValueError, RuntimeError) as exc:
                row["error"] = f"{type(exc).__name__}: {exc}"
                row["status"] = "invalid_output" if row["output_tokens"] is not None else "generation_error"
            row["seconds"] = time.perf_counter()-start
            output.write(canonical(row)+"\n")
            output.flush()
            print(f"{row['instance_id']} {row['arm']} {row['status']}", flush=True)


def validate_responses(responses, requests, m):
    if [(r["instance_id"], r["arm"]) for r in responses] != [(r["instance_id"], r["arm"]) for r in requests]:
        raise ValueError("Incomplete or reordered generation responses")
    for response, request in zip(responses, requests):
        if (response["manifest_sha256"] != m["manifest_sha256"] or response["model_sha256"] != m["model_sha256"]
                or response["request_sha256"] != request["request_sha256"] or response["model_calls"] != 1
                or response["input_tokens"] != m["input_token_counts"][request["request_sha256"]]
                or response["input_tokens"] > CONFIG["max_input_tokens"]):
            raise ValueError("Response provenance or token count mismatch")
        tokens = response["output_tokens"]
        if tokens is not None and (type(tokens) is not int or not 0 <= tokens <= CONFIG["max_output_tokens"]
                                   or tokens+response["input_tokens"] > CONFIG["max_total_tokens"]):
            raise ValueError("Generation token budget exceeded")
        if response["status"] == "ok":
            if tokens is None or response["queries"] != parse_queries(response["raw_output"]):
                raise ValueError("Query differs from saved model output")
        elif response["status"] not in ("generation_error", "invalid_output") or response["queries"] or not response.get("error"):
            raise ValueError("Malformed failed generation")


def build_index(files):
    if sum(map(len, files.values())) > CONFIG["max_source_chars"]:
        raise ValueError("Source cap exceeded")
    graph, _ = build_graph(files)
    if len(graph.nodes) > CONFIG["max_index_nodes"]:
        raise ValueError("Index cap exceeded")
    lines = {path: source.splitlines() for path, source in files.items()}
    docs = {}
    for node_id, node in sorted(graph.nodes.items()):
        start = max(node["lineno"]-1, 0)
        end = min(node["end_lineno"], start+CONFIG["body_lines"])
        docs[node_id] = document_text(node)+"\n"+"\n".join(lines[node["file"]][start:end])
    return BM25(docs)


def retrieve(args):
    m, requests, traces = load_run(args)
    responses = read_rows(args.run_dir / "responses.jsonl")
    validate_responses(responses, requests, m)
    with (args.run_dir / "retrieval.jsonl").open("x", encoding="utf-8") as output:
        for number, trace in enumerate(traces):
            start = time.perf_counter()
            path = SnapshotIndex(args.repos).path_for(trace)
            if path is None:
                raise FileNotFoundError(trace["instance_id"])
            files = read_snapshot(path)
            if digest(sorted(files.items())) != trace["snapshot_content_sha256"]:
                raise ValueError("Snapshot changed")
            index = build_index(files)
            original_action = trace["actions"]["original"]
            original = original_action["candidates"]
            replay_original, _ = stable_search(index, original_action["query"], CONFIG["per_action_candidates"])
            if [(x["id"],x["score"]) for x in replay_original] != [(x["id"],x["score"]) for x in original]:
                raise ValueError("Original ranking no longer reproduces")
            prep_seconds = time.perf_counter()-start
            for response in responses[number*2:number*2+2]:
                actions = []
                for query in response["queries"]:
                    query_start = time.perf_counter()
                    candidates, scored = stable_search(index, query, CONFIG["per_action_candidates"])
                    actions.append({"query": query, "candidates": candidates, "scored_documents": scored,
                                    "seconds": time.perf_counter()-query_start})
                scored_total = original_action["cost"]["scored_documents"]+sum(x["scored_documents"] for x in actions)
                if scored_total > CONFIG["max_scored_documents"]:
                    raise ValueError("Retrieval scoring budget exceeded")
                row = {"instance_id": trace["instance_id"], "repo": trace["repo"], "base_commit": trace["base_commit"],
                       "arm": response["arm"], "request_sha256": response["request_sha256"],
                       "manifest_sha256": m["manifest_sha256"], "response_sha256": digest(response),
                       "status": response["status"], "actions": actions,
                       "order": rank_queries(original, [x["candidates"] for x in actions]),
                       "scored_documents": scored_total, "retrieval_calls": 1+len(actions), "index_nodes": index.n,
                       "shared_index_seconds": prep_seconds,
                       "source_chars_read": sum(map(len, files.values()))}
                output.write(canonical(row)+"\n")
                output.flush()
            print(f"retrieved {trace['instance_id']}", flush=True)



def validate_retrieval(result, response, trace, manifest):
    if (result["manifest_sha256"] != manifest["manifest_sha256"] or result["response_sha256"] != digest(response)
            or result["request_sha256"] != response["request_sha256"] or result["arm"] != response["arm"]
            or result["status"] != response["status"]
            or any(result[key] != trace[key] for key in ("instance_id", "repo", "base_commit"))):
        raise ValueError("Retrieval provenance mismatch")
    if [a["query"] for a in result["actions"]] != response["queries"]:
        raise ValueError("Executed query differs from model response")
    if result["retrieval_calls"] != 1+len(result["actions"]) or result["retrieval_calls"] > CONFIG["retrieval_calls"]:
        raise ValueError("Retrieval call budget mismatch")
    if not 0 <= result["index_nodes"] <= CONFIG["max_index_nodes"]:
        raise ValueError("Index size limit mismatch")
    total = trace["actions"]["original"]["cost"]["scored_documents"]
    for action in result["actions"]:
        candidates = action["candidates"]
        ids = [x["id"] for x in candidates]
        if len(ids) != len(set(ids)) or len(ids) > CONFIG["per_action_candidates"]:
            raise ValueError("Invalid generated candidate count")
        if any(not math.isfinite(x["score"]) or x["score"] <= 0 for x in candidates):
            raise ValueError("Invalid candidate score")
        if candidates != sorted(candidates,key=lambda x:(-x["score"],x["id"])):
            raise ValueError("Generated action ranking changed")
        if not len(ids) <= action["scored_documents"] <= result["index_nodes"]:
            raise ValueError("Scored document count mismatch")
        total += action["scored_documents"]
    if total != result["scored_documents"] or total > CONFIG["max_scored_documents"]:
        raise ValueError("Retrieval scoring budget mismatch")
    expected = rank_queries(trace["actions"]["original"]["candidates"], [a["candidates"] for a in result["actions"]])
    if result["order"] != expected:
        raise ValueError("Candidate fusion changed")
    return expected


def evaluate(args):
    # Gold is imported and opened only here, after generation and retrieval.
    from tools.evaluate_query_pilot import gold_targets
    m, requests, traces = load_run(args)
    responses = read_rows(args.run_dir / "responses.jsonl")
    validate_responses(responses, requests, m)
    retrievals = read_rows(args.run_dir / "retrieval.jsonl")
    if [(r["instance_id"],r["arm"]) for r in retrievals] != [(r["instance_id"],r["arm"]) for r in requests]:
        raise ValueError("Incomplete retrieval pairs")
    records = read_rows(args.gold)
    gold = {r["instance_id"]: r for r in records}
    if len(gold) != len(records):
        raise ValueError("Duplicate gold IDs")
    scored = []
    for i, trace in enumerate(traces):
        record = gold.get(trace["instance_id"])
        if record and any(record.get(key) != trace[key] for key in ("repo", "base_commit")):
            raise ValueError("Gold identity mismatch")
        targets = gold_targets(record) if record else set()
        row = {"instance_id": trace["instance_id"], "repo": trace["repo"], "scorable": bool(targets),
               "gold_status": "missing" if record is None else ("symbols" if targets else "no_symbols"), "arms": {}}
        for result, response in zip(retrievals[2*i:2*i+2],responses[2*i:2*i+2]):
            expected = validate_retrieval(result, response, trace, m)
            row["arms"][result["arm"]] = {"coverage": len(set(expected)&targets)/len(targets) if targets else None,
                "recall_at_10": len(set(expected[:CONFIG["final_k"]])&targets)/len(targets) if targets else None,
                "status": response["status"], "input_tokens": response["input_tokens"], "output_tokens": response["output_tokens"],
                "model_calls": response["model_calls"], "retrieval_calls": result["retrieval_calls"]}
        scored.append(row)
    valid = [r for r in scored if r["scorable"]]
    if not valid:
        raise ValueError("No scorable tasks")
    means = {arm: {metric: statistics.mean(r["arms"][arm][metric] for r in valid) for metric in ("coverage", "recall_at_10")} for arm in ARMS}
    groups = {}
    for row in valid:
        groups.setdefault(row["repo"],[]).append(row["arms"]["feedback"]["recall_at_10"]-row["arms"]["preplanned"]["recall_at_10"])
    rng = random.Random(20261102)
    repos = sorted(groups)
    interval = None
    if len(repos) >= 2:
        values = sorted(statistics.mean(v for repo in rng.choices(repos,k=len(repos)) for v in groups[repo]) for _ in range(2000))
        interval = [values[int(.025*1999)],values[int(.975*1999)]]
    summary = {"manifest_sha256": m["manifest_sha256"], "gold_sha256": file_hash(args.gold),
               "responses_sha256": file_hash(args.run_dir/"responses.jsonl"),
               "retrieval_sha256": file_hash(args.run_dir/"retrieval.jsonl"), "tasks": len(traces), "scorable_tasks": len(valid),
               "means": means, "primary_delta": means["feedback"]["recall_at_10"]-means["preplanned"]["recall_at_10"],
               "descriptive_repo_bootstrap_95": interval,
               "fallbacks": {arm: sum(r["arm"]==arm and r["status"]!="ok" for r in responses) for arm in ARMS},
               "unknown_output_token_counts": sum(r["output_tokens"] is None for r in responses),
               "usage": {arm: {"input_tokens": sum(r["input_tokens"] for r in responses if r["arm"] == arm),
                                "known_output_tokens": sum(r["output_tokens"] or 0 for r in responses if r["arm"] == arm),
                                "model_calls": sum(r["model_calls"] for r in responses if r["arm"] == arm),
                                "retrieval_calls": sum(r["retrieval_calls"] for r in retrievals if r["arm"] == arm),
                                "code_chars_exposed": sum(r["code_chars_exposed"] for r in requests if r["arm"] == arm)} for arm in ARMS},
               "automatic_expansion": False, "claim": "exploratory paired feedback probe; no evidence-state mechanism claim"}
    with (args.run_dir/"scores.jsonl").open("x",encoding="utf-8") as stream:
        for row in scored:
            stream.write(canonical(row)+"\n")
    write_json(args.run_dir/"summary.json",summary)
    print(json.dumps(summary,ensure_ascii=False,indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command",required=True)
    for command in ("prepare-inputs","freeze","generate","retrieve","evaluate"):
        p = sub.add_parser(command)
        p.add_argument("--parent",type=Path,default=ROOT/"experiments/runs/query-pilot-20261102-v1")
        if command != "prepare-inputs":
            p.add_argument("--bundle",type=Path,required=True)
        if command in ("prepare-inputs","freeze"):
            p.add_argument("--out",type=Path,required=True)
        else:
            p.add_argument("--run-dir",type=Path,required=True)
        if command in ("prepare-inputs","retrieve"):
            p.add_argument("--repos",type=Path,default=ROOT/"data/repos")
        if command in ("freeze","generate"):
            p.add_argument("--model-dir",type=Path,required=True)
        if command == "freeze":
            p.add_argument("--device",choices=("cuda","cpu"),default="cuda")
        if command == "evaluate":
            p.add_argument("--gold",type=Path,default=ROOT/"data/gold_symbols.jsonl")
    args=parser.parse_args()
    {"prepare-inputs":prepare_inputs,"freeze":freeze,"generate":generate,"retrieve":retrieve,"evaluate":evaluate}[args.command](args)


if __name__ == "__main__":
    main()
