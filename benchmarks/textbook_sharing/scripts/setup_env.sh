#!/bin/bash
# Create the pinned Python 3.11 environment used by every step (micromamba + pip, versions from requirements-lock.txt)
# under benchmarks/textbook_sharing/.env (or $TSB_ENV).  Run once on a Linux x86-64 host with network access.
set -e
HERE=$(cd "$(dirname "$0")/.." && pwd)
ENV=${TSB_ENV:-$HERE/.env}
mkdir -p "$ENV/home"
if [ ! -x "$ENV/bin/micromamba" ]; then
  curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/2.9.0 | tar -xj -C "$ENV" bin/micromamba
fi
[ -x "$ENV/py311/bin/python" ] || "$ENV/bin/micromamba" create -y -p "$ENV/py311" -c conda-forge python=3.11.17 pip
"$ENV/py311/bin/python" -m pip install --no-deps -r "$HERE/requirements-lock.txt"
# ngspice: one thread per simulation (parallelism comes from running many simulations at once)
printf 'set num_threads=1\n' > "$ENV/home/.spiceinit"
echo "environment ready in $ENV"
