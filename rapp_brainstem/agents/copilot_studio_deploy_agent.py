"""CopilotStudioDeploy — deploy a shared folder of agent.py files into a Copilot Studio environment.

WHAT IT DOES
The DEPLOY slice of the RAPP transcript-to-prototype pipeline, and only that
slice: no transcript processing, no document ingestion, no LLM authoring.
Point it at a folder of BasicAgent ``*.py`` files (a "stack") and it:

  1. packages them into a connected-agents Copilot Studio solution — one
     orchestrator bot + one connected sub-agent bot per agent.py, each with a
     deterministic capability flow (delegated to the pipeline's
     ConnectedSolutionPackager, dynamically imported — see packager_path)
  2. imports the solution into the target Dataverse environment via the pure
     Web API (ImportSolutionAsync with a fixed idempotent ImportJobId,
     bounded backoff on 429/5xx, NO pac CLI, NO subprocess)
  3. polls importjobs(<id>) until completion — a "completed" job below 99.5%
     progress is treated as a FAILED import and the platform's own
     errortext is surfaced (transient flow-service 503s mid-provisioning)
  4. activates the imported capability flows (Draft -> Activated; a flow
     waiting on a connection binding reports pending_connection, which is the
     expected hook-into-your-data step, not a failure)
  5. publishes every bot — CHILDREN first, ORCHESTRATOR last (a connected-
     agent root cannot publish until its invoked sub-agents are published;
     wrong order 409s)

Also accepts a prebuilt connected-solution zip (``solution_zip``) and deploys
it the same way, recovering bot schemas / workflow ids / publish order from
the zip itself.

Credentials come ONLY from a settings file or env vars — never from chat, and
the secret is never echoed back. Same resolution chain as the pipeline:
explicit credentials_path (authoritative, fails loud) -> $RAPP_DEPLOY_SETTINGS
-> ~/.rapp_deploy_settings.json -> ./local.settings.json -> process env
(DYNAMICS_365_CLIENT_ID / _CLIENT_SECRET / _TENANT_ID / _RESOURCE).

Usage:
  CopilotStudioDeploy(stack_dir='~/my_stack', dry_run=True)          # package + validate only
  CopilotStudioDeploy(stack_dir='~/my_stack')                        # package, import, activate, publish
  CopilotStudioDeploy(stack_dir='~/my_stack', publish=False)         # import unpublished for review
  CopilotStudioDeploy(solution_zip='MyStack_connected_solution.zip', environment_url='https://org.crm.dynamics.com')
"""

import base64
import glob
import importlib.util
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path

try:
    from basic_agent import BasicAgent
except ModuleNotFoundError:
    from agents.basic_agent import BasicAgent

__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@kody-w/copilot_studio_deploy_agent",
    "version": "1.0.0",
    "display_name": "CopilotStudioDeploy",
    "description": "Deploy a folder of BasicAgent *.py files (or a prebuilt connected-solution zip) into a Copilot Studio environment: package as connected agents, ImportSolutionAsync over the pure Dataverse Web API, poll the import job, activate capability flows, publish children-first.",
    "author": "Kody Wildfeuer",
    "tags": ["copilot_studio", "deploy", "dataverse", "connected_agents", "power_platform", "stack"],
    "category": "integrations",
    "quality_tier": "official",
    "requires_env": [],
    "dependencies": ["@rapp/basic_agent"],
}

_AUTH_BASE = "https://login.microsoftonline.com"
_API = "/api/data/v9.2/"
# Where the pipeline's connected_solution_agent.py (the packager) is looked for
# when packager_path isn't given: next to this agent, then the pipeline checkout.
_PACKAGER_DEFAULT_CANDIDATES = [
    str(Path(__file__).resolve().parent / "connected_solution_agent.py"),
    os.path.expanduser("~/MSFTAIBASTRAPP/RAPPtranscript2Prototype/agents/connected_solution_agent.py"),
]


# --------------------------------------------------------------------------- #
# HTTP + Dataverse primitives (vendored from the pipeline deploy engine)      #
# --------------------------------------------------------------------------- #

def _http(url, data=None, headers=None, method=None, timeout=300):
    """Minimal stdlib HTTP: dict data -> form-encoded (OAuth), else JSON bytes."""
    if isinstance(data, dict):
        data = urllib.parse.urlencode(data).encode()
    elif data is not None and not isinstance(data, (bytes, bytearray)):
        data = json.dumps(data).encode()
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            return r.status, (json.loads(body) if body[:1] in ("{", "[") else body)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, body
    except Exception as e:  # network / DNS / timeout
        return 0, str(e)


def _call_with_backoff(fn, attempts=4, base_delay=2):
    """Bounded backoff on transient 429/5xx/network blips. fn -> (code, body)."""
    code, r = 0, None
    for n in range(attempts):
        code, r = fn()
        if code and code != 429 and code < 500:
            return code, r
        if n < attempts - 1:
            time.sleep(base_delay * (2 ** n))
    return code, r


def _extract_dyn_creds(creds):
    """From a settings dict ({IsEncrypted,Values} or bare), a Values dict, or a
    JSON string -> {client_id, client_secret, tenant_id, resource} or None."""
    if isinstance(creds, str):
        try:
            creds = json.loads(creds)
        except Exception:
            return None
    if not isinstance(creds, dict):
        return None
    vals = creds.get("Values", creds)
    cid, sec = vals.get("DYNAMICS_365_CLIENT_ID"), vals.get("DYNAMICS_365_CLIENT_SECRET")
    ten, res = vals.get("DYNAMICS_365_TENANT_ID"), vals.get("DYNAMICS_365_RESOURCE")
    if not all([cid, sec, ten, res]):
        return None
    return {"client_id": cid, "client_secret": sec, "tenant_id": ten,
            "resource": str(res).rstrip("/")}


def _deploy_creds(kwargs):
    """Resolve app-registration creds — settings file / env ONLY, never chat.
    Returns (creds_dict, source_label) or (None, reason).

    An explicit credentials_path is AUTHORITATIVE: only that file is considered,
    and it fails loudly naming the file rather than silently falling through to
    other creds (which could land the deploy in the WRONG environment)."""
    explicit = kwargs.get("credentials_path")
    if explicit:
        path = os.path.expanduser(explicit)
        if not os.path.isfile(path):
            return None, "%s unusable: file not found" % path
        try:
            raw = json.load(open(path))
        except Exception as e:
            return None, "%s unusable: not valid JSON (%s)" % (path, str(e)[:120])
        c = _extract_dyn_creds(raw)
        if not c:
            return None, ("%s unusable: missing required DYNAMICS_365_CLIENT_ID / "
                          "CLIENT_SECRET / TENANT_ID / RESOURCE" % path)
        return c, path
    candidates = [
        os.environ.get("RAPP_DEPLOY_SETTINGS"),
        os.path.expanduser("~/.rapp_deploy_settings.json"),
        "local.settings.json",
    ]
    for cand in candidates:
        if cand and os.path.isfile(cand):
            try:
                c = _extract_dyn_creds(json.load(open(cand)))
                if c:
                    return c, cand
            except Exception:
                pass
    c = _extract_dyn_creds({"Values": dict(os.environ)})
    if c:
        return c, "process env"
    return None, None


def _sp_token(client_id, secret, tenant, resource):
    """Service-principal (client-credentials) token for the Dataverse env."""
    code, t = _http(f"{_AUTH_BASE}/{tenant}/oauth2/v2.0/token",
                    data={"grant_type": "client_credentials", "client_id": client_id,
                          "client_secret": secret, "scope": resource.rstrip("/") + "/.default"},
                    headers={"Content-Type": "application/x-www-form-urlencoded"})
    if code != 200 or not isinstance(t, dict) or "access_token" not in t:
        raise RuntimeError("service-principal auth failed: " + str(t)[:200])
    return t["access_token"]


def _dataverse_action(resource, token, action, body=None, method="POST"):
    data = json.dumps(body).encode() if body is not None else None
    return _http(resource.rstrip("/") + _API + action, data=data, method=method,
                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json",
                          "Accept": "application/json", "OData-MaxVersion": "4.0",
                          "OData-Version": "4.0"})


# --------------------------------------------------------------------------- #
# deploy steps                                                                #
# --------------------------------------------------------------------------- #

def _import_solution_async(resource, token, zip_bytes, publish_workflows, overwrite):
    """Start the import (ImportSolutionAsync). The ImportJobId is fixed BEFORE
    the retry loop, so a retry reuses the SAME job id (idempotent — Dataverse
    treats it as the same import), never a duplicate. Returns (job_id, error)."""
    job_id = str(uuid.uuid4())
    code, r = _call_with_backoff(
        lambda: _dataverse_action(resource, token, "ImportSolutionAsync", {
            "OverwriteUnmanagedCustomizations": bool(overwrite),
            "PublishWorkflows": bool(publish_workflows),
            "ImportJobId": job_id,
            "CustomizationFile": base64.b64encode(zip_bytes).decode()}))
    if code == 429:
        return None, ("Dataverse is throttling requests right now (HTTP 429). "
                      "Wait a few seconds and deploy again.")
    if code not in (200, 202, 204):
        return None, "Import could not start (%s): %s" % (code, str(r)[:300])
    return job_id, None


def _poll_import_job(resource, token, job_id, timeout_seconds, interval=5):
    """Poll importjobs(<id>) until completedon. A completed job below ~100%%
    progress is a FAILED import — surface the platform's own errortext rather
    than blundering on to activate/publish components that don't exist."""
    import html as _html
    qs = urllib.parse.urlencode({"$select": "progress,completedon,data"})
    deadline = time.time() + max(30, int(timeout_seconds))
    last_progress = 0
    while time.time() < deadline:
        code, r = _call_with_backoff(
            lambda: _http(resource.rstrip("/") + _API + "importjobs(%s)?%s" % (job_id, qs),
                          headers={"Authorization": "Bearer " + token,
                                   "Accept": "application/json"}))
        if code == 404 or not isinstance(r, dict):
            time.sleep(interval)  # job row not materialized yet — still importing
            continue
        last_progress = r.get("progress") or last_progress
        if not r.get("completedon"):
            time.sleep(interval)
            continue
        if (r.get("progress") or 0) < 99.5:
            err = ""
            for m in re.finditer(r'errortext="([^"]+)"', r.get("data") or ""):
                if m.group(1).strip():
                    err = _html.unescape(m.group(1))[:400]
                    break
            return False, ("Solution import failed at %s%%: %s Re-deploy to retry "
                           "(transient platform errors are common)."
                           % (round(r.get("progress") or 0), err or "(no detail)"))
        return True, None
    return False, ("Import still running after %ss (last progress %s%%). Poll importjobs(%s) "
                   "or re-run — the fixed job id makes retries idempotent."
                   % (timeout_seconds, round(last_progress), job_id))


def _activate_flows(resource, token, workflow_ids):
    """Activate imported capability flows (Draft -> Activated). ImportSolution's
    PublishWorkflows alone leaves hand-packaged flows in Draft. A flow that can't
    activate because it needs a bound connection/consent is pending_connection —
    the expected bind-your-data step, NOT a deploy failure."""
    out = []
    for wf in workflow_ids or []:
        wf = str(wf).strip("{}")
        code, r = _http(
            resource.rstrip("/") + _API + "workflows(" + wf + ")",
            data=json.dumps({"statecode": 1, "statuscode": 2}).encode(),
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json",
                     "Accept": "application/json", "If-Match": "*"},
            method="PATCH")
        if code in (200, 204):
            out.append({"workflow_id": wf, "status": "activated"})
        else:
            err = str(r)[:300]
            low = err.lower()
            pending = ("connection" in low or "consent" in low
                       or "invalidopenapiflow" in low or "dynamicoperation" in low)
            out.append({"workflow_id": wf,
                        "status": "pending_connection" if pending else "activate_failed",
                        "error": err[:160]})
    return out


def _find_botid(resource, token, schema):
    qs = urllib.parse.urlencode({"$select": "botid,schemaname",
                                 "$filter": "schemaname eq '%s'" % schema,
                                 "$orderby": "createdon desc", "$top": "1"})
    code, r = _http(resource.rstrip("/") + _API + "bots?" + qs,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
    rows = (r.get("value") if isinstance(r, dict) else None) or []
    return rows[0]["botid"] if rows else None


def _publish_botid(botid, resource, token):
    """Publish ONE bot via the Dataverse PvaPublish Web API action."""
    code, r = _dataverse_action(resource, token,
                                "bots(%s)/Microsoft.Dynamics.CRM.PvaPublish" % botid, {})
    if code in (200, 204):
        return {"bot_id": botid, "status": "publish_requested", "via": "PvaPublish"}
    return {"bot_id": botid, "status": "publish_failed", "via": "PvaPublish",
            "error": str(r)[:160]}


def _publish_connected(bot_schemas, resource, token):
    """Publish every bot — CHILDREN first, ORCHESTRATOR last (a connected-agent
    root cannot publish until its invoked sub-agents are published; the wrong
    order fails with a 409 ExternalServiceException)."""
    if not bot_schemas:
        return []
    orch = bot_schemas[0]
    order = list(bot_schemas[1:]) + [orch]
    out = []
    for schema in order:
        botid = _find_botid(resource, token, schema)
        if not botid:
            out.append({"schema": schema, "status": "not_found"})
            continue
        out.append({"schema": schema, **_publish_botid(botid, resource, token)})
    return out


# --------------------------------------------------------------------------- #
# packaging: delegate the folder -> solution-zip step to the pipeline packager #
# --------------------------------------------------------------------------- #

def _load_packager_module(packager_path=None):
    """Dynamically import the pipeline's connected_solution_agent.py (the
    ConnectedSolutionPackager home). Returns (module, path) or (None, tried)."""
    tried = []
    candidates = ([os.path.expanduser(packager_path)] if packager_path
                  else list(_PACKAGER_DEFAULT_CANDIDATES))
    env = os.environ.get("RAPP_CSA_PATH")
    if not packager_path and env:
        candidates.insert(0, os.path.expanduser(env))
    for cand in candidates:
        tried.append(cand)
        if not os.path.isfile(cand):
            continue
        parent = str(Path(cand).resolve().parent)
        if parent not in sys.path:
            sys.path.insert(0, parent)
        spec = importlib.util.spec_from_file_location("_csd_packager", cand)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if hasattr(mod, "ConnectedSolutionPackager") and hasattr(mod, "_subagents_from_stack"):
            return mod, cand
    return None, tried


def _package_stack(stack_dir, kwargs):
    """Folder of agent.py files -> (zip_bytes, bot_schemas, workflow_ids,
    display_name, zip_path, validation_ok, packager_source)."""
    csa, src = _load_packager_module(kwargs.get("packager_path"))
    if csa is None:
        raise RuntimeError(
            "ConnectedSolutionPackager not found (tried: %s). Pass packager_path="
            "<path to the pipeline's connected_solution_agent.py>, set $RAPP_CSA_PATH, "
            "or drop that file next to this agent. Alternatively pass a prebuilt "
            "solution_zip and skip packaging entirely." % ", ".join(src))
    sd = Path(os.path.expanduser(str(stack_dir)))
    subs = csa._subagents_from_stack(sd, capir_mode=str(kwargs.get("capir_mode") or "auto"))
    if not subs:
        raise RuntimeError("No BasicAgent *.py files found in %s — nothing to deploy." % sd)
    fallback = re.sub(r"[_\-]+", " ", sd.name).strip().title() or "Agent Stack"
    unique = re.sub(r"[^A-Za-z0-9]", "",
                    str(kwargs.get("solution_name") or fallback.replace(" ", ""))) or "ConnectedAgents"
    display = kwargs.get("solution_display_name") or f"{fallback} Agents"
    spec = csa.ConnectedSolutionSpec(
        solution_unique_name=unique,
        solution_display_name=display,
        orchestrator_display_name=kwargs.get("orchestrator_name") or f"{fallback} Orchestrator",
        subagents=subs,
        orchestrator_channels=bool(kwargs.get("orchestrator_channels", False)),
        capability_mode=str(kwargs.get("capability_mode") or "flow"),
        topology=str(kwargs.get("topology") or "hierarchical"),
        solution_version=str(kwargs.get("version") or "1.0.0.0"),
        publisher_prefix=re.sub(r"[^a-z0-9]", "",
                                str(kwargs.get("publisher_prefix") or "rapp").lower())[:8] or "rapp",
    )
    packager = csa.ConnectedSolutionPackager(spec)
    out = Path(os.path.expanduser(str(kwargs.get("output_path")
                                      or f"{unique}_connected_solution.zip")))
    data = packager.package(output_path=out)
    ok = True
    if hasattr(csa, "validate_connected_solution"):
        ok = bool(csa.validate_connected_solution(out))
    return (data, list(packager.bot_schemas), list(packager.workflow_ids.values()),
            display, str(out), ok, src)


def _introspect_zip(zip_bytes):
    """Recover (bot_schemas orchestrator-first, workflow_ids, display_name) from
    a prebuilt connected-solution zip, so publish order and flow activation work
    without the packager. Orchestrators are the bots owning
    InvokeConnectedAgentTaskAction components; they publish LAST."""
    zf = zipfile.ZipFile(__import__("io").BytesIO(zip_bytes))
    names = zf.namelist()
    schemas = sorted({m.group(1) for n in names
                      for m in [re.match(r"^bots/([^/]+)/bot\.xml$", n)] if m})
    orchestrators = sorted({m.group(1) for n in names
                            for m in [re.match(r"^botcomponents/([^./]+)\.InvokeConnectedAgentTaskAction\.", n)] if m})
    children = [s for s in schemas if s not in orchestrators]
    bot_schemas = [s for s in orchestrators if s in schemas] + children  # orchestrator(s) first
    workflow_ids = []
    try:
        cust = zf.read("customizations.xml").decode("utf-8", "replace")
        workflow_ids = sorted(set(re.findall(
            r'<Workflow\s+WorkflowId="\{?([0-9a-fA-F-]{36})\}?"', cust)))
    except KeyError:
        pass
    if not workflow_ids:
        workflow_ids = sorted({m.group(1).lower() for n in names
                               for m in [re.match(r"^Workflows/.*-([0-9a-fA-F-]{36})\.json$", n)] if m})
    display = None
    try:
        sol = zf.read("solution.xml").decode("utf-8", "replace")
        m = re.search(r'<LocalizedName\s+description="([^"]+)"', sol)
        display = m.group(1) if m else None
        if not display:
            m = re.search(r"<UniqueName>([^<]+)</UniqueName>", sol)
            display = m.group(1) if m else None
    except KeyError:
        pass
    return bot_schemas, workflow_ids, display or "Connected Agents"


# --------------------------------------------------------------------------- #
# the agent                                                                   #
# --------------------------------------------------------------------------- #

class CopilotStudioDeployAgent(BasicAgent):
    def __init__(self):
        self.name = "CopilotStudioDeploy"
        self.metadata = {
            "name": self.name,
            "description": (
                "Deploys a grouping of agent.py files (a shared folder of BasicAgent *.py 'stack') into a Microsoft "
                "Copilot Studio environment as a connected-agents solution: one orchestrator bot + one connected "
                "sub-agent bot per agent file, each with a deterministic capability flow. Pure Dataverse Web API — "
                "ImportSolutionAsync with an idempotent job id and 429/5xx backoff, import-job polling that treats "
                "a sub-99.5% 'completed' job as a failed import (surfacing the platform errortext), Draft->Activated "
                "flow activation (connection-pending flows are the expected bind-your-data step, not failures), and "
                "publish ordered CHILDREN FIRST, ORCHESTRATOR LAST to avoid the connected-agent 409. Also deploys a "
                "prebuilt connected-solution zip directly. Credentials are read from a settings file or env vars "
                "(DYNAMICS_365_CLIENT_ID/_CLIENT_SECRET/_TENANT_ID/_RESOURCE), never from chat, and the secret is "
                "never echoed. This is ONLY the deploy step of the RAPP pipeline — no transcript or document processing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "stack_dir": {
                        "type": "string",
                        "description": "Path to the shared folder containing the agent.py files to deploy (BasicAgent subclasses; basic_agent.py and _* files are skipped). Provide this OR solution_zip.",
                    },
                    "solution_zip": {
                        "type": "string",
                        "description": "Path to a prebuilt connected-solution .zip to import as-is (skips packaging). Bot publish order and flow ids are recovered from the zip. Provide this OR stack_dir.",
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "If true, only package and validate the solution (or introspect the given zip) and report what WOULD be deployed — no Dataverse calls, no credentials needed. Default false.",
                    },
                    "publish": {
                        "type": "boolean",
                        "description": "If true (default) publish every bot after import, children first then orchestrator. If false, import unpublished so an operator can review and publish inside Copilot Studio.",
                    },
                    "solution_name": {
                        "type": "string",
                        "description": "Solution unique name (alphanumeric). Defaults to the stack folder name.",
                    },
                    "solution_display_name": {
                        "type": "string",
                        "description": "Solution display name shown in Copilot Studio / Solutions. Defaults to '<Folder Name> Agents'.",
                    },
                    "orchestrator_name": {
                        "type": "string",
                        "description": "Display name for the orchestrator (root) bot. Defaults to '<Folder Name> Orchestrator'.",
                    },
                    "publisher_prefix": {
                        "type": "string",
                        "description": "Dataverse publisher customization prefix for bot schema names (max 8 chars, lowercase alphanumeric). Default 'rapp'. Use a fresh prefix to mint brand-new bots instead of updating existing ones.",
                    },
                    "topology": {
                        "type": "string",
                        "enum": ["hierarchical", "flat"],
                        "description": "hierarchical (default) = orchestrator + one connected child bot per agent.py. flat = a single orchestrator with each capability attached directly as a tool, no child bots.",
                    },
                    "capir_mode": {
                        "type": "string",
                        "enum": ["auto", "static", "embedded", "off"],
                        "description": "How each agent.py's capability IR is resolved by the packager. Default 'auto'.",
                    },
                    "environment_url": {
                        "type": "string",
                        "description": "Target Dataverse environment URL, e.g. https://orgXXXX.crm.dynamics.com. Overrides the DYNAMICS_365_RESOURCE from the resolved credentials, so one app registration can deploy to multiple environments.",
                    },
                    "credentials_path": {
                        "type": "string",
                        "description": "Path to a local.settings.json-style file holding DYNAMICS_365_CLIENT_ID / _CLIENT_SECRET / _TENANT_ID / _RESOURCE. When given it is AUTHORITATIVE — no fallback to env or home settings. When omitted the chain is $RAPP_DEPLOY_SETTINGS -> ~/.rapp_deploy_settings.json -> ./local.settings.json -> process env.",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Where to write the packaged solution zip when building from stack_dir. Defaults to ./<SolutionName>_connected_solution.zip.",
                    },
                    "packager_path": {
                        "type": "string",
                        "description": "Path to the pipeline's connected_solution_agent.py providing ConnectedSolutionPackager. Defaults: $RAPP_CSA_PATH, a copy next to this agent, then ~/MSFTAIBASTRAPP/RAPPtranscript2Prototype/agents/connected_solution_agent.py. Not needed when deploying a prebuilt solution_zip.",
                    },
                    "poll_timeout_seconds": {
                        "type": "integer",
                        "description": "How long to wait for the Dataverse import job to complete before giving up (the import keeps running server-side; retries are idempotent). Default 600.",
                    },
                    "overwrite_unmanaged": {
                        "type": "boolean",
                        "description": "Pass OverwriteUnmanagedCustomizations=true on import (overwrites unmanaged layers of existing components). Default false — the safer choice for shared environments.",
                    },
                },
                "required": [],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        stack_dir, solution_zip = kwargs.get("stack_dir"), kwargs.get("solution_zip")
        if not stack_dir and not solution_zip:
            return self._result("needs_input",
                                "Provide 'stack_dir' (a shared folder of BasicAgent agent.py files) "
                                "or 'solution_zip' (a prebuilt connected-solution zip).")
        try:
            # ---- 1. get solution bytes + deploy handles ----------------------
            if stack_dir:
                sd = Path(os.path.expanduser(str(stack_dir)))
                if not sd.is_dir():
                    return self._result("error", f"stack_dir not found: {sd}")
                (zip_bytes, bot_schemas, workflow_ids, display,
                 zip_path, valid, pk_src) = _package_stack(sd, kwargs)
                agent_count = max(len(bot_schemas) - 1, 0)
                built = (f"Packaged {agent_count} agent.py file(s) from {sd} into '{Path(zip_path).name}' "
                         f"({round(len(zip_bytes) / 1024, 1)} KB, validation: {'pass' if valid else 'FAIL'}, "
                         f"packager: {pk_src}).")
                if not valid:
                    return self._result("error", built + " Not deploying an invalid solution.",
                                        {"solution_zip": zip_path})
            else:
                zp = Path(os.path.expanduser(str(solution_zip)))
                if not zp.is_file():
                    return self._result("error", f"solution_zip not found: {zp}")
                zip_bytes = zp.read_bytes()
                bot_schemas, workflow_ids, display = _introspect_zip(zip_bytes)
                zip_path = str(zp)
                built = (f"Using prebuilt '{zp.name}' ({round(len(zip_bytes) / 1024, 1)} KB): "
                         f"{len(bot_schemas)} bot(s), {len(workflow_ids)} capability flow(s).")

            plan = {
                "solution_zip": zip_path,
                "display_name": display,
                "bot_schemas_publish_order": (bot_schemas[1:] + bot_schemas[:1]) if bot_schemas else [],
                "workflow_ids": workflow_ids,
            }
            if kwargs.get("dry_run"):
                return self._result("success", built + " DRY RUN — nothing was sent to Dataverse. "
                                    "Re-run without dry_run to import" +
                                    (", activate flows and publish." if kwargs.get("publish", True) else "."),
                                    plan)

            # ---- 2. credentials + token --------------------------------------
            creds, src = _deploy_creds(kwargs)
            if creds and kwargs.get("environment_url"):
                creds = {**creds, "resource": str(kwargs["environment_url"]).rstrip("/")}
            if not creds:
                return self._result("needs_input",
                                    built + " NOT deployed — no app-registration credentials found"
                                    + (f" ({src})." if src else ".") +
                                    " Set env DYNAMICS_365_CLIENT_ID / DYNAMICS_365_CLIENT_SECRET / "
                                    "DYNAMICS_365_TENANT_ID / DYNAMICS_365_RESOURCE, pass "
                                    "credentials_path=<local.settings.json>, or place "
                                    "~/.rapp_deploy_settings.json. Secrets never travel through chat.",
                                    plan)
            resource = creds["resource"]
            try:
                token = _sp_token(creds["client_id"], creds["client_secret"],
                                  creds["tenant_id"], resource)
            except Exception as e:
                return self._result("error", built + f" NOT deployed — service-principal auth failed: "
                                    f"{str(e)[:300]} (creds source: {src}, environment: {resource})", plan)

            # ---- 3. import + poll --------------------------------------------
            publish = bool(kwargs.get("publish", True))
            job_id, err = _import_solution_async(resource, token, zip_bytes,
                                                 publish_workflows=publish,
                                                 overwrite=kwargs.get("overwrite_unmanaged", False))
            if err:
                return self._result("error", built + " Import FAILED to start: " + err,
                                    {**plan, "environment": resource, "creds_source": src})
            ok, err = _poll_import_job(resource, token, job_id,
                                       kwargs.get("poll_timeout_seconds") or 600)
            if not ok:
                return self._result("error", built + " " + (err or "Import failed."),
                                    {**plan, "environment": resource,
                                     "import_job_id": job_id, "creds_source": src})

            # ---- 4. activate flows + 5. publish children-first ----------------
            activated = _activate_flows(resource, token, workflow_ids)
            nact = sum(1 for a in activated if a.get("status") == "activated")
            npend = sum(1 for a in activated if a.get("status") == "pending_connection")
            published = _publish_connected(bot_schemas, resource, token) if publish else []
            npub = sum(1 for p in published if p.get("status") in ("published", "publish_requested"))

            errors = []
            for a in activated:
                if a.get("status") == "activate_failed":
                    errors.append("flow %s activate_failed: %s"
                                  % (a.get("workflow_id"), str(a.get("error", ""))[:120]))
            for p in published:
                if p.get("status") in ("publish_failed", "not_found"):
                    errors.append("bot %s %s%s" % (p.get("schema"), p.get("status"),
                                                   (": " + str(p.get("error"))[:120]) if p.get("error") else ""))

            summary = (built + " Imported into " + resource + ", "
                       + (("activated %d/%d flows, " % (nact, len(activated))) if activated else "")
                       + (("%d flow(s) pending connection binding (bind under Solutions > "
                           "Connection references, then turn them on), " % npend) if npend else "")
                       + (("published %d/%d bots. " % (npub, len(published))) if publish
                          else "left unpublished for review in Copilot Studio. ")
                       + "Open https://copilotstudio.microsoft.com, pick that environment, open '"
                       + str(display)[:42] + "' and use the Test pane.")
            if errors:
                summary += (" %d step(s) FAILED — " % len(errors)) + "; ".join(errors)
            return self._result("success" if not errors else "partial", summary, {
                **plan,
                "environment": resource,
                "import_job_id": job_id,
                "creds_source": src,
                "publish_enabled": publish,
                "flows_activated": activated,
                "published": published,
                "errors": errors,
                "test_in_studio": "https://copilotstudio.microsoft.com",
            })
        except Exception as exc:  # surface, never crash the chat loop
            return self._result("error", f"{type(exc).__name__}: {exc}")

    def _result(self, status, message, data=None):
        out = {"status": status, "agent": self.name, "message": message}
        if data is not None:
            out["data"] = data
        return out


def main():
    """CLI smoke: python3 copilot_studio_deploy_agent.py <stack_dir_or_zip> [--dry-run] [--no-publish]"""
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    kwargs = {}
    if args:
        target = args[0]
        kwargs["solution_zip" if target.lower().endswith(".zip") else "stack_dir"] = target
    kwargs["dry_run"] = "--dry-run" in sys.argv
    if "--no-publish" in sys.argv:
        kwargs["publish"] = False
    print(json.dumps(CopilotStudioDeployAgent().perform(**kwargs), indent=2, default=str))


if __name__ == "__main__":
    main()
