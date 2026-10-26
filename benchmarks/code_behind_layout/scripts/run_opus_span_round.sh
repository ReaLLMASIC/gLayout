#!/bin/bash
# Workstation-side driver for one Claude literal-span proposal round over frozen multi-state parents on the server:
#   wait until every parent has produced the packets of the selected states -> server: prepare v2 bundle -> copy here ->
#   run the Claude collector -> copy proposals back -> server: prepare/freeze/validate/execute the v2 acceptance (gated).
# Usage: run_opus_span_round.sh <proposal_collection_id> <trials> <acceptance_workers> <origins: natural|injected|natural,injected> <skip_first:0|1> <parent_collection_id>...
set -u
CID="$1"; TRIALS="$2"; WORKERS="$3"; ORIGINS="${4//,/ }"; SKIPFIRST="$5"; shift 5; PARENTS="$*"
KEY=~/.ssh/cbl_server_key; HOST=cbl-server; R=/srv/code-behind-layout
SSH="ssh -i $KEY -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=12 -o ControlPath=/tmp/cbl-ssh-control"
cd "$(dirname "$0")/.."
if [ -f runtime/train_collection_proposals/$CID/collection.json ] && [ ! -f runs/train_proposals/$CID/completion.json ]; then echo "bundle already here; resuming at the collector"; RESUME=1; else RESUME=0; fi
SKIP=""; [ "$SKIPFIRST" = "1" ] && SKIP="--skip-first-state"
if [ "$RESUME" = "0" ]; then
for i in $(seq 1 288); do
  READY=$($SSH $HOST "cd $R && python3 - $PARENTS <<'PY'
import json,sys,os
ok=True
for parent in sys.argv[1:]:
    m=json.load(open('runtime/train_collections/%s/collection.json'%parent))
    states=[json.loads(l) for l in open(m['initial_states_path']) if l.strip()]
    for s in states:
        if not os.path.exists(os.path.join(m['output_root'], s['initial_state_id'], 'task_packet.json')): ok=False
print('READY' if ok else 'WAIT')
PY")
  case "$READY" in *READY*) break;; esac
  sleep 300
done
echo "$(date -u +%FT%TZ) parents ready: $PARENTS"
$SSH $HOST "cd $R && runtime/training-venv/bin/python scripts/prepare_textbook_opus_span_collection_v2.py --parents $PARENTS --origins $ORIGINS $SKIP --trials $TRIALS --proposal-workers 2 --collection-id $CID --hours 12" || { echo "bundle preparation failed"; exit 1; }
mkdir -p runtime/train_collection_proposals
rsync -a -e "$SSH" $HOST:$R/runtime/train_collection_proposals/$CID/ runtime/train_collection_proposals/$CID/ || exit 1
fi
.venv/research-plots/bin/python scripts/collect_textbook_opus_spans.py --collection runtime/train_collection_proposals/$CID/collection.json --execute > logs/collect_$CID.log 2>&1
.venv/research-plots/bin/python -c "import json,collections; c=json.load(open('runs/train_proposals/$CID/completion.json')); print({k:c[k] for k in ('status','planned_proposals','returned_attempts','unique_student_fit_terminal_programs_within_state')}); m=json.load(open('runs/train_proposals/$CID/matrix.json')); print(collections.Counter(r['status'] for r in m))"
rsync -a -e "$SSH" runs/train_proposals/$CID/ $HOST:$R/runs/train_proposals/$CID/ || exit 1
$SSH $HOST "cd $R && runtime/training-venv/bin/python scripts/evaluate_textbook_opus_spans_v2.py --prepare --proposal runtime/train_collection_proposals/$CID/collection.json --folder runtime/collection_preparation/${CID}_acceptance --output-root runs/train_collection/${CID}_physical --workers $WORKERS --hours 36 > /dev/null && runtime/training-venv/bin/python scripts/evaluate_textbook_opus_spans_v2.py --freeze --plan runtime/collection_preparation/${CID}_acceptance/acceptance.json > /dev/null && runtime/training-venv/bin/python scripts/evaluate_textbook_opus_spans_v2.py --validate-only --plan runtime/collection_preparation/${CID}_acceptance/acceptance.json && (nohup runtime/training-venv/bin/python scripts/evaluate_textbook_opus_spans_v2.py --execute --plan runtime/collection_preparation/${CID}_acceptance/acceptance.json > logs/${CID}_physical.log 2>&1 &) && sleep 2 && echo launched"
echo "$(date -u +%FT%TZ) span round $CID dispatched"
