#!/usr/bin/env bash
# Build the dashboard and create cad-monitor.zip for upload to S3:  ./scripts/package.sh
set -e
cd "$(dirname "$0")/.."
(cd frontend && npm install && npm run build)
rm -f cad-monitor.zip
zip -r cad-monitor.zip backend frontend/dist \
  -x "*/__pycache__/*" "*/.pytest_cache/*" "backend/venv/*" "backend/.env" "*.pyc"
echo "Created cad-monitor.zip"
