"""Share two live inference slots across frozen source and ACTION brokers.

This transport preserves exact request/response bytes and both existing broker
implementations. Queue time remains inside each client's original wall budget.
"""
import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import signal
import threading
import time
import urllib.error
import urllib.request
import uuid


def upstream_for(target,path,planning_context,literal_spans=False):
    """One explicit new consumer shares the existing semaphore; old paths persist."""
    if planning_context and target==8116 and path in ('/context16384/decision','/context16384/health'):
        return 8118,path.removeprefix('/context16384')
    if literal_spans and target==8116 and path in ('/spans/decision','/spans/health'):
        return 8122,path.removeprefix('/spans')
    return target,path


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--enable-context16384-route',action='store_true',help='At a drained maintenance boundary, add the separately frozen16k planning teacher on8118 to the same two slots; old broker bytes and routes remain unchanged')
    parser.add_argument('--enable-literal-span-route',action='store_true',help='At a drained boundary, route the separately frozen train-only span teacher on8122 through the same two inference slots')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    slots=threading.BoundedSemaphore(2);lock=threading.Lock();active=0;peak=0;stopping=threading.Event()
    state={'status':'READY','global_teacher_slots':2,'listeners':{'8125':'8115','8126':'8116'},
        'started_at_utc':datetime.now(timezone.utc).isoformat(),'frozen_broker_bytes_changed':False,
        'body_bytes_changed':False,'queue_time_in_original_240second_client_budget':True,'events':[],
        'context16384_route_enabled':args.enable_context16384_route,
        'literal_span_route_enabled':args.enable_literal_span_route}
    def save():
        (args.output/'transport.json').write_text(json.dumps({**state,'active_forwards':active,'peak_concurrent_forwards':peak},indent=2)+'\n')
    def stop(*unused):stopping.set()
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    def handler(target):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*unused):pass
            def send(self,status,payload,content_type='application/json'):
                self.send_response(status);self.send_header('Content-Type',content_type);self.send_header('Content-Length',str(len(payload)));self.end_headers()
                try:self.wfile.write(payload)
                except (BrokenPipeError,ConnectionResetError):pass
            def do_GET(self):
                upstream,path=upstream_for(target,self.path,args.enable_context16384_route,args.enable_literal_span_route)
                if self.path=='/transport-health':
                    with lock:payload=json.dumps({**state,'active_forwards':active,'peak_concurrent_forwards':peak}).encode()
                    self.send(200,payload);return
                if path!='/health':self.send(404,b'{"error":"unknown path"}');return
                try:
                    with urllib.request.urlopen('http://127.0.0.1:'+str(upstream)+'/health',timeout=10) as response:self.send(response.status,response.read())
                except Exception as exc:self.send(502,json.dumps({'error':type(exc).__name__+': '+str(exc)}).encode())
            def do_POST(self):
                nonlocal active,peak
                began=time.monotonic();at=datetime.now(timezone.utc).isoformat();identifier=str(uuid.uuid4())
                upstream,path=upstream_for(target,self.path,args.enable_context16384_route,args.enable_literal_span_route)
                if path!='/decision':self.send(404,b'{"error":"unknown path"}');return
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=1024*1024:self.send(413,b'{"error":"unexpected payload size"}');return
                body=self.rfile.read(length)
                record={'transport_id':identifier,'target':upstream,'started_at_utc':at,'request_bytes':len(body)}
                acquired=slots.acquire(timeout=max(0,240-(time.monotonic()-began)))
                if not acquired:
                    record.update(status='QUEUE_BUDGET_EXHAUSTED_NO_INFERENCE',wall_seconds=time.monotonic()-began)
                    with lock:state['events'].append(record);save()
                    self.send(504,b'{"error":"shared teacher transport queue consumed original240s budget; no inference forwarded"}');return
                record['queue_seconds']=time.monotonic()-began
                with lock:
                    active+=1;peak=max(peak,active);save()
                try:
                    request=urllib.request.Request('http://127.0.0.1:'+str(upstream)+'/decision',data=body,headers={'Content-Type':'application/json'})
                    try:
                        with urllib.request.urlopen(request,timeout=600) as response:status=response.status;payload=response.read()
                    except urllib.error.HTTPError as exc:status=exc.code;payload=exc.read()
                    record.update(status='FORWARDED',http_status=status,response_bytes=len(payload),wall_seconds=time.monotonic()-began,original_client_budget_exceeded=time.monotonic()-began>240)
                    # Keep the slot through upstream completion even if the
                    # frozen240s client has already disconnected.
                    try:
                        result=json.loads(payload);record['upstream_inference_id']=result.get('inference_id');record['actual_usage']=result.get('usage')
                    except (ValueError,AttributeError):pass
                    self.send(status,payload)
                except Exception as exc:
                    record.update(status='FORWARD_FAILED_RAW_UPSTREAM_RETAINED',error=type(exc).__name__+': '+str(exc),wall_seconds=time.monotonic()-began)
                    self.send(502,json.dumps({'error':record['error']}).encode())
                finally:
                    with lock:
                        active-=1;state['events'].append(record);save()
                    slots.release()
        return Handler
    servers=[ThreadingHTTPServer(('127.0.0.1',port),handler(target)) for port,target in [(8125,8115),(8126,8116)]]
    for server in servers:server.timeout=.5
    def serve(server):
        while not stopping.is_set():server.handle_request()
        server.server_close()
    save();threads=[threading.Thread(target=serve,args=(s,)) for s in servers]
    for thread in threads:thread.start()
    for thread in threads:thread.join()
    with lock:state['status']='STOPPED';save()


if __name__=='__main__':main()
