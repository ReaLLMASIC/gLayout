#!/bin/bash
# Server-side: once the formal SFT stage has finished, run every GPU-serial post-SFT stage without idle gaps:
#   T1 checkpoint validation/selection (3 seeds) -> DPO training (T3/T4 x 3 seeds, from the selected T1 adapters)
#   -> T2 selections -> T3/T4 selections. Each stage is the existing launcher; the chain only sequences and checks them.
# Usage: run_e4_post_sft_chain.sh <data_dir e.g. data/training/e4_textbook_v1> <frozen_validation_plan.json>
set -u
cd "$(dirname "$0")/.."
DATA="$1"; PLAN="$2"; FREEZE=$(basename "$DATA")
log() { echo "$(date -u +%FT%TZ) $*"; }
run_status() { python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('status'))" "checkpoints/$FREEZE/$1/seed-$2/run.json" 2>/dev/null; }
sel_status() { python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('status'))" "runs/e4_validation/$FREEZE/$1/seed-$2/selection.json" 2>/dev/null; }
wait_gpu() { for i in $(seq 1 60); do FREE=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1); [ "$FREE" -ge 66560 ] && return 0; sleep 10; done; log "GPU not free ($FREE MiB)"; return 1; }
until grep -q "SFT stage finished" logs/e4_sft_${FREEZE}.log 2>/dev/null; do sleep 120; done
log "SFT stage finished; checking the six runs"
for m in T1 T2; do for s in 41 73 109; do
  st=$(run_status $m $s); [ "$st" = "TRAINING_COMPLETED_NOT_SELECTED" ] || { log "$m seed $s status '$st'; chain stops"; exit 1; }
done; done
for s in 41 73 109; do
  log "T1 seed $s selection"; wait_gpu || exit 1
  bash scripts/run_e4_validation_selection.sh $DATA $PLAN T1 $s >> logs/e4_selection_${FREEZE}_T1_seed$s.log 2>&1
  st=$(sel_status T1 $s); log "T1 seed $s selection status '$st'"; [ "$st" = "COMPLETED_E4_VALIDATION_CHECKPOINT_SELECTION" ] || { log "chain stops"; exit 1; }
done
log "DPO stage"; wait_gpu || exit 1
bash scripts/run_e4_dpo_training.sh $DATA runs/e4_validation/$FREEZE/T1 >> logs/e4_dpo_${FREEZE}.log 2>&1
for m in T3 T4; do for s in 41 73 109; do
  st=$(run_status $m $s); [ "$st" = "TRAINING_COMPLETED_NOT_SELECTED" ] || { log "$m seed $s status '$st'; chain stops"; exit 1; }
done; done
for m in T2 T3 T4; do for s in 41 73 109; do
  log "$m seed $s selection"; wait_gpu || exit 1
  bash scripts/run_e4_validation_selection.sh $DATA $PLAN $m $s >> logs/e4_selection_${FREEZE}_${m}_seed$s.log 2>&1
  st=$(sel_status $m $s); log "$m seed $s selection status '$st'"; [ "$st" = "COMPLETED_E4_VALIDATION_CHECKPOINT_SELECTION" ] || { log "chain stops"; exit 1; }
done; done
log "post-SFT chain finished: 12 runs trained and selected"
