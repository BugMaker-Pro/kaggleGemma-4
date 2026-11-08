"""Audit real ranker calls, query fidelity and complete repair artifacts."""
from __future__ import annotations
import argparse,hashlib,json,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from tools.audit_main_track import summarize_trace


def ranker_evidence(details: dict, issue: str) -> dict:
    """Distinguish invocation, successful full output, and original-query fidelity."""
    calls=[r for r in details['ranker_calls'] if r.get('script')=='scripts/localize.py'
           and isinstance(r.get('args'),dict) and r['args'].get('mode','full')=='full']
    exact=[r for r in calls if r['args'].get('issue')==issue]
    normalized=issue.replace('\r\n','\n')
    faithful=[r for r in calls if isinstance(r['args'].get('issue'),str)
              and r['args']['issue'].replace('\r\n','\n')==normalized]
    presentation=[r for r in calls if isinstance(r['args'].get('issue'),str) and r['args']['issue'].replace('\r\n','\n') in {normalized,normalized+'\n',normalized.removesuffix('\n')}]
    presentation_hashes={hashlib.sha256(r['args']['issue'].encode()).hexdigest() for r in presentation}
    exact_hash=hashlib.sha256(issue.encode()).hexdigest()
    faithful_hashes={hashlib.sha256(r['args']['issue'].encode()).hexdigest() for r in faithful}
    good=[r for r in details['ranker_outputs'] if r.get('status')=='ok' and r.get('mode')=='full'
          and len(r.get('results',[]))==10 and r.get('candidate_count',0)>0]
    exact_outputs=[r for r in good if r.get('query_sha256')==exact_hash]
    faithful_outputs=[r for r in good if r.get('query_sha256') in faithful_hashes]
    presentation_outputs=[r for r in good if r.get('query_sha256') in presentation_hashes]
    return {'full_ranker_invocations':len(calls),
            'presentation_equivalent_full_ranker_invocations':len(presentation),
            'presentation_equivalent_full_ranker_successes':len(presentation_outputs),
            'full_pipeline_executed_with_text_equivalent_issue':bool(presentation and presentation_outputs),
            'accepted_presentation_changes':'CRLF to LF and at most one terminal newline; no other text changes',
            'issue_transport_checks':[{'exact':r['args']['issue']==issue,
                'original_crlf_count':issue.count('\r\n'),'query_crlf_count':r['args']['issue'].count('\r\n'),
                'normalized_length_delta':len(r['args']['issue'].replace('\r\n','\n'))-len(normalized)} for r in presentation],
            'exact_original_issue_full_ranker_invocations':len(exact),
            'exact_original_issue_full_ranker_successes':len(exact_outputs),
            'line_ending_equivalent_full_ranker_invocations':len(faithful),
            'line_ending_equivalent_full_ranker_successes':len(faithful_outputs),
            'full_pipeline_executed_with_original_issue':bool(faithful and faithful_outputs)}

def audit(directory: Path, tasks_path: Path) -> dict:
    manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    output=directory/'output'
    split=json.loads((output/'frozen_split.json').read_text(encoding='utf-8'))
    if split!=manifest['split']:raise ValueError('Frozen split differs')
    if hashlib.sha256(tasks_path.read_bytes()).hexdigest()!=split['task_file_sha256']:raise ValueError('Task input changed')
    allowed=set(manifest['engineering_task_ids'])
    if not allowed<=set(split['development']) or allowed&set(split['confirmation']):raise ValueError('Improper task selection')
    issues={row['instance_id']:row['problem_statement'] for row in (json.loads(line) for line in tasks_path.read_text(encoding='utf-8').splitlines() if line) if row['instance_id'] in allowed}
    rows=[json.loads(line) for line in (output/manifest.get('result_file','smoke_results.jsonl')).read_text(encoding='utf-8').splitlines() if line]
    expected={(arm,i) for arm in manifest['arms'] for i in allowed}
    if len(rows)!=len(expected) or {(r['arm'],r['task_id']) for r in rows}!=expected:raise ValueError('Task/arm results incomplete')
    checks=0
    for arm,info in manifest['arms'].items():
        with zipfile.ZipFile(output/(arm+'_submission.zip')) as archive:
            if set(archive.namelist())!=set(info['files']):raise ValueError('Runtime ZIP file set differs')
            for name,expected_hash in info['files'].items():
                if hashlib.sha256(archive.read(name)).hexdigest()!=expected_hash:raise ValueError('Runtime ZIP content differs: '+name)
                if hashlib.sha256((output/'agents'/arm/name).read_bytes()).hexdigest()!=expected_hash:raise ValueError('Runtime source differs: '+name)
                checks+=2
    results=[]
    for row in rows:
        task_id,arm=row['task_id'],row['arm']
        base=output/'results'/arm
        raw=[json.loads(line) for line in (base/'task_results.jsonl').read_text(encoding='utf-8').splitlines() if line]
        original=next(r for r in raw if r['instance_id']==task_id)
        for key in ('resolved','test_exit_code','tool_calls'):
            if row[key]!=original[key]:raise ValueError('Raw result differs')
            checks+=1
        patch=base/'patches'/(task_id+'.patch')
        data=patch.read_bytes() if patch.exists() else b''
        if hashlib.sha256(data).hexdigest()!=row['patch_sha256'] or len(data.decode())!=row['patch_chars']:raise ValueError('Patch missing or changed')
        if row['resolved'] and not (base/'test_outputs'/(task_id+'.log')).is_file():raise ValueError('Successful repair lacks test output')
        trace_path=base/'traces'/('trace_'+task_id+'.json')
        if trace_path.is_file():
            trace=json.loads(trace_path.read_text(encoding='utf-8'))
        elif original.get('error') and not row['resolved']:
            trace={'steps':[]}
        else:
            raise ValueError('Missing trace without recorded failure: '+task_id)
        staged=manifest.get('workflow')=='sequential' and arm=='ranker'
        expected_prompt=(output/'agents'/arm/'prompts/system.md').read_text(encoding='utf-8').rstrip()
        actual_prompt=trace['steps'][0].get('message','').rstrip() if trace['steps'] else ''
        if trace_path.is_file() and not staged and actual_prompt!=expected_prompt and not actual_prompt.startswith(expected_prompt):
            raise ValueError('Trace prompt differs from configured prompt')
        details=summarize_trace(trace)
        authors=list(dict.fromkeys(step.get('extra',{}).get('author') for step in trace['steps']
                                  if step.get('source')=='agent' and step.get('extra',{}).get('author')))
        result={**row,'harness_error':original.get('error'),'trace_summary':details,
                **ranker_evidence(details,issues[task_id]),
                'configured_prompt_present':None if staged or not trace_path.is_file() else True,
                'trace_file_present':trace_path.is_file(),
                'prompt_evidence':'Runtime package hashes; workflow child prompts are not stored as root system steps' if staged else 'Runtime package hashes and trace system step',
                'workflow_agents_observed':authors,
                'test_output_present':(base/'test_outputs'/(task_id+'.log')).is_file()}
        results.append(result)
        checks+=2
    return {'passed':True,'artifact_checks':checks,'results':results,
            'integration_executed':any(r['arm']=='ranker' and r['full_pipeline_executed_with_text_equivalent_issue'] for r in results),
            'scope':'Development engineering comparison with INT8 deployment encoder, not proof of method effectiveness or official Docker compatibility'}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--run-dir',type=Path,required=True)
    ap.add_argument('--tasks',type=Path,default=ROOT/'.cache/main-track/official/tasks.jsonl')
    args=ap.parse_args()
    report=audit(args.run_dir,args.tasks)
    (args.run_dir/'audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Artifact checks',report['artifact_checks'],'actual full integration',report['integration_executed'])
    for row in report['results']:
        print(row['arm'],'resolved',row['resolved'],'ranker_calls',row['full_ranker_invocations'],'text_equivalent_issue_full_outputs',row['presentation_equivalent_full_ranker_successes'])
if __name__=='__main__':main()
