#!/usr/bin/env bash
# Check the deployed app. Usage: HOST=spark12.local PORT=8000 src/app/check.sh
set -euo pipefail
curl -fsS --max-time 10 "http://${HOST:-spark12.local}:${PORT:-8000}/health"
echo
