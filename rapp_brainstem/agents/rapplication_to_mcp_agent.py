"""RapplicationToMcp — convert a rapplication into an M365 Copilot MCP app (declarative agent + MCP server + UI widget).

WHAT IT DOES
Takes a RAPP rapplication (a directory with a `manifest.json` of schema
`rapp-rapplication/1.0`, bundled `agents/*_agent.py`, an optional `soul.md`
and an optional `web/` UI) — or any directory of drop-in agents, or a single
agent file — and generates a complete, runnable MCP app package following the
Microsoft 365 Copilot MCP-apps pattern
(https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/plugin-mcp-apps):

  <output>/
    server/                    dependency-free streamable-HTTP MCP server (pure stdlib)
      mcp_server.py            exposes every bundled agent's perform() as an MCP tool,
                               each tool tagged with _meta["openai/outputTemplate"] and
                               _meta.ui.resourceUri pointing at the ui:// widget resource
      web/app.html             the UI widget (rapplication's web/index.html with an
                               MCP bridge injected, or a generated result-viewer widget
                               with window.openai.* availability checks)
      agents/                  the bundled agents + basic_agent.py + storage shim
      config.json              name / port / server_url / widget wiring
    appPackage/
      manifest.json            Teams app manifest (copilotAgents.declarativeAgents)
      declarativeAgent.json    declarative agent (soul.md becomes `instructions`)
      ai-plugin.json           v2.3 plugin manifest with an MCP runtime
      color.png, outline.png   generated placeholder icons
    <name>-appPackage.zip      sideloadable package
    .vscode/mcp.json           Agents Toolkit "Start / Fetch action from MCP" wiring
    README.md                  dev-tunnel + provisioning walkthrough

The generated server is REAL, not a mock: it speaks MCP JSON-RPC
(initialize / tools/list / tools/call / resources/list / resources/read),
reloads agents from disk on every request (brainstem philosophy), and serves
the widget as a `ui://` resource with mimeType `text/html+skybridge`.
Flip the dev `server_url` to a devtunnel/hosted HTTPS URL and the same
package provisions into Copilot unchanged.

Usage:
  RapplicationToMcp(action='list')                                   # find rapplications on this machine
  RapplicationToMcp(action='inspect', path='~/.brainstem/cubbies/deploy-os/rapplications/deploy-os')
  RapplicationToMcp(action='convert', path='<rapplication dir>', output_path='./deploy-os_mcp_app',
                    server_url='https://xyz.devtunnels.ms/mcp', port=8787)
"""

import ast
import json
import os
import re
import shutil
import struct
import sys
import uuid
import zipfile
import zlib
from pathlib import Path

try:
    from basic_agent import BasicAgent
except ModuleNotFoundError:
    from agents.basic_agent import BasicAgent

__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@kody-w/rapplication_to_mcp_agent",
    "version": "1.0.0",
    "display_name": "RapplicationToMcp",
    "description": "Convert a rapplication (manifest + bundled agents + web UI) into a Microsoft 365 Copilot MCP app: declarative agent package + stdlib MCP server whose tools render ui:// widgets in Copilot chat.",
    "author": "Kody Wildfeuer",
    "tags": ["mcp", "copilot", "declarative_agent", "mcp_apps", "ui_widgets", "converter", "rapplication"],
    "category": "integrations",
    "quality_tier": "official",
    "requires_env": [],
    "dependencies": ["@rapp/basic_agent"],
}

_RAPPLICATION_SCHEMA = "rapp-rapplication/1.0"
_AGENT_FILE_RE = re.compile(r"^[a-z][a-z0-9_]*_agent\.py$")
_SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build"}


class RapplicationToMcpAgent(BasicAgent):
    def __init__(self):
        self.name = "RapplicationToMcp"
        self.metadata = {
            "name": self.name,
            "description": (
                "Converts a rapplication into a Microsoft 365 Copilot MCP app (the plugin-mcp-apps pattern): "
                "generates a runnable dependency-free MCP server that exposes each bundled agent's perform() as an MCP tool "
                "with a ui:// interactive widget (MCP Apps / OpenAI Apps SDK _meta wiring), plus the full declarative-agent "
                "appPackage (manifest.json, declarativeAgent.json with soul.md as instructions, ai-plugin.json with an MCP runtime, "
                "icons, sideloadable zip). Use action='list' to discover rapplications on this machine, action='inspect' to preview "
                "what a conversion would produce without writing files, and action='convert' to generate the package."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["convert", "inspect", "list"],
                        "description": "convert = generate the MCP app package; inspect = dry-run report of what would be generated; list = discover rapplications (rapp-rapplication/1.0 manifests) under root.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Path to the rapplication to convert/inspect: a directory containing manifest.json (schema rapp-rapplication/1.0), OR any directory containing *_agent.py drop-in agents, OR a single *_agent.py file. Required for convert/inspect.",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Directory to write the generated MCP app package into. Defaults to ./<name>_mcp_app next to the current working directory. Created if missing; existing generated files are overwritten.",
                    },
                    "server_url": {
                        "type": "string",
                        "description": "Public URL Copilot will call for the MCP server, e.g. https://<tunnel>.devtunnels.ms/mcp. Defaults to http://localhost:<port>/mcp (dev only — Copilot itself requires HTTPS; the README explains the devtunnel step).",
                    },
                    "port": {
                        "type": "integer",
                        "description": "Local port the generated MCP server listens on. Default 8787.",
                    },
                    "root": {
                        "type": "string",
                        "description": "For action='list': directory tree to scan for rapplication manifests. Defaults to ~/.brainstem plus the current working directory.",
                    },
                },
                "required": ["action"],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    # ------------------------------------------------------------------ #
    # dispatch                                                           #
    # ------------------------------------------------------------------ #

    def perform(self, **kwargs):
        action = (kwargs.get("action") or "").strip().lower()
        try:
            if action == "list":
                return self._list(kwargs.get("root"))
            if action in ("convert", "inspect"):
                path = kwargs.get("path")
                if not path:
                    return self._result("needs_input", "Give me the path to the rapplication (its directory with manifest.json), a directory of *_agent.py files, or a single agent file.")
                app = self._load_rapplication(Path(os.path.expanduser(path)))
                if action == "inspect":
                    return self._inspect(app)
                return self._convert(app, kwargs)
            return self._result("error", f"Unknown action '{action}'. Use convert, inspect, or list.")
        except FileNotFoundError as exc:
            return self._result("error", str(exc))
        except Exception as exc:  # surface, don't crash the chat loop
            return self._result("error", f"{type(exc).__name__}: {exc}")

    def _result(self, status, message, data=None):
        out = {"status": status, "agent": self.name, "message": message}
        if data is not None:
            out["data"] = data
        return out

    # ------------------------------------------------------------------ #
    # discovery                                                          #
    # ------------------------------------------------------------------ #

    def _list(self, root):
        roots = []
        if root:
            roots.append(Path(os.path.expanduser(root)))
        else:
            roots.append(Path.home() / ".brainstem")
            roots.append(Path.cwd())
        found, seen = [], set()
        for base in roots:
            if not base.is_dir():
                continue
            base = base.resolve()
            for dirpath, dirnames, filenames in os.walk(base):
                rel_depth = len(Path(dirpath).relative_to(base).parts)
                dirnames[:] = [] if rel_depth >= 6 else [d for d in dirnames if d not in _SKIP_DIRS]
                if "manifest.json" not in filenames:
                    continue
                mpath = Path(dirpath) / "manifest.json"
                try:
                    manifest = json.loads(mpath.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if manifest.get("schema") != _RAPPLICATION_SCHEMA:
                    continue
                key = str(mpath.parent)
                if key in seen:
                    continue
                seen.add(key)
                found.append({
                    "name": manifest.get("name"),
                    "display_name": manifest.get("display_name", manifest.get("name")),
                    "path": key,
                    "bundled_agents": manifest.get("bundled_agents", []),
                    "has_web_ui": bool(manifest.get("ui")) and (mpath.parent / str(manifest.get("ui"))).is_file(),
                })
        msg = f"Found {len(found)} rapplication(s). Use action='convert' with one of these paths." if found \
            else "No rapp-rapplication/1.0 manifests found. You can still convert any directory of *_agent.py files by passing its path."
        return self._result("success", msg, {"rapplications": found})

    # ------------------------------------------------------------------ #
    # loading a rapplication (or bare agents)                            #
    # ------------------------------------------------------------------ #

    def _load_rapplication(self, path):
        if not path.exists():
            raise FileNotFoundError(f"Path not found: {path}")
        app = {
            "path": path, "manifest": None, "name": None, "display_name": None,
            "summary": None, "instructions": None, "web_ui_html": None,
            "web_ui_source": None, "agent_files": [],
        }
        if path.is_file():
            if not _AGENT_FILE_RE.match(path.name):
                raise FileNotFoundError(f"{path.name} is not a *_agent.py drop-in agent file.")
            app["agent_files"] = [path]
            app["name"] = path.stem.replace("_agent", "")
        else:
            mpath = path / "manifest.json"
            if mpath.is_file():
                try:
                    manifest = json.loads(mpath.read_text(encoding="utf-8"))
                except Exception as exc:
                    raise FileNotFoundError(f"manifest.json in {path} is not valid JSON: {exc}")
                app["manifest"] = manifest
                app["name"] = manifest.get("name") or path.name
                app["display_name"] = manifest.get("display_name") or app["name"]
                app["summary"] = manifest.get("summary") or manifest.get("description")
                ui_rel = manifest.get("ui")
                if ui_rel and (path / ui_rel).is_file():
                    app["web_ui_html"] = (path / ui_rel).read_text(encoding="utf-8", errors="replace")
                    app["web_ui_source"] = str(path / ui_rel)
            else:
                app["name"] = path.name
            soul = path / "soul.md"
            if soul.is_file():
                app["instructions"] = soul.read_text(encoding="utf-8", errors="replace")
            agents_dir = path / "agents"
            search_dirs = [agents_dir] if agents_dir.is_dir() else [path]
            files = []
            for d in search_dirs:
                for f in sorted(d.rglob("*_agent.py")):
                    if _AGENT_FILE_RE.match(f.name) and f.name != "basic_agent.py" \
                            and not any(p in ("experimental", "experimental_agents", "disabled_agents") for p in f.relative_to(d).parts):
                        files.append(f)
            app["agent_files"] = files
        if not app["agent_files"]:
            raise FileNotFoundError(f"No *_agent.py agents found under {path} — nothing to expose as MCP tools.")
        app["name"] = re.sub(r"[^A-Za-z0-9_-]+", "-", str(app["name"])).strip("-") or "rapplication"
        app["display_name"] = app["display_name"] or app["name"]
        app["summary"] = app["summary"] or f"MCP app generated from the '{app['name']}' rapplication. Its agents run as MCP tools with interactive widgets in Microsoft 365 Copilot."
        app["tools"] = self._extract_tools(app["agent_files"])
        if not app["tools"]:
            raise FileNotFoundError("Found agent files but could not extract any tool metadata (import and AST parse both failed).")
        return app

    # ------------------------------------------------------------------ #
    # tool metadata extraction: import first, AST literal fallback       #
    # ------------------------------------------------------------------ #

    def _extract_tools(self, agent_files):
        tools, seen = [], set()
        for f in agent_files:
            meta = None
            try:
                meta = self._metadata_via_import(f)
            except Exception:
                meta = None
            if meta is None:
                try:
                    meta = self._metadata_via_ast(f)
                except Exception:
                    meta = None
            if not meta:
                continue
            name = re.sub(r"[^A-Za-z0-9_]", "_", str(meta.get("name") or f.stem))
            if name in seen:
                continue
            seen.add(name)
            tools.append({
                "name": name,
                "description": str(meta.get("description") or "")[:4000],
                "parameters": meta.get("parameters") or {"type": "object", "properties": {}},
                "file": str(f),
                "extraction": meta.get("_extraction", "import"),
            })
        return tools

    def _metadata_via_import(self, f):
        import importlib.util
        for extra in (str(f.parent), str(Path(__file__).resolve().parents[1])):
            if extra not in sys.path:
                sys.path.insert(0, extra)
        spec = importlib.util.spec_from_file_location(f"_rapp2mcp_{f.stem}_{abs(hash(str(f)))}", f)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for obj in vars(mod).values():
            if isinstance(obj, type) and issubclass(obj, BasicAgent) and obj is not BasicAgent:
                inst = obj()
                md = dict(getattr(inst, "metadata", {}) or {})
                if md.get("name"):
                    return md
        for obj in vars(mod).values():  # duck-typed agents not importing our BasicAgent instance
            if isinstance(obj, type) and hasattr(obj, "perform") and obj.__name__ != "BasicAgent" \
                    and obj.__module__ == mod.__name__:
                inst = obj()
                md = dict(getattr(inst, "metadata", {}) or {})
                if md.get("name"):
                    return md
        return None

    def _metadata_via_ast(self, f):
        """Extract `self.metadata = {...}` as a literal, substituting `self.name = "X"` first."""
        tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            self_name, meta_node = None, None
            for node in ast.walk(cls):
                if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                        and isinstance(node.targets[0], ast.Attribute) \
                        and isinstance(node.targets[0].value, ast.Name) \
                        and node.targets[0].value.id == "self":
                    attr = node.targets[0].attr
                    if attr == "name" and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        self_name = node.value.value
                    elif attr == "metadata" and isinstance(node.value, ast.Dict):
                        meta_node = node.value
            if meta_node is None:
                continue

            class _SelfName(ast.NodeTransformer):
                def visit_Attribute(self, node):  # noqa: N802
                    if isinstance(node.value, ast.Name) and node.value.id == "self" and node.attr == "name":
                        return ast.copy_location(ast.Constant(value=self_name or cls.name), node)
                    return self.generic_visit(node)

            expr = ast.Expression(body=_SelfName().visit(meta_node))
            ast.fix_missing_locations(expr)
            try:
                md = eval(compile(expr, filename=str(f), mode="eval"), {"__builtins__": {}}, {})  # noqa: S307 — literals only after transform
            except Exception:
                continue
            if isinstance(md, dict) and md.get("name"):
                md["_extraction"] = "ast"
                return md
        return None

    # ------------------------------------------------------------------ #
    # inspect                                                            #
    # ------------------------------------------------------------------ #

    def _inspect(self, app):
        return self._result("success",
            f"'{app['name']}' converts cleanly: {len(app['tools'])} MCP tool(s), "
            f"widget from {'its own web UI (' + str(app['web_ui_source']) + ')' if app['web_ui_html'] else 'the generated result-viewer template'}, "
            f"instructions from {'soul.md' if app['instructions'] else 'the manifest summary'}. "
            "Run action='convert' to generate the package.",
            {
                "name": app["name"],
                "display_name": app["display_name"],
                "tools": [{"name": t["name"], "description": t["description"][:200], "extraction": t["extraction"]} for t in app["tools"]],
                "widget_source": app["web_ui_source"] or "generated result-viewer",
                "has_soul_instructions": bool(app["instructions"]),
            })

    # ------------------------------------------------------------------ #
    # convert                                                            #
    # ------------------------------------------------------------------ #

    def _convert(self, app, kwargs):
        port = int(kwargs.get("port") or 8787)
        server_url = kwargs.get("server_url") or f"http://localhost:{port}/mcp"
        out = Path(os.path.expanduser(kwargs.get("output_path") or f"{app['name']}_mcp_app")).resolve()
        slug = re.sub(r"[^a-z0-9_]", "_", app["name"].lower()) or "rapplication"
        widget_uri = f"ui://{slug}/app.html"

        server_dir = out / "server"
        (server_dir / "agents").mkdir(parents=True, exist_ok=True)
        (server_dir / "web").mkdir(parents=True, exist_ok=True)
        pkg_dir = out / "appPackage"
        pkg_dir.mkdir(parents=True, exist_ok=True)
        (out / ".vscode").mkdir(parents=True, exist_ok=True)

        # --- server: agents + runtime support files ---------------------
        for f in app["agent_files"]:
            shutil.copy2(f, server_dir / "agents" / Path(f).name)
        brain_root = Path(__file__).resolve().parents[1]
        basic = brain_root / "agents" / "basic_agent.py"
        if not basic.is_file():
            basic = brain_root / "basic_agent.py"
        if basic.is_file():
            shutil.copy2(basic, server_dir / "agents" / "basic_agent.py")
        else:
            (server_dir / "agents" / "basic_agent.py").write_text(_FALLBACK_BASIC_AGENT, encoding="utf-8")
        storage = brain_root / "local_storage.py"
        if storage.is_file():
            shutil.copy2(storage, server_dir / "local_storage.py")
        else:
            (server_dir / "local_storage.py").write_text(_FALLBACK_LOCAL_STORAGE, encoding="utf-8")

        # --- widget ------------------------------------------------------
        if app["web_ui_html"]:
            widget = self._inject_bridge(app["web_ui_html"])
            widget_source = app["web_ui_source"]
        else:
            widget = _WIDGET_HTML.replace("__APP_TITLE__", app["display_name"])
            widget_source = "generated result-viewer"
        (server_dir / "web" / "app.html").write_text(widget, encoding="utf-8")

        # --- server config + runtime --------------------------------------
        config = {
            "name": app["name"],
            "display_name": app["display_name"],
            "version": (app["manifest"] or {}).get("version", "1.0.0"),
            "port": port,
            "server_url": server_url,
            "widget": {"resource_uri": widget_uri, "html": "web/app.html", "mime_type": "text/html+skybridge"},
            "generated_from": str(app["path"]),
            "generator": "@kody-w/rapplication_to_mcp_agent",
        }
        (server_dir / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
        (server_dir / "mcp_server.py").write_text(_SERVER_PY, encoding="utf-8")

        # --- appPackage ----------------------------------------------------
        display = app["display_name"]
        summary = app["summary"]
        instructions = (app["instructions"] or f"You are {display}. {summary} Use the MCP tools to do real work; the tools render interactive widgets in the chat.").strip()[:8000]
        tool_names = [t["name"] for t in app["tools"]]

        ai_plugin = {
            "$schema": "https://developer.microsoft.com/json-schemas/copilot/plugin/v2.3/schema.json",
            "schema_version": "v2.3",
            "name_for_human": display[:100],
            "description_for_human": summary[:100],
            "description_for_model": (f"MCP tools generated from the '{app['name']}' rapplication. " + summary)[:2048],
            "namespace": slug[:64],
            "contact_email": "publisher@example.com",
            "runtimes": [{
                "type": "mcp",
                "spec": {"url": server_url},
                "run_for_functions": tool_names,
            }],
            "functions": [{"name": t["name"], "description": (t["description"] or t["name"])[:100]} for t in app["tools"]],
        }
        declarative_agent = {
            "$schema": "https://developer.microsoft.com/json-schemas/copilot/declarative-agent/v1.5/schema.json",
            "version": "v1.5",
            "name": display[:100],
            "description": summary[:1000],
            "instructions": instructions,
            "actions": [{"id": f"{slug}_mcp", "file": "ai-plugin.json"}],
        }
        teams_manifest = {
            "$schema": "https://developer.microsoft.com/json-schemas/teams/v1.19/MicrosoftTeams.schema.json",
            "manifestVersion": "1.19",
            "version": "1.0.0",
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"rapp-mcp-app:{app['name']}")),
            "developer": {
                "name": "RAPP",
                "websiteUrl": "https://kody-w.github.io/rapp-installer",
                "privacyUrl": "https://kody-w.github.io/rapp-installer",
                "termsOfUseUrl": "https://kody-w.github.io/rapp-installer",
            },
            "name": {"short": display[:30], "full": display[:100]},
            "description": {"short": summary[:80], "full": summary[:4000]},
            "icons": {"color": "color.png", "outline": "outline.png"},
            "accentColor": "#5B2D90",
            "copilotAgents": {"declarativeAgents": [{"id": slug[:64], "file": "declarativeAgent.json"}]},
            "validDomains": [],
        }
        (pkg_dir / "ai-plugin.json").write_text(json.dumps(ai_plugin, indent=2), encoding="utf-8")
        (pkg_dir / "declarativeAgent.json").write_text(json.dumps(declarative_agent, indent=2), encoding="utf-8")
        (pkg_dir / "manifest.json").write_text(json.dumps(teams_manifest, indent=2), encoding="utf-8")
        (pkg_dir / "color.png").write_bytes(_png(192, 192, (91, 45, 144, 255)))
        (pkg_dir / "outline.png").write_bytes(_png(32, 32, (255, 255, 255, 255)))

        zip_path = out / f"{app['name']}-appPackage.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for name in ("manifest.json", "declarativeAgent.json", "ai-plugin.json", "color.png", "outline.png"):
                z.write(pkg_dir / name, name)

        (out / ".vscode" / "mcp.json").write_text(json.dumps(
            {"servers": {slug: {"type": "http", "url": server_url}}}, indent=2), encoding="utf-8")

        readme = (_README_MD
                  .replace("__NAME__", app["name"])
                  .replace("__DISPLAY__", display)
                  .replace("__PORT__", str(port))
                  .replace("__SERVER_URL__", server_url)
                  .replace("__WIDGET_URI__", widget_uri)
                  .replace("__TOOLS__", "\n".join(f"- `{t['name']}` — {t['description'][:120]}" for t in app["tools"])))
        (out / "README.md").write_text(readme, encoding="utf-8")

        https_note = "" if server_url.startswith("https://") else \
            " NOTE: server_url is a local http URL — fine for MCP Inspector / local testing, but Copilot provisioning needs a public HTTPS URL (see README devtunnel step, then re-run convert with server_url=...)."
        return self._result("success",
            f"Generated the '{display}' MCP app at {out}: {len(app['tools'])} tool(s) exposed as MCP tools with the {widget_uri} widget "
            f"({widget_source}), declarative-agent appPackage zipped and sideloadable. "
            f"Start the server with: python3 {server_dir / 'mcp_server.py'}." + https_note,
            {
                "output_path": str(out),
                "server": str(server_dir / "mcp_server.py"),
                "server_url": server_url,
                "port": port,
                "app_package_zip": str(zip_path),
                "widget_resource_uri": widget_uri,
                "widget_source": widget_source,
                "tools": tool_names,
                "next_steps": [
                    f"python3 {server_dir / 'mcp_server.py'}  # starts the MCP server on port {port}",
                    "devtunnel host -p __PORT__ --allow-anonymous  # get a public HTTPS URL, then re-run convert with server_url".replace("__PORT__", str(port)),
                    "Open the output folder in VS Code with Agents Toolkit >= 6.6.1, sign in to M365, Lifecycle > Provision",
                    f"Or sideload {zip_path.name} directly, then test at https://m365.cloud.microsoft/chat",
                ],
            })

    # ------------------------------------------------------------------ #
    # widget bridge injection for existing rapplication web UIs          #
    # ------------------------------------------------------------------ #

    def _inject_bridge(self, html):
        script = "<script>\n" + _BRIDGE_JS + "\n</script>"
        m = re.search(r"</body\s*>", html, flags=re.IGNORECASE)
        if m:
            return html[:m.start()] + script + "\n" + html[m.start():]
        return html + "\n" + script


# ---------------------------------------------------------------------- #
# generated-file templates (kept interpolation-free; tokens are replaced) #
# ---------------------------------------------------------------------- #

_png_cache = {}


def _png(width, height, rgba):
    """Minimal valid PNG (RGBA, solid color) — stdlib only, for the required app icons."""
    key = (width, height, rgba)
    if key in _png_cache:
        return _png_cache[key]
    raw = b"".join(b"\x00" + bytes(rgba) * width for _ in range(height))

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    _png_cache[key] = png
    return png


_BRIDGE_JS = r"""
// RAPP -> MCP app bridge (injected by RapplicationToMcp).
// Maps the rapplication's local twin endpoints onto the Copilot component bridge,
// with availability checks per the M365 MCP-apps guidance (unsupported APIs are undefined).
(function () {
  'use strict';
  var hasOpenAI = typeof window.openai === 'object' && window.openai !== null;
  var canCallTool = hasOpenAI && typeof window.openai.callTool === 'function';
  if (!hasOpenAI) return; // running outside Copilot (e.g. the rapplication's own serve.py) — leave fetch alone
  var realFetch = window.fetch ? window.fetch.bind(window) : null;
  window.fetch = function (url, opts) {
    var m = String(url).match(/\/api\/agent\/([A-Za-z0-9_]+)/);
    if (m && canCallTool) {
      var args = {};
      try { if (opts && opts.body) args = JSON.parse(opts.body); } catch (e) { args = {}; }
      return window.openai.callTool(m[1], args).then(function (result) {
        return new Response(JSON.stringify(result), { status: 200, headers: { 'Content-Type': 'application/json' } });
      });
    }
    if (realFetch) return realFetch(url, opts);
    return Promise.reject(new Error('fetch unavailable in this host'));
  };
  // Surface tool output pushed by the host so the page can react if it wants to.
  window.addEventListener('openai:set_globals', function (e) {
    try {
      var g = e.detail && e.detail.globals;
      if (g && 'toolOutput' in g) {
        window.dispatchEvent(new CustomEvent('rapp:toolOutput', { detail: g.toolOutput }));
      }
    } catch (err) { /* ignore */ }
  });
})();
""".strip()


_WIDGET_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__APP_TITLE__</title>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; margin: 0; }
  body { font-family: "Segoe UI", system-ui, -apple-system, sans-serif; padding: 12px; background: transparent; }
  .card { border: 1px solid rgba(128,128,128,.35); border-radius: 12px; padding: 16px; }
  .head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 10px; }
  h1 { font-size: 15px; font-weight: 600; }
  #fs { font: inherit; font-size: 12px; padding: 4px 10px; border-radius: 8px; border: 1px solid rgba(128,128,128,.45); background: transparent; color: inherit; cursor: pointer; }
  #status { font-size: 13px; opacity: .7; }
  .msg { font-size: 14px; margin-bottom: 10px; white-space: pre-wrap; }
  pre { font: 12px/1.5 ui-monospace, "Cascadia Code", Menlo, monospace; padding: 10px; border-radius: 8px;
        background: rgba(128,128,128,.12); overflow-x: auto; max-height: 340px; }
  .pill { display: inline-block; font-size: 11px; padding: 2px 8px; border-radius: 999px; border: 1px solid rgba(128,128,128,.45); margin-bottom: 8px; }
</style>
</head>
<body>
<div class="card">
  <div class="head"><h1>__APP_TITLE__</h1><button id="fs" hidden>Full screen</button></div>
  <div id="status">Waiting for tool output…</div>
  <div id="out"></div>
</div>
<script>
(function () {
  'use strict';
  var out = document.getElementById('out');
  var status = document.getElementById('status');
  var fs = document.getElementById('fs');

  function render(data) {
    status.textContent = '';
    out.innerHTML = '';
    if (data === null || data === undefined) { status.textContent = 'No output.'; return; }
    if (typeof data === 'object' && !Array.isArray(data)) {
      if (data.status) {
        var pill = document.createElement('span');
        pill.className = 'pill';
        pill.textContent = String(data.status);
        out.appendChild(pill);
      }
      if (data.message) {
        var msg = document.createElement('div');
        msg.className = 'msg';
        msg.textContent = String(data.message);
        out.appendChild(msg);
      }
      var rest = data.data !== undefined ? data.data : data;
      var pre = document.createElement('pre');
      pre.textContent = typeof rest === 'string' ? rest : JSON.stringify(rest, null, 2);
      out.appendChild(pre);
      return;
    }
    var p = document.createElement('pre');
    p.textContent = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
    out.appendChild(p);
  }

  // OpenAI Apps SDK component bridge (supported by M365 Copilot) — check every API before use.
  if (typeof window.openai === 'object' && window.openai !== null) {
    if (window.openai.toolOutput !== undefined) render(window.openai.toolOutput);
    window.addEventListener('openai:set_globals', function (e) {
      try {
        var g = e.detail && e.detail.globals;
        if (g && 'toolOutput' in g) render(g.toolOutput);
      } catch (err) { /* ignore */ }
    });
    if (typeof window.openai.requestDisplayMode === 'function') {
      fs.hidden = false;
      fs.addEventListener('click', function () { window.openai.requestDisplayMode({ mode: 'fullscreen' }); });
    }
  } else if (typeof window.app === 'object' && window.app !== null) {
    // MCP Apps standard bridge
    try {
      window.app.ontoolresult = function (params) {
        var r = params && (params.structuredContent || params.result || params);
        render(r);
      };
    } catch (err) { /* ignore */ }
  }
})();
</script>
</body>
</html>
"""


_SERVER_PY = r'''#!/usr/bin/env python3
"""Streamable-HTTP MCP server generated by RapplicationToMcp (@kody-w/rapplication_to_mcp_agent).

Pure stdlib — no pip installs. Exposes every agents/*_agent.py perform() as an MCP tool,
each tagged with _meta["openai/outputTemplate"] / _meta.ui.resourceUri pointing at the
ui:// widget resource, per the M365 Copilot MCP-apps pattern:
https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/plugin-mcp-apps

Run:  python3 mcp_server.py            (port from config.json; override with PORT env var)
Test: curl -s -X POST localhost:<port>/mcp -H 'Content-Type: application/json' \
        -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
"""
import glob
import importlib.util
import json
import os
import re
import sys
import types
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
PORT = int(os.environ.get("PORT", CONFIG.get("port", 8787)))
WIDGET_URI = CONFIG["widget"]["resource_uri"]
WIDGET_MIME = CONFIG["widget"].get("mime_type", "text/html+skybridge")
WIDGET_PATH = HERE / CONFIG["widget"]["html"]
PROTOCOL_VERSION = "2025-06-18"

# --- import shims: agents written for CommunityRAPP/brainstem work here too ---
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "agents"))
try:
    import local_storage
    _utils = types.ModuleType("utils")
    _afs = types.ModuleType("utils.azure_file_storage")
    _afs.AzureFileStorageManager = local_storage.AzureFileStorageManager
    _utils.azure_file_storage = _afs
    sys.modules.setdefault("utils", _utils)
    sys.modules["utils.azure_file_storage"] = _afs
except Exception:
    pass

_AGENT_FILE_RE = re.compile(r"^[a-z][a-z0-9_]*_agent\.py$")


def load_agents():
    """Fresh-load agents from disk on every request (edit and re-call, no restart)."""
    agents = {}
    for path in sorted(glob.glob(str(HERE / "agents" / "*_agent.py"))):
        fname = os.path.basename(path)
        if not _AGENT_FILE_RE.match(fname) or fname == "basic_agent.py":
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"mcpapp_{fname[:-3]}", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            for obj in vars(mod).values():
                if isinstance(obj, type) and obj.__module__ == mod.__name__ \
                        and hasattr(obj, "perform") and obj.__name__ != "BasicAgent":
                    inst = obj()
                    md = getattr(inst, "metadata", None)
                    if md and md.get("name"):
                        agents[re.sub(r"[^A-Za-z0-9_]", "_", md["name"])] = (inst, md)
                        break
        except Exception:
            traceback.print_exc()
    return agents


def tool_descriptors(agents):
    tools = []
    for name, (_inst, md) in agents.items():
        tools.append({
            "name": name,
            "description": md.get("description", ""),
            "inputSchema": md.get("parameters", {"type": "object", "properties": {}}),
            "annotations": {"readOnlyHint": False},
            "_meta": {
                # OpenAI Apps SDK form (supported by M365 Copilot)
                "openai/outputTemplate": WIDGET_URI,
                # MCP Apps standard form
                "ui": {"resourceUri": WIDGET_URI},
            },
        })
    return tools


def call_tool(agents, name, arguments):
    if name not in agents:
        return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}
    inst, _md = agents[name]
    try:
        result = inst.perform(**(arguments or {}))
    except Exception as exc:
        return {"content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}], "isError": True}
    structured = None
    if isinstance(result, dict):
        structured = result
        text = result.get("message") or json.dumps(result, default=str)
    else:
        text = str(result)
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                structured = parsed
        except Exception:
            pass
    out = {"content": [{"type": "text", "text": text}]}
    if structured is not None:
        out["structuredContent"] = json.loads(json.dumps(structured, default=str))
    return out


def widget_resource():
    html = WIDGET_PATH.read_text(encoding="utf-8")
    csp = {"connect_domains": [], "resource_domains": []}
    return {
        "uri": WIDGET_URI,
        "mimeType": WIDGET_MIME,
        "text": html,
        "_meta": {
            "openai/widgetCSP": csp,
            "ui": {"csp": {"connectDomains": [], "resourceDomains": []}},
        },
    }


def handle_rpc(msg):
    method = msg.get("method")
    params = msg.get("params") or {}
    if method == "initialize":
        return {
            "protocolVersion": params.get("protocolVersion") or PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}, "resources": {"listChanged": False}},
            "serverInfo": {"name": CONFIG["name"], "title": CONFIG.get("display_name", CONFIG["name"]),
                           "version": CONFIG.get("version", "1.0.0")},
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": tool_descriptors(load_agents())}
    if method == "tools/call":
        return call_tool(load_agents(), params.get("name"), params.get("arguments"))
    if method == "resources/list":
        return {"resources": [{"uri": WIDGET_URI, "name": "app-widget",
                               "title": CONFIG.get("display_name", CONFIG["name"]),
                               "mimeType": WIDGET_MIME}]}
    if method == "resources/read":
        if params.get("uri") == WIDGET_URI:
            return {"contents": [widget_resource()]}
        raise RpcError(-32002, f"Unknown resource: {params.get('uri')}")
    if method in ("resources/templates/list",):
        return {"resourceTemplates": []}
    if method in ("prompts/list",):
        return {"prompts": []}
    raise RpcError(-32601, f"Method not found: {method}")


class RpcError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, DELETE")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):  # noqa: N802
        self._send(200, b"", "text/plain")

    def do_GET(self):  # noqa: N802
        if self.path.rstrip("/") in ("", "/health"):
            self._send(200, {"ok": True, "name": CONFIG["name"], "mcp_endpoint": "/mcp",
                             "tools": sorted(load_agents().keys()), "widget": WIDGET_URI})
        elif self.path == "/mcp":
            # No SSE stream support; streamable-HTTP clients fall back to plain POST responses.
            self._send(405, {"error": "GET stream not supported; POST JSON-RPC to /mcp"})
        else:
            self._send(404, {"error": "not found"})

    def do_DELETE(self):  # noqa: N802
        self._send(200, b"", "text/plain")

    def do_POST(self):  # noqa: N802
        if self.path != "/mcp":
            self._send(404, {"error": "POST to /mcp"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            msg = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self._send(400, {"jsonrpc": "2.0", "id": None,
                             "error": {"code": -32700, "message": "Parse error"}})
            return
        if "id" not in msg:  # notification (e.g. notifications/initialized)
            self._send(202, b"", "text/plain")
            return
        try:
            result = handle_rpc(msg)
            self._send(200, {"jsonrpc": "2.0", "id": msg["id"], "result": result})
        except RpcError as exc:
            self._send(200, {"jsonrpc": "2.0", "id": msg["id"],
                             "error": {"code": exc.code, "message": str(exc)}})
        except Exception as exc:
            traceback.print_exc()
            self._send(200, {"jsonrpc": "2.0", "id": msg["id"],
                             "error": {"code": -32603, "message": f"{type(exc).__name__}: {exc}"}})

    def log_message(self, fmt, *args):
        sys.stderr.write("[mcp] %s\n" % (fmt % args))


if __name__ == "__main__":
    agents = load_agents()
    print(f"MCP app '{CONFIG['name']}' on http://localhost:{PORT}/mcp")
    print(f"  tools:  {', '.join(sorted(agents)) or '(none found!)'}")
    print(f"  widget: {WIDGET_URI} ({WIDGET_MIME})")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
'''


_FALLBACK_BASIC_AGENT = '''class BasicAgent:
    """Minimal BasicAgent shim bundled by RapplicationToMcp (source brainstem copy not found)."""

    def __init__(self, name=None, metadata=None):
        if name is not None:
            self.name = name
        elif not hasattr(self, "name"):
            self.name = "BasicAgent"
        if metadata is not None:
            self.metadata = metadata
        elif not hasattr(self, "metadata"):
            self.metadata = {
                "name": self.name,
                "description": "Base agent -- override this.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            }

    def perform(self, **kwargs):
        return "Not implemented."

    def system_context(self):
        return None
'''


_FALLBACK_LOCAL_STORAGE = '''"""Minimal AzureFileStorageManager shim bundled by RapplicationToMcp.

Only used when the brainstem's real local_storage.py was not available at convert
time. Persists JSON under ./.mcp_app_data next to the server.
"""
import json
import os
from pathlib import Path

_DATA = Path(__file__).resolve().parent / ".mcp_app_data"


class AzureFileStorageManager:
    def __init__(self, *args, **kwargs):
        _DATA.mkdir(parents=True, exist_ok=True)
        self._context = "shared_memories"

    def set_memory_context(self, user_guid=None):
        self._context = f"memory/{user_guid}" if user_guid else "shared_memories"

    def _path(self, file_path=None):
        rel = file_path or f"{self._context}/memory.json"
        p = (_DATA / rel).resolve()
        if not str(p).startswith(str(_DATA)):
            raise ValueError("path escapes data dir")
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def read_json(self, file_path=None):
        p = self._path(file_path)
        if not p.is_file():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def write_json(self, data, file_path=None):
        p = self._path(file_path)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        os.replace(tmp, p)
        return True

    def read_file(self, file_path):
        p = self._path(file_path)
        return p.read_text(encoding="utf-8") if p.is_file() else None

    def write_file(self, content, file_path):
        self._path(file_path).write_text(content, encoding="utf-8")
        return True

    def list_files(self, directory=""):
        base = self._path(directory + "/x").parent if directory else _DATA
        return [str(f.relative_to(_DATA)) for f in base.rglob("*") if f.is_file()]

    def file_exists(self, file_path):
        return self._path(file_path).is_file()

    def delete_file(self, file_path):
        p = self._path(file_path)
        if p.is_file():
            p.unlink()
            return True
        return False
'''


_README_MD = """# __DISPLAY__ — MCP app for Microsoft 365 Copilot

Generated from the `__NAME__` rapplication by `RapplicationToMcp`
(@kody-w/rapplication_to_mcp_agent), following the M365 Copilot MCP-apps pattern:
<https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/plugin-mcp-apps>

## What's here

- `server/mcp_server.py` — dependency-free streamable-HTTP MCP server. Every bundled
  agent's `perform()` is an MCP tool tagged with `_meta["openai/outputTemplate"]` and
  `_meta.ui.resourceUri` = `__WIDGET_URI__`, so tool results render as an interactive
  widget in Copilot chat. Agents hot-reload from `server/agents/` on every request.
- `server/web/app.html` — the widget (served as the `__WIDGET_URI__` resource,
  mimeType `text/html+skybridge`). Uses `window.openai.*` with availability checks
  and falls back to the MCP Apps `app` bridge.
- `appPackage/` — Teams app manifest + `declarativeAgent.json` (rapplication `soul.md`
  became the agent `instructions`) + `ai-plugin.json` (v2.3, `runtimes[0].type = "mcp"`).
- `__NAME__-appPackage.zip` — sideloadable package.
- `.vscode/mcp.json` — lets Agents Toolkit "Start" / "Fetch action from MCP" against the server.

## Tools

__TOOLS__

## Run it locally

```bash
python3 server/mcp_server.py        # listens on port __PORT__
curl -s localhost:__PORT__/health
curl -s -X POST localhost:__PORT__/mcp -H 'Content-Type: application/json' \\
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Inspect interactively: `npx @modelcontextprotocol/inspector` → connect to `__SERVER_URL__`.

## Get it into Copilot

Copilot requires a public **HTTPS** URL for the MCP server. Current configured URL: `__SERVER_URL__`

1. Tunnel: `devtunnel host -p __PORT__ --allow-anonymous` (or ngrok / a real host).
2. Re-run the converter with `server_url='https://<your-tunnel>/mcp'` so the
   `ai-plugin.json` runtime and `.vscode/mcp.json` point at the public URL
   (or edit those two files by hand).
3. Open this folder in VS Code with **Microsoft 365 Agents Toolkit** (>= 6.6.1),
   sign in to Microsoft 365 (needs Custom App Upload + Copilot Access), then
   **Lifecycle > Provision** — or sideload `__NAME__-appPackage.zip` directly.
4. Go to <https://m365.cloud.microsoft/chat>, pick the agent, and invoke a tool —
   the widget renders inline (anonymous auth is dev-only; add OAuth 2.1 / Entra SSO
   before production).
"""


def main():
    """CLI smoke: python3 rapplication_to_mcp_agent.py <action> [path] [output_path]"""
    agent = RapplicationToMcpAgent()
    args = sys.argv[1:]
    kwargs = {"action": args[0] if args else "list"}
    if len(args) > 1:
        kwargs["path"] = args[1]
    if len(args) > 2:
        kwargs["output_path"] = args[2]
    print(json.dumps(agent.perform(**kwargs), indent=2, default=str))


if __name__ == "__main__":
    main()
