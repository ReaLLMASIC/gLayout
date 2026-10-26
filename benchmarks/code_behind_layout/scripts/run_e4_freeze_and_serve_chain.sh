#!/bin/bash
# Server-side: once the plan-v2 T3/T4 selections finish, assemble the E4 methods draft, validate and write the
# read-only methods freeze, validate it for serving, and start the frozen 8117 policy service. Stops at the first failure.
# Usage: run_e4_freeze_and_serve_chain.sh <dpo_selection_chain_log>
set -u
cd "$(dirname "$0")/.."
CHAINLOG="$1"; PY=runtime/training-venv/bin/python; export PYTHONPYCACHEPREFIX="$PWD/runtime/training-pycache"
DATA=data/training/e4_textbook_v1; PLAN=runtime/e4_validation_preparation/e4_textbook_v1_validation_plan_v2.json
VROOT=runs/e4_validation_v2/e4_textbook_v1; OUT=runtime/protocol_freezes/E4_primary
log() { echo "$(date -u +%FT%TZ) $*"; }
ready() { $PY scripts/serve_frozen_policy.py --health 2>/dev/null | python3 -c "import json,sys; sys.exit(json.loads(sys.stdin.read()).get('status')!='READY')" 2>/dev/null; }
until grep -q "v2 DPO selection chain finished\|chain stops" "$CHAINLOG"; do sleep 60; done
grep -q "v2 DPO selection chain finished" "$CHAINLOG" || { log "STOP: DPO selection chain stopped; nothing frozen"; exit 1; }
for m in T1 T2 T3 T4; do for s in 41 73 109; do
  python3 -c "import json,sys; sys.exit(json.load(open(sys.argv[1])).get('status')!='COMPLETED_E4_VALIDATION_CHECKPOINT_SELECTION')" $VROOT/$m/seed-$s/selection.json \
    || { log "STOP: $m seed $s selection incomplete"; exit 1; }
done; done
[ -e $OUT/manifest.json ] && { log "STOP: a methods freeze already exists"; exit 1; }
log "12 selections complete; assembling the methods draft"; mkdir -p $OUT
$PY scripts/assemble_e4_methods_draft.py --data $DATA --plan $PLAN --validation-root $VROOT --checkpoint-root checkpoints/e4_textbook_v1 --output $OUT/draft.json || { log "STOP: draft assembly failed"; exit 1; }
$PY scripts/freeze_e4_methods.py --draft $OUT/draft.json --output $OUT/manifest.json --validate-only || { log "STOP: freeze validation failed"; exit 1; }
$PY scripts/freeze_e4_methods.py --draft $OUT/draft.json --output $OUT/manifest.json || { log "STOP: freeze write failed"; exit 1; }
log "methods freeze written, sha256 $(sha256sum $OUT/manifest.json | cut -d' ' -f1)"
$PY scripts/serve_frozen_policy.py --validate-only --methods $OUT/manifest.json || { log "STOP: service validation failed"; exit 1; }
ready && { log "STOP: something already answers on 8117"; exit 1; }
SVC=runtime/e4_frozen_service/$(date -u +%Y%m%dT%H%M%SZ)
CUDA_VISIBLE_DEVICES=0 nohup $PY scripts/serve_frozen_policy.py --serve --methods $OUT/manifest.json --output $SVC > logs/e4_frozen_service_e4_textbook_v1.log 2>&1 < /dev/null &
log "8117 service starting, pid $!, output $SVC"
for i in $(seq 1 90); do ready && { log "8117 READY"; exit 0; }; sleep 10; done
log "STOP: 8117 not READY after 15 min"; exit 1
