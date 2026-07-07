# PLAN: Get Help flow — stop filing empty/duplicate issues, stop lying about failures, triage the backlog

**Rank: 2 of 5.**
**Fixes the root causes behind open issues #2, #4, #6 (empty reports), #8+#9 (exact
duplicates 6 seconds apart), and the empty `issue_url` telemetry in #2. Also clears the
6-issue backlog, every one of which is an unanswered user.**

## Goal

One click on 🆘 Get Help produces at most one GitHub issue, always with a user
description, and the UI tells the truth about whether the issue was filed. Then triage
and close the existing backlog with real answers.

## Files to touch

- `rapp_brainstem/brainstem.py` — `diagnostics_report()` at `:1850-1963`
- `rapp_brainstem/index.html` — `shareWithAdmin()` at `:1059-1087`, plus the two
  triggers: login-overlay link at `:811` and toolbar button at `:982`
- `rapp_brainstem/test_local_agents.py` — new test class
- GitHub issues #2, #4, #5, #6, #8, #9 via `gh` CLI (part 2 — no code)

## Current behavior (verified on main @ v0.6.3)

- `index.html:1061` — `prompt('Describe what went wrong (optional):') || ''` →
  description optional; server substitutes `"_No description provided_"`
  (`brainstem.py:1859`). Four of six open issues have no description → undiagnosable.
- No in-flight guard or disable on either trigger → two clicks = two issues (#8/#9).
- Server has **no cooldown or dedupe** — every POST creates a fresh issue (`:1918-1953`).
- CLI fallback (`:1943-1953`) returns `{"status":"ok","issue_url":result.stdout.strip()}`
  whenever `returncode == 0` **without checking stdout is non-empty**. Issue #2's
  telemetry shows `report_created_via_cli` with `issue_url: ""`. The UI then treats the
  falsy URL as failure (`index.html:1069` → `throw` at `:1076`) and tells the user to
  file manually — **even though an issue was actually created**. That's the likely
  origin of some duplicates: users retry after a false "failure".
- Privacy: `_SCRUB_KEYS = {"user_code", "device_code", "session_id"}` (`:1876`) — but
  event payloads can carry a GitHub **username** (the `no_copilot_access` auth event
  includes the login), and everything is posted to a **public** repo.

## Implementation order

### Part 1 — code hardening

1. **Require a description (UI).** In `shareWithAdmin()` (`index.html:1059`): if the
   prompt result is empty/whitespace, `appendMsg('system', 'Please describe what went wrong — reports without a description can\'t be diagnosed.')`
   and return without POSTing. Keep the prompt text but drop "(optional)".
2. **In-flight guard (UI).** Module-scope `let helpRequestInFlight = false;` — set true
   before the fetch, false in a `finally`. If already true, return immediately. Also
   `disabled = true` on the toolbar button (`:982`) during flight (the overlay link at
   `:811` is an `<a>` — the boolean guard covers it).
3. **Server cooldown.** In `brainstem.py`, add module globals
   `_last_report = {"ts": 0.0, "url": ""}` and `_report_lock = threading.Lock()` next to
   the other locks (pattern: `_flight_log_lock` at `:390`). At the top of
   `diagnostics_report()` (after the auth check at `:1856`), under the lock: if
   `time.time() - _last_report["ts"] < 600`, return
   `jsonify({"status": "ok", "issue_url": _last_report["url"], "deduped": True})` —
   returning the **previous** URL keeps the UI success path working and genuinely helps
   the user find their ticket. On successful creation (both API and CLI paths), record
   `ts` and `url`. Hold the lock across the whole create so two concurrent POSTs can't
   both pass the check (the GitHub call inside the lock is acceptable here — this
   endpoint is rare and the lock is dedicated to it, not shared with /chat).
4. **Honest CLI fallback.** At `:1950-1953`: only return ok if
   `result.stdout.strip().startswith("https://")`. Otherwise `_tlog("diagnostics.report_cli_no_url", {"stdout": result.stdout[:200]}, level="warn")`
   and fall through to the error return, so the UI's manual-fallback message is truthful.
5. **Widen the scrub.** Add `"user"`, `"username"`, `"login"` to `_SCRUB_KEYS` (`:1876`).
6. **Label the issue.** In the API path (`:1929`) set `"labels": ["help-request"]`.
   Note the CLI path must NOT pass `--label help-request` unless the label already
   exists — `gh issue create --label` **fails on a missing label** (API path silently
   drops unknown labels; CLI path errors). Create the label once by hand:
   `gh label create help-request --color E99695 --description "Auto-filed from the in-app Get Help button"`.

### Part 2 — triage the backlog (gh CLI, exact commands)

Post a comment then close, for each (verify the claim against the issue body first —
if the diagnostics contradict the canned text, adapt it):

- **#2 and #4** (v0.5.4, no description, ancient auth-era sessions):
  `gh issue close 2 4 --comment "Closing stale help requests from v0.5.4 — the auth flow was rewritten in v0.6.0 (account switcher, poll-race fix) and diagnostics privacy improved. If you still hit this on v0.6.3+, re-run the installer (curl -fsSL https://kody-w.github.io/rapp-installer/install.sh | bash) and file a new report with a description of what went wrong."`
- **#5** (gpt-5.3-codex `unsupported_api_for_model` + "start is very slow"):
  the model-picker bug is **already fixed on main** — v0.6.2 commit `7f2ec6d` filters
  `/models` to entries whose `supported_endpoints` include `/chat/completions`
  (`brainstem.py:362-370`). Comment explaining that, ask them to update via the
  one-liner. Note their reported version "0.12.2" does not exist in this repo (max is
  0.6.3) — ask what `brainstem --version` / the header badge shows after updating, and
  whether "slow start" means the installer one-liner (which git-pulls every run) or the
  server boot. Keep #5 **open** until they confirm.
- **#6** (v0.6.0, no errors recorded, no description): close with the same canned text
  as #2/#4 but mention v0.6.3 specifically.
- **#9**: `gh issue close 9 --comment "Duplicate of #8 (same session, filed 6s apart by a double-click we've since guarded against)."`
- **#8** (the read-timeout with claude-opus-4.8): keep open; comment that the fix is
  planned (streaming — see PLAN-chat-timeout-streaming.md) and will land in the next
  release. Close it only when that release ships.

## Edge cases a weaker model would miss

- **The empty-URL bug and the duplicate bug feed each other**: returning `""` as a
  "success" makes the UI report failure, users click again, and the second attempt
  files another issue. Fix both or the loop persists.
- **`gh issue create` prints the URL to stdout on success — usually.** With `GH_FORCE_TTY`
  or certain gh versions/aliases it can print extra lines; use the *last*
  `https://`-prefixed token of stdout, not raw stdout.
- **Issues are filed under the END USER's identity** (their `ghu_` token via API, their
  `gh` login via CLI) — closing with a comment notifies the actual reporter. Don't
  bulk-close silently.
- **Cooldown must return the previous URL**, not an error — a 429-style rejection would
  re-trigger the UI's "file manually" fallback and recreate the duplicate problem the
  cooldown exists to solve.
- **Don't move the description requirement server-side only**: `brainstem.py:1859` is
  also hit by curl users; keep the server default (`"_No description provided_"`) as a
  fallback but enforce non-empty in the UI, so scripted reports still work.
- **The book is public.** Never widen what's *included*; only widen what's scrubbed.
  Event `data` dicts are scrubbed by key only (`:1877-1881`) — nested dicts are not
  descended into; if you add nested event payloads elsewhere, flat-key scrubbing misses
  them.

## Acceptance criteria

1. New unit tests pass (pattern-match `TestLoginPoll` in `test_local_agents.py`, which
   already shows how to exercise Flask routes with mocked globals):
   - two POSTs to `/diagnostics/report` within the window → second returns
     `deduped: True` and the first URL; exactly one `requests.post` to the GitHub API
     (mock it).
   - CLI fallback with `returncode=0, stdout=""` → response is an error, not
     `status: ok`.
   - description defaulting still works server-side.
2. Manual: double-click 🆘 fast → exactly one issue in the repo; UI shows its URL twice.
3. Manual: with a `ghu_` token (no repo scope) and `gh` authed → issue filed via CLI,
   UI links it.
4. Backlog: issues #2, #4, #6, #9 closed with comments; #5 and #8 have maintainer
   comments; `gh issue list` shows only #5 and #8 open.
5. `~/.brainstem/venv/bin/python -m pytest test_local_agents.py -q` green;
   `bash tests/preflight_local.sh fresh` green; branch pushed; **no push to main**.
