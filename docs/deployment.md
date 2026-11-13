# Deployment (DGX Spark)

Every push to `main` deploys to the DGX Spark through a GitHub Actions [self-hosted runner](https://docs.github.com/en/actions/hosting-your-own-runners) on that machine (`.github/workflows/deploy.yml`). The runner connects out to GitHub, so the Spark needs no inbound access. The workflow runs [`deploy.sh`](../deploy.sh), which syncs the code to `~/hack-for-impact` on the Spark (its local `data/` is kept) and then starts the app. To redeploy without pushing, use **Actions → Deploy to DGX Spark → Run workflow**.

## Runner setup

One-time, done on the Spark over SSH:

1. In GitHub, go to **Settings → Actions → Runners → New self-hosted runner**, choose **Linux / ARM64**, and follow the download steps it shows.
2. Configure the runner with the `spark` label and install it as a service:
   ```bash
   ./config.sh --url https://github.com/rcgsheffield/hack-for-impact --token <TOKEN> --labels spark --unattended
   sudo ./svc.sh install && sudo ./svc.sh start
   ```
3. Make sure `rsync` and `curl` are installed.

## What each deploy does

`deploy.sh`:

- Installs [uv](https://docs.astral.sh/uv/) into `~/.local/bin` if it's missing.
- Syncs `uv.lock` into a venv at `~/.local/share/hack-for-impact/venv`.
- Restarts the app on port 8000, logging to `~/hack-for-impact.log` (pid in `~/.local/share/hack-for-impact/app.pid`).
- Fails the deploy if `/health` isn't green within 60 seconds, which includes Ollama being reachable.

The app is a plain background process: the runner has no systemd user session and no sudo. So it doesn't come back after a reboot: rerun the workflow if that happens. To change the model or the Ollama endpoint without a code change, set the repository variables `APP_MODEL` and `OLLAMA_URL`.

## Ports 80 and 443

The unprivileged runner can't bind them, so a Caddy reverse proxy on the Spark forwards both to the app on `127.0.0.1:8000`. One-time setup, done by a person with sudo on the Spark:

```bash
sudo ss -ltnp 'sport = :80 or sport = :443'   # check nothing else holds the ports
sudo apt install caddy
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
sudo systemctl enable --now caddy              # starts at boot; reload with: sudo systemctl reload caddy
```

[`deploy/Caddyfile`](../deploy/Caddyfile) is the reference copy. `deploy.sh` doesn't install it. Caddy keeps running across app redeploys.
