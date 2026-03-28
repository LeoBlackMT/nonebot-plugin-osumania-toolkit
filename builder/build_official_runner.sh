#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REFS_ROOT="${SCRIPT_DIR}/etterna-master"
MINACALC_DIR="${REFS_ROOT}/src/Etterna/MinaCalc"
ETTERNA_DIR="${REFS_ROOT}/src/Etterna"

if [[ ! -f "${MINACALC_DIR}/MinaCalc.cpp" ]]; then
  echo "[ERROR] MinaCalc source not found: ${MINACALC_DIR}/MinaCalc.cpp" >&2
  exit 1
fi

if ! command -v g++ >/dev/null 2>&1; then
  echo "[ERROR] g++ not found. Please install build-essential (or equivalent)." >&2
  exit 1
fi

g++ -std=c++20 -O2 -DSTANDALONE_CALC \
  -I "${MINACALC_DIR}" \
  -I "${ETTERNA_DIR}" \
  "${SCRIPT_DIR}/official_minacalc_runner.cpp" \
  "${MINACALC_DIR}/MinaCalc.cpp" \
  -o "${SCRIPT_DIR}/official_minacalc_runner"

chmod +x "${SCRIPT_DIR}/official_minacalc_runner"
echo "[OK] Built ${SCRIPT_DIR}/official_minacalc_runner"
