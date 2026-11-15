"""HW08-10 serving contract extended with an explicitly simulated streaming backend."""
import asyncio
from collections import OrderedDict
from contextlib import asynccontextmanager
import hashlib
import json
import os
from pathlib import Path
import time
import uuid
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST

POD=os.getenv('POD_NAME','local')
VERSION=os.getenv('MODEL_VERSION','A')
BUCKETS=(.05,.1,.2,.4,.8,1.6,3.2,6.4,12.8,25.6,60)
REQUESTS=Counter('hw11_requests','Final request outcomes',['pod','version','outcome'])
TTFC=Histogram('hw11_ttfc_seconds','First content chunk including queue',['pod','version'],buckets=BUCKETS)
TOTAL=Histogram('hw11_duration_seconds','Successful full stream latency',['pod','version'],buckets=BUCKETS)
QUEUE=Histogram('hw11_queue_seconds','Queue wait',['pod'],buckets=BUCKETS)
RUNNING=Gauge('hw11_running','Active computations and streams',['pod'])
WAITING=Gauge('hw11_waiting','Queued requests',['pod'])
READY=Gauge('hw11_ready','Loaded and warmed process',['pod'])
CACHE=Counter('hw11_cache','Explicit simulated prefix cache',['pod','result'])


def event(**fields):
    print(json.dumps({'utc':time.time(),'monotonic':time.monotonic(),'pod':POD,'backend_mode':'simulated',**fields},ensure_ascii=False),flush=True)


def burn(seconds):
    start=time.thread_time()
    while time.thread_time()-start<seconds:
        hashlib.pbkdf2_hmac('sha256',b'hw11-computational-simulator',b'cpu',12000)


class SimulatedBackend:
    """Injectable backend following HW08-10's loaded identity / warmup interface."""
    def __init__(self):
        artifact=Path(os.getenv('ARTIFACT_DIRECTORY','artifacts'))/f'model-{VERSION}.json'
        actual=hashlib.sha256(artifact.read_bytes()).hexdigest()
        expected=os.environ.get('MODEL_SHA256',actual)
        if actual!=expected:raise ValueError('Artifact checksum mismatch')
        self.loaded=json.loads(artifact.read_text())
        self.loaded_id=self.loaded['model_id'];self.runtime_sha256=actual
        self.capacity=int(os.getenv('MAX_RUNNING','1'))
        self.semaphore=asyncio.Semaphore(self.capacity)
        self.waiting=0;self.running=0;self.warmed=False;self.draining=False;self.calls=0
        self.cache=OrderedDict();self.cache_capacity=int(os.getenv('CACHE_ENTRIES','8'))
        self.hit_cpu=float(os.getenv('HIT_CPU_SECONDS','.15'));self.miss_cpu=float(os.getenv('MISS_CPU_SECONDS','.6'))
        self.max_waiting=int(os.getenv('MAX_WAITING','8'))

    async def warmup(self):
        event(event='warmup_start',model_id=self.loaded_id)
        await asyncio.sleep(float(os.getenv('WARMUP_SECONDS','20')))
        if os.getenv('NEVER_READY','false')=='true':return
        self.warmed=True;READY.labels(POD).set(1)
        event(event='warmup_complete',model_id=self.loaded_id)

    @property
    def ready(self):return self.warmed and not self.draining


@asynccontextmanager
async def lifespan(app):
    app.state.backend=SimulatedBackend()
    warm=asyncio.create_task(app.state.backend.warmup())
    yield
    warm.cancel()


app=FastAPI(lifespan=lifespan)


@app.get('/health')
def health():return {'alive':True,'backend_mode':'simulated','pod':POD}


@app.get('/startup')
@app.get('/ready')
def ready():
    b=app.state.backend
    return JSONResponse({'ready':b.ready,'model_id':b.loaded_id,'pod':POD,'backend_mode':'simulated'},status_code=200 if b.ready else 503)


@app.get('/debug')
def debug():
    b=app.state.backend
    return {'pod':POD,'model_id':b.loaded_id,'runtime_sha256':b.runtime_sha256,'warmup_finished':b.warmed,
            'running':b.running,'waiting':b.waiting,'calls':b.calls,'cache_entries':len(b.cache),'backend_mode':'simulated'}


@app.post('/drain')
def drain():
    b=app.state.backend;b.draining=True;READY.labels(POD).set(0)
    event(event='draining',model_id=b.loaded_id,active=b.running,waiting=b.waiting)
    # Existing and in-flight traffic can complete while EndpointSlices converge.
    return {'draining':True}


@app.post('/cache/reset')
def reset():
    b=app.state.backend
    if b.running or b.waiting:return JSONResponse({'error':'busy'},409)
    b.cache.clear();return {'reset':True}


@app.get('/metrics')
def metrics():return Response(generate_latest(),media_type=CONTENT_TYPE_LATEST)


@app.post('/generate')
async def generate(request:Request):
    b=app.state.backend;rid=request.headers.get('X-Request-ID',str(uuid.uuid4()));started=time.monotonic()
    def reject(status,reason):
        REQUESTS.labels(POD,VERSION,'rejected').inc()
        event(event='rejected',request_id=rid,status=status,reason=reason,model_id=b.loaded_id)
        return JSONResponse({'error':reason,'request_id':rid,'pod':POD,'model_id':b.loaded_id,'backend_mode':'simulated'},status)
    try:
        body=bytearray()
        async for part in request.stream():
            body.extend(part)
            if len(body)>65536:return reject(413,'body too large')
        payload=json.loads(body)
        prompt=payload.get('prompt');limit=payload.get('max_new_tokens',4);history=payload.get('history',[])
        if not isinstance(prompt,str) or not prompt.strip() or len(prompt)>16384:raise ValueError('invalid prompt')
        if type(limit) is not int or not 1<=limit<=64:raise ValueError('chunk limit 1..64')
        if not isinstance(history,list) or len(history)>16 or any(not isinstance(m,dict) or not isinstance(m.get('content'),str) or len(m['content'])>2048 for m in history):raise ValueError('invalid history')
        interval=payload.get('chunk_interval',.06)
        if type(interval) not in (int,float) or not 0<=interval<=1:raise ValueError('invalid interval')
    except (ValueError,TypeError,AttributeError):return reject(400,'invalid request')
    was_ready=b.warmed
    if not b.warmed and os.getenv('BROKEN_READINESS','false')!='true':return reject(503,'warming up')
    if b.semaphore.locked() and b.waiting>=b.max_waiting:return reject(429,'queue full')
    b.waiting+=1;WAITING.labels(POD).set(b.waiting)
    event(event='accepted',request_id=rid,model_id=b.loaded_id,warmup_finished=was_ready,
          client_ip=request.client.host,session_id=payload.get('session_id'),waiting=b.waiting)
    async def stream():
        acquired=False;completed=False;outcome='aborted';first=None
        try:
            try:await asyncio.wait_for(b.semaphore.acquire(),timeout=20)
            except asyncio.TimeoutError:
                outcome='deadline';yield json.dumps({'error':'queue deadline','request_id':rid,'complete':False,'pod':POD,'model_id':b.loaded_id,'backend_mode':'simulated'})+'\n';return
            acquired=True;b.waiting-=1;WAITING.labels(POD).set(b.waiting)
            b.running+=1;RUNNING.labels(POD).set(b.running);b.calls+=1
            wait=time.monotonic()-started;QUEUE.labels(POD).observe(wait)
            prefix=hashlib.sha256(str(payload.get('prefix',prompt[:32])).encode()).hexdigest()
            hit=prefix in b.cache
            CACHE.labels(POD,'hit' if hit else 'miss').inc()
            await asyncio.to_thread(burn,b.hit_cpu if hit else b.miss_cpu)
            b.cache[prefix]=True;b.cache.move_to_end(prefix)
            while len(b.cache)>b.cache_capacity:b.cache.popitem(last=False)
            for index in range(limit):
                if await request.is_disconnected():return
                if index:await asyncio.sleep(interval)
                now=time.monotonic()
                if first is None:first=now;TTFC.labels(POD,VERSION).observe(first-started)
                record={'request_id':rid,'pod':POD,'model_id':b.loaded_id,'runtime_sha256':b.runtime_sha256,
                        'backend_mode':'simulated','part':index,'text':f'SIMULATED {index}',
                        'complete':index==limit-1,'queue_seconds':wait,'cache_hit':hit,
                        'warmup_finished_at_accept':was_ready,'history':[m['content'] for m in history]}
                yield json.dumps(record,ensure_ascii=False)+'\n'
            completed=True;outcome='completed';TOTAL.labels(POD,VERSION).observe(time.monotonic()-started)
        except asyncio.CancelledError:raise
        finally:
            if acquired:b.running-=1;RUNNING.labels(POD).set(b.running);b.semaphore.release()
            else:b.waiting-=1;WAITING.labels(POD).set(b.waiting)
            REQUESTS.labels(POD,VERSION,outcome).inc()
            event(event=outcome,request_id=rid,model_id=b.loaded_id,duration_seconds=time.monotonic()-started,
                  ttfc_seconds=first-started if first else None,parts=limit if completed else None)
    return StreamingResponse(stream(),media_type='application/x-ndjson',headers={'X-Request-ID':rid,'X-Pod':POD,'X-Model-ID':b.loaded_id})
