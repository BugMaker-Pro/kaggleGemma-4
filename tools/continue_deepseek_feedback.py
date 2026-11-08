"""DeepSeek API adapter for the frozen paired feedback inputs.

No key is stored in manifests, requests, receipts or error logs. No automatic retries.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import random
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from experiments.feedback_pilot import ARMS, CONFIG, parse_queries, rank_queries
from experiments.query_pilot import canonical, digest, file_hash, stable_search
from experiments.buildgraph import read_snapshot
from experiments.snapindex import SnapshotIndex
from tools.analyse_candidate_retention import read_rows
from tools.run_feedback_pilot import load_bundle, build_index, validate_retrieval, write_json

ENDPOINT = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-flash"
API_CONFIG = {"model": MODEL, "thinking": {"type": "disabled"},
              "response_format": {"type": "json_object"}, "temperature": 0,
              "max_tokens": 256, "stream": False}
PRICES = {"idle": {"input_hit": .02, "input_miss": 1.0, "output": 4.0},
          "peak": {"input_hit": .04, "input_miss": 2.0, "output": 8.0}}


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def load_key(path):
    """A small non-interpolating dotenv reader; never log values or parse errors."""
    values = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.removeprefix("export ").split("=", 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            else:
                value = value.split(" #", 1)[0].strip()
            values[name.strip()] = value
    key = os.environ.get("DEEPSEEK_API_KEY") or values.get("DEEPSEEK_API_KEY") or values.get("API_KEY")
    if not key or any(c.isspace() for c in key):
        raise ValueError("Missing or malformed API key; use DEEPSEEK_API_KEY or API_KEY in local .env")
    return key


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "Redirect refused", headers, fp)


def reserve_cost(request):
    # Conservative planning surrogate, not claimed to be actual tokenizer counts.
    input_bound = len(canonical(request["messages"]).encode("utf-8")) + 1024
    return (input_bound * PRICES["peak"]["input_miss"] + 256 * PRICES["peak"]["output"])/1e6


def usage_cost(usage, tariff):
    price = PRICES[tariff]
    total = usage["prompt_tokens"]
    hit = usage.get("prompt_cache_hit_tokens", 0)
    miss = usage.get("prompt_cache_miss_tokens", total-hit)
    if hit < 0 or miss < 0 or hit+miss != total:
        raise ValueError("Inconsistent cache usage counts")
    return (hit*price["input_hit"] + miss*price["input_miss"] + usage["completion_tokens"]*price["output"])/1e6


def freeze(args):
    bundle, requests, _ = load_bundle(args.bundle, args.parent)
    # Validate credentials locally, without sending them and without persisting them.
    load_key(args.env_file)
    reserve = sum(reserve_cost(r) for r in requests)
    if reserve > 5:
        raise ValueError("Planned API reservation exceeds 5 CNY")
    m = {"schema": 1, "date": "2026-11-02", "created_utc": utc_now(),
         "stage": "frozen_deepseek_flash_single_round", "bundle_sha256": bundle["manifest_sha256"],
         "task_ids": bundle["task_ids"], "request_ids": [r["request_sha256"] for r in requests],
         "config": CONFIG, "api": API_CONFIG, "endpoint": ENDPOINT,
         "source_hashes": {"tools/run_deepseek_feedback.py": file_hash(Path(__file__))},
         "model_sha256": digest(API_CONFIG), "max_calls": len(requests), "retries": 0,
         "budget_cny": 5.0, "planning_reservation_cny": reserve,
         "prices_cny_per_million": PRICES, "price_date": "2026-11-02",
         "token_preflight": "Exact remote tokenizer unavailable; postcheck provider usage against frozen caps. Budget planning uses UTF-8 bytes plus 1024 overhead per request, not an exact token guarantee.",
         "version_policy": "Record API response model and system_fingerprint; alias is mutable, not an immutable checkpoint.",
         "evaluation": {"primary": "feedback minus preplanned macro recall@10", "minimum_worthwhile_delta": .02,
                        "bootstrap_replicates": 2000, "bootstrap_seed": 20261102,
                        "failure_policy": "invalid completed output -> original-only fallback; transport or accounting uncertainty -> stop without retry",
                        "automatic_expansion": False}}
    m["manifest_sha256"] = digest(m)
    args.out.mkdir(parents=True, exist_ok=False)
    write_json(args.out/"manifest.json",m)
    print(canonical({"frozen":str(args.out), "model":MODEL, "calls":len(requests), "reservation_cny":reserve, "key":"loaded, not displayed"}))


def load_run(args):
    bundle, requests, traces = load_bundle(args.bundle,args.parent)
    m = json.loads((args.run_dir/"manifest.json").read_text(encoding="utf-8"))
    expected = m.pop("manifest_sha256")
    if digest(m) != expected or m["bundle_sha256"] != bundle["manifest_sha256"]:
        raise ValueError("API manifest or bundle mismatch")
    m["manifest_sha256"] = expected
    if m["api"] != API_CONFIG or m["endpoint"] != ENDPOINT or m["request_ids"] != [r["request_sha256"] for r in requests]:
        raise ValueError("API settings or request set changed")
    for name, value in m["source_hashes"].items():
        if file_hash(ROOT/name) != value:
            raise ValueError("API source changed after freeze")
    continuation = json.loads((args.run_dir/"continuation.json").read_text(encoding="utf-8"))
    fingerprint = continuation.pop("sha256")
    if digest(continuation) != fingerprint or continuation["parent_manifest_sha256"] != m["manifest_sha256"] or continuation["source_sha256"] != file_hash(Path(__file__)):
        raise ValueError("Continuation configuration or code changed")
    return m, requests, traces


def decode_response(raw, request, m, elapsed):
    usage = raw.get("usage", {})
    prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
    if type(prompt) is not int or type(completion) is not int or prompt < 0 or completion < 0:
        raise ValueError("Provider usage missing or invalid; stop for accounting review")
    if prompt > CONFIG["max_input_tokens"] or completion > CONFIG["max_output_tokens"] or prompt+completion > CONFIG["max_total_tokens"]:
        raise ValueError("Provider token usage exceeds frozen cap; stop")
    choices = raw.get("choices", [])
    if len(choices) != 1:
        raise ValueError("Unexpected provider choices")
    message = choices[0].get("message", {})
    if message.get("reasoning_content"):
        raise ValueError("Provider returned thinking content despite disabled mode")
    output = message.get("content") or ""
    row = {"instance_id":request["instance_id"], "arm":request["arm"], "request_sha256":request["request_sha256"],
           "manifest_sha256":m["manifest_sha256"], "model_sha256":m["model_sha256"],
           "provider_model":raw.get("model"), "system_fingerprint":raw.get("system_fingerprint"),
           "provider_response_id":raw.get("id"), "finish_reason":choices[0].get("finish_reason"),
           "input_tokens":prompt, "output_tokens":completion, "provider_usage":usage,
           "model_calls":1, "status":"ok", "raw_output":output, "queries":[], "seconds":elapsed,
           "estimated_cny_idle":usage_cost(usage,"idle"), "estimated_cny_peak":usage_cost(usage,"peak")}
    try:
        if row["finish_reason"] != "stop":
            raise ValueError("Generation did not finish normally")
        row["queries"] = parse_queries(output)
    except (ValueError, TypeError):
        row["status"] = "invalid_output"
        row["error"] = "Output violated frozen query schema or finish condition; no repair attempted"
    return row



def unknown_response(request, m):
    return {"instance_id":request["instance_id"],"arm":request["arm"],"request_sha256":request["request_sha256"],
            "manifest_sha256":m["manifest_sha256"],"model_sha256":m["model_sha256"],"model_calls":1,
            "provider_model":None,"system_fingerprint":None,"input_tokens":None,"output_tokens":None,
            "provider_usage":None,"status":"transport_unknown","raw_output":"","queries":[],
            "error":"Request failed at transport/JSON stage; not resent; provider completion and billing unknown",
            "estimated_cny_idle":None,"estimated_cny_peak":None,"reservation_cny":reserve_cost(request)}


def validate_responses(responses, requests, m):
    if len(responses) != len(requests):
        raise ValueError("Incomplete API response set")
    for row, request in zip(responses,requests):
        if any(row[k] != request[k] for k in ("instance_id","arm","request_sha256")):
            raise ValueError("Response/request identity mismatch")
        if row["manifest_sha256"] != m["manifest_sha256"] or row["model_sha256"] != m["model_sha256"] or row["model_calls"] != 1:
            raise ValueError("Response provenance mismatch")
        if row["status"] == "transport_unknown":
            if any(row[k] is not None for k in ("input_tokens","output_tokens","provider_usage")) or row["queries"] or row["raw_output"]:
                raise ValueError("Unknown completion must not fabricate usage or queries")
            if row["reservation_cny"] != reserve_cost(request):
                raise ValueError("Unknown request reservation changed")
            continue
        u=row["provider_usage"]
        if row["input_tokens"] != u["prompt_tokens"] or row["output_tokens"] != u["completion_tokens"]:
            raise ValueError("Response usage mismatch")
        if not 0 <= row["input_tokens"] <= CONFIG["max_input_tokens"] or not 0 <= row["output_tokens"] <= CONFIG["max_output_tokens"] or row["input_tokens"]+row["output_tokens"] > CONFIG["max_total_tokens"]:
            raise ValueError("Token budget violation")
        for tariff in ("idle","peak"):
            if abs(row[f"estimated_cny_{tariff}"]-usage_cost(u,tariff)) > 1e-12:
                raise ValueError("Cost accounting mismatch")
        if row["status"] == "ok":
            if row["finish_reason"] != "stop" or row["queries"] != parse_queries(row["raw_output"]):
                raise ValueError("Parsed query mismatch")
        elif row["status"] != "invalid_output" or row["queries"] or not row.get("error"):
            raise ValueError("Invalid failure record")
    if sum((r["estimated_cny_peak"] if r["estimated_cny_peak"] is not None else r["reservation_cny"]) for r in responses) > m["budget_cny"]:
        raise ValueError("API spend exceeds frozen budget")


def generate(args):
    m, requests, _ = load_run(args)
    key=load_key(args.env_file)
    if (args.run_dir/"responses.jsonl").exists():
        raise FileExistsError("Completed response set already exists; refusing additional API calls")
    receipts=args.run_dir/"receipts"
    receipts.mkdir(exist_ok=True)
    opener=urllib.request.build_opener(NoRedirect())
    responses=[]
    for i,request in enumerate(requests):
        path=receipts/f"{i:03d}.json"
        started=receipts/f"{i:03d}.started.json"
        if path.exists():
            receipt=json.loads(path.read_text(encoding="utf-8"))
            if receipt["request_sha256"] != request["request_sha256"] or receipt["manifest_sha256"] != m["manifest_sha256"]:
                raise ValueError("Stored receipt mismatch")
            responses.append(decode_response(receipt["response"],request,m,receipt["seconds"]))
            continue
        if started.exists():
            if not (receipts/f"{i:03d}.error.json").exists():
                raise RuntimeError("Request still potentially active; refusing continuation")
            responses.append(unknown_response(request,m))
            print(f"{i+1}/{len(requests)} {request["instance_id"]} {request["arm"]} transport_unknown: skipped, not resent",flush=True)
            continue
        if sum((r["estimated_cny_peak"] if r["estimated_cny_peak"] is not None else r["reservation_cny"]) for r in responses)+reserve_cost(request) > m["budget_cny"]:
            raise ValueError("Budget guard stopped before sending")
        payload={**API_CONFIG,"messages":request["messages"]}
        write_json(started,{"request_sha256":request["request_sha256"], "manifest_sha256":m["manifest_sha256"], "started_utc":utc_now()})
        req=urllib.request.Request(ENDPOINT,data=json.dumps(payload,ensure_ascii=False).encode("utf-8"),
                                   headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"},method="POST")
        start=time.perf_counter()
        try:
            with opener.open(req,timeout=60) as response:
                raw=json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # Never persist response body, URL, request headers or exception text.
            write_json(receipts/f"{i:03d}.error.json",{"http_status":exc.code,"request_sha256":request["request_sha256"]})
            raise RuntimeError(f"Provider HTTP {exc.code}; stopped without retry") from None
        except Exception:
            write_json(receipts/f"{i:03d}.error.json",{"error":"transport_or_json_error","request_sha256":request["request_sha256"]})
            responses.append(unknown_response(request,m))
            print(f"{i+1}/{len(requests)} transport_unknown: continuing only to unsent requests",flush=True)
            continue
        elapsed=time.perf_counter()-start
        if key in canonical(raw):
            raise RuntimeError("Credential appeared in provider output; refusing to persist it")
        write_json(path,{"request_sha256":request["request_sha256"], "manifest_sha256":m["manifest_sha256"],
                         "received_utc":utc_now(),"seconds":elapsed,"response":raw})
        row=decode_response(raw,request,m,elapsed)
        responses.append(row)
        print(f"{i+1}/{len(requests)} {row['instance_id']} {row['arm']} {row['status']} input={row['input_tokens']} output={row['output_tokens']}",flush=True)
    validate_responses(responses,requests,m)
    with (args.run_dir/"responses.jsonl").open("x",encoding="utf-8") as output:
        for row in responses:
            output.write(canonical(row)+"\n")
    print(canonical({"calls":len(responses),"cost_estimate_cny_idle":sum(r["estimated_cny_idle"] or 0 for r in responses),
                     "cost_estimate_cny_peak":sum((r["estimated_cny_peak"] if r["estimated_cny_peak"] is not None else r["reservation_cny"]) for r in responses)}))

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
               "usage": {arm: {"input_tokens": sum(r["input_tokens"] or 0 for r in responses if r["arm"] == arm),
                                "known_output_tokens": sum(r["output_tokens"] or 0 for r in responses if r["arm"] == arm),
                                "model_calls": sum(r["model_calls"] for r in responses if r["arm"] == arm),
                                "retrieval_calls": sum(r["retrieval_calls"] for r in retrievals if r["arm"] == arm),
                                "code_chars_exposed": sum(r["code_chars_exposed"] for r in requests if r["arm"] == arm)} for arm in ARMS},
               "automatic_expansion": False, "claim": "exploratory paired feedback probe; no evidence-state mechanism claim"}
    summary["provider_models"] = sorted({r["provider_model"] for r in responses if r["provider_model"]})
    summary["system_fingerprints"] = sorted({r["system_fingerprint"] for r in responses if r["system_fingerprint"]})
    summary["unknown_usage_requests"] = [{"instance_id":r["instance_id"],"arm":r["arm"],"reservation_cny":r["reservation_cny"]} for r in responses if r["status"] == "transport_unknown"]
    summary["known_usage_cny_peak"] = sum(r["estimated_cny_peak"] or 0 for r in responses)
    summary["continuation_sha256"] = file_hash(args.run_dir/"continuation.json")
    summary["estimated_cny_idle"] = sum(r["estimated_cny_idle"] or 0 for r in responses)
    summary["known_plus_unknown_reservation_cny_peak"] = sum((r["estimated_cny_peak"] if r["estimated_cny_peak"] is not None else r["reservation_cny"]) for r in responses)
    with (args.run_dir/"scores.jsonl").open("x",encoding="utf-8") as stream:
        for row in scored:
            stream.write(canonical(row)+"\n")
    write_json(args.run_dir/"summary.json",summary)
    print(json.dumps(summary,ensure_ascii=False,indent=2))



def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest="command",required=True)
    for command in ("generate","retrieve","evaluate"):
        ap=sub.add_parser(command)
        ap.add_argument("--parent",type=Path,default=ROOT/"experiments/runs/query-pilot-20261102-v1")
        ap.add_argument("--bundle",type=Path,default=ROOT/"experiments/runs/feedback-inputs-20261102-v1")
        if command=="freeze":
            ap.add_argument("--out",type=Path,required=True)
        else:
            ap.add_argument("--run-dir",type=Path,required=True)
        if command in ("freeze","generate"):
            ap.add_argument("--env-file",type=Path,default=ROOT/".env")
        if command=="retrieve":
            ap.add_argument("--repos",type=Path,default=ROOT/"data/repos")
        if command=="evaluate":
            ap.add_argument("--gold",type=Path,default=ROOT/"data/gold_symbols.jsonl")
    args=p.parse_args()
    {"freeze":freeze,"generate":generate,"retrieve":retrieve,"evaluate":evaluate}[args.command](args)


if __name__=="__main__":
    main()
