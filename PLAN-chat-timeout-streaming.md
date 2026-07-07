# PLAN: /chat dies at 60 seconds with slow models — stream from Copilot instead

**Rank: 1 of 5 (do this first).**
**Fixes open issues #8 and #9** (`chat.error: Read timed out. (read timeout=60)` with `claude-opus-4.8`).

## Goal

A `/chat` request must survive model generations that take longer than 60 seconds, and a
network timeout must never surface to the user as a raw Python exception string. This
matters more than ever because v0.6.2 made **Claude Sonnet the auto-selected default
model** (`_auto_select_default_model`, `rapp_brainstem/brainstem.py:284`) — Claude models
produce long generations slowly, which is exactly what blows the current 60s ceiling.

The `/chat` request/response JSON contract **must not change** (see RELEASING.md — the
client still receives one complete JSON response; streaming is purely between brainstem
and the Copilot API).

## Files to touch

- `rapp_brainstem/brainstem.py` — only `call_copilot()` (`:1111`) and the `/chat`
  exception handlers (`:1378-1397`)
- `rapp_brainstem/index.html` — the chat error rendering (generic branch near the
  `sendMsg` catch, and optionally an AbortController)
- `rapp_brainstem/test_local_agents.py` or a new `rapp_brainstem/test_call_copilot.py` — tests
- Do **not** touch `install.sh` / `install.ps1` / VERSION (VERSION is bumped only in the
  release commit by the maintainer).

## Current behavior (verified on main @ v0.6.3)

- `brainstem.py:1133` — primary call: `requests.post(url, headers=headers, json=body, timeout=60)`.
  No `"stream": true` in the body (`:1122-1129`). Response fully buffered, `resp.json()` at `:1184`.
- `brainstem.py:1148` — same 60s timeout on the 401-retry call.
- `brainstem.py:1175` — same 60s timeout on each model-fallback call.
- `brainstem.py:1152-1178` — the fallback loop only triggers on `resp.status_code in
  (400, 429, 500, 502, 503)`. **A `requests.exceptions.ReadTimeout` raises before `resp`
  exists, so it never enters this loop** and never reaches `raise_for_status()`.
- The timeout lands in the generic handler at `brainstem.py:1393-1397` → HTTP 500 with
  `{"error": "HTTPSConnectionPool(...): Read timed out. (read timeout=60)"}` — the exact
  string in issues #8/#9. The web UI has no branch for it and prints it raw.
- The UI `fetch` to `/chat` has no timeout/AbortController — the browser waits forever if
  the server hangs.

## Implementation order

### Step 1 — friendly timeout handling (safe, do first, commit separately)

1. In `call_copilot()`, change all three `timeout=60` values (`:1133`, `:1148`, `:1175`)
   to the tuple `timeout=(10, 300)` — 10s to connect, 300s to read. `requests` accepts a
   `(connect, read)` tuple; keeping connect short means a dead network still fails fast.
2. Wrap the **primary** call at `:1133` in a `try/except requests.exceptions.Timeout` that
   retries **once** with the same body (transient blips are common on the enterprise
   endpoint — see the "blip retry" precedent in commit `3abfc5a`). Log
   `_tlog("api.timeout_retry", {"model": MODEL}, level="warn")` before the retry.
3. If the retry also times out, raise a **RuntimeError with a human message**:
   `raise RuntimeError(f"The model '{body['model']}' took too long to respond. Try a shorter prompt or switch models (gear icon).")`
   The `/chat` generic handler at `:1393` already forwards `str(e)` to the UI, so this
   message is what users see. Do NOT add a new exception class — keep the single-file style.

### Step 2 — stream from Copilot and aggregate server-side (the real fix)

1. In the body construction (`:1122-1129`) add `"stream": True`.
2. Change the primary call to
   `resp = requests.post(url, headers=headers, json=body, timeout=(10, 60), stream=True)`.
   With streaming, the 60s read timeout applies **between chunks**, not to the whole
   generation — a model that emits a token every few seconds never times out, no matter
   how long the total generation takes.
3. **Status-code check still works before reading the body**: `resp.status_code` is
   available immediately after headers. For non-200, read the error body with
   `resp.text` (this drains the stream — fine for errors) so the existing 401-retry
   (`:1140`) and 400/429/5xx fallback loop (`:1152-1178`) keep working **unchanged**,
   except each retry call also gets `stream=True`.
4. For a 200, aggregate the SSE stream into the exact same dict shape `resp.json()`
   returned before, then let the rest of the function run untouched. Aggregation spec:
   - Iterate `resp.iter_lines(decode_unicode=False)` and decode each line as UTF-8
     yourself (`line.decode("utf-8", errors="replace")`) — this preserves the mojibake
     fix currently done via `resp.encoding = "utf-8"` at `:1183`, which no longer applies
     once you stop using `resp.json()`.
   - Skip empty lines. Lines look like `data: {json}`. Stop at `data: [DONE]`.
   - Each chunk is `{"choices": [{"index": i, "delta": {...}, "finish_reason": ...}], ...}`.
     Build one message **per choice index**: concatenate `delta.content` strings;
     capture `delta.role` when present; record the last non-null `finish_reason`.
   - **Tool-call deltas are fragmented**: `delta.tool_calls` is a list of
     `{"index": n, "id": ..., "type": ..., "function": {"name": ..., "arguments": "<fragment>"}}`.
     Keyed by `tool_calls[].index`, create the entry when `id` is present and **append**
     each `function.arguments` fragment to that entry's arguments string. A weaker model
     will naively overwrite arguments per chunk — that silently truncates every agent
     call to its last JSON fragment and breaks all tools.
   - Some chunks carry a `usage` object and an **empty `choices` list** — guard with
     `if not chunk.get("choices"): continue` (mirror of the guard at `:1190`).
   - Assemble `result = {"choices": [{"index": i, "message": {...}, "finish_reason": ...} for each index]}`.
5. Leave the multi-choice merge at `:1197-1210` alone — Claude via Copilot really does
   split text and tool_calls into separate choices, and your per-index aggregation feeds
   it exactly what it expects.
6. Keep the empty-choices RuntimeError (`:1190-1191`) — apply it to the aggregate.

### Step 3 — UI polish (small)

1. In `rapp_brainstem/index.html`, in the chat error rendering, add a branch before the
   generic one: if the error text contains `"took too long"` or `"timed out"`, render
   `⏱️ The model took too long to respond. Try a shorter prompt, or switch models from the picker.`
   instead of the raw text.
2. Add an `AbortController` with a 360s timeout to the `/chat` fetch so the browser can
   never hang forever (360s > server-side worst case; on abort, show the same friendly
   timeout message).

## Edge cases a weaker model would miss

- **ReadTimeout never had a `resp`** — you cannot "add Timeout to the status-code retry
  set"; timeouts must be caught as exceptions, separately from the status-code loop.
- **The fallback loop multiplies the wait**: on 400/429/5xx it tries every other
  available model sequentially (`:1165-1178`), each with its own read timeout. Do not
  raise the per-call read timeout in that loop above ~60s or a total outage takes
  `n_models × timeout` to fail. Streaming makes this moot for 200s; keep fallback calls
  at `timeout=(10, 60)`.
- **`tool_choice` juggling**: the fallback loop pops/re-adds `tool_choice` per model
  (`:1171-1174`, `_NO_TOOL_CHOICE_MODELS` at `:126`). Don't restructure the body dict in
  a way that loses this.
- **UTF-8**: dropping `resp.json()` drops the `resp.encoding = "utf-8"` fix (`:1183`).
  Decode stream bytes as UTF-8 explicitly or emoji/em-dashes regress to mojibake
  (regression of commit `3ccabde`).
- **The 401-retry** (`:1140-1150`) rebuilds `url` and the auth header from a fresh token —
  it must also pass `stream=True` after Step 2.
- **Telemetry names are load-bearing**: keep `_tlog("api.error", ...)` (`:1154`) and
  `chat.error` events unchanged — the Get Help diagnostics report and the existing
  GitHub issues reference these exact event names.
- **Flask threaded dev server**: the aggregation loop runs per-request on a worker
  thread; do not add module-level mutable state for aggregation.

## Acceptance criteria

1. `~/.brainstem/venv/bin/python -m pytest test_local_agents.py test_model_selection.py -q`
   passes, plus new tests:
   - SSE aggregation: feed a canned stream (use `unittest.mock` on `requests.post`
     returning a fake response whose `iter_lines()` yields bytes) containing a
     tool_call split across 3 argument fragments → assert the aggregated
     `function.arguments` is the full concatenated JSON.
   - A stream with a usage-only chunk (empty `choices`) does not crash.
   - `requests.exceptions.ReadTimeout` on the primary call → retried once → second
     timeout raises RuntimeError containing "took too long" (assert no raw
     "HTTPSConnectionPool" text can reach the return value).
   - Non-200 first response still enters the fallback loop (mock a 400 then a 200).
2. `bash tests/preflight_local.sh fresh` and `upgrade` pass (per RELEASING.md).
3. Manual (requires Copilot auth): start the server, pick a Claude model, send
   "Write a 3,000-word short story." → full response arrives, no timeout, `book.json`
   shows no `chat.error`.
4. Manual: with `GITHUB_MODEL` pinned to a valid model, temporarily set the read timeout
   to 1s locally → UI shows the friendly ⏱️ message, not `HTTPSConnectionPool(...)`.
5. Branch pushed, CI preflight green. **No push to main** — release merge is the
   maintainer's step 6 in RELEASING.md.
