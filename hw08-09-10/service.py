"""Shared serving state, a stdlib test adapter, and the final FastAPI application."""
import argparse
from contextlib import asynccontextmanager
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import time
import uuid
from backend import StubBackend, TransformersBackend
from release import canonical, digest


class Unavailable(Exception):
    pass


class Busy(Exception):
    pass


class ServiceState:
    def __init__(self, root, warmup_seconds=0, backend_factory=StubBackend):
        self.root = Path(root)
        self.ready = False
        self.backend = None
        self.error = None
        self.warmup_finished = threading.Event()
        self.lock = threading.Lock()
        self.capacity = threading.BoundedSemaphore(4)
        def load():
            try:
                manifest = json.loads((self.root/'accepted.json').read_text())
                if digest(canonical(manifest['runtime'])) != manifest['runtime_sha256']:
                    raise ValueError('Runtime fingerprint mismatch')
                self.backend = backend_factory(manifest, self.root)
                self.backend.warmup()
                time.sleep(warmup_seconds)
                self.warmup_finished.set()
                self.ready = True
            except Exception as exc:
                self.error = f'{type(exc).__name__}: {exc}'
        self.loader = threading.Thread(target=load, daemon=True)
        self.loader.start()

    def debug(self):
        return {'loaded_id': self.backend.loaded_id if self.backend else None,
                'calls': self.backend.calls if self.backend else 0,
                'warmup_finished': self.warmup_finished.is_set(), 'error': self.error}

    def generate(self, request):
        started = time.perf_counter()
        if not isinstance(request, dict):
            raise ValueError('Expected JSON object')
        prompt, limit = request.get('prompt'), request.get('max_new_tokens', self.backend.limit if self.backend else 32)
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 16384:
            raise ValueError('prompt must contain 1..16384 characters')
        if type(limit) is not int or not 1 <= limit <= 32:
            raise ValueError('max_new_tokens must be integer 1..32')
        if not self.ready:
            raise Unavailable('Loading or warming up')
        if limit > self.backend.limit or self.backend.fixed_limit and limit != self.backend.limit:
            raise ValueError('Limit differs from evaluated protocol')
        if not self.capacity.acquire(blocking=False):
            raise Busy('Queue capacity reached')
        try:
            with self.lock:
                generation_start = time.perf_counter()
                result = self.backend.generate(prompt, limit)
                elapsed = time.perf_counter()-generation_start
                result.update(model_id=self.backend.loaded_id, runtime_sha256=self.backend.runtime_sha256,
                              request_id=str(uuid.uuid4()), generation_seconds=elapsed,
                              queue_seconds=generation_start-started, total_seconds=time.perf_counter()-started)
                return result
        finally:
            self.capacity.release()


def handler_for(state, debug=True):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send_json(self, status, payload):
            data=json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == '/health': self.send_json(200, {'alive': True})
            elif self.path == '/ready': self.send_json(200 if state.ready else 503, {'ready':state.ready})
            elif self.path == '/debug' and debug: self.send_json(200, state.debug())
            else: self.send_json(404, {'error':'not found'})

        def do_POST(self):
            if self.path != '/generate': self.send_json(404, {'error':'not found'}); return
            try:
                size = int(self.headers.get('Content-Length','0'))
                if not 0 < size <= 65536:
                    self.send_json(413, {'error':'body too large or missing'}); return
                result=state.generate(json.loads(self.rfile.read(size)))
                self.send_json(200,result)
            except Unavailable as exc: self.send_json(503, {'error':str(exc)})
            except Busy as exc: self.send_json(429, {'error':str(exc)})
            except (ValueError, TypeError) as exc: self.send_json(400, {'error':str(exc)})
    return Handler


def create_app(root, warmup_seconds=0, backend_factory=StubBackend, debug=False):
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    from starlette.concurrency import run_in_threadpool
    @asynccontextmanager
    async def lifespan(app):
        app.state.service = ServiceState(root, warmup_seconds, backend_factory)
        yield
    app=FastAPI(lifespan=lifespan)
    @app.get('/health')
    def health(): return {'alive':True}
    @app.get('/ready')
    def ready():
        state=app.state.service
        return JSONResponse({'ready':state.ready},status_code=200 if state.ready else 503)
    if debug:
        @app.get('/debug')
        def inspect(): return app.state.service.debug()
    @app.post('/generate')
    async def generate(request: Request):
        try:
            # Stream and bound the body before decoding; Content-Length is not trusted.
            body=bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body)>65536: return JSONResponse({'error':'body too large'},status_code=413)
            result=await run_in_threadpool(app.state.service.generate,json.loads(body))
            return result
        except Unavailable as exc: return JSONResponse({'error':str(exc)},status_code=503)
        except Busy as exc: return JSONResponse({'error':str(exc)},status_code=429)
        except (ValueError,TypeError) as exc: return JSONResponse({'error':str(exc)},status_code=400)
    return app


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--workspace',type=Path,default=Path('.lab'))
    p.add_argument('--port',type=int,default=8091)
    p.add_argument('--warmup-seconds',type=float,default=5)
    p.add_argument('--engine',choices=['stdlib','fastapi'],default=os.environ.get('HW8910_HTTP_ENGINE','stdlib'))
    p.add_argument('--backend',choices=['stub','real'],default='stub')
    p.add_argument('--debug',action='store_true')
    args=p.parse_args()
    factory=StubBackend if args.backend=='stub' else TransformersBackend
    if args.engine=='fastapi':
        import uvicorn
        uvicorn.run(create_app(args.workspace,args.warmup_seconds,factory,debug=args.debug or args.backend=='stub'),
                    host='127.0.0.1',port=args.port,log_level='warning')
    else:
        state=ServiceState(args.workspace,args.warmup_seconds,factory)
        server=ThreadingHTTPServer(('127.0.0.1',args.port),handler_for(state,debug=args.debug or args.backend=='stub'))
        print(f'http://127.0.0.1:{server.server_port}',flush=True)
        try: server.serve_forever()
        except KeyboardInterrupt: pass
        finally: server.server_close()


if __name__=='__main__': main()
