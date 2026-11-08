"""Independent arithmetic audit of fixed cheap-fusion replay. No API/inference."""
import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from experiments.query_pilot import file_hash
from tools.analyse_candidate_retention import read_rows
from tools.evaluate_query_pilot import gold_targets
from tools.run_simple_fusion import load_run,interval
from tools.run_feedback_pilot import write_json
from tools.run_deepseek_feedback import load_key


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-dir',type=Path,required=True)
    p.add_argument('--strong',type=Path,default=ROOT/'experiments/runs/strong-query-20261103-v2')
    p.add_argument('--gold',type=Path,default=ROOT/'data/gold_symbols.jsonl')
    p.add_argument('--out',type=Path)
    args=p.parse_args();m,pairs=load_run(args)
    replays=read_rows(args.run_dir/'replay.jsonl');scores=read_rows(args.run_dir/'scores.jsonl')
    summary=json.loads((args.run_dir/'summary.json').read_text(encoding='utf-8'))
    assert [r['instance_id'] for r in replays]==[r['instance_id'] for r in scores]==m['task_ids']
    assert summary['manifest_sha256']==m['manifest_sha256']
    assert summary['gold_sha256']==file_hash(args.gold)
    assert summary['replay_sha256']==file_hash(args.run_dir/'replay.jsonl')
    gold={r['instance_id']:r for r in read_rows(args.gold)}
    checks=0
    for row,scored,(candidate,prediction) in zip(replays,scores,pairs):
        assert row['manifest_sha256']==m['manifest_sha256']
        votes=defaultdict(float)
        for source in ('historical','body_original'):
            assert row['pools'][source]==candidate['arms'][source]
            for rank,node in enumerate(candidate['arms'][source],1):votes[node]+=1/(60+rank)
        expected=sorted(votes,key=lambda n:(-votes[n],n))[:200]
        assert expected==row['pools']['simple_fusion']
        assert row['pools']['generated']==candidate['arms']['generated']
        targets=gold_targets(gold.get(row['instance_id'],{}))
        assert len(targets)==scored['gold_count'] and bool(targets)==scored['scorable']
        for arm in row['orders']:
            assert row['orders'][arm]==sorted(row['pools'][arm],key=lambda n:-prediction['scores'][n])
            assert len(row['pools'][arm])<=200 and len(set(row['pools'][arm]))==len(row['pools'][arm])
            for metric,ids in (('coverage',row['pools'][arm]),('recall_at_10',row['orders'][arm][:10])):
                actual=scored['arms'][arm][metric]
                expected=len(set(ids)&targets)/len(targets) if targets else None
                assert actual is None and expected is None or expected is not None and math.isclose(actual,expected,abs_tol=1e-12)
                checks+=1
        union=set(candidate['arms']['historical'])|set(candidate['arms']['body_original'])
        assert sorted(union)==row['metadata_body_union']
        assert sorted((set(row['orders']['generated'][:10])&targets)-union)==scored['generated_top_targets_outside_original_union']
        assert sorted((union&targets)-set(row['pools']['simple_fusion']))==scored['fusion_removed_original_union_targets']
    valid=[r for r in scores if r['scorable']]
    for arm,means in summary['means'].items():
        for metric,value in means.items():assert math.isclose(statistics.mean(r['arms'][arm][metric] for r in valid),value,abs_tol=1e-12)
    assert interval(valid)==summary['descriptive_repo_bootstrap_95']
    key=load_key(ROOT/'.env')
    assert not any(key in f.read_text(encoding='utf-8') for f in args.run_dir.rglob('*') if f.is_file())
    result={'tasks':len(scores),'independent_metric_checks':checks,'independent_rrf_membership':'passed',
            'frozen_score_ordering':'passed','novel_target_union_check':'passed','credential_scan':'passed',
            'new_api_calls':0,'audit_source_sha256':file_hash(Path(__file__)),
            'summary_sha256':file_hash(args.run_dir/'summary.json'),'scores_sha256':file_hash(args.run_dir/'scores.jsonl')}
    if args.out:write_json(args.out,result)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
