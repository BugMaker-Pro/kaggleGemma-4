"""Create a self-contained experimental agent archive from a verified local ranker skill."""
from pathlib import Path
import argparse,hashlib,json,sys,zipfile
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from tools.build_main_track import agent_files
from tools.build_ranker_agent_probe import staged_overrides

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--package',type=Path,default=ROOT/'.cache/main-track/ranker-package-v1')
    ap.add_argument('--out',type=Path,default=ROOT/'artifacts/ranker-agent-v1')
    ap.add_argument('--staged',action='store_true',help='Run localization before repair using the supported sequential workflow')
    args=ap.parse_args()
    if args.out.exists():raise ValueError('Refusing existing output')
    args.out.mkdir(parents=True)
    manifest=json.loads((args.package/'package-manifest.json').read_text(encoding='utf-8'))
    files={}
    for name,digest in manifest['files'].items():
        data=(args.package/name).read_bytes()
        if hashlib.sha256(data).hexdigest()!=digest:raise ValueError('Ranker payload changed: '+name)
        files[name]=data
    base=agent_files(ROOT/'.cache/main-track/official/sample_submission','evidence',completion_guardrails=True,max_output_tokens=8192)
    plain_base=dict(base)
    base['agent.yaml']=base['agent.yaml'].replace('instruction: !include prompts/system.md','instruction: !include prompts/system.md\nskills:\n  - skills/ranker')
    base['eval_config.yaml']=base['eval_config.yaml'].replace('timeout_seconds: 60','timeout_seconds: 120')
    prefix='''## First run the complete repository ranker

Call run_skill_script with skill_name="ranker", file_path="scripts/localize.py", and args={"issue": the complete original problem statement, "mode": "full"}. The script computes candidate features and dense scores, applies learned ranking trees, and returns ten source locations. Read the relevant returned definition before editing. Do not ask the ranker to repair code. Do not repeat the same localization call. If it reports an explicit error, continue with normal search and record the limitation; do not claim a dense result was produced.

'''
    base['prompts/system.md']=prefix+base['prompts/system.md']
    if args.staged:base.update(staged_overrides(plain_base))
    files.update({name:text.encode() for name,text in base.items()})
    final={'schema':1,'skill_bytes':manifest['skill_bytes'],
           'workflow':'sequential' if args.staged else 'single_agent',
           'files':{name:hashlib.sha256(data).hexdigest() for name,data in files.items()},
           'encoder_variant':'per-row INT8, dequantized to FP32 CPU; differs from paper saved FP16 encoder',
           'requires':['numpy','torch','transformers','tokenizers'],
           'training_repo_policy':'Excluded all four official public competition repositories',
           'status':'experimental_not_officially_submitted','local_integration':json.loads((args.package/'local-integration.json').read_text()),
           'training_manifest_sha256':hashlib.sha256((args.package/'training-manifest.json').read_bytes()).hexdigest()}
    files['ranker-package-manifest.json']=json.dumps(final,indent=2).encode()
    with zipfile.ZipFile(args.out/'ranker-agent.zip','w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for name,data in sorted(files.items()):archive.writestr(name,data)
    final['zip_sha256']=hashlib.sha256((args.out/'ranker-agent.zip').read_bytes()).hexdigest()
    (args.out/'manifest.json').write_text(json.dumps(final,indent=2),encoding='utf-8')
    print('Packed',len(files),'files; archive bytes',(args.out/'ranker-agent.zip').stat().st_size)
if __name__=='__main__':main()
