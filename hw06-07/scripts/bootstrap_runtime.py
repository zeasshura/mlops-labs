"""Install only the pinned Compose client; use the existing rootless Podman."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
TARGET=ROOT/'tools/docker-compose'
VERSION='v2.39.4'
SHA256='7af95166a730b87e172d4fc9aefea8725d3c6c7327d59149267b452114ddb7d4'
if Path('/usr/bin/docker').exists():
    print('Using system Docker')
else:
    if not shutil.which('podman'):
        raise SystemExit('Install Docker Compose v2 or rootless Podman first.')
    if not TARGET.exists():
        url=f'https://github.com/docker/compose/releases/download/{VERSION}/docker-compose-linux-x86_64'
        print('Downloading official Compose client:',url,flush=True)
        with urllib.request.urlopen(url) as response, TARGET.open('wb') as dest:
            shutil.copyfileobj(response,dest)
    if hashlib.sha256(TARGET.read_bytes()).hexdigest()!=SHA256:
        raise SystemExit('Compose checksum mismatch; refusing to execute.')
    TARGET.chmod(0o755)
    subprocess.run(['systemctl','--user','start','podman.socket'],check=True)
    print('Rootless Podman socket ready; Compose client verified.')
