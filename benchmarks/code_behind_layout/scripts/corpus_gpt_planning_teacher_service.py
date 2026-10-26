"""Independent16k ordinary-ACTION GPT teacher using the existing isolated policy adapter."""
import argparse
import copy
from datetime import datetime,timezone
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import signal
import sys
import threading
import time


def save(path,value):Path(path).write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n')


def serve(args):
    manifest=json.loads(args.manifest.read_text());sampling=manifest['sampling']
    if (manifest.get('status')!='frozen' or manifest.get('role')!='train_collection' or
        manifest.get('teacher_interface_version')!='ordinary_action_teacher_context_v2' or
        sampling.get('mode')!='train_collection_action_gpt' or sampling.get('backend')!='isolated_gpt_cli' or
        sampling.get('model')!='gpt-6.1-sol' or sampling.get('reasoning_effort')!='high' or
        sampling.get('timeout_seconds')!=240 or sampling.get('max_new_tokens')!=1024 or sampling.get('max_context_tokens')!=16384 or
        sampling.get('trials')!=list(range(1,9)) or sampling.get('seed') is not None):
        raise ValueError('An independently frozen eight-proposal ordinary ACTION teacher is required')
    interface=args.manifest.parent/'interface';identity=json.loads((args.manifest.parent/'freeze_identity.json').read_text())
    for name in ['broker.py','src/__init__.py','src/model_adapter.py','src/local_model_adapter.py','src/policy_state.py','action_schema.json']:
        relative='interface/'+name
        if hashlib.sha256((interface/name).read_bytes()).hexdigest()!=identity.get(relative):raise ValueError('Frozen teacher interface differs: '+name)
    if Path(__file__).read_bytes()!=(interface/'broker.py').read_bytes():raise ValueError('Launch the exact frozen broker source')
    sys.path.insert(0,str(interface))
    from src.model_adapter import ACTION_SCHEMA,GptDecisionAdapter
    if ACTION_SCHEMA!=json.loads((interface/'action_schema.json').read_text()):raise ValueError('Frozen schema differs from its adapter')
    from transformers import AutoTokenizer
    tokenizer=AutoTokenizer.from_pretrained(str(args.tokenizer),local_files_only=True,trust_remote_code=False)
    if tokenizer.eos_token_id!=151645:raise ValueError('Unexpected shared policy tokenizer EOS')
    executable=shutil.which(os.environ.get('GPT_CLI', 'gpt-cli'))
    if not executable:raise ValueError('Existing authenticated local GPT CLI is unavailable')
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    shutil.copyfile(__file__,out/'broker_snapshot.py');save(out/'collection_manifest.json',manifest)
    import os,subprocess
    version=subprocess.check_output([executable,'--version'],text=True).strip()
    config={'model':sampling['model'],'reasoning_effort':'high','timeout_seconds_per_decision':240,
            'max_context_tokens':16384,'max_new_tokens':1024}
    adapter=GptDecisionAdapter(out/'sessions',executable=executable,tokenizer=tokenizer)
    metadata={'status':'INITIALIZED_NOT_LISTENING','pid':os.getpid(),'backend':'isolated_gpt_cli','model':sampling['model'],
        'reasoning_effort':'high','teacher_interface_version':'ordinary_action_teacher_context_v2',
        'source_role':'isolated_GPT_formal_train_action_teacher','max_new_tokens':1024,'max_context_tokens':16384,
        'timeout_seconds':240,'maximum_concurrent_requests':2,'native_tools_enabled':False,'seed_control_available':False,
        'cli_version':version,'tokenizer':str(args.tokenizer.resolve()),'tokenizer_revision':manifest['budget_tokenizer_revision'],
        'started_at_utc':datetime.now(timezone.utc).isoformat(),'output':str(out),'completed_requests':0,'failed_requests':0,
        'queue_constraint':'Shared transport retains the global two inference slots across old8k and new16k teachers; no extra slots'}
    save(out/'service.json',metadata);semaphore=threading.BoundedSemaphore(2);lock=threading.Lock();stopped=False
    def stop(*unused):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*unused):pass
        def respond(self,status,value):
            payload=json.dumps(value).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        def do_GET(self):
            if self.path!='/health':self.respond(404,{'error':'unknown endpoint'});return
            self.respond(200,metadata)
        def do_POST(self):
            if self.path!='/decision':self.respond(404,{'error':'unknown endpoint'});return
            if not semaphore.acquire(blocking=False):self.respond(429,{'error':'Both declared teacher slots occupied; no inference issued'});return
            began=time.monotonic();session=None;response={};accepted=False
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=1024*1024:raise ValueError('Unexpected packet size')
                body=json.loads(self.rfile.read(length))
                if set(body)!={'mode','trial_id','request'} or body['mode']!='train_collection_action_gpt' or body['trial_id'] not in range(1,9):raise ValueError('Only declared ACTION teacher trials are accepted')
                request=body['request'];history=copy.deepcopy(request['visible_history'])
                if not history or set(history[-1])!={'observation'}:raise ValueError('Teacher needs its exact visible baseline feedback')
                session=adapter.start(copy.deepcopy(request['task_packet']),copy.deepcopy(config));work=Path(session['output'])
                save(work/'teacher_request.json',body);session['history']=history[:-1]
                action=adapter.step(session,history[-1]['observation'])
                if time.monotonic()-began>240:raise TimeoutError('Teacher wall budget exceeded; raw output retained, never applied')
                response['action']=action;accepted=True
            except Exception as exc:response['error']=type(exc).__name__+': '+str(exc)
            finally:
                if session is not None:
                    work=Path(session['output']);adapter.finish(session);decision=work/'decision_000'
                    answer=decision/'action.json';budget=decision/'token_budget.json'
                    if answer.exists():response['raw_action_text']=answer.read_text()
                    response.update(inference_id=session['session_id'],native_tools=[],
                        model={'variant':'GPT_teacher','base_model':sampling['model'],'requested_model':sampling['model'],
                            'source_role':'isolated_GPT_formal_train_action_teacher','cli_version':version,
                            'model_identity_scope':'Requested catalog slug; provider checkpoint and sampling seed are unavailable',
                            'settings':{'reasoning_effort':'high','max_new_tokens':1024,'maximum_context_tokens':16384,'sampling_seed':None}},
                        usage={'public_cli_usage':session['usage'][-1] if session['usage'] else None,'all_public_usage_events':session['usage'],
                            'policy_token_budget':json.loads(budget.read_text()) if budget.exists() else None,
                            'request_mode':'train_collection_action_gpt','output_format':'ordinary_action_json',
                            'server_wall_seconds':time.monotonic()-began,'max_new_tokens':1024,'maximum_context_tokens':16384,'sampling_seed':None,
                            'output_budget_scope':'Exact raw ACTION text plus EOS and full single-user prompt use the shared policy tokenizer. Provider reasoning and usage are retained separately.'})
                    save(work/'teacher_invocation.json',{'trial_id':body['trial_id'],'status':'COMPLETED' if accepted else 'FAILED',
                        'ended_at_utc':datetime.now(timezone.utc).isoformat(),'wall_seconds':time.monotonic()-began,'response':response})
                with lock:
                    metadata['completed_requests' if accepted else 'failed_requests']+=1;save(out/'service.json',metadata)
                try:self.respond(200 if accepted else 422,response)
                except (BrokenPipeError,ConnectionResetError):pass
                semaphore.release()
    server=ThreadingHTTPServer(('127.0.0.1',8118),Handler);server.timeout=.5
    metadata.update(status='READY',ready_at_utc=datetime.now(timezone.utc).isoformat());save(out/'service.json',metadata)
    print(json.dumps(metadata),flush=True)
    while not stopped:server.handle_request()
    server.server_close();metadata.update(status='STOPPED',stopped_at_utc=datetime.now(timezone.utc).isoformat());save(out/'service.json',metadata)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--manifest',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--tokenizer',type=Path,required=True);serve(parser.parse_args())
