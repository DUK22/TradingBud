#!/usr/bin/env bash
# ==== IR Traders - inicializador (macOS/Linux) ====
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
python -m pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
python seed.py
( sleep 2; (open http://127.0.0.1:5000 2>/dev/null || xdg-open http://127.0.0.1:5000 2>/dev/null) ) &
python run.py
