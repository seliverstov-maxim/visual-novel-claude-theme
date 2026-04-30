# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A minimal Claude-Desktop-like web UI that wraps the `claude` CLI. The entire app — FastAPI server, embedded HTML, CSS, and JS — lives in a single file: `claude_local.py`. There is no build step, no package manager, no tests, and no config files. Auth is delegated to whatever the host's `claude` CLI is already using (OAuth subscription or `ANTHROPIC_API_KEY`).

## Run

```bash
bin/setup    # one-time: creates .venv and installs fastapi + uvicorn
bin/run      # starts uvicorn with --reload on http://127.0.0.1:8000
```

Both scripts `cd` to the repo root from their own location, so they work from any cwd. Server auto-reloads on file changes; the browser still needs a manual refresh.

## Architecture

Two layers in one file, communicating over SSE:

1. **Server (`/chat`)** spawns `claude -p <prompt> --output-format stream-json --include-partial-messages --verbose` as a subprocess and forwards each stdout line verbatim as an SSE `data:` frame. It does not parse the JSON. On non-zero exit it emits a synthetic `{"type": "_error", ...}` frame. Session continuity is achieved by passing `--resume <session_id>` when the client supplies one.

2. **Browser (`INDEX_HTML`)** is the parser. It handles three event shapes from the CLI's stream-json format:
   - `system/init` → captures `session_id`, persists it in `localStorage`, and includes it on subsequent `/chat` calls. This is what makes multi-turn context work.
   - `stream_event` with `delta.type === "text_delta"` → token-by-token incremental render (preferred path).
   - `assistant` with full `message.content` → fallback used **only** when no deltas were seen (`state.hasDeltas` guard prevents double-rendering).
   - `_error` → appended to the current assistant bubble.

   Markdown is rendered with `marked` + `highlight.js` from CDN. Conversation history and session id are persisted in `localStorage` (`claude_history`, `claude_session`); "New chat" clears both.

## Persona overlay

The server passes a hardcoded `--append-system-prompt PERSONA` to every `claude -p` invocation. `PERSONA` is defined as a module-level constant in `claude_local.py` and gives the assistant a Japanese-schoolgirl character (Hinata Asagiri). It is appended (not replaced) so default tool-use instructions stay intact. The prompt explicitly tells the assistant to keep technical answers honest even when in-character.

## Things to know when editing

- The HTML/CSS/JS lives inside the `INDEX_HTML` raw string in `claude_local.py`. There is no separate frontend.
- The server is intentionally a dumb pipe — keep stream parsing on the client. If you add a new event type, update `handleEvent` in the browser, not the server.
- The `hasDeltas` guard exists because the CLI emits both partial deltas and a final `assistant` message; rendering both would duplicate output. Preserve this invariant.
- Session id flows: CLI → `system/init` event → browser `localStorage` → next `/chat` request body → `--resume` flag. Breaking any link breaks multi-turn.
