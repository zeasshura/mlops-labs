"""Four Prefect tasks; only small descriptors cross task boundaries."""
import argparse
import json
import os
from pathlib import Path
import uuid
from release import atomic_bytes, cache_key, canonical, digest, publish_event, validate_release, verify_artifact

PROJECT=Path(__file__).resolve().parent
os.environ.setdefault('PREFECT_HOME',str(PROJECT/'.prefect'))
os.environ.setdefault('PREFECT_SERVER_ANALYTICS_ENABLED','false')
os.environ.setdefault('PREFECT_LOCAL_STORAGE_PATH',str(PROJECT/'.prefect/results'))
os.environ.setdefault('PREFECT_LOGGING_LEVEL','INFO')
from prefect import flow, task
from prefect.cache_policies import NO_CACHE


def read(path):return json.loads(Path(path).read_text())


def config_for(root):
    config=read(Path(root)/'config.json')
    config['code_revision']=digest(Path(__file__).read_bytes())
    return config


def preparation_key(context,parameters):
    root=Path(parameters['root']).resolve()
    return digest(canonical({'workspace':str(root),'content_key':cache_key(root/'input.txt',config_for(root))}))


@task(cache_key_fn=preparation_key,persist_result=True)
def prepare_data(root):
    root=Path(root);config=config_for(root)
    key=cache_key(root/'input.txt',config);cache=root/'cache';cache.mkdir(exist_ok=True)
    path=cache/(key+'.json')
    if path.exists():
        print('CACHE_HIT',key,flush=True)
        return {'cache_key':key,'artifact_uri':str(path)}
    payload=(root/'input.txt').read_bytes()
    summary={'input_sha256':digest(payload),'config':config}
    if config.get('real'):
        from integrate_hw67 import contract
        data=read(root/'input.txt')
        summary['schema_validation']=contract.validate_golden(data['golden'],data['training_index'],data['behavioral'])
        if any(len(r['input'])>16384 for r in data['golden']+data['behavioral']):raise ValueError('Oversized input')
    else:summary['rows']=len(payload.splitlines())
    atomic_bytes(path,canonical(summary)+b'\n')
    print('PREPARED',key,flush=True)
    return {'cache_key':key,'artifact_uri':str(path)}


@task(cache_policy=NO_CACHE,persist_result=False)
def obtain_artifact(root,role,prepared):
    path=Path(root)/f'manifest-{role}.json';manifest=read(path)
    verify_artifact(manifest,root)
    return {'manifest_path':str(path),'model_id':manifest['model_id'],'prepared':prepared}


@task(cache_policy=NO_CACHE,persist_result=False)
def evaluate_admission(root,role,artifact):
    root=Path(root);manifest=read(artifact['manifest_path'])
    if read(root/'config.json').get('real'):
        from integrate_hw67 import linked_report
        report=linked_report(root,role)
        path=root/f'release-report-{role}.json'
    else:
        path=root/f'report-{role}.json';report=read(path)
    validate_release(manifest,report)
    return {'manifest_path':artifact['manifest_path'],'report_path':str(path)}


@task(cache_policy=NO_CACHE,persist_result=False)
def publish_release(root,admission,fail_after_pointer=False):
    return publish_event(read(admission['manifest_path']),read(admission['report_path']),root,fail_after_pointer)


@flow(name='validated-model-release',log_prints=True)
def release_flow(root,role='B',fail_after_prepare=False,fail_after_pointer=False):
    root=str(Path(root).resolve());attempt=str(uuid.uuid4())
    path=Path(root)/'flow-attempts.jsonl'
    with path.open('a') as stream:stream.write(json.dumps({'attempt_id':attempt,'role':role})+'\n')
    prepared=prepare_data(root)
    print('PREPARATION_DESCRIPTOR',prepared,flush=True)
    if fail_after_prepare:raise RuntimeError('Injected failure after preparation')
    artifact=obtain_artifact(root,role,prepared)
    admission=evaluate_admission(root,role,artifact)
    result=publish_release(root,admission,fail_after_pointer)
    print('RELEASE',result,flush=True)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--workspace',type=Path,default=Path('.lab-prefect'))
    p.add_argument('--role',default='B');p.add_argument('--fail-after-prepare',action='store_true');p.add_argument('--fail-after-pointer',action='store_true')
    args=p.parse_args()
    release_flow(str(args.workspace),args.role,args.fail_after_prepare,args.fail_after_pointer)
