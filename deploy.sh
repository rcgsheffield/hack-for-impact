#!/usr/bin/env bash
# Deploy the current checkout on the DGX Spark. Run by the self-hosted
# GitHub Actions runner (see .github/workflows/deploy.yml) or by hand.
#
# Runs the app as a plain background process: the runner has no user D-Bus session,
# so `systemctl --user` fails ("Failed to connect to bus"), and no sudo.
# It won't restart after a reboot; rerun the deploy workflow if the Spark restarts.
set -euo pipefail

DEPLOY_DIR="${DEPLOY_DIR:-$HOME/hack-for-impact}"
SHA="${GITHUB_SHA:-$(git rev-parse HEAD)}"
# Kept outside DEPLOY_DIR so rsync --delete doesn't wipe it.
STATE_DIR="${STATE_DIR:-$HOME/.local/share/hack-for-impact}"
PIDFILE="$STATE_DIR/app.pid"
LOG="${APP_LOG:-$HOME/hack-for-impact.log}"
PORT="${PORT:-8000}"
HEALTH_TIMEOUT=15   # Seconds to wait for /health.

mkdir -p "$DEPLOY_DIR" "$STATE_DIR"
# Copy code to a stable path; keep the Spark's local data/ untouched.
rsync -a --delete --exclude .git --exclude data/ ./ "$DEPLOY_DIR/"
cd "$DEPLOY_DIR"

# Stop the previous version.
if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  old_pid="$(cat "$PIDFILE")"
  echo "Stopping previous app (pid $old_pid)"
  kill "$old_pid"
  for _ in $(seq 10); do kill -0 "$old_pid" 2>/dev/null || break; sleep 1; done
  kill -9 "$old_pid" 2>/dev/null || true
fi

# Start the new one. An empty RUNNER_TRACKING_ID and a new session stop GitHub Actions
# from killing the process when this job finishes.
echo "=== Deploy ${SHA:0:7} at $(date -Is) ===" >>"$LOG"
GIT_SHA="${SHA:0:7}" PORT="$PORT" RUNNER_TRACKING_ID="" \
  setsid nohup python3 src/app/server.py >>"$LOG" 2>&1 </dev/null &
echo $! >"$PIDFILE"

# Fail the deploy unless the app comes up healthy.
# Check our process is alive first, so a stray process holding the port can't pass the check.
for _ in $(seq "$HEALTH_TIMEOUT"); do
  if ! kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then break; fi
  if curl -fsS --max-time 3 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    echo "Deployed ${SHA:0:7} to $DEPLOY_DIR (app healthy, port $PORT)"
    exit 0
  fi
  sleep 1
done
echo "ERROR: app not healthy after deploy. Last lines of $LOG:" >&2
tail -n 50 "$LOG" >&2
exit 1
