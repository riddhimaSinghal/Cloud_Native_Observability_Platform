#!/usr/bin/env bash
# Run the whole project locally with simulated data:  ./scripts/run_local.sh
set -e
cd "$(dirname "$0")/../backend"
[ -d venv ] || python3 -m venv venv
source venv/bin/activate
pip install -q -r requirements.txt
echo "Dashboard + API: http://localhost:8000   (API key for demo controls: demo-key)"
uvicorn app.main:app --port 8000
