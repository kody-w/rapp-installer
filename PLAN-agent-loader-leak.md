# PLAN: Agent loader leaks a module per request; MODEL global races across requests

**Rank: 5 of 5.**

## Goal

A long-running brainstem must not grow memory without bound or slow down over a session,
and one user's model switch must not hijack another request mid-flight. This is also the
most plausible real cause behind "brainstem is very slow" reports (issue #5, from a user
running 17 agents): every `/chat`, `/health`, `/agents`, and diagnostics call re-imports
**every** agent file and permanently registers a fresh module in `sys.modules`.

## Files to touch

- `rapp_brainstem/brainstem.py` — `_load_agent_from_file` (module naming at `:939`),
  `load_agents()` (`:1095`), `MODEL` mutation sites (`:290`, `:1485`), `call_copilot()`
  (`:1111`)
- `rapp_brainstem/test_local_agents.py` — extend `TestAgentLoading`

## Current behavior (verified on main @ v0.6.3)

- `brainstem.py:939`:
  `mod_name = f"agent_{os.path.basename(filepath).replace('.', '_')}_{id(filepath)}_{attempt}"`
  — a **unique** module name per load attempt, inserted into `sys.modules` by
  `exec_module`, never evicted. Every request that calls `load_agents()` re-execs every
  agent file and leaks its previous module object.
- `load_agents()` call sites: `/agents` `:1294`, post-login refresh `:1676`, `/chat`
  `:1721`, `/health` `:1831` (hit by the UI on a poll), diagnostics `:1895`, RAR flows
  `:1986`. With N agents and a UI polling `/health`, that's N execs + N leaked modules
  every few seconds, forever.
- The hot-reload contract is real and must survive: "Agents reload from disk every
  request — no restart needed" (CLAUDE.md; the pearl-pass comments around `:958`/`:1069`
  already cache *failed* imports to keep pip off the request path — successful imports
  got no such cache).
- `MODEL` is a module global written by `/models/set` (`global MODEL` at `:1485`) and by
  auto-select (`:290`), read mid-request in `call_copilot` (`body = {"model": MODEL...}`
  at `:1123`) and in `/chat`'s error handlers (`:1383`, `:1387`). Flask's dev server is
  threaded: switching models during another user's in-flight request changes which model
  serves it (and mislabels its error messages).

## Implementation order

1. **mtime-keyed module cache.** Add module globals:
   `_agent_module_cache = {}` (key: absolute filepath → `{"sig": (mtime_ns, size), "agents": {name: cls}}`)
   and `_agent_cache_lock = threading.Lock()`.
   In `_load_agent_from_file`: `st = os.stat(filepath)`; `sig = (st.st_mtime_ns, st.st_size)`;
   under the lock, if the cache entry exists with the same sig, return its agents dict
   without exec. On miss: exec as today, but **before inserting the new module, delete
   the previous one**: keep the generated `mod_name` inside the cache entry and
   `sys.modules.pop(old_mod_name, None)` when replacing. Store the new entry.
2. **Deleted files.** In `load_agents()`, after globbing, drop cache entries whose
   filepath no longer exists (and pop their modules from `sys.modules`) — otherwise a
   deleted agent's module lingers.
3. **Snapshot MODEL per call.** In `call_copilot()`, first line: `model = MODEL`, then
   use `model` everywhere in the function (body construction `:1123`, the
   `_NO_TOOL_CHOICE_MODELS` check `:1128`, log lines, `api.error` telemetry `:1154`).
   The fallback loop already mutates `body["model"]` locally — leave that. In `/chat`'s
   HTTPError handler (`:1383-1387`), the message should name `body`'s final model if
   available, else the snapshot — at minimum stop re-reading the global there.
   Do NOT add a lock around MODEL; a torn read of a Python str is impossible, the bug is
   *rereading* it mid-request.
4. **Keep the failure-cache intact.** The existing negative cache for unresolvable
   imports (comments at `:958`, `:1069`) keys off its own structure — make sure a file
   edit (new sig) also clears that file's negative entry, or a user who fixes a broken
   agent won't see it load until restart, breaking the hot-reload contract in the
   opposite direction.

## Edge cases a weaker model would miss

- **`id(filepath)` is not a stable key** — it's the id of a transient string object;
  equal ids across calls are coincidental. Never use it in the new cache key.
- **mtime alone is insufficient on coarse filesystems** (1s granularity on some
  systems; editors doing atomic-rename can preserve mtime) — hence `(mtime_ns, size)`.
  Document in a comment that a same-second same-size edit may require a `touch`; that's
  an acceptable trade for the constitution's simplicity rule.
- **Two agent files can define classes with the same name** — the cache must be keyed
  by filepath, and `load_agents()`'s merge order must stay stable (today: glob order).
  Don't dedupe by class name.
- **`agents/experimental/` is intentionally excluded** from the glob — don't "fix" that
  while touching `load_agents()`.
- **Import shims must stay registered before any exec** (`_register_shims()`,
  `sys.modules` entries at `:989-1003`) — cached hits skip exec, which is fine, but a
  cache-miss re-exec still needs the shims; don't move shim registration inside the
  cache-hit branch.
- **Agents hold state?** `BasicAgent` subclasses are instantiated per `load_agents()`
  call today (check whether classes or instances are returned — if instances, reusing
  the cached *class* and re-instantiating per request preserves current semantics;
  reusing cached *instances* would silently introduce cross-request agent state).
  Preserve exactly the current instantiation point.
- **The auto-select writer** (`:290`) runs once at startup and on login — snapshotting
  in `call_copilot` makes the race harmless; do not "fix" auto-select by locking, it
  would deadlock with the token lock ordering used at `:588-637`.

## Acceptance criteria

1. New tests in `test_local_agents.py` (`TestAgentLoading` has the harness):
   - call `load_agents()` 5× → `len(sys.modules)` identical after runs 2–5, and the
     same class object is returned (`is` comparison) for an unchanged file.
   - rewrite the agent file (change its `perform` return string, bump mtime via
     `os.utime` with a different time) → next `load_agents()` returns the NEW behavior
     and the old module name is gone from `sys.modules`.
   - delete the file → next `load_agents()` drops the agent and its module.
   - a file that raises on import, then is fixed and re-stat'd → loads (negative-cache
     invalidation).
2. Perf sanity: with the bundled 3 agents, time 100 sequential `load_agents()` calls
   before/after (a simple `time.perf_counter` loop in a scratch script) — after must be
   ≥10× faster for the cached path.
3. `~/.brainstem/venv/bin/python -m pytest test_local_agents.py test_model_selection.py test_polish.py -q` all green.
4. `bash tests/preflight_local.sh upgrade` green — proves a real custom agent still
   hot-reloads through an upgrade.
5. Manual: start server, `/chat` once, edit `agents/hacker_news_agent.py` description,
   `/agents` shows the new description without restart.
6. Branch pushed; **no push to main**.
