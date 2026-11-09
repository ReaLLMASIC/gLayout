#!/bin/bash
# Record the environment of a run into <results>/environment/: container image digest, EDA tool and PDK versions,
# Python packages and the repository commit.
set -e
HERE=$(cd "$(dirname "$0")/.." && pwd)
O=${TSB_RESULTS:-$HERE/results}/environment; mkdir -p "$O"
IMAGE=${TSB_IMAGE:-hpretl/iic-osic-tools@sha256:7ef29be71a33b5b8994cde7f7476dfefd1af94f2922354242d1579346feec462}
docker image inspect "$IMAGE" --format '{{.Id}} {{index .RepoDigests 0}}' > "$O/container_image.txt"
"$HERE/scripts/run_in_container.sh" "magic --version; netgen -batch quit 2>&1 | head -1; ngspice -v 2>&1 | grep ngspice | head -1; klayout -v; python --version; ls /foss/pdks" > "$O/tools_and_pdks.txt" 2>&1
"$HERE/scripts/run_in_container.sh" "python -m pip freeze" > "$O/python_freeze.txt" 2>/dev/null
git -C "$HERE" rev-parse HEAD > "$O/git_head.txt"
echo "written $O"; ls -la "$O"
