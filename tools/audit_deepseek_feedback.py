"""Post-run sensitivity and provenance audit; sends no API requests."""
import argparse
import json
import random
import statistics
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from experiments.query_pilot import file_hash
from tools.continue_deepseek_feedback import load_run,validate_responses
from tools.run_feedback_pilot import validate_retrieval,write_json
from tools.analyse_candidate_retention import read_rows
from tools.run_deepseek_feedback import load_key


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--run-dir',type=Path,required=True)
    p.add_argument('--bundle',type=Path,default=ROOT/'experiments/runs/feedback-inputs-20261102-v1')
    p.add_argument('--parent',type=Path,default=ROOT/'experiments/runs/query-pilot-20261102-v1')
    args=p.parse_args()
    manifest,requests,traces=load_run(args)
    responses=read_rows(args.run_dir/'responses.jsonl')
    validate_responses(responses,requests,manifest)
    retrieval=read_rows(args.run_dir/'retrieval.jsonl')
    for i,(r,response) in enumerate(zip(retrieval,responses)):
        validate_retrieval(r,response,traces[i//2],manifest)
    scores=read_rows(args.run_dir/'scores.jsonl')
    complete=[r for r in scores if all(v['status']=='ok' for v in r['arms'].values())]
    means={arm:{metric:statistics.mean(r['arms'][arm][metric] for r in complete) for metric in ('coverage','recall_at_10')} for arm in ('preplanned','feedback')}
    deltas=[r['arms']['feedback']['recall_at_10']-r['arms']['preplanned']['recall_at_10'] for r in complete]
    # This pilot has one task per repository; task bootstrap equals repository bootstrap here.
    assert len({r['repo'] for r in complete})==len(complete)
    rng=random.Random(20261102)
    draws=sorted(statistics.mean(rng.choices(deltas,k=len(deltas))) for _ in range(2000))
    key=load_key(ROOT/'.env')
    assert not any(key in f.read_text(encoding='utf-8') for f in args.run_dir.rglob('*') if f.is_file())
    out={'status':'post-run sensitivity, not replacement of main analysis',
         'source_sha256':file_hash(Path(__file__)),
         'input_hashes':{name:file_hash(args.run_dir/name) for name in ('summary.json','scores.jsonl','responses.jsonl','retrieval.jsonl')},
         'complete_pairs':len(complete),'excluded_transport_pair':['psf__requests-2148'],
         'complete_pair_means':means,'complete_pair_primary_delta':statistics.mean(deltas),
         'complete_pair_descriptive_95':[draws[int(.025*1999)],draws[int(.975*1999)]],
         'complete_pair_improvements':[r['instance_id'] for r in complete if r['arms']['feedback']['recall_at_10']>r['arms']['preplanned']['recall_at_10']],
         'complete_pair_harms':[r['instance_id'] for r in complete if r['arms']['feedback']['recall_at_10']<r['arms']['preplanned']['recall_at_10']],
         'known_usage':{'input_tokens':sum(r['input_tokens'] or 0 for r in responses),'output_tokens':sum(r['output_tokens'] or 0 for r in responses)},
         'known_idle_estimate_cny':sum(r['estimated_cny_idle'] or 0 for r in responses),
         'unknown_billing_requests':sum(r['status']=='transport_unknown' for r in responses),
         'known_peak_plus_unknown_reservation_cny':sum((r['estimated_cny_peak'] if r['estimated_cny_peak'] is not None else r['reservation_cny']) for r in responses),
         'credential_scan':'passed: no credential in run artifacts',
         'remaining_limit':'API alias is mutable; actual billing for failed request unknown; 11 historical complete pairs do not establish general effect'}
    write_json(args.run_dir/'sensitivity.json',out)
    print(json.dumps(out,indent=2))


if __name__=='__main__':main()
