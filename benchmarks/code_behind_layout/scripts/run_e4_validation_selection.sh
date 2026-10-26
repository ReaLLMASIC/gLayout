#!/bin/bash
# Server-side: validate every saved checkpoint of one completed formal training run on the frozen validation plan and select.
# For each checkpoint: start scripts/serve_checkpoint_policy.py on the GPU (port fixed by the service), wait for READY,
# run scripts/e4_checkpoint_validation.py run (editing session + search points + nine final points), stop the service.
# Then select over all editing ledgers. The 8114 service must already be stopped (GPU free).
# Usage: run_e4_validation_selection.sh <data_dir> <frozen_plan.json> <method> <seed> [validation_root=runs/e4_validation]
set -u
cd "$(dirname "$0")/.."
DATA="$1"; PLAN="$2"; M="$3"; S="$4"; VALROOT="${5:-runs/e4_validation}"; FREEZE=$(basename "$DATA"); PY=runtime/training-venv/bin/python
export PYTHONPYCACHEPREFIX="$PWD/runtime/training-pycache"
RUN=checkpoints/$FREEZE/$M/seed-$S; MANIFEST=$DATA/training_manifest.json
# T3/T4 were trained from the DPO manifest, which records the selected T1 starting checkpoints
case "$M" in T3|T4) MANIFEST=$DATA/training_manifest_dpo.json;; esac
VAL=$VALROOT/$FREEZE/$M/seed-$S; mkdir -p $VAL
ENTRY=$VAL/entry.json
python3 - "$M" "$S" "$RUN" "$MANIFEST" "$ENTRY" <<'PY'
import json,sys,os
m,s,run,manifest,entry=sys.argv[1:]
json.dump({'method':m,'seed':int(s),'run_directory':os.path.abspath(run),'training_manifest':os.path.abspath(manifest)},open(entry,'w'),indent=1)
PY
LEDGERS=""
for CK in $(ls -d $RUN/checkpoint-* | sort); do
  NAME=$(basename $CK); OUT=$VAL/$NAME
  if [ -f $OUT/editing_ledger.json ]; then echo "$(date -u +%FT%TZ) $NAME already validated"; LEDGERS="$LEDGERS --editing-ledger $OUT/editing_ledger.json"; continue; fi
  SHA=$(sha256sum $CK/adapter/policy/adapter_model.safetensors | cut -d" " -f1)
  SVC=$VAL/${NAME}_service; rm -rf $SVC
  CUDA_VISIBLE_DEVICES=0 nohup $PY scripts/serve_checkpoint_policy.py --serve --validation-plan $PLAN --run-directory $RUN --training-manifest $MANIFEST --checkpoint $CK --method $M --training-seed $S --adapter-sha256 $SHA --output $SVC > logs/validation_service_${FREEZE}_${M}_${S}_${NAME}.log 2>&1 &
  SVCPID=$!
  for i in $(seq 1 180); do
    if $PY scripts/serve_checkpoint_policy.py --health 2>/dev/null | grep -q '"status": "READY"'; then break; fi
    kill -0 $SVCPID 2>/dev/null || { echo "$(date -u +%FT%TZ) service exited early for $NAME"; break; }
    sleep 10
  done
  if ! $PY scripts/serve_checkpoint_policy.py --health 2>/dev/null | grep -q '"status": "READY"'; then echo "$(date -u +%FT%TZ) service not READY for $NAME; stopping"; kill -TERM $SVCPID 2>/dev/null; exit 1; fi
  echo "$(date -u +%FT%TZ) validating $NAME"
  $PY scripts/e4_checkpoint_validation.py run --plan $PLAN --entry $ENTRY --checkpoint $CK --output $OUT > logs/validation_run_${FREEZE}_${M}_${S}_${NAME}.log 2>&1
  echo "$(date -u +%FT%TZ) $NAME run exit $?"
  kill -TERM $SVCPID 2>/dev/null; sleep 15
  [ -f $OUT/editing_ledger.json ] && LEDGERS="$LEDGERS --editing-ledger $OUT/editing_ledger.json"
done
$PY scripts/e4_checkpoint_validation.py select --plan $PLAN --entry $ENTRY $LEDGERS --output $VAL/selection.json 2>&1 | tail -5
echo "$(date -u +%FT%TZ) selection written to $VAL/selection.json"
