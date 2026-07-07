"""AskBrainstem — drop-in bridge that lets any agent host call a locally running RAPP brainstem.

WHAT IT DOES
One stdlib-only file = the whole capability. Drop it into ANY host that speaks
the single-file agent contract — a Scout crews/squad folder (the metadata block
IS the typed tool node Scout sees), another brainstem's agents/ directory, or
run it bare from the CLI — and that host can now drive the local brainstem
server (default http://localhost:7071) through its one sacred endpoint:

    POST /chat  { user_input, conversation_history?, session_id? }
                -> { response, session_id, agent_logs, model }

Everything the brainstem offers (memory, RAR community agents, the twin, every
drop-in in its agents/ folder) flows through that call, so this bridge is the
ONLY file Scout needs to inherit all of it. A 'status' action wraps GET /health
so the caller can see which agents/model are live before asking.

No pip installs, no config file. The endpoint comes from the `endpoint` param,
else the BRAINSTEM_URL env var, else localhost:7071. Conversation continuity:
pass back the session_id from a previous reply.

NOTE for brainstem hosts: if this file is loaded by the SAME brainstem it
points at, the model could ask the brainstem to ask itself. The brainstem's
3-round tool budget bounds that, but the intended home is a DIFFERENT host
(Scout, a second brainstem, a script).

Usage:
  AskBrainstem(action='status')
  AskBrainstem(user_input='what twins should I create under ~/code?')
  AskBrainstem(user_input='remember that demos are on Fridays', session_id='scout-1')
"""

import json
import os
import urllib.error
import urllib.request

try:
    from basic_agent import BasicAgent
except ModuleNotFoundError:
    try:
        from agents.basic_agent import BasicAgent
    except ModuleNotFoundError:
        class BasicAgent:  # bare-host fallback: the file still drops in anywhere
            def __init__(self, name=None, metadata=None):
                self.name = name or getattr(self, "name", "BasicAgent")
                self.metadata = metadata or getattr(self, "metadata", {})

            def perform(self, **kwargs):
                return "Not implemented."

            def system_context(self):
                return None


__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@kody-w/ask_brainstem_agent",
    "version": "1.0.0",
    "display_name": "AskBrainstem",
    "description": "Bridge any agent host (Scout squads, another brainstem, a bare script) to a locally running RAPP brainstem: POST /chat with the request, get the twin's reply + agent_logs back. Status action lists the live agents/model via /health.",
    "author": "Kody Wildfeuer",
    "tags": ["brainstem", "bridge", "scout", "chat", "twin", "gateway"],
    "category": "core",
    "quality_tier": "official",
    "requires_env": [],
    "dependencies": [],
}

_DEFAULT_ENDPOINT = "http://localhost:7071"


class AskBrainstemAgent(BasicAgent):
    def __init__(self):
        self.name = "AskBrainstem"
        self.metadata = {
            "name": self.name,
            "description": (
                "Sends a request to the locally running RAPP brainstem server and returns the twin's reply. "
                "The brainstem routes the request through its own soul + agents (memory, RAR registry, community "
                "agents, everything in its agents/ folder), so use this whenever a task should be handled by the "
                "user's local brainstem/twin rather than by this host: asking the twin something, storing/recalling "
                "memory, running a brainstem agent by describing what you want done. Use action='status' first if "
                "you need to know which agents and model are live. Pass the session_id returned by a previous call "
                "to continue the same conversation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_input": {
                        "type": "string",
                        "description": "The request to send to the brainstem, in plain language — exactly what a user would type into its chat (e.g. 'scout ~/code for twin candidates', 'remember that the demo is Friday'). Required for action='ask'.",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["ask", "status"],
                        "description": "ask (default) = POST the user_input to /chat and return the reply. status = GET /health and report the live agents, model, and readiness without sending a chat.",
                    },
                    "session_id": {
                        "type": "string",
                        "description": "Conversation id for continuity. Pass the session_id returned by a previous AskBrainstem reply to keep talking in the same brainstem conversation; omit to start fresh.",
                    },
                    "endpoint": {
                        "type": "string",
                        "description": "Base URL of the brainstem server. Defaults to the BRAINSTEM_URL env var, else http://localhost:7071.",
                    },
                    "timeout_seconds": {
                        "type": "integer",
                        "description": "How long to wait for the brainstem's reply (its LLM + agent rounds can take a while). Default 120.",
                    },
                    "include_agent_logs": {
                        "type": "boolean",
                        "description": "If true (default), include the brainstem's agent_logs (which of its agents ran and what they returned) in the result data.",
                    },
                },
                "required": [],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    # ------------------------------------------------------------------ #

    def perform(self, **kwargs):
        endpoint = (kwargs.get("endpoint") or os.environ.get("BRAINSTEM_URL")
                    or _DEFAULT_ENDPOINT).rstrip("/")
        timeout = int(kwargs.get("timeout_seconds") or 120)
        action = (kwargs.get("action") or "ask").strip().lower()

        if action == "status":
            code, body = self._http(endpoint + "/health", timeout=min(timeout, 15))
            if code != 200 or not isinstance(body, dict):
                return self._down(endpoint, code, body)
            return self._result("success",
                                "Brainstem is up at %s — model %s, %d agent(s) live: %s." % (
                                    endpoint, body.get("model"), len(body.get("agents") or []),
                                    ", ".join(sorted(body.get("agents") or [])) or "(none)"),
                                {"endpoint": endpoint, **body})

        user_input = (kwargs.get("user_input") or "").strip()
        if not user_input:
            return self._result("needs_input",
                                "Give me user_input — the plain-language request to send to the brainstem "
                                "(or action='status' to just check what's live).")
        payload = {"user_input": user_input}
        if kwargs.get("session_id"):
            payload["session_id"] = str(kwargs["session_id"])
        code, body = self._http(endpoint + "/chat", payload, timeout=timeout)
        if code != 200 or not isinstance(body, dict):
            return self._down(endpoint, code, body)
        reply = (body.get("response") or "").strip() or "(the brainstem returned an empty reply)"
        data = {
            "endpoint": endpoint,
            "session_id": body.get("session_id"),
            "model": body.get("model"),
        }
        if kwargs.get("include_agent_logs", True) and body.get("agent_logs"):
            data["agent_logs"] = str(body["agent_logs"])[:4000]
        return self._result("success", reply, data)

    # ------------------------------------------------------------------ #

    @staticmethod
    def _http(url, payload=None, timeout=120):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data,
                                     headers={"Content-Type": "application/json",
                                              "Accept": "application/json"},
                                     method="POST" if data else "GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8", "replace")
                try:
                    return r.status, json.loads(raw)
                except Exception:
                    return r.status, raw
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                return e.code, json.loads(raw)
            except Exception:
                return e.code, raw
        except Exception as e:  # connection refused / timeout / DNS
            return 0, str(e)

    def _down(self, endpoint, code, body):
        detail = (body.get("error") if isinstance(body, dict) else str(body))[:200]
        hint = (" Is the brainstem running? Start it with: cd ~/.brainstem/src/rapp_brainstem && ./start.sh"
                if code == 0 else "")
        return self._result("error",
                            "Brainstem at %s did not answer (HTTP %s: %s).%s" % (endpoint, code, detail, hint),
                            {"endpoint": endpoint, "http_status": code})

    def _result(self, status, message, data=None):
        out = {"status": status, "agent": self.name, "message": message}
        if data is not None:
            out["data"] = data
        return out


def main():
    """CLI smoke: python3 ask_brainstem_agent.py [status | <question...>]"""
    import sys
    args = sys.argv[1:]
    if args and args[0] == "status":
        r = AskBrainstemAgent().perform(action="status")
    elif args:
        r = AskBrainstemAgent().perform(user_input=" ".join(args))
    else:
        r = AskBrainstemAgent().perform()
    print(json.dumps(r, indent=2, default=str))


if __name__ == "__main__":
    main()
