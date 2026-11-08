"""Runtime localization tool: issue + repository -> 200 candidates -> dense + learned top ten.

No evaluation labels are read. Work products live under /tmp, never in the patch.
The full mode fails explicitly if its dense runtime is unavailable; it never
silently substitutes a lexical-only result while reporting dense-fusion output.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

SKILL_ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(Path(__file__).resolve().parent))
from experiments.buildgraph import build_graph,iter_python_files
from experiments.symbols import python_symbols
from localization_features import candidate_features
from tree_predict import ensemble_scores,load_ranker

def workspace_root(explicit=None):
    if explicit:return Path(explicit).resolve(strict=True)
    choices=[Path('/workspace')]
    choices.extend(Path(p) for p in os.environ.get('PYTHONPATH','').split(os.pathsep) if p)
    choices.append(Path(os.environ.get('PWD',os.getcwd())))
    for p in choices:
        if p.is_dir() and (p/'.git').exists():return p.resolve()
    raise ValueError('Workspace not found; pass --root explicitly')

def source_files(root,max_bytes=80*1024*1024):
    if not root.is_dir():raise ValueError('Repository root is not a directory')
    result={};total=0
    for current,dirs,files in os.walk(root,followlinks=False):
        relative=Path(current).relative_to(root)
        dirs[:]=sorted(d for d in dirs if not (Path(current)/d).is_symlink() and iter_python_files([str(relative/d/'placeholder.py').replace('\\','/')]))
        for name in sorted(files):
            path=Path(current)/name
            key=path.relative_to(root).as_posix()
            if path.is_symlink() or name.startswith('.adk_exec_') or not iter_python_files([key]):continue
            if not path.resolve().is_relative_to(root):raise ValueError('Source escapes repository')
            raw=path.read_bytes();total+=len(raw)
            if total>max_bytes:raise ValueError('Source input exceeds configured runtime budget')
            try:result[key]=raw.decode('utf-8')
            except UnicodeDecodeError:continue
    return result

def dense_documents(ids,paths,files):
    cache={};documents=[]
    for node_id,path in zip(ids,paths):
        source=files.get(path,'')
        if path not in cache:cache[path]=python_symbols(source)
        module=path[:-3].replace('/','.').replace('.__init__','')
        prefix=module+'.'
        qualname=node_id[len(prefix):] if node_id.startswith(prefix) else node_id.rsplit('.',1)[-1]
        body=''
        for symbol in cache[path]:
            if symbol.qualname==qualname:
                body='\n'.join(source.splitlines()[symbol.lineno-1:(symbol.end_lineno or symbol.lineno)])
                break
        documents.append(f'{path} :: {node_id}\n{body[:800]}')
    return documents

def rank(issue,root,assets,mode='full',encoder_dir=None):
    if not isinstance(issue,str) or not issue.strip():raise ValueError('A non-empty issue is required')
    if mode not in ('full','lexical'):raise ValueError('Unsupported ranker mode')
    started=time.monotonic()
    files=source_files(root)
    graph,_=build_graph(files)
    candidates=candidate_features(issue,files,graph)
    if not candidates['ids']:raise ValueError('BM25 returned no candidates; use another query or text search')
    features=candidates['rows']
    feature_seconds=time.monotonic()-started
    precision=None
    if mode=='full':
        from dense_encoder import dense_scores
        dense,precision=dense_scores(issue,dense_documents(candidates['ids'],candidates['files'],files),assets,encoder_dir)
        features=[row+[dense[i]] for i,row in enumerate(features)]
    models=load_ranker(assets/('ranker-full.json' if mode=='full' else 'ranker-lexical.json'))
    scores=ensemble_scores(models,features)
    order=sorted(range(len(scores)),key=lambda i:-scores[i])[:10]
    ranked=[]
    for i in order:
        node=graph.nodes[candidates['ids'][i]]
        first=node.get('lineno') or 1
        last=node.get('end_lineno') or first
        snippet='\n'.join(files.get(candidates['files'][i],'').splitlines()[first-1:min(last,first+15)])[:500]
        ranked.append({'symbol':candidates['ids'][i],'path':candidates['files'][i],
                       'start_line':first,'end_line':last,'score':round(scores[i],6),'snippet':snippet})
    return {'status':'ok','mode':mode,'encoder_precision':precision,'candidate_count':len(scores),
            'query_sha256':hashlib.sha256(issue.encode()).hexdigest(),'source_files':len(files),
            'feature_seconds':round(feature_seconds,3),'seconds':round(time.monotonic()-started,3),
            'results':ranked,'scope':'New-issue localization; no reference labels used; not a repair success claim'}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--issue',required=True)
    ap.add_argument('--root')
    ap.add_argument('--mode',choices=('full','lexical'),default='full')
    ap.add_argument('--encoder-dir',type=Path,help='Development only: original frozen encoder on local disk')
    ap.add_argument('--assets',type=Path,default=SKILL_ROOT/'assets')
    args=ap.parse_args()
    try:
        print(json.dumps(rank(args.issue,workspace_root(args.root),args.assets,args.mode,args.encoder_dir),ensure_ascii=False))
    except Exception as error:
        print(json.dumps({'status':'error','mode':args.mode,'error':type(error).__name__+': '+str(error),
                          'fallback':'Use normal repository search; no dense result was produced.'}))
        raise SystemExit(1)
if __name__=='__main__':main()
