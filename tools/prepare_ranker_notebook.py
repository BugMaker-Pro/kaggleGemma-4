"""Prepare a private online CPU notebook that builds a complete offline ranker skill.

Model downloads are pinned and hashed. No task evaluation or repair agent runs
in this preparation notebook. The output is consumed by offline probes.
"""
from pathlib import Path
import argparse,hashlib,json,sys
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from tools.build_main_track import cell,agent_files,MODEL

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--package',type=Path,default=ROOT/'.cache/main-track/ranker-package-v1')
    ap.add_argument('--out',type=Path,default=ROOT/'.cache/main-track/ranker-bootstrap-v1')
    args=ap.parse_args()
    if args.out.exists():raise ValueError('Refusing existing build')
    original=json.loads((ROOT/'.cache/main-track/official-starter.json').read_text(encoding='utf-8-sig'))
    starter=json.loads(original['blob']['source'])
    manifest=json.loads((args.package/'package-manifest.json').read_text())
    contents={}
    for relative,digest in manifest['files'].items():
        path=args.package/relative
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('Package hash mismatch: '+relative)
        if relative.endswith('weights-int8.txt'):continue
        contents[relative]=path.read_text(encoding='utf-8-sig')
    base=agent_files(ROOT/'.cache/main-track/official/sample_submission','evidence',completion_guardrails=True,max_output_tokens=8192)
    base['agent.yaml']=base['agent.yaml'].replace('instruction: !include prompts/system.md','instruction: !include prompts/system.md\nskills:\n  - skills/ranker')
    base['eval_config.yaml']=base['eval_config.yaml'].replace('timeout_seconds: 60','timeout_seconds: 120')
    prefix='''## Use the repository ranker once at the start

Call run_skill_script with skill_name="ranker", file_path="scripts/localize.py", and args={"issue": the complete original problem statement, "mode": "full"}. This runs a local trained retriever and returns up to ten definitions with source paths and line ranges. Do not ask it to repair code. Read the most relevant returned definition, make the smallest supported fix, run one focused check, and explicitly submit. If localization returns an explicit error, continue using ordinary text search; do not report a dense ranking that was not produced.

'''
    base['prompts/system.md']=prefix+base['prompts/system.md']
    contents.update(base)
    reference_hash=hashlib.sha256((ROOT/'models/bge-small-en-v1.5/model.safetensors').read_bytes()).hexdigest()
    code='''import base64,hashlib,io,json,os,zipfile
from pathlib import Path
import numpy as np
from safetensors.numpy import load_file
from huggingface_hub import hf_hub_download
from adk_submission import validate_directory
from swegemma.config import build_submission_limits
WORK=Path('/kaggle/working')
PACKAGE=WORK/'ranker-agent'
PACKAGE.mkdir(exist_ok=True)
'''
    code+='FILES=json.loads('+repr(json.dumps(contents))+')\n'
    code+='EXPECTED_WEIGHT_SHA256='+repr(reference_hash)+'\n'
    code+='''for relative,text in FILES.items():
    path=(PACKAGE/relative).resolve()
    assert path.is_relative_to(PACKAGE.resolve())
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(text,encoding='utf-8')
# Only this preparation notebook has network access.
checkpoint=hf_hub_download('BAAI/bge-small-en-v1.5','model.safetensors',revision='5c38ec7c405ec4b44b94cc5a9bb96e735b38267a')
assert hashlib.sha256(Path(checkpoint).read_bytes()).hexdigest()==EXPECTED_WEIGHT_SHA256
state=load_file(checkpoint)
arrays={};records=[]
for i,(name,value) in enumerate(sorted(state.items())):
    quantized=value.ndim>=2 and np.issubdtype(value.dtype,np.floating)
    value=value.astype(np.float32);key='a'+str(i)
    record={'name':name,'key':key,'quantized':quantized}
    if record['quantized']:
        scale=np.maximum(np.max(np.abs(value),axis=-1,keepdims=True)/127,np.finfo(np.float32).tiny)
        arrays[key]=np.rint(value/scale).clip(-127,127).astype(np.int8)
        arrays[key+'s']=scale.astype(np.float32);record['scale_key']=key+'s'
    else:arrays[key]=value
    records.append(record)
encoder=PACKAGE/'skills/ranker/assets/encoder'
buffer=io.BytesIO();np.savez_compressed(buffer,**arrays)
(encoder/'weights-int8.txt').write_bytes(base64.b85encode(buffer.getvalue()))
(encoder/'quantization.json').write_text(json.dumps({'method':'symmetric per-row INT8','original_weight_sha256':EXPECTED_WEIGHT_SHA256,'tensors':records},separators=(',',':')))
skill_size=sum(p.stat().st_size for p in (PACKAGE/'skills/ranker').rglob('*') if p.is_file())
assert skill_size<50*1024**2,skill_size
limits,_=build_submission_limits()
validate_directory(PACKAGE,limits=limits)
files={p.relative_to(PACKAGE).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in PACKAGE.rglob('*') if p.is_file()}
with zipfile.ZipFile(WORK/'ranker-submission.zip','w',zipfile.ZIP_DEFLATED) as archive:
    for relative in sorted(files):archive.write(PACKAGE/relative,relative)
record={'files':files,'skill_bytes':skill_size,'original_encoder_sha256':EXPECTED_WEIGHT_SHA256,
        'encoder_variant':'per-row INT8 reconstructed in FP32','official_directory_validation':True,
        'agent_model':'gemma-4-12b-it-qat-w4a16-ct','runtime_dependencies':['numpy','torch','transformers','tokenizers'],
        'scope':'Complete experimental retrieval skill; no claim of official Docker dependency availability or leaderboard eligibility'}
(WORK/'ranker-package-manifest.json').write_text(json.dumps(record,indent=2))
print('Built complete ranker package',skill_size,'bytes; official structure validation passed.')
'''
    nb={'nbformat':4,'nbformat_minor':5,'metadata':{'kernelspec':{'name':'python3','display_name':'Python 3','language':'python'}},
        'cells':[cell('markdown','# Offline ranker package preparation\n\nPrivate CPU preparation only. Downloads one pinned public encoder, verifies its hash, packs trained trees and a compressed encoder into a bounded ADK skill. No task or patch data are bundled; no repair agent or evaluation runs with network access.\n'),cell('code',''.join(starter['cells'][2]['source'])),cell('code',code)]}
    args.out.mkdir(parents=True)
    (args.out/'prepare.ipynb').write_text(json.dumps(nb,indent=2),encoding='utf-8')
    request={'newTitle':'Gemma4 complete ranker package 20261108','slug':'gemma4-complete-ranker-package-20261108',
             'text':json.dumps(nb),'language':'python','kernelType':'notebook','isPrivate':True,'enableGpu':False,'enableInternet':True,'enableTpu':False,
             'sessionTimeoutSeconds':1800,'dockerImage':original['metadata']['dockerImage'],'dockerImagePinningType':'original',
             'datasetDataSources':original['metadata']['datasetDataSources'],'competitionDataSources':[],'modelDataSources':[]}
    (args.out/'kernel-request.json').write_text(json.dumps(request),encoding='utf-8')
    (args.out/'manifest.json').write_text(json.dumps({'local_package_manifest_sha256':hashlib.sha256((args.package/'package-manifest.json').read_bytes()).hexdigest(),
        'training_manifest_sha256':hashlib.sha256((args.package/'training-manifest.json').read_bytes()).hexdigest(),'mode':'preparation_only','weights_source_hash':reference_hash},indent=2),encoding='utf-8')
    print('Prepared private CPU package-building notebook; request bytes', (args.out/'kernel-request.json').stat().st_size)
if __name__=='__main__':main()
