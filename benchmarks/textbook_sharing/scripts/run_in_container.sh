#!/bin/bash
# Run a command inside the pinned IIC-OSIC-TOOLS image (EDA tools and PDKs), with this repository mounted at the same
# absolute path and the Python environment created by scripts/setup_env.sh.
# usage: scripts/run_in_container.sh "<shell command>"        (the command starts in benchmarks/textbook_sharing)
set -e
HERE=$(cd "$(dirname "$0")/.." && pwd)                       # benchmarks/textbook_sharing
REPO=$(cd "$HERE/../.." && pwd)                              # repository root (provides src/glayout)
ENV=${TSB_ENV:-$HERE/.env}
IMAGE=${TSB_IMAGE:-hpretl/iic-osic-tools@sha256:7ef29be71a33b5b8994cde7f7476dfefd1af94f2922354242d1579346feec462}
MOUNTS=(-v "$REPO:$REPO")
for d in "${TSB_RUNS:-}" "${TSB_RESULTS:-}" "${TSB_ENV:-}"; do
  if [ -n "$d" ]; then mkdir -p "$d"; MOUNTS+=(-v "$d:$d"); fi
done
exec docker run --rm -u "$(id -u):$(id -g)" "${MOUNTS[@]}" -w "$HERE" \
  -e HOME="$ENV/home" -e PDK_ROOT=/foss/pdks \
  -e PATH="$ENV/py311/bin:/foss/tools/bin:/foss/tools/klayout:/usr/local/bin:/usr/bin:/bin" \
  -e PYTHONPATH="$REPO/src:$HERE" -e GLAYOUT_BACKEND=gdsfactory -e TSB_RUNS -e TSB_RESULTS \
  -e PYTHONDONTWRITEBYTECODE=1 -e MPLCONFIGDIR="$ENV/home/mpl" -e OMP_NUM_THREADS=1 -e OPENBLAS_NUM_THREADS=1 \
  -e TZ=UTC -e LC_ALL=C.UTF-8 -e LANG=C.UTF-8 --entrypoint /bin/bash "$IMAGE" -c "$*"
