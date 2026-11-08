"""Offline integration check on a historical held-out Requests snapshot.

Checks feature parity and tree parity without reading reference patches. Dense
quantization is evaluated explicitly; no repair success is inferred.
"""
from pathlib import Path
import hashlib,json,sys,time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'agent/ranker/scripts'))
from experiments.snapindex import SnapshotIndex
from experiments.buildgraph import build_graph,read_snapshot
from localization_features import candidate_features
from localize import rank,dense_documents
from dense_encoder import dense_scores
from tree_predict import ensemble_scores,load_ranker

import argparse
parser=argparse.ArgumentParser()
parser.add_argument('--package',type=Path,default=ROOT/'.cache/main-track/ranker-package-v1')
args=parser.parse_args()
package=args.package
assets=package/'skills/ranker/assets'
rows=[json.loads(line) for line in (ROOT/'data/features_full.jsonl').read_text(encoding='utf-8').splitlines() if line]
row=sorted((r for r in rows if r['repo']=='psf/requests'),key=lambda r:hashlib.sha256(('ranker-integration-v1:'+r['instance_id']).encode()).hexdigest())[0]
metadata={r['instance_id']:{k:r[k] for k in ('instance_id','repo','base_commit','problem_statement')} for r in (json.loads(line) for line in (ROOT/'data/swebench_full.jsonl').read_text(encoding='utf-8').splitlines() if line)}
task=metadata[row['instance_id']]
snapshot=SnapshotIndex(ROOT/'data/repos').path_for(task)
files=read_snapshot(snapshot)
graph,_=build_graph(files)
new=candidate_features(task['problem_statement'],files,graph)
from tools import features as original_features
original_features._INDEX=SnapshotIndex(ROOT/'data/repos')
original_features.KEEP_EMPTY_GOLD=True
reference=original_features._work(task)  # task projection deliberately excludes patch/test_patch
assert new['ids']==reference['ids'] and new['rows']==reference['rows'], 'Runtime feature implementation differs'
historical_order_changes=sum(a!=b for a,b in zip(new['ids'],row['ids']))
assert set(new['ids'])==set(row['ids']), 'Candidate membership changed'
print('Feature parity:',row['instance_id'],len(new['ids']),'candidates x 16 columns exact against source builder; saved-order differences',historical_order_changes,flush=True)
docs=dense_documents(new['ids'],new['files'],files)
started=time.monotonic()
original,original_precision=dense_scores(task['problem_statement'],docs,assets,ROOT/'models/bge-small-en-v1.5')
original_seconds=time.monotonic()-started
print('Original encoder seconds:',original_seconds,flush=True)
started=time.monotonic()
compact,compact_precision=dense_scores(task['problem_statement'],docs,assets)
compact_seconds=time.monotonic()-started
models=load_ranker(assets/'ranker-full.json')
orders=[]
for dense in (original,compact):
    scores=ensemble_scores(models,[v+[dense[i]] for i,v in enumerate(new['rows'])])
    orders.append(sorted(range(len(scores)),key=lambda i:-scores[i])[:10])
report={'task_id':row['instance_id'],'source_snapshot_sha256':hashlib.sha256(snapshot.read_bytes()).hexdigest(),
        'feature_values_matched':len(new['ids'])*16,'candidate_ids_exact_vs_current_source':True,'saved_candidate_position_changes':historical_order_changes,
        'encoder_modes':[original_precision,compact_precision],
        'max_dense_score_delta':max(abs(a-b) for a,b in zip(original,compact)),
        'mean_dense_score_delta':sum(abs(a-b) for a,b in zip(original,compact))/len(original),
        'original_top10':orders[0],'compact_top10':orders[1],'top10_overlap':len(set(orders[0])&set(orders[1])),
        'original_encoder_seconds':original_seconds,'compact_encoder_seconds':compact_seconds,
        'scope':'One historical task, no repair evaluation; original FP32 CPU vs row-INT8 reconstructed FP32'}
(package/'local-integration.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report),flush=True)
