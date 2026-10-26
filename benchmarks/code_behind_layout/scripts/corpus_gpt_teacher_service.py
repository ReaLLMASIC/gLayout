"""Local authenticated GPT full-source teacher; no credentials leave this host."""
import argparse
from datetime import datetime,timezone
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.local_model_adapter import SOURCE_PROPOSAL_SCHEMA,source_proposal_prompt,validate_source_proposal

DISABLED=['shell_tool','unified_exec','apps','plugins','memories','multi_agent','multi_agent_v2',
 'computer_use','browser_use','browser_use_external','image_generation','view_image','hooks',
 'workspace_dependencies','tool_suggest','in_app_browser','in_app_chat','in_app_local_automation',
 'code_mode','code_mode_host','skill_search']


def save(path,value):Path(path).write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n')


def command(executable,work,model):
    argv=[executable,'exec','--ignore-user-config','--ephemeral','--skip-git-repo-check',
      '--sandbox','read-only','--json','--color','never','--model',model,'-C',str(work),
      '-c','approval_policy="never"','-c','web_search="disabled"','-c','model_reasoning_effort="high"',
      '-c','model_reasoning_summary="none"','-c','show_raw_agent_reasoning=false',
      '-c','project_doc_max_bytes=0','-c','mcp_servers={}',
      '-c','skills.bundled.enabled=false','-c','skills.include_instructions=false']
    for feature in DISABLED:argv.extend(['--disable',feature])
    return argv+['--output-schema',str(work/'source_schema.json'),'--output-last-message',str(work/'proposal.json'),'-']


def serve(args):
    manifest=json.loads(args.manifest.read_text());sampling=manifest['sampling']
    if (manifest.get('status')!='frozen' or manifest.get('role')!='train_collection' or
        sampling.get('backend')!='isolated_gpt_cli' or sampling.get('model')!='gpt-6.1-sol' or
        sampling.get('reasoning_effort')!='high' or sampling.get('timeout_seconds')!=240 or
        sampling.get('max_new_tokens')!=3072 or sampling.get('max_context_tokens')!=8192):
        raise ValueError('Service requires the explicit frozen isolated-GPT teacher contract')
    executable=shutil.which(os.environ.get('GPT_CLI', 'gpt-cli'))
    if not executable:raise ValueError('The existing local authenticated GPT CLI is unavailable')
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    shutil.copyfile(__file__,out/'broker_snapshot.py')
    version=subprocess.check_output([executable,'--version'],text=True).strip()
    metadata={'status':'READY','pid':__import__('os').getpid(),'backend':'isolated_gpt_cli','model':sampling['model'],
        'reasoning_effort':'high','source_role':'isolated_GPT_formal_train_source_teacher','max_new_tokens':3072,
        'max_context_tokens':8192,'timeout_seconds':240,'maximum_concurrent_requests':2,'seed_control_available':False,
        'cli_version':version,'native_tools_enabled':False,'started_at_utc':datetime.now(timezone.utc).isoformat(),
        'output':str(out),'collection_manifest':str(args.manifest.resolve()),'completed_requests':0,'failed_requests':0}
    save(out/'service.json',metadata);save(out/'collection_manifest.json',manifest)
    semaphore=threading.BoundedSemaphore(2);lock=threading.Lock();stopped=False
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
            if not semaphore.acquire(blocking=False):self.respond(429,{'error':'Both declared GPT teacher slots are occupied; no inference was issued'});return
            identifier=str(uuid.uuid4());work=out/'sessions'/identifier;work.mkdir(parents=True)
            started=time.monotonic();invocation={'inference_id':identifier,'started_at_utc':datetime.now(timezone.utc).isoformat(),'status':'RUNNING','backend':'isolated_gpt_cli','requested_model':sampling['model'],'seed':None}
            response={'inference_id':identifier}
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=1024*1024:raise ValueError('Unexpected teacher packet size')
                body=json.loads(self.rfile.read(length))
                if set(body)!={'mode','trial_id','request'} or body['mode']!='train_collection_source_gpt' or body['trial_id'] not in range(1,9):raise ValueError('Only eight declared source-teacher trials are accepted')
                prompt=source_proposal_prompt(body['request']);save(work/'request.json',body);(work/'prompt.txt').write_text(prompt)
                save(work/'source_schema.json',SOURCE_PROPOSAL_SCHEMA);argv=command(executable,work,sampling['model'])
                invocation.update(argv=argv,trial_id=body['trial_id'],timeout_seconds=240);save(work/'invocation.json',invocation)
                with (work/'events.jsonl').open('w') as events,(work/'stderr.log').open('w') as errors:
                    process=subprocess.Popen(argv,stdin=subprocess.PIPE,text=True,stdout=events,stderr=errors)
                    invocation['pid']=process.pid;save(work/'invocation.json',invocation)
                    try:process.communicate(prompt,timeout=max(.1,240-(time.monotonic()-started)))
                    except subprocess.TimeoutExpired:
                        process.kill();process.communicate();invocation['status']='TIMEOUT'
                    invocation['returncode']=process.returncode
                usage=[];tool_events=[];event_types=[]
                for line in (work/'events.jsonl').read_text().splitlines():
                    try:event=json.loads(line)
                    except json.JSONDecodeError:continue
                    if event.get('usage'):usage.append(event['usage'])
                    item=event.get('item',{});kind=item.get('type');event_types.append(kind or event.get('type'))
                    if kind in ['command_execution','file_change','mcp_tool_call','web_search','tool_call']:
                        tool_events.append({'event_type':event.get('type'),'item_type':kind})
                public=usage[-1] if usage else None
                measured={'public_cli_usage':public,'all_public_usage_events':usage,'request_mode':'train_collection_source_gpt',
                    'output_format':'complete_module_source','server_wall_seconds':time.monotonic()-started,
                    'max_new_tokens':3072,'maximum_context_tokens':8192,'sampling_seed':None,
                    'output_budget_scope':'Qwen-token budget enforced on exact returned source by the collector; provider reasoning/compute is preserved separately in public CLI usage'}
                identity={'variant':'GPT_teacher','base_model':sampling['model'],'requested_model':sampling['model'],
                    'source_role':'isolated_GPT_formal_train_source_teacher','model_identity_scope':'Requested catalog slug; provider checkpoint and decoding seed are not exposed',
                    'cli_version':version,'settings':{'reasoning_effort':'high','max_new_tokens':3072,'maximum_context_tokens':8192,'sampling_seed':None}}
                response.update(usage=measured,model=identity,native_tools=tool_events)
                if invocation['status']=='TIMEOUT' or time.monotonic()-started>240:raise TimeoutError('Declared teacher request wall budget expired; no proposal accepted')
                if process.returncode:raise RuntimeError('Isolated GPT CLI failed; raw stderr/events retained')
                if tool_events:raise ValueError('Teacher used a native tool outside its declared interface')
                proposal=validate_source_proposal(json.loads((work/'proposal.json').read_text()))
                response['proposal']=proposal;invocation.update(status='COMPLETED',event_types=event_types)
                self.respond(200,response)
                with lock:metadata['completed_requests']+=1
            except Exception as exc:
                response['error']=type(exc).__name__+': '+str(exc);invocation['status']='TIMEOUT' if invocation['status']=='TIMEOUT' else 'FAILED'
                with lock:metadata['failed_requests']+=1
                try:self.respond(422,response)
                except (BrokenPipeError,ConnectionResetError):pass
            finally:
                invocation.update(ended_at_utc=datetime.now(timezone.utc).isoformat(),wall_seconds=time.monotonic()-started,response=response)
                save(work/'invocation.json',invocation)
                with lock:save(out/'service.json',metadata)
                semaphore.release()
    server=ThreadingHTTPServer(('127.0.0.1',8115),Handler);server.timeout=.5
    print(json.dumps(metadata),flush=True)
    while not stopped:server.handle_request()
    server.server_close();metadata.update(status='STOPPED',stopped_at_utc=datetime.now(timezone.utc).isoformat());save(out/'service.json',metadata)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',type=Path,required=True);p.add_argument('--output',type=Path,required=True);serve(p.parse_args())
