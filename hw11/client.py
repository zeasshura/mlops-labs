"""Open-loop clients: planned and actual dispatch are recorded separately."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import http.client
import json
import socket
import time
from urllib.parse import urlsplit


def one(url,item,run_id,base_mono,base_epoch,history=None):
    planned=base_mono+item.get('offset',0)
    if time.monotonic()<planned:time.sleep(planned-time.monotonic())
    started=time.monotonic();parts=[];first=None;status=0;error=None;complete=False
    target=urlsplit(url);rid=f"{run_id}-{item['index']}"
    row={'run_id':run_id,'index':item['index'],'client':item.get('client',0),'request_id':rid,
         'scheduled_offset':item.get('offset',0),'actual_offset':started-base_mono,'send_lag_seconds':started-planned,
         'scheduled_epoch':base_epoch+item.get('offset',0),'sent_epoch':time.time(),'send_monotonic':started,
         'prompt_chars':item.get('length',128),'requested_chunks':item.get('chunks',4),'backend_mode':'simulated'}
    conn=http.client.HTTPConnection(target.hostname,target.port or 80,timeout=item.get('timeout',30))
    try:
        payload={'prompt':('x'*item.get('length',128)),'prefix':str(item.get('prefix',item.get('client',0))),
                 'session_id':f"client-{item.get('client',0)}",'max_new_tokens':item.get('chunks',4),
                 'chunk_interval':item.get('interval',.06),'history':history or []}
        conn.request('POST',target.path or '/generate',body=json.dumps(payload),headers={'Content-Type':'application/json','X-Request-ID':rid,'Connection':'close'})
        response=conn.getresponse();status=response.status
        row.update(pod=response.getheader('X-Pod'),model_id=response.getheader('X-Model-ID'))
        if status!=200:
            error=response.read().decode()[:256]
            try:
                rejected=json.loads(error);row.update(pod=rejected.get('pod'),model_id=rejected.get('model_id'))
            except ValueError:pass
        else:
            while True:
                line=response.readline()
                if not line:break
                now=time.monotonic();piece=json.loads(line)
                if not piece.get('error'):
                    if first is None:first=now
                    parts.append(now)
                row.update(pod=piece.get('pod',row.get('pod')),model_id=piece.get('model_id',row.get('model_id')),queue_seconds=piece.get('queue_seconds'),
                           cache_hit=piece.get('cache_hit'),warmup_finished_at_accept=piece.get('warmup_finished_at_accept'),
                           history=piece.get('history'))
                if piece.get('error'):error=piece['error']
                complete=piece.get('complete',False)
    except (TimeoutError,socket.timeout) as exc:error=f'{type(exc).__name__}: timeout'
    except Exception as exc:error=f'{type(exc).__name__}: {exc}'
    finally:conn.close()
    ended=time.monotonic()
    outcome='completed' if status==200 and complete else 'rejected' if status in (400,413,429,503) else 'deadline' if error and any(x in error.lower() for x in ['timeout','deadline']) else 'aborted'
    row.update(status=status,outcome=outcome,error=error,parts=len(parts),first_monotonic=first,finish_monotonic=ended,
               ttfc_seconds=first-started if first else None,duration_seconds=ended-started,
               inter_chunk_seconds=[b-a for a,b in zip(parts,parts[1:])],complete=complete)
    return row


def main():
    p=argparse.ArgumentParser();p.add_argument('--url',required=True);p.add_argument('--schedule',required=True)
    p.add_argument('--client',type=int,required=True);p.add_argument('--start-at',type=float,required=True);p.add_argument('--run-id',required=True)
    args=p.parse_args();items=[r for r in json.load(open(args.schedule)) if r['client']==args.client]
    base_mono=time.monotonic()+args.start_at-time.time()
    with ThreadPoolExecutor(max_workers=64) as pool:
        futures=[pool.submit(one,args.url,item,args.run_id,base_mono,args.start_at) for item in items]
        for future in as_completed(futures):print(json.dumps(future.result(),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
