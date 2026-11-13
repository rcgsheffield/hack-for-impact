#!/usr/bin/env bash
# Deploy the current checkout on the DGX Spark. Run by the self-hosted
# GitHub Actions runner (see .github/workflows/deploy.yml) or by hand.
set -euo pipefail

DEPLOY_DIR="${DEPLOY_DIR:-$HOME/hack-for-impact}"
SHA="${GITHUB_SHA:-$(git rev-parse HEAD)}"

mkdir -p "$DEPLOY_DIR"
# Copy code to a stable path; keep the Spark's local data/ untouched.
rsync -a --delete --exclude .git --exclude data/ ./ "$DEPLOY_DIR/"
cd "$DEPLOY_DIR"

# TODO: start/restart the app once the stack is chosen, e.g.
#   docker compose up -d --build

echo "Deployed ${SHA:0:7} to $DEPLOY_DIR"
