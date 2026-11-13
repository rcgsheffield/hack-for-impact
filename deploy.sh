#!/usr/bin/env bash
# Deploy the current checkout on the DGX Spark. Run by the self-hosted
# GitHub Actions runner (see .github/workflows/deploy.yml) or by hand.
#
# Runs the app (src/app) as a plain background process: the runner has no user D-Bus session,
# so `systemctl --user` fails ("Failed to connect to bus"), and it has no Docker and no sudo.
# The app won't restart after a reboot; rerun the deploy workflow if the Spark restarts.
set -euo pipefail

DEPLOY_DIR="${DEPLOY_DIR:-$HOME/hack-for-impact}"
SHA="${GITHUB_SHA:-$(git rev-parse HEAD)}"
# Kept outside DEPLOY_DIR so rsync --delete doesn't wipe the venv on every deploy.
STATE_DIR="${STATE_DIR:-$HOME/.local/share/hack-for-impact}"
VENV="$STATE_DIR/venv"
PIDFILE="$STATE_DIR/app.pid"
LOG="${APP_LOG:-$HOME/hack-for-impact.log}"
HOST="${HOST:-0.0.0.0}"    # Reachable from the venue network, so the team can demo it.
PORT="${PORT:-8000}"
UV_VERSION="0.9.5"         # Pinned uv installer, used only if uv isn't already installed.
HEALTH_TIMEOUT=60          # Seconds to wait for /health. Gradio's first import is slow.

mkdir -p "$DEPLOY_DIR" "$STATE_DIR"
# Copy code to a stable path; keep the Spark's local data/ (and filed reports) untouched.
rsync -a --delete --exclude .git --exclude data/ ./ "$DEPLOY_DIR/"
cd "$DEPLOY_DIR"
mkdir -p data

# Python environment from pyproject.toml + uv.lock. uv needs no sudo or python3-venv,
# and fetches Python 3.12 (.python-version) if the host lacks it.
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null; then
  echo "Installing uv $UV_VERSION into ~/.local/bin"
  curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" | env UV_NO_MODIFY_PATH=1 sh
fi
UV_PROJECT_ENVIRONMENT="$VENV" uv sync --frozen --no-dev --no-install-project --quiet

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
GIT_SHA="${SHA:0:7}" RUNNER_TRACKING_ID="" \
  setsid nohup "$VENV/bin/uvicorn" app.main:app --app-dir src --host "$HOST" --port "$PORT" \
  >>"$LOG" 2>&1 </dev/null &
echo $! >"$PIDFILE"

# Fail the deploy unless the app comes up healthy (which includes Ollama being reachable).
# Check our process is alive first, so a stray process holding the port can't pass the check.
for _ in $(seq "$HEALTH_TIMEOUT"); do
  if ! kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then break; fi
  if health="$(curl -fsS --max-time 3 "http://127.0.0.1:$PORT/health" 2>/dev/null)"; then
    echo "App healthy: $health"
    echo "Deployed ${SHA:0:7} to $DEPLOY_DIR (port $PORT)"
    exit 0
  fi
  sleep 1
done

echo "ERROR: app not healthy after deploy. Last lines of $LOG:" >&2
tail -n 50 "$LOG" >&2
curl -sS --max-time 3 "http://127.0.0.1:$PORT/health" >&2 || true
exit 1
