"""Release contracts and atomic, recoverable single-writer publication."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(8*1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def cache_key(data_path: Path, config: dict) -> str:
    return digest(canonical({'data_sha256': digest(Path(data_path).read_bytes()), 'config': config}))


def validate_release(manifest: dict, report: dict) -> None:
    if not isinstance(manifest, dict) or not isinstance(report, dict):
        raise ValueError('manifest and report must be objects')
    if type(manifest.get('schema_version')) is not int or manifest['schema_version'] != 1:
        raise ValueError('schema_version must be integer 1')
    for field in ('model_id', 'artifact_uri'):
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            raise ValueError('Missing ' + field)
    hashes = ('model_sha256', 'protocol_sha256', 'golden_sha256', 'runtime_sha256')
    for field in hashes:
        if not isinstance(manifest.get(field), str) or not re.fullmatch('[0-9a-f]{64}', manifest[field]):
            raise ValueError('Invalid ' + field)
    runtime = manifest.get('runtime')
    if not isinstance(runtime, dict) or not runtime:
        raise ValueError('Missing runtime')
    try:
        actual = digest(canonical(runtime))
    except (TypeError, ValueError) as exc:
        raise ValueError('Invalid runtime') from exc
    if actual != manifest['runtime_sha256']:
        raise ValueError('Runtime changed since evaluation')
    if report.get('status') != 'complete' or report.get('passed') is not True:
        raise ValueError('Incomplete or rejected evaluation')
    if not isinstance(report.get('evaluation_run_id'), str) or not report['evaluation_run_id'].strip():
        raise ValueError('Missing evaluation_run_id')
    for field in ('model_id', *hashes):
        if report.get(field) != manifest[field]:
            raise ValueError('Report mismatch: ' + field)
    metrics = report.get('metrics')
    if not isinstance(metrics, dict):
        raise ValueError('Missing metrics')
    for field in ('accuracy', 'format_rate'):
        value = metrics.get(field)
        if type(value) not in (int, float) or not 0 <= value <= 1 or not math.isfinite(value):
            raise ValueError('Invalid metric: ' + field)


def atomic_bytes(target, data):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.'+target.name+'.',
                                         suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def publish(manifest: dict, report: dict, target: Path) -> None:
    validate_release(manifest, report)
    payload = canonical(manifest) + b'\n'
    if Path(target).exists() and Path(target).read_bytes() == payload:
        return
    atomic_bytes(target, payload)


def verify_artifact(manifest, root):
    files = manifest.get('file_hashes')
    if not isinstance(files, dict) or not files or digest(canonical(files)) != manifest['model_sha256']:
        raise ValueError('Invalid artifact file list')
    artifact = Path(manifest['artifact_uri'].removeprefix('file://'))
    if not artifact.is_absolute():
        artifact = Path(root) / artifact
    for name, expected in files.items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Artifact path traversal')
        path = artifact / relative if artifact.is_dir() else artifact
        if not artifact.is_dir() and name != artifact.name:
            raise ValueError('Unexpected artifact name')
        if not path.is_file() or file_digest(path) != expected:
            raise ValueError('Artifact bytes mismatch: ' + name)
    return artifact


def recover_publication(root):
    """An intent repairs a crash after pointer replacement, before ledger replacement."""
    root = Path(root)
    pending = root / 'pending-release.json'
    ledger = root / 'publications.jsonl'
    events = [json.loads(line) for line in ledger.read_text().splitlines()] if ledger.exists() else []
    if pending.exists():
        intent = json.loads(pending.read_text())
        pointer = root / 'accepted.json'
        if pointer.exists() and digest(pointer.read_bytes()) == intent['pointer_sha256']:
            if not any(event['release_id'] == intent['event']['release_id'] for event in events):
                events.append(intent['event'])
                atomic_bytes(ledger, b''.join(canonical(event)+b'\n' for event in events))
        pending.unlink()
    return events


def publish_event(manifest, report, root, fail_after_pointer=False):
    root = Path(root)
    events = recover_publication(root)
    validate_release(manifest, report)
    verify_artifact(manifest, root)
    release_id = digest(canonical({'manifest': manifest, 'report': report}))
    accepted = {**manifest, 'release_id': release_id, 'evaluation_run_id': report['evaluation_run_id']}
    event = {'release_id': release_id, 'model_id': manifest['model_id'],
             'runtime_sha256': manifest['runtime_sha256'], 'evaluation_run_id': report['evaluation_run_id']}
    payload = canonical(accepted) + b'\n'
    intent = {'event': event, 'pointer_sha256': digest(payload)}
    atomic_bytes(root/'pending-release.json', canonical(intent)+b'\n')
    try:
        publish(accepted, report, root/'accepted.json')
    except Exception:
        (root/'pending-release.json').unlink(missing_ok=True)
        raise
    if fail_after_pointer:
        raise RuntimeError('Injected crash after pointer, before publication ledger')
    already = any(e['release_id'] == release_id for e in events)
    recover_publication(root)
    return {'release_id': release_id, 'model_id': manifest['model_id'], 'new_event': not already}
