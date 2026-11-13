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

# Run the app as a systemd user service (needs `loginctl enable-linger` once).
# The commit SHA reaches the app through an env file read by the unit.
echo "GIT_SHA=${SHA:0:7}" > .app.env
mkdir -p "$HOME/.config/systemd/user"
cp src/app/hack-app.service "$HOME/.config/systemd/user/hack-app.service"
systemctl --user daemon-reload
systemctl --user enable hack-app >/dev/null 2>&1 || true
systemctl --user restart hack-app

# Fail the deploy unless the app comes up healthy.
for _ in $(seq 15); do
  if curl -fsS --max-time 3 "http://127.0.0.1:${PORT:-8000}/health" >/dev/null; then
    echo "Deployed ${SHA:0:7} to $DEPLOY_DIR (app healthy)"
    exit 0
  fi
  sleep 1
done
echo "ERROR: app not healthy after deploy; see: journalctl --user -u hack-app" >&2
exit 1
