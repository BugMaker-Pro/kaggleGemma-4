"""Post-hoc sensitivity to historical rounded-dense-score tie handling.

Primary protocol retains the encoder's saved candidate order. Historical
rank_with_dense instead sorts the rounded scores stably by candidate index.
This reports both without changing the primary data or protocol.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from experiments.graph_controls import evaluate
from tools.analyse_graph_controls import summarize,load


def main():
    dense={row['instance_id']:row for row in load(ROOT/'data/embed_retrieval.jsonl')}
    primary=load(ROOT/'data/graph_controls.jsonl')
    by_id={row['instance_id']:row for row in primary}
    changes=[]
    for line in (ROOT/'data/graph_controls_context.jsonl').open(encoding='utf-8'):
        context=json.loads(line);instance=context['instance_id'];stored=dense[instance]
        scores=[0.0]*len(stored['candidates'])
        for i,value in zip(stored['candidates'],stored['scores']):scores[i]=value
        historical=sorted(range(len(scores)),key=lambda i:-scores[i])
        original=context['orders']['dense']
        if historical==original:continue
        before=by_id[instance]
        context['orders']['dense']=historical
        after=evaluate(context)
        by_id[instance]=after
        changes.append({'instance_id':instance,'original_top10':original[:10],
                        'historical_top10':historical[:10],
                        'original_seed5':original[:5],'historical_seed5':historical[:5],
                        'dense_arm_symbol_deltas':{arm:after['representations']['dense']['arms'][arm]['symbol']-
                            value['symbol'] for arm,value in before['representations']['dense']['arms'].items()}})
    summary=summarize([by_id[row['instance_id']] for row in primary])
    out={'status':'post-hoc sensitivity; primary protocol unchanged',
         'changed_order_tasks':len(changes),
         'changed_top10_order_tasks':sum(row['original_top10']!=row['historical_top10'] for row in changes),
         'changed_top10_membership_tasks':sum(set(row['original_top10'])!=set(row['historical_top10']) for row in changes),
         'changed_seed_membership_tasks':sum(set(row['original_seed5'])!=set(row['historical_seed5']) for row in changes),
         'changes':changes,'full':summary}
    (ROOT/'data/graph_controls_tie_sensitivity.json').write_text(json.dumps(out,indent=2)+'\n',encoding='utf-8')
    print('changed order tasks',len(changes),'top10 membership',out['changed_top10_membership_tasks'],
          'seed membership',out['changed_seed_membership_tasks'])
    for name,stats in summary['primary'].items():
        print(name,round(stats['delta'],6),'Holm',round(stats['holm_p'],6))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
