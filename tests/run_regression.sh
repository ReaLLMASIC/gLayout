#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
export PYTHONWARNINGS="${PYTHONWARNINGS:-ignore}"

python3 -m unittest discover -s "${ROOT_DIR}/tests" -p 'test_*.py'
