"""Reuse a finished HW67 training run; freshly evaluate the fixed serving runtime."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import time
from release import atomic_bytes, canonical, digest, verify_artifact

PROJECT=Path(__file__).resolve().parent
HW67=PROJECT.parent/'hw06-07'
LOCAL_HW67=PROJECT.parents[1]/'mlops_hw6-7'


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


contract=module('hw67_contract',HW67/'evaluation/contract.py')
solution=module('hw67_solution',HW67/'evaluation/solution.py')


def read(path): return json.loads(Path(path).read_text())

def write(path,value): atomic_bytes(path,canonical(value)+b'\n')


def file_digest(path):
    import hashlib
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(8*1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def artifact_manifest(root,kind,artifact,spec,config,protocol,golden):
    from transformers import AutoTokenizer
    artifact=Path(artifact).resolve()
    if kind=='base':
        names=['config.json','generation_config.json','model.safetensors','tokenizer.json',
               'tokenizer_config.json','vocab.json','merges.txt']
    else:
        names=sorted(p.name for p in artifact.iterdir() if p.is_file() and p.suffix in {'.json','.txt','.safetensors','.jinja'})
        if not {'adapter_config.json','adapter_model.safetensors'} <= set(names):raise ValueError('Missing adapter weights/config')
    files={name:file_digest(artifact/name) for name in names}
    tokenizer_files=[n for n in names if n in {'tokenizer.json','tokenizer_config.json','special_tokens_map.json','vocab.json','merges.txt','added_tokens.json','chat_template.jinja'}]
    tokenizer=AutoTokenizer.from_pretrained(artifact,local_files_only=True)
    runtime={'base_revision':read(HW67/'evaluation/baseline.json')['revision'],
             'tokenizer_sha256':digest(canonical({n:files[n] for n in tokenizer_files})),
             'template_sha256':digest(tokenizer.chat_template.encode()),
             'generation':{**{k:config[k] for k in ['system','max_new_tokens','enable_thinking','seed']},'do_sample':False},
             'dtype':'float32'}
    return {'schema_version':1,'model_id':('qwen3-baseline-'+runtime['base_revision'] if kind=='base' else 'adapter-run-'+spec['run_id']),
            'model_kind':kind,'artifact_uri':str(artifact),'source_model':spec,
            'model_sha256':digest(canonical(files)),'file_hashes':files,'tokenizer_files':tokenizer_files,
            'protocol_sha256':protocol,'golden_sha256':golden,'runtime':runtime,
            'runtime_sha256':digest(canonical(runtime)),'max_input_tokens':2048}


def protocol_digest(config,data):
    return digest(canonical({'eval_config':config,'data':data,
            'hw67_evaluation_code':{p.name:file_digest(p) for p in sorted((HW67/'evaluation').glob('*.py'))},
            'serving_backend_code':file_digest(PROJECT/'backend.py'),'evaluation_wrapper':file_digest(Path(__file__))}))


def verify_bundle(root):
    root=Path(root)
    data=read(root/'input.txt');config=read(root/'eval-config.json')
    contract.validate_golden(data['golden'],data['training_index'],data['behavioral'])
    reports={}
    for role in ['baseline','candidate']:
        report=read(root/f'{role}-eval.json');outputs=read(root/f'{role}-outputs.json')
        manifest=read(root/f'manifest-{role}.json')
        by_id={r['id']:r for r in outputs}
        expected={r['id'] for r in data['golden']+data['behavioral']}
        if len(by_id)!=len(outputs) or set(by_id)!=expected:raise ValueError('Changed output IDs')
        if report['model']!=manifest['source_model'] or report['runtime_sha256']!=manifest['runtime_sha256']:
            raise ValueError('Changed evaluation model/runtime')
        if report['outputs_sha256']!=contract.fingerprint(outputs):raise ValueError('Changed raw outputs')
        if report['protocol_sha256']!=manifest['protocol_sha256'] or report['protocol_sha256']!=protocol_digest(config,data) or report['golden_sha256']!=contract.fingerprint(data['golden']):
            raise ValueError('Changed evaluation protocol/data')
        score=solution.score(data['golden'],[by_id[r['id']] for r in data['golden']])
        if any(score[k]!=report[k] for k in ['overall','slices','per_item']):raise ValueError('Changed summary')
        if solution.score(data['behavioral'],[by_id[r['id']] for r in data['behavioral']])!=report['behavioral']:
            raise ValueError('Changed behavioral results')
        reports[role]=report
    return reports,config


def linked_report(root,role):
    root=Path(root);reports,config=verify_bundle(root)
    manifest=read(root/f'manifest-{role}.json')
    source=reports[role]
    try:
        decision=solution.quality_gate(reports['baseline'],source,config['critical_slices'])
    except ValueError as exc:
        decision={'passed':False,'reason':str(exc)}
    evidence={name:{'path':str(root/name),'sha256':file_digest(root/name)} for name in
              ['baseline-eval.json','candidate-eval.json','baseline-outputs.json','candidate-outputs.json','eval-config.json']}
    report={k:manifest[k] for k in ['model_id','model_sha256','protocol_sha256','golden_sha256','runtime_sha256']}
    report.update(status=source['status'],passed=decision.get('passed') is True,
                  evaluation_run_id=source['evaluation_run_id'],metrics={k:source['overall'][k] for k in ['accuracy','format_rate']},
                  decision=decision,source_evidence=evidence,source_training_run=read(HW67/'docs/mlflow_links.json')['candidate']['run_id'],
                  policy='baseline self-check retains the pinned base; candidate compared against that base',synthetic=False)
    write(root/f'release-report-{role}.json',report)
    return report


def evaluate(root,role,manifest,data,protocol,run_id):
    from backend import TransformersBackend
    backend=TransformersBackend(manifest,root)
    outputs=[]
    for index,row in enumerate(data['golden']+data['behavioral'],1):
        start=time.perf_counter()
        try:
            response=backend.generate(row['input'],backend.limit)
            output={'id':row['id'],'raw':response['answer'],'error':None,'latency_seconds':time.perf_counter()-start,
                    'output_tokens':response['output_tokens']}
        except Exception as exc:
            output={'id':row['id'],'raw':'','error':f'{type(exc).__name__}: {exc}','latency_seconds':time.perf_counter()-start}
        outputs.append(output);write(root/f'{role}-outputs.partial.json',outputs)
        if index%10==0 or index==len(data['golden']+data['behavioral']):print(role,index,'/',len(data['golden']+data['behavioral']),flush=True)
    write(root/f'{role}-outputs.json',outputs)
    by_id={r['id']:r for r in outputs}
    report=solution.score(data['golden'],[by_id[r['id']] for r in data['golden']])
    report.update(status='complete',model=manifest['source_model'],protocol_sha256=protocol,
                  golden_sha256=contract.fingerprint(data['golden']),runtime_sha256=manifest['runtime_sha256'],
                  baseline_spec_sha256=contract.fingerprint(read(HW67/'evaluation/baseline.json')),
                  behavioral=solution.score(data['behavioral'],[by_id[r['id']] for r in data['behavioral']]),
                  outputs_sha256=contract.fingerprint(outputs),evaluation_run_id=run_id)
    write(root/f'{role}-eval.json',report)
    del backend
    import gc
    gc.collect()


def main():
    p=argparse.ArgumentParser();p.add_argument('--workspace',type=Path,default=PROJECT/'.runtime/real')
    p.add_argument('--source',type=Path,default=LOCAL_HW67);p.add_argument('--tracking-uri',default='http://127.0.0.1:5006')
    p.add_argument('--reuse-evaluation',action='store_true',help='Verify existing HW08 evaluations; do not regenerate responses')
    args=p.parse_args();root=args.workspace.resolve();root.mkdir(parents=True,exist_ok=True)
    if not args.reuse_evaluation:
        import mlflow
        from mlflow import MlflowClient
        mlflow.set_tracking_uri(args.tracking_uri)
        client=MlflowClient(tracking_uri=args.tracking_uri)
        spec=read(HW67/'docs/mlflow_links.json')['candidate']
        version=client.get_model_version(spec['name'],spec['version'])
        run=client.get_run(spec['run_id'])
        if version.run_id!=spec['run_id'] or run.info.status!='FINISHED':raise ValueError('Invalid training run')
        download=root/'downloaded';download.mkdir(exist_ok=True)
        model_root=Path(client.download_artifacts(spec['run_id'],'model',str(download)))
        import yaml
        model_info=yaml.safe_load((model_root/'MLmodel').read_text())
        adapter=(model_root/model_info['flavors']['python_function']['artifacts']['adapter']['path']).resolve()
        if not adapter.is_relative_to(model_root.resolve()):raise ValueError('Invalid MLflow artifact path')
        config=read(HW67/'evaluation/params.json')
        data={k:contract.read_rows(args.source/'data/eval'/name) for k,name in
              [('golden','golden.jsonl'),('behavioral','behavioral.jsonl'),('training_index','training-index.jsonl')]}
        proof=contract.validate_golden(data['golden'],data['training_index'],data['behavioral'])
        protocol=protocol_digest(config,data)
        baseline=read(HW67/'evaluation/baseline.json')
        from huggingface_hub import snapshot_download
        base=Path(snapshot_download(baseline['name'],revision=baseline['revision'],local_files_only=True))
        manifests={'baseline':artifact_manifest(root,'base',base,baseline,config,protocol,contract.fingerprint(data['golden'])),
                   'candidate':artifact_manifest(root,'adapter',adapter,spec,config,protocol,contract.fingerprint(data['golden']))}
        manifests['candidate']['base_artifact_uri']=str(base)
        write(root/'input.txt',data);write(root/'eval-config.json',config)
        write(root/'config.json',{'real':True,'tokenizer_revision':baseline['revision'],
              'tokenizer_sha256':manifests['baseline']['runtime']['tokenizer_sha256'],
              'template_sha256':manifests['baseline']['runtime']['template_sha256'],'max_length':2048,
              'code_revision':file_digest(PROJECT/'flow.py')})
        write(root/'training-provenance.json',{'tracking_uri':args.tracking_uri,'candidate':spec,'training_status':run.info.status,
              'training_metrics':run.data.metrics,'original_evaluation_run':read(HW67/'docs/mlflow_links.json')['evaluation'],
              'note':'Finished HW67 training reused; only inference and full evaluation rerun for the fixed runtime','leakage':proof})
        for role,m in manifests.items():write(root/f'manifest-{role}.json',m)
        # One real MLflow evaluation run; no training/sweep or Registry alias updates.
        import mlflow
        mlflow.set_tracking_uri(args.tracking_uri);mlflow.set_experiment('hw8910-release-evaluation')
        with mlflow.start_run(run_name='fixed-runtime-baseline-vs-candidate') as eval_run:
            for role,m in manifests.items():
                evaluate(root,role,m,data,protocol,eval_run.info.run_id)
                report=read(root/f'{role}-eval.json')
                mlflow.log_metrics({role+'.'+k:report['overall'][k] for k in ['accuracy','format_rate']})
                for suffix in ['eval','outputs']:mlflow.log_artifact(str(root/f'{role}-{suffix}.json'),'evaluation')
            mlflow.set_tags({'source_training_run':spec['run_id'],'protocol_sha256':protocol,'kind':'evaluation-only'})
    for role in ['baseline','candidate']:
        report=linked_report(root,role)
        print(role,'gate:',report['decision'],flush=True)
    destination=PROJECT/'docs/real';destination.mkdir(parents=True,exist_ok=True)
    for pattern in ['manifest-*.json','release-report-*.json','*-eval.json','*-outputs.json','training-provenance.json','eval-config.json']:
        for path in root.glob(pattern):shutil.copy2(path,destination/path.name)
    print('Evaluation and linked reports ready. Publish using flow.py; rejected candidate must not replace baseline.',flush=True)


if __name__=='__main__':main()
