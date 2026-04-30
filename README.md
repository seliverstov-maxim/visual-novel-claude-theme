# Claude Local

A minimal Claude-Desktop-like web UI that wraps the `claude` CLI. Runs locally, talks to whatever `claude` already does on your machine — no extra API keys, no extra config. Single-file FastAPI app: server + embedded HTML/CSS/JS in `claude_local.py`.

Features:
- Streaming responses rendered as Markdown (token-by-token).
- Sidebar with chat history — multiple conversations, each with its own context.
- Server hot-reload on file changes (`uvicorn --reload`).

![Claude Local UI](example.png)

## Requirements

- Python 3.10+
- `claude` CLI installed and authenticated (OAuth subscription or `ANTHROPIC_API_KEY`). Verify with `claude --version`.

## Install

```bash
bin/setup
```

Creates a local `.venv` and installs `fastapi` + `uvicorn` into it. Idempotent — safe to re-run.

## Run

```bash
bin/run
```

Starts the server on **http://127.0.0.1:8000**. Open in a browser.

The server auto-reloads when `claude_local.py` changes (the embedded HTML lives inside that file, so UI tweaks reload too). The browser does not auto-refresh — hit Cmd-R after edits.

## Use

- **Send a message:** type in the composer, Enter to send, Shift+Enter for a newline.
- **New chat:** click `+ New chat` in the sidebar. Each chat gets its own `session_id` and isolated context — the model only sees history from the current chat.
- **Switch chats:** click an entry in the sidebar.
- **Delete a chat:** hover an entry, click `×`. Local-only deletion; the underlying session file in `~/.claude/projects/...` is not touched.
- **Persistence:** chat list and active chat live in browser `localStorage`. Wiping localStorage resets the UI but does not delete server-side session history.

### Context model

Within a single chat, the model sees the **full conversation history** — context is loaded by the `claude` CLI from its on-disk session storage via `--resume <session_id>`. We send only the new prompt and the session id; the CLI handles the rest. Switching to a different chat in the sidebar means a fresh context — chats do not share memory.

## Limitations

- **Slash commands** (`/mcp`, `/help`, `/clear`, etc.) don't work — they're features of the interactive Claude Code REPL, and this UI uses one-shot `claude -p` mode.
- **Tool / MCP permission prompts** are not interactive in `-p` mode. Tool calls that would normally ask for confirmation get rejected. To allow specific tools without prompting, the server would need `--allowed-tools` or `--permission-mode` flags added to the subprocess call in `claude_local.py`.
- **No streaming pause / cancel** — once a request starts, you wait for it to finish (or close the tab).

## Project layout

```
claude_local.py    server + embedded HTML/CSS/JS (single file)
bin/setup          create .venv, install deps
bin/run            start the server
CLAUDE.md          notes for AI agents working in this repo
```
