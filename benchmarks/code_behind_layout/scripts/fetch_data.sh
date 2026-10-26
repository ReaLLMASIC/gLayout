#!/bin/bash
# Download and unpack the frozen task packets and the E4 training set into this directory.
set -euo pipefail
cd "$(dirname "$0")/.."
URL="${CBL_DATA_URL:-https://github.com/DonaldLucy/gLayout/releases/download/cbl-data-v1/cbl-data-v1.tar.gz}"
curl -fL "$URL" | tar -xz
echo "Unpacked runtime/protocol_freezes, runtime/e4_validation_* and data/training/e4_textbook_v1"
