"""Read-only independent metric/hash/credential audit for stratified Flash replication."""
import argparse
import json
import math
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from experiments.query_pilot import file_hash
from experiments.retrieve import tokenize
from tools.evaluate_query_pilot import gold_targets
from tools.analyse_candidate_retention import read_rows
from tools.run_flash_replication import load_inputs, validate_generated, effective_pair, summarize_rows
from tools.run_deepseek_feedback import load_key
from tools.run_feedback_pilot import validate_retrieval


def close(a,b):
    if a is None or b is None:
        assert a is b
    else:assert math.isclose(a,b,abs_tol=1e-12), (a,b)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-dir',type=Path,required=True)
    p.add_argument('--gold',type=Path,default=ROOT/'data/gold_symbols.jsonl')
    p.add_argument('--out',type=Path)
    args=p.parse_args()
    m,inputs,requests,seal=load_inputs(args.run_dir)
    responses=validate_generated(args.run_dir,m,requests)
    summary=json.loads((args.run_dir/'summary.json').read_text(encoding='utf-8'))
    assert summary['manifest_sha256']==m['manifest_sha256']
    assert summary['responses_sha256']==file_hash(args.run_dir/'responses.jsonl')
    assert summary['gold_sha256']==file_hash(args.gold)
    assert summary['input_seal_sha256']==file_hash(args.run_dir/'inputs.seal.json')
    scores=read_rows(args.run_dir/'scores.jsonl')
    assert [r['instance_id'] for r in scores]==m['task_ids']
    gold={r['instance_id']:r for r in read_rows(args.gold)}
    checks=0
    for i,(item,scored) in enumerate(zip(inputs,scores)):
        path=args.run_dir/'retrieval_tasks'/f'{i:03d}.json'
        assert summary['retrieval_hashes'][path.name]==file_hash(path)
        results=json.loads(path.read_text(encoding='utf-8'))['results']
        trace=item['baseline']
        effective=effective_pair(responses[2*i:2*i+2])
        fallback=any(r['status']!='ok' for r in responses[2*i:2*i+2])
        assert fallback==scored['paired_fallback']
        targets=gold_targets(gold.get(item['instance_id'],{}))
        assert len(targets)==scored['gold_count']
        assert bool(targets)==scored['scorable']
        original=[x['id'] for x in trace['actions']['original']['candidates']]
        for result,response in zip(results,effective):
            order=validate_retrieval(result,response,trace,m)
            if fallback:assert order==original[:200]
            arm=scored['arms'][result['arm']]
            close(arm['coverage'],len(set(order)&targets)/len(targets) if targets else None)
            close(arm['recall_at_10'],len(set(order[:10])&targets)/len(targets) if targets else None)
            checks+=2
        if fallback:assert scored['arms']['feedback']==scored['arms']['preplanned']
    valid=[r for r in scores if r['scorable']]
    assert summarize_rows(valid)==summary['primary']
    assert summarize_rows([r for r in valid if not r['paired_fallback']])==summary['complete_pair_sensitivity']
    assert summary['prior_plus_current_peak_reservation_cny']<=m['combined_budget_cny']
    key=load_key(ROOT/'.env')
    assert not any(key in f.read_text(encoding='utf-8') for f in args.run_dir.rglob('*') if f.is_file())
    identical=0
    lexical={arm:0 for arm in ('preplanned','feedback')}
    for i,item in enumerate(inputs):
        pair=responses[2*i:2*i+2]
        identical += set(pair[0]['queries'])==set(pair[1]['queries'])
        payload=json.loads(requests[2*i]['messages'][0]['content'].split('INPUT_JSON:\n',1)[1])
        issue_tokens=set(tokenize(payload['issue']))
        code_tokens=set(tokenize(' '.join(e['text'] for e in item['excerpts'])))
        for response in pair:
            lexical[response['arm']] += bool((set(tokenize(' '.join(response['queries'])))-issue_tokens)&code_tokens)
    result={'tasks':len(scores),'arm_metrics_independently_checked':checks,
                      'task_ids_disjoint_from_pilot':not bool(set(m['task_ids'])&set(m['excluded_task_ids'])),
                      'all_provenance_and_intervals_verified':True,'credential_scan':'passed','no_api_calls':True,
                      'identical_query_pairs':identical,'queries_containing_code_only_tokens':lexical,
                      'lexical_diagnostic_limit':'Token overlap is descriptive; does not prove causal use of code.',
                      'audit_source_sha256':file_hash(Path(__file__)),
                      'summary_sha256':file_hash(args.run_dir/'summary.json'),
                      'scores_sha256':file_hash(args.run_dir/'scores.jsonl')}
    if args.out:
        with args.out.open('x',encoding='utf-8') as stream:stream.write(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__=='__main__':main()
