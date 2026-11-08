"""Compare complete frozen development sweeps only after auditing both runs."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.audit_main_track import audit_development_batch
from tools.audit_ranker_agent import audit

def matched_settings(ranker_dir: Path, control_dir: Path) -> dict:
    ranker=json.loads((ranker_dir/'manifest.json').read_text(encoding='utf-8'))
    control=json.loads((control_dir/'manifest.json').read_text(encoding='utf-8'))
    if ranker['split']!=control['split'] or ranker['model']!=control['model']:
        raise ValueError('Split or model differs')
    ids=set(ranker['engineering_task_ids'])
    if ids!=set(control['engineering_task_ids']) or ids!=set(ranker['split']['development']):
        raise ValueError('Comparison requires the entire same frozen development set')
    if set(ranker['arms'])!={'ranker'} or set(control['arms'])!={'evidence'}:
        raise ValueError('Unexpected comparison arms')
    if ranker['concurrency']!=control['concurrency']:
        raise ValueError('Concurrency differs')
    for name in ('configs/sampling.yaml','eval_config.yaml'):
        if ranker['arms']['ranker']['files'][name]!=control['arms']['evidence']['files'][name]:
            raise ValueError('Model settings or tool/time budgets differ: '+name)
    rr=json.loads((ranker_dir/'kernel-request.json').read_text(encoding='utf-8'))
    cr=json.loads((control_dir/'kernel-request.json').read_text(encoding='utf-8'))
    for key in ('dockerImage','machineShape','competitionDataSources','kernelDataSources','modelDataSources','enableInternet','enableGpu'):
        if rr.get(key)!=cr.get(key):raise ValueError('Environment differs: '+key)
    if [v for v in rr['datasetDataSources'] if v!=ranker['ranker_asset_dataset']]!=cr['datasetDataSources']:
        raise ValueError('Unexpected additional input datasets')
    for task_id in ids:
        filename='verification-gate-'+task_id+'.json'
        rg=json.loads((ranker_dir/filename).read_text(encoding='utf-8-sig'))
        cg=json.loads((control_dir/filename).read_text(encoding='utf-8-sig'))
        if rg!=cg or not rg['passed']:raise ValueError('Verification gates differ or fail: '+task_id)
    return {'tasks':len(ids),'model':ranker['model'],'concurrency':ranker['concurrency'],
            'sampling_and_budget_hashes_identical':True,'environment_and_reference_controls_matched':True,
            'scope':'Exploratory development comparison; sequential workflow is part of the deployed method, not an isolated causal graph ablation'}

def compare(ranker_dir: Path, control_dir: Path) -> dict:
    settings=matched_settings(ranker_dir,control_dir)
    ranker=audit(ranker_dir,ROOT/'.cache/main-track/official/tasks.jsonl')
    control=audit_development_batch(control_dir)
    (ranker_dir/'audit.json').write_text(json.dumps(ranker,indent=2),encoding='utf-8')
    (control_dir/'audit.json').write_text(json.dumps(control,indent=2),encoding='utf-8')
    rrows={r['task_id']:r for r in ranker['results']}
    crows={r['task_id']:r for r in control['results']}
    rows=[]
    for task_id in sorted(rrows):
        r,c=rrows[task_id],crows[task_id]
        outputs=[v for v in r['trace_summary']['ranker_outputs'] if v.get('status')=='ok' and v.get('mode')=='full']
        rows.append({'task_id':task_id,'control_resolved':c['resolved'],'ranker_resolved':r['resolved'],
                     'ranker_invocations':r['full_ranker_invocations'],'successful_full_outputs':len(outputs),
                     'original_text_equivalent':r['full_pipeline_executed_with_text_equivalent_issue'],
                     'ranker_internal_seconds':[v['seconds'] for v in outputs],
                     'control_error':c.get('error'),'ranker_error':r.get('harness_error')})
    report={'matched_settings':settings,'artifact_checks':{'ranker':ranker['artifact_checks'],'control':control['checks']},
            'tasks':len(rows),'control_resolved':sum(r['control_resolved'] for r in rows),
            'ranker_resolved':sum(r['ranker_resolved'] for r in rows),
            'ranker_only_successes':sum(r['ranker_resolved'] and not r['control_resolved'] for r in rows),
            'control_only_successes':sum(r['control_resolved'] and not r['ranker_resolved'] for r in rows),
            'actual_full_output_tasks':sum(r['successful_full_outputs']>0 for r in rows),
            'original_text_equivalent_tasks':sum(r['original_text_equivalent'] for r in rows),
            'confirmation_tasks_used':0,'rows':rows}
    (ranker_dir/'comparison.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report

if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--ranker-run',type=Path,required=True)
    ap.add_argument('--control-run',type=Path,required=True)
    args=ap.parse_args()
    report=compare(args.ranker_run,args.control_run)
    print(json.dumps({k:v for k,v in report.items() if k!='rows'},indent=2))
    for row in report['rows']:print(json.dumps(row))
