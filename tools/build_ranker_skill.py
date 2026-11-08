"""Train deployment rankers and quantize the frozen encoder into a bounded text skill.

Training excludes every repository present in the public competition tasks;
no competition patch/test_patch fields enter training or feature extraction.
"""
from __future__ import annotations
import zlib
import argparse,base64,hashlib,io,json,os,shutil,sys,time
from pathlib import Path
os.environ.setdefault('OMP_NUM_THREADS','4')
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'agent/ranker/scripts'))
import numpy as np
from tools.run_combo_ltr import ORDER,SEEDS
from tools.rank_with_dense import train
from tree_predict import ensemble_scores

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--out',type=Path,default=ROOT/'.cache/main-track/ranker-package-v1')
    args=ap.parse_args()
    if args.out.exists():raise ValueError('Refusing to overwrite package build')
    args.out.mkdir(parents=True)
    skill=args.out/'skills/ranker'
    shutil.copytree(ROOT/'agent/ranker',skill,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for text_file in skill.rglob('*'):
        if text_file.suffix in ('.py','.md'):
            text_file.write_text(text_file.read_text(encoding='utf-8-sig'),encoding='utf-8')
    scripts=skill/'scripts';assets=skill/'assets';assets.mkdir(exist_ok=True)
    vendor=scripts/'experiments';vendor.mkdir()
    (vendor/'__init__.py').write_text('')
    for name in ('buildgraph.py','retrieve.py','symbols.py'):
        shutil.copy2(ROOT/'experiments'/name,vendor/name)
    public_repos=sorted({row['repo'] for row in read(ROOT/'.cache/main-track/official/tasks.jsonl')})
    all_tasks=read(ROOT/'data/features_full.jsonl')
    embeds={row['instance_id']:row for row in read(ROOT/'data/embed_retrieval.jsonl')}
    tasks=[row for row in all_tasks if row['repo'] not in set(public_repos)]
    if not tasks or any(tuple(t['features'])!=ORDER for t in tasks):raise ValueError('Training input schema mismatch')
    for task in tasks:
        dense=embeds[task['instance_id']]
        if sorted(dense['candidates'])!=list(range(len(task['rows']))):raise ValueError('Incomplete dense training scores')
        scores=[0.0]*len(task['rows'])
        for i,score in zip(dense['candidates'],dense['scores']):scores[i]=score
        task['rows']=[row+[scores[i]] for i,row in enumerate(task['rows'])]
    training={'training_tasks':len(tasks),'training_repos':sorted({t['repo'] for t in tasks}),
              'excluded_competition_repos':public_repos,'task_ids':[t['instance_id'] for t in tasks],
              'input_sha256':{name:sha(ROOT/'data'/name) for name in ('features_full.jsonl','embed_retrieval.jsonl')},
              'seeds':list(SEEDS),'features':[*ORDER,'dense_cosine'],
              'deployment_note':'Trained on historical SWE-bench repositories excluding all four competition repositories; differs from paper two-fold estimator.'}
    (args.out/'training-manifest.json').write_text(json.dumps(training,indent=2),encoding='utf-8')
    for name,columns in [('full',list(range(17))),('lexical',list(range(16)))]:
        models=[train(tasks,seed,columns) for seed in SEEDS]
        dumps=[model.dump_model() for model in models]
        sample=[task['rows'][0] for task in tasks[::5]]
        sample=[[row[i] for i in columns] for row in sample]
        actual=ensemble_scores(dumps,sample)
        expected=np.mean([model.predict(np.asarray(sample)) for model in models],axis=0)
        difference=float(np.max(np.abs(expected-np.asarray(actual))))
        if difference>1e-10:raise ValueError('Portable tree inference differs')
        serialized=json.dumps({'models':dumps},separators=(',',':')).encode()
        packed={'format':'zlib-json-v1','payload':base64.b85encode(zlib.compress(serialized,9)).decode()}
        (assets/('ranker-'+name+'.json')).write_text(json.dumps(packed,separators=(',',':')),encoding='utf-8')
        print(name,'portable tree parity max error',difference,flush=True)
    import torch
    from safetensors.torch import load_file
    state=load_file(str(ROOT/'models/bge-small-en-v1.5/model.safetensors'),device='cpu')
    arrays={};records=[]
    for i,(name,tensor) in enumerate(state.items()):
        value=tensor.float().numpy();key='a'+str(i)
        record={'name':name,'key':key,'quantized':value.ndim>=2 and tensor.is_floating_point()}
        if record['quantized']:
            scale=np.maximum(np.max(np.abs(value),axis=-1,keepdims=True)/127,np.finfo(np.float32).tiny)
            arrays[key]=np.rint(value/scale).clip(-127,127).astype(np.int8)
            arrays[key+'s']=scale.astype(np.float32)
            record['scale_key']=key+'s'
        else:arrays[key]=value.astype(np.float32)
        records.append(record)
    buffer=io.BytesIO();np.savez_compressed(buffer,**arrays)
    encoder=assets/'encoder';encoder.mkdir()
    (encoder/'weights-int8.txt').write_bytes(base64.b85encode(buffer.getvalue()))
    for name in ('config.json','tokenizer.json','tokenizer_config.json','vocab.txt','special_tokens_map.json'):
        shutil.copy2(ROOT/'models/bge-small-en-v1.5'/name,encoder/name)
    quant={'method':'symmetric per-row int8; float32 scales/biases; dequantize to fp32 CPU',
           'original_weight_sha256':sha(ROOT/'models/bge-small-en-v1.5/model.safetensors'),'tensors':records}
    (encoder/'quantization.json').write_text(json.dumps(quant,separators=(',',':')),encoding='utf-8')
    shutil.copy2(ROOT/'models/bge-small-en-v1.5/README.md',assets/'encoder-model-card.md')
    (assets/'model-notice.md').write_text('Encoder: BAAI/bge-small-en-v1.5, MIT license as declared in the original model card. Quantized locally; original weight SHA256 is recorded in quantization.json.\n',encoding='utf-8')
    files=[p for p in skill.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    size=sum(p.stat().st_size for p in files)
    print('Skill bytes',size,'limit',50*1024**2,flush=True)
    if size>50*1024**2:raise ValueError('Skill exceeds 50 MiB; do not submit')
    manifest={'skill_bytes':size,'skill_limit_bytes':50*1024**2,'training_manifest_sha256':sha(args.out/'training-manifest.json'),
              'runtime_dependencies':['numpy','torch','transformers','tokenizers'],
              'full_original_mode':'pass --encoder-dir to original frozen checkpoint in development only',
              'deployment_mode':'per-row INT8 encoder, portable JSON ranking trees; no reference labels or patch data',
              'files':{p.relative_to(args.out).as_posix():sha(p) for p in files}}
    (args.out/'package-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('Prepared complete compact retrieval skill; runtime integration still requires verification.',flush=True)
if __name__=='__main__':main()
