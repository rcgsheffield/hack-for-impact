# Form agents: testing locally

LangChain agents that fill in the mock council forms (`src/mock/`) in a browser, using a local Ollama model.

| Form | Toolkit | Mock |
|---|---|---|
| Pothole or crack | `src/app/pothole_form_toolkit.py` | `src/mock/report_pothole_crack.html` |
| Tree problem | `src/app/tree_form_toolkit.py` | `src/mock/report_tree.html` (questions unverified) |

Shared browser driver and tools: `src/app/council_form.py`.

## Setup on a laptop

1. Install Ollama (Windows: `winget install Ollama.Ollama`) and pull a small tool-calling model:
   ```
   ollama pull qwen3:4b-instruct
   ```
   Use the `-instruct` tag. Plain `qwen3:4b` is a thinking model that can't switch thinking off, and on a CPU it
   spends minutes on each reply.
2. Browser: `uv run playwright install chromium`, or use an installed Chrome with `FORM_BROWSER_CHANNEL=chrome`.

## Run

```powershell
$env:OLLAMA_MODEL="qwen3:4b-instruct"; $env:FORM_BROWSER_CHANNEL="chrome"
uv run python -m app.form_agent_cli pothole --headed          # chat in the terminal, watch the browser
uv run python -m app.form_agent_cli tree -m "A branch has fallen across the pavement on Derbyshire Lane"
uv run python -m app.pothole_form_toolkit --headed --keep-open   # fixed answers, no model
```

Every submission is also saved to `data/mock_submissions.jsonl`; watch them arrive at `/dashboard` while the
app is running (`uv run uvicorn app.main:app --app-dir src`).

`form_agent_cli` prints every tool call. It also warns (`GUARD`) if the model quotes a reference number
that no submit tool returned.

## Notes from testing with qwen3:4b-instruct (CPU, 13 Nov 2026)

- A whole report takes about 1 to 2 minutes on a laptop CPU. The Spark's GPU should be much faster.
- Ollama's default 4096-token context truncates the prompt. The CLI sets `num_ctx=16384`. Do the same anywhere
  else the agents run.
- Small models follow the `next_step` hint in each tool result much better than the system prompt, so the tools
  steer the flow. Advice the user must hear (for example "phone now" for a fallen tree) is carried in `tell_user`
  and added to the hint on the review page.
- Before those fixes, the 4B model once made up a reference number without submitting. Keep the guard, or an
  equivalent check, in any user-facing app.
