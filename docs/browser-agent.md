# Browser agent

`src/app/browser_agent.py`, served at `/browser`. The agent opens a council form in a real browser and fills it in the way a person would: it reads the page, then clicks, types and picks from dropdowns one element at a time. Nothing in it knows any form's fields, so it isn't limited to forms we've written tools for. Compare the form toolkits (`pothole_form_toolkit.py`, `tree_form_toolkit.py`), which have one coded tool per form page: faster and more reliable, but only for those forms.

## How it works

- The browser is the [Playwright MCP server](https://github.com/microsoft/playwright-mcp), started with `npx` (one per conversation, Firefox, headless). It's pinned in `config.BROWSER_MCP_PACKAGE` and `deploy.sh`.
- The agent gets seven LangChain tools: `open_page`, `read_page`, `click`, `type_text`, `select_option`, `wait_for_text` and `upload_file`. Each action returns the page afterwards as an accessibility tree, cut down to the `<main>` part (about 300 to 600 tokens), with refs like `[ref=e57]` for the next action.
- `open_page` only opens pages under `BROWSER_FORMS_URL` (the app's own `/mock/` by default).

Guards in code, because small models don't reliably follow the prompt:

| Guard | Why |
|---|---|
| The final **Submit** on a review page is refused until the user has replied in a later message | In testing, Nemotron went straight to Submit without asking the user |
| After a click, any validation errors (`Error: ...`) and an unchanged page are spelled out in the result | Models missed the error message in the page and repeated the same click |
| Clicking a container (e.g. the `generic` box around the buttons) is refused, listing the buttons inside it | Models clicked the box instead of the button, which does nothing |
| Clicking a dropdown says to use `select_option` | |

## Run it

Needs Node.js, and Playwright's Firefox once per machine:

```bash
npx -y @playwright/mcp@0.0.83 install-browser firefox
```

In the terminal (the app serves the forms at `/mock/`, so start it first, or point `BROWSER_FORMS_URL` at any server for `src/mock/`):

```bash
uv run uvicorn app.main:app --app-dir src &
uv run python -m app.form_agent_cli browser --headed
uv run python -m app.form_agent_cli browser -m "Pothole 6cm deep in the road on Western Bank, S10 2TN. Report it anonymously." -m "Yes, submit it."
```

In the web app: <http://127.0.0.1:8000/browser/>. Each tool call's result (the page) is shown under its 🔧 bubble.

## Settings

| Variable | Default | |
|---|---|---|
| `BROWSER_FORMS_URL` | `http://127.0.0.1:8000/mock/` | Where the forms are; the only pages the agent may open |
| `BROWSER_MCP_PACKAGE` | `@playwright/mcp@0.0.83` | Keep in step with `deploy.sh` |
| `BROWSER_MCP_COMMAND` | `npx -y $BROWSER_MCP_PACKAGE` | |
| `BROWSER_NAME` | `firefox` | Playwright builds Firefox for ARM Linux (the Spark) |
| `BROWSER_HEADLESS` | `1` | `0` shows the window (the CLI's `--headed` does this) |
| `BROWSER_MAX_AGENT_STEPS` | `40` | Model calls per user message. A form takes about 15 |
| `BROWSER_NUM_CTX` | `65536` | Model context; every action adds a page |
| `BROWSER_MAX_SESSIONS` | `3` | Browsers open at once in the web app; the oldest is closed for a new one |
| `BROWSER_IDLE_SECONDS` | `900` | Close a conversation's browser after this long unused |

## Measured

`nemotron-3.5-lightning:30b` on the Spark, mock pothole form, "pothole about 6cm deep in the road on Western Bank, S10 2TN, report it anonymously" (13 Nov 2026):

- Reached the review page in 12 to 13 actions, about 50 seconds to 2 minutes. It chose the matching address from the search results and recovered from the form's "Enter further information" error.
- Showed the answers and asked to confirm; submitted on "yes" and quoted the reference from the confirmation page.
- Before the guards above it looped until the step limit, and once tried to submit without asking.

## Deployment

`deploy.sh` installs Node.js into `~/.local/share/hack-for-impact/` (no sudo) and runs `install-browser firefox`. If either fails the app still deploys and `/browser` reports that the browser couldn't start. Firefox also needs some system libraries; if the Spark lacks them, someone with sudo needs to run `npx playwright install-deps firefox` once. This hasn't been tried on the Spark yet.
