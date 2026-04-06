#!/usr/bin/env bash
set -euo pipefail

if [[ ! -d .venv ]]; then
  echo "Missing .venv. Run ./scripts/setup_venv.sh first."
  exit 1
fi

source .venv/bin/activate
python -m PyInstaller --clean --noconfirm plantuml_previewer.spec
