"""Independently rescore every saved graph-control shortlist and verify lineage.

This does not rerun AST construction; run_graph_controls checks that projection
against historical graph ranks. This checks population, candidate alignment,
all per-arm metrics, randomized graph invariants/replay on a fixed sample, input
hashes, and full metadata/dense agreement with historical result files.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import statistics
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from experiments.graph_controls import evaluate


def rows(path):
    with Path(path).open(encoding='utf-8-sig') as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def sha(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda:handle.read(1024*1024),b''):
            value.update(chunk)
    return value.hexdigest()


def main(argv=None):
    ap=argparse.ArgumentParser()
    ap.add_argument('--rows',default=str(ROOT/'data/graph_controls.jsonl'))
    args=ap.parse_args(argv)
    path=Path(args.rows)
    manifest=json.loads(path.with_suffix('.manifest.json').read_text(encoding='utf-8'))
    portable_path = path.with_suffix('.portable.json')
    portable = json.loads(portable_path.read_text(encoding='utf-8')) if portable_path.exists() else {}
    failures=[]
    checks=0
    def check(condition,message):
        nonlocal checks
        checks+=1
        if not condition:
            failures.append(message)
    if portable:
        manifest_path = path.with_suffix('.manifest.json')
        canonical_manifest = hashlib.sha256(
            manifest_path.read_text(encoding='utf-8-sig').encode('utf-8')).hexdigest()
        check(portable.get('execution_manifest_sha256') == sha(manifest_path)
              or portable.get('execution_manifest_canonical_sha256') == canonical_manifest,
              'portable hashes belong to a different execution manifest')
    normalized_inputs = 0
    for name,expected in manifest['input_sha256'].items():
        source = ROOT / name.replace('\\', '/')
        raw_matches = source.exists() and sha(source)==expected
        normalized_matches = False
        portable_expected = portable.get('input_sha256', {}).get(name)
        if not raw_matches and source.exists() and portable_expected:
            canonical = source.read_text(encoding='utf-8-sig').encode('utf-8')
            normalized_matches = hashlib.sha256(canonical).hexdigest()==portable_expected
            normalized_inputs += int(normalized_matches)
        check(raw_matches or normalized_matches,f'input changed: {name}')
    actual=list(rows(path))
    actual_by_id={row['instance_id']:row for row in actual}
    check(len(actual)==len(actual_by_id),'duplicate results')
    check(sorted(actual_by_id)==manifest['task_ids'],'result population differs from manifest')
    selected_keys=('ids','files','labels','gold_total','gold_files','rerank_top10')
    features={row['instance_id']:{key:row[key] for key in selected_keys}
              for row in rows(ROOT/'data/features_full.jsonl')}
    dense_rows={row['instance_id']:row for row in rows(ROOT/'data/embed_retrieval.jsonl')}
    dense={key:row['candidates'] for key,row in dense_rows.items()}
    context_ids=[]
    replayed=set()
    for context in rows(path.with_name(path.stem+'_context.jsonl')):
        instance=context['instance_id'];context_ids.append(instance)
        row=actual_by_id.get(instance)
        if row is None:
            check(False,f'missing result {instance}');continue
        feature=features[instance]
        for name in ('ids','files','labels','gold_total','gold_files'):
            check(context[name]==feature[name],f'{instance}: context {name} changed')
        check(context['graph_reproduced'] is True,f'{instance}: graph not reproduced')
        check(context['orders']['dense']==dense[instance],f'{instance}: dense mapping changed')
        check(row['representations']['metadata']['arms']['real']['top10']==feature['rerank_top10'],
              f'{instance}: metadata graph rank changed')
        check(row['gold_total']==context['gold_total'],f'{instance}: gold denominator')
        for representation,order in context['orders'].items():
            check(sorted(order)==list(range(len(context['ids']))),f'{instance}/{representation}: invalid base order')
            baseline=set(order[:10])
            check(row['representations'][representation]['arms']['base']['top10']==order[:10],
                  f'{instance}/{representation}: base order differs')
            for arm,values in row['representations'][representation]['arms'].items():
                top=values['top10']; chosen=set(top)
                label=f'{instance}/{representation}/{arm}'
                check(len(top)==len(chosen)==min(10,len(order)),f'{label}: duplicate or missing slot')
                check(top[:5]==order[:5],f'{label}: changed seed positions')
                check(chosen<=set(order),f'{label}: candidate outside pool')
                hits=sum(context['labels'][i] for i in chosen)
                file_hits=len({context['files'][i] for i in chosen}&set(context['gold_files']))
                expected={'symbol':hits/context['gold_total'],
                          'file':file_hits/len(set(context['gold_files'])) if context['gold_files'] else 0,
                          'gained':sum(context['labels'][i] for i in chosen-baseline),
                          'lost':sum(context['labels'][i] for i in baseline-chosen)}
                for metric,target in expected.items():
                    check(math.isclose(values[metric],target,abs_tol=1e-12),f'{label}: {metric} mismatch')
                baseline_hits=sum(context['labels'][i] for i in baseline)
                check(hits-baseline_hits==values['gained']-values['lost'],f'{label}: displacement accounting')
        # First encountered task per repository in the stored
        # stream is not an outcome-based sample. Replay all rewiring and ranking.
        if context['repo'] not in replayed:
            check(evaluate(context)==row,f'{instance}: randomized replay changed')
            replayed.add(context['repo'])
    check(sorted(context_ids)==manifest['task_ids'],'context population differs')
    historic={row['instance_id']:row for row in rows(ROOT/'data/dense_scores.jsonl')}
    tie_differences=[]
    for row in actual:
        instance=row['instance_id']; feature=features[instance]; saved=dense_rows[instance]
        scores=[0.0]*len(saved['candidates'])
        for index,score in zip(saved['candidates'],saved['scores']): scores[index]=score
        historical_order=sorted(range(len(scores)),key=lambda index:-scores[index])[:10]
        labels=feature['labels'];files=feature['files'];gold_files=set(feature['gold_files'])
        historical_values={'symbol':sum(labels[i] for i in historical_order)/feature['gold_total'],
                           'file':len({files[i] for i in historical_order}&gold_files)/len(gold_files) if gold_files else 0.0}
        for metric,expected in historical_values.items():
            check(abs(expected-historic[instance][f'cosine_{metric}'])<=0.0001,
                  f'{instance}: historical rounded dense {metric} not reproduced')
            primary=row['representations']['dense']['arms']['base'][metric]
            if abs(primary-expected)>0.0001:
                tie_differences.append({'instance_id':instance,'metric':metric,
                                        'primary':primary,'historical':expected})
    print('Primary saved-order versus historical rounded-score tie differences:',tie_differences)
    print(f'{len(actual)} tasks; {checks} checks; rewiring replayed on {len(replayed)} repositories')
    print(f'{normalized_inputs} inputs matched via recorded UTF-8/LF canonical hashes')
    print(f'{len(failures)} failures')
    for failure in failures[:40]:
        print('FAIL',failure)
    if not failures:
        print('Historical graph ranking, historical dense tie rule, all primary control metrics and input hashes verified.')
    return bool(failures)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',errors='replace')
    raise SystemExit(main())
