"""
RAPP Brainstem — minimal local AI agent endpoint.
Only dependency: a GitHub account with Copilot access.

Uses the GitHub Copilot API directly (same pattern as openrappter).
No API keys needed — just `gh auth login`.

Usage:
    ./start.sh
    # or: python brainstem.py

POST /chat  { user_input, conversation_history?, session_id? }
GET  /health
"""

import os
import sys
import json
import uuid
import glob
import time
import importlib.util
import subprocess
import traceback

import requests
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, static_folder=os.path.dirname(os.path.abspath(__file__)))
CORS(app)

# ── Config ────────────────────────────────────────────────────────────────────

SOUL_PATH   = os.getenv("SOUL_PATH",   os.path.join(os.path.dirname(__file__), "soul.md"))
AGENTS_PATH = os.getenv("AGENTS_PATH", os.path.join(os.path.dirname(__file__), "agents"))
MODEL       = os.getenv("GITHUB_MODEL", "gpt-4o")
PORT        = int(os.getenv("PORT", 7071))

COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"

AVAILABLE_MODELS = [
    {"id": "gpt-4.1",         "name": "GPT-4.1"},
    {"id": "gpt-4o",          "name": "GPT-4o"},
    {"id": "gpt-4o-mini",     "name": "GPT-4o Mini"},
    {"id": "claude-sonnet-4", "name": "Claude Sonnet 4"},
    {"id": "gpt-4",           "name": "GPT-4"},
    {"id": "gpt-3.5-turbo",   "name": "GPT-3.5 Turbo"},
]

# ── GitHub token ──────────────────────────────────────────────────────────────

# GitHub Copilot VS Code extension client ID (same as openrappter)
COPILOT_CLIENT_ID = "Iv1.b507a08c87ecfe98"
_token_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".copilot_token")

def get_github_token():
    """Get GitHub token from env, saved file, or gh CLI."""
    # 1. Env var
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        return token
    # 2. Saved token from device code login
    if os.path.exists(_token_file):
        with open(_token_file) as f:
            token = f.read().strip()
            if token:
                return token
    # 3. gh CLI
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True, text=True, timeout=5
        )
        token = result.stdout.strip()
        if token:
            return token
    except Exception:
        pass
    return None

def save_github_token(token):
    """Persist token for reuse across restarts."""
    with open(_token_file, "w") as f:
        f.write(token)

# ── Copilot token exchange ────────────────────────────────────────────────────

_copilot_token_cache = {"token": None, "endpoint": None, "expires_at": 0}

def get_copilot_token():
    """Exchange GitHub token for a short-lived Copilot API token."""
    global _copilot_token_cache
    
    # Return cached token if still valid (with 60s buffer)
    if _copilot_token_cache["token"] and time.time() < _copilot_token_cache["expires_at"] - 60:
        return _copilot_token_cache["token"], _copilot_token_cache["endpoint"]
    
    github_token = get_github_token()
    if not github_token:
        raise RuntimeError("Not authenticated. Visit /login in your browser to sign in with GitHub.")
    
    # ghu_ tokens from device code OAuth use "token" auth, others use "Bearer"
    auth_prefix = "token" if github_token.startswith("ghu_") else "Bearer"
    resp = requests.get(
        COPILOT_TOKEN_URL,
        headers={
            "Authorization": f"{auth_prefix} {github_token}",
            "Accept": "application/json",
            "Editor-Version": "vscode/1.95.0",
            "Editor-Plugin-Version": "copilot/1.0.0",
        },
        timeout=10,
    )
    
    if resp.status_code in (401, 404):
        raise RuntimeError(
            "GitHub token doesn't have Copilot access. "
            "Visit /login in your browser to authenticate with GitHub Copilot."
        )
    resp.raise_for_status()
    
    data = resp.json()
    copilot_token = data.get("token")
    endpoint = data.get("endpoints", {}).get("api", "https://api.individual.githubcopilot.com")
    expires_at = data.get("expires_at", time.time() + 600)
    
    if not copilot_token:
        raise RuntimeError("Failed to get Copilot API token. Check your Copilot subscription.")
    
    _copilot_token_cache = {
        "token": copilot_token,
        "endpoint": endpoint,
        "expires_at": expires_at,
    }
    
    print(f"[brainstem] Copilot token refreshed (expires in {int(expires_at - time.time())}s)")
    return copilot_token, endpoint

# ── Device code OAuth flow ────────────────────────────────────────────────────

_pending_login = {}

def start_device_code_login():
    """Start GitHub device code OAuth flow. Returns user_code and verification_uri."""
    global _pending_login
    resp = requests.post(
        "https://github.com/login/device/code",
        headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        data=f"client_id={COPILOT_CLIENT_ID}&scope=read:user",
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    _pending_login = {
        "device_code": data["device_code"],
        "interval": data.get("interval", 5),
        "expires_at": time.time() + data.get("expires_in", 900),
    }
    return {
        "user_code": data["user_code"],
        "verification_uri": data["verification_uri"],
    }

def poll_device_code():
    """Poll for completed device code authorization. Returns token or None."""
    global _pending_login
    if not _pending_login:
        return None
    
    resp = requests.post(
        "https://github.com/login/oauth/access_token",
        headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        data=(
            f"client_id={COPILOT_CLIENT_ID}"
            f"&device_code={_pending_login['device_code']}"
            f"&grant_type=urn:ietf:params:oauth:grant-type:device_code"
        ),
        timeout=10,
    )
    data = resp.json()
    
    if data.get("access_token"):
        token = data["access_token"]
        save_github_token(token)
        _pending_login = {}
        return token
    
    error = data.get("error", "")
    if error in ("authorization_pending", "slow_down"):
        return None  # Keep polling
    if error == "expired_token":
        _pending_login = {}
        raise RuntimeError("Login expired. Please try again.")
    if error:
        _pending_login = {}
        raise RuntimeError(f"Login failed: {error}")
    
    return None

# ── Soul loader ───────────────────────────────────────────────────────────────

_soul_cache = None

def load_soul():
    global _soul_cache
    if _soul_cache is not None:
        return _soul_cache
    if not os.path.exists(SOUL_PATH):
        print(f"[brainstem] Warning: soul file not found at {SOUL_PATH}, using default.")
        _soul_cache = "You are a helpful AI assistant."
        return _soul_cache
    with open(SOUL_PATH, "r") as f:
        _soul_cache = f.read().strip()
    print(f"[brainstem] Soul loaded: {SOUL_PATH}")
    return _soul_cache

# ── Agent loader ──────────────────────────────────────────────────────────────

_agents_cache = None
_remote_agents = {}  # name → instance (hot-loaded from repos)
_connected_repos = {}  # url → {manifest, enabled_agents}
_remote_agents_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".remote_agents")
_repos_config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".repos.json")

def _load_agent_from_file(filepath):
    """Load agent classes from a single .py file. Returns dict of name→instance.
    Auto-installs missing pip packages and shims cloud deps to local storage."""
    agents = {}
    brainstem_dir = os.path.dirname(os.path.abspath(__file__))
    if brainstem_dir not in sys.path:
        sys.path.insert(0, brainstem_dir)
    
    _register_shims()
    
    # Try loading, auto-install missing deps, retry once
    for attempt in range(2):
        try:
            mod_name = f"agent_{os.path.basename(filepath).replace('.', '_')}_{id(filepath)}_{attempt}"
            spec = importlib.util.spec_from_file_location(mod_name, filepath)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            for attr in dir(mod):
                cls = getattr(mod, attr)
                if (
                    isinstance(cls, type)
                    and hasattr(cls, "perform")
                    and attr not in ("BasicAgent", "object")
                    and not attr.startswith("_")
                ):
                    instance = cls()
                    agents[instance.name] = instance
            break  # success
        except ModuleNotFoundError as e:
            missing = _extract_package_name(e)
            if missing and attempt == 0:
                _auto_install(missing)
                continue  # retry after install
            print(f"[brainstem] Failed to load {filepath}: {e}")
        except Exception as e:
            print(f"[brainstem] Failed to load {filepath}: {e}")
            break
    return agents


# ── Shims & auto-install ─────────────────────────────────────────────────────

_shims_registered = False

def _register_shims():
    """Register local shims for cloud dependencies so remote agents import them transparently."""
    global _shims_registered
    if _shims_registered:
        return
    
    import types
    brainstem_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Shim: agents.basic_agent → local basic_agent
    try:
        from basic_agent import BasicAgent as _BA
        if "agents" not in sys.modules:
            agents_mod = types.ModuleType("agents")
            agents_mod.__path__ = [os.path.join(brainstem_dir, "agents")]
            sys.modules["agents"] = agents_mod
        if "agents.basic_agent" not in sys.modules:
            ba_mod = types.ModuleType("agents.basic_agent")
            ba_mod.BasicAgent = _BA
            sys.modules["agents.basic_agent"] = ba_mod
            sys.modules["agents"].basic_agent = ba_mod
    except ImportError:
        pass
    
    # Shim: utils.azure_file_storage → local_storage.py
    from local_storage import AzureFileStorageManager as _LSM
    if "utils" not in sys.modules:
        utils_mod = types.ModuleType("utils")
        utils_mod.__path__ = [os.path.join(brainstem_dir, "utils")]
        sys.modules["utils"] = utils_mod
    afs_mod = types.ModuleType("utils.azure_file_storage")
    afs_mod.AzureFileStorageManager = _LSM
    sys.modules["utils.azure_file_storage"] = afs_mod
    if hasattr(sys.modules["utils"], "__path__"):
        sys.modules["utils"].azure_file_storage = afs_mod
    
    # Shim: utils.dynamics_storage → same local storage
    ds_mod = types.ModuleType("utils.dynamics_storage")
    ds_mod.DynamicsStorageManager = _LSM
    sys.modules["utils.dynamics_storage"] = ds_mod
    
    _shims_registered = True
    print("[brainstem] Local storage shims registered")


# Map of import names → pip package names
_PIP_MAP = {
    "bs4": "beautifulsoup4",
    "beautifulsoup4": "beautifulsoup4",
    "PIL": "Pillow",
    "cv2": "opencv-python",
    "sklearn": "scikit-learn",
    "yaml": "pyyaml",
    "docx": "python-docx",
    "pptx": "python-pptx",
    "dotenv": "python-dotenv",
}


def _extract_package_name(error):
    """Extract the pip-installable package name from a ModuleNotFoundError."""
    msg = str(error)
    # "No module named 'bs4'"
    match = __import__("re").search(r"No module named '([^']+)'", msg)
    if not match:
        return None
    mod = match.group(1).split(".")[0]
    return _PIP_MAP.get(mod, mod)


def _auto_install(package):
    """Auto-install a pip package."""
    print(f"[brainstem] Auto-installing dependency: {package}")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", package, "-q"],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0:
            print(f"[brainstem] Installed {package}")
            # Clear import caches so retry works
            importlib.invalidate_caches()
        else:
            print(f"[brainstem] Failed to install {package}: {result.stderr[:200]}")
    except Exception as e:
        print(f"[brainstem] Failed to install {package}: {e}")

def load_agents():
    global _agents_cache
    if _agents_cache is not None:
        return _agents_cache

    agents = {}
    pattern = os.path.join(AGENTS_PATH, "**", "*_agent.py")
    files = glob.glob(pattern, recursive=True) + glob.glob(os.path.join(AGENTS_PATH, "*_agent.py"))
    files = list(set(files))

    for filepath in files:
        loaded = _load_agent_from_file(filepath)
        for name, instance in loaded.items():
            agents[name] = instance
            print(f"[brainstem] Agent loaded: {name}")

    _agents_cache = agents
    print(f"[brainstem] {len(agents)} agent(s) ready.")
    
    # Restore saved repos
    _restore_repos()
    
    return agents

def get_all_agents():
    """Get local + remote agents combined."""
    agents = dict(load_agents())
    agents.update(_remote_agents)
    return agents

def reload_agents():
    """Force reload all agents."""
    global _agents_cache
    _agents_cache = None
    return load_agents()

# ── Remote repo agent loading ────────────────────────────────────────────────

def _save_repos():
    """Persist connected repos to disk."""
    data = {}
    for url, info in _connected_repos.items():
        data[url] = {"enabled_agents": list(info.get("enabled_agents", []))}
    with open(_repos_config_file, "w") as f:
        json.dump(data, f, indent=2)

def _restore_repos():
    """Restore previously connected repos on startup."""
    if not os.path.exists(_repos_config_file):
        return
    try:
        with open(_repos_config_file) as f:
            data = json.load(f)
        for url, info in data.items():
            try:
                manifest = _fetch_repo_manifest(url)
                _connected_repos[url] = {
                    "manifest": manifest,
                    "enabled_agents": set(info.get("enabled_agents", []))
                }
                # Re-enable previously enabled agents
                for agent_id in info.get("enabled_agents", []):
                    _install_remote_agent(url, agent_id, manifest)
                print(f"[brainstem] Restored repo: {url} ({len(info.get('enabled_agents', []))} agents)")
            except Exception as e:
                print(f"[brainstem] Failed to restore repo {url}: {e}")
    except Exception as e:
        print(f"[brainstem] Failed to load repos config: {e}")

def _normalize_repo_url(url):
    """Convert various GitHub URL formats to owner/repo."""
    url = url.strip().rstrip("/")
    # Handle full URLs
    for prefix in ["https://github.com/", "http://github.com/", "github.com/"]:
        if url.startswith(prefix):
            url = url[len(prefix):]
    # Handle GitHub Pages URLs like kody-w.github.io/AI-Agent-Templates
    if ".github.io/" in url:
        parts = url.split(".github.io/")
        owner = parts[0].replace("https://", "").replace("http://", "")
        repo = parts[1].split("/")[0] if "/" in parts[1] else parts[1]
        return f"{owner}/{repo}"
    # Already owner/repo
    parts = url.split("/")
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return url

def _fetch_repo_manifest(repo_url):
    """Fetch manifest.json or build one from agents/ directory listing."""
    owner_repo = _normalize_repo_url(repo_url)
    
    # Try manifest.json first
    manifest_url = f"https://raw.githubusercontent.com/{owner_repo}/main/manifest.json"
    resp = requests.get(manifest_url, timeout=10)
    if resp.status_code == 200:
        return resp.json()
    
    # Try agents/index.json
    index_url = f"https://raw.githubusercontent.com/{owner_repo}/main/agents/index.json"
    resp = requests.get(index_url, timeout=10)
    if resp.status_code == 200:
        index = resp.json()
        agents = []
        for filename in index.get("agents", []):
            if filename == "basic_agent.py":
                continue
            agent_id = filename.replace(".py", "")
            agents.append({
                "id": agent_id,
                "name": agent_id.replace("_", " ").title(),
                "filename": filename,
                "path": f"agents/{filename}",
                "url": f"https://raw.githubusercontent.com/{owner_repo}/main/agents/{filename}",
            })
        return {"agents": agents, "repository": owner_repo}
    
    # Try GitHub API to list agents/ directory
    api_url = f"https://api.github.com/repos/{owner_repo}/contents/agents"
    resp = requests.get(api_url, timeout=10)
    if resp.status_code == 200:
        files = resp.json()
        agents = []
        for f in files:
            if f["name"].endswith("_agent.py") and f["name"] != "basic_agent.py":
                agent_id = f["name"].replace(".py", "")
                agents.append({
                    "id": agent_id,
                    "name": agent_id.replace("_", " ").title(),
                    "filename": f["name"],
                    "path": f"agents/{f['name']}",
                    "url": f["download_url"],
                })
        return {"agents": agents, "repository": owner_repo}
    
    raise RuntimeError(f"Could not fetch agents from {owner_repo}. Make sure it has agents/ directory or manifest.json.")

def _install_remote_agent(repo_url, agent_id, manifest):
    """Download and hot-load a single agent from a remote repo."""
    global _remote_agents
    
    agent_info = None
    for a in manifest.get("agents", []):
        if a["id"] == agent_id:
            agent_info = a
            break
    if not agent_info:
        raise RuntimeError(f"Agent '{agent_id}' not found in manifest")
    
    # Download agent file
    os.makedirs(_remote_agents_dir, exist_ok=True)
    
    # Also ensure basic_agent.py is available
    owner_repo = _normalize_repo_url(repo_url)
    basic_path = os.path.join(_remote_agents_dir, "basic_agent.py")
    if not os.path.exists(basic_path):
        # Copy local basic_agent.py
        local_basic = os.path.join(os.path.dirname(os.path.abspath(__file__)), "basic_agent.py")
        if os.path.exists(local_basic):
            import shutil
            shutil.copy2(local_basic, basic_path)
    
    # Add remote agents dir to sys.path
    if _remote_agents_dir not in sys.path:
        sys.path.insert(0, _remote_agents_dir)
    
    url = agent_info.get("url")
    if not url:
        url = f"https://raw.githubusercontent.com/{owner_repo}/main/{agent_info['path']}"
    
    filepath = os.path.join(_remote_agents_dir, agent_info["filename"])
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    with open(filepath, "w") as f:
        f.write(resp.text)
    
    # Hot-load
    loaded = _load_agent_from_file(filepath)
    _remote_agents.update(loaded)
    print(f"[brainstem] Remote agent installed: {list(loaded.keys())} from {owner_repo}")
    return list(loaded.keys())

def _uninstall_remote_agent(agent_id, manifest):
    """Remove a remote agent."""
    global _remote_agents
    agent_info = None
    for a in manifest.get("agents", []):
        if a["id"] == agent_id:
            agent_info = a
            break
    if not agent_info:
        return
    
    # Remove from loaded agents
    filepath = os.path.join(_remote_agents_dir, agent_info["filename"])
    loaded = _load_agent_from_file(filepath) if os.path.exists(filepath) else {}
    for name in loaded:
        _remote_agents.pop(name, None)
    
    # Remove file
    if os.path.exists(filepath):
        os.remove(filepath)

# ── LLM call ─────────────────────────────────────────────────────────────────

def call_copilot(messages, tools=None):
    """Call the Copilot chat completions API."""
    copilot_token, endpoint = get_copilot_token()
    
    url = f"{endpoint}/chat/completions"
    headers = {
        "Authorization": f"Bearer {copilot_token}",
        "Content-Type": "application/json",
        "Editor-Version": "vscode/1.95.0",
        "Copilot-Integration-Id": "vscode-chat",
    }
    body = {
        "model": MODEL,
        "messages": messages,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"

    resp = requests.post(url, headers=headers, json=body, timeout=60)
    resp.raise_for_status()
    return resp.json()

# ── Agent execution ───────────────────────────────────────────────────────────

def run_tool_calls(tool_calls, agents):
    results = []
    logs = []
    for tc in tool_calls:
        fn_name = tc["function"]["name"]
        try:
            args = json.loads(tc["function"].get("arguments", "{}"))
        except Exception:
            args = {}

        agent = agents.get(fn_name)
        if agent:
            try:
                result = agent.perform(**args)
                logs.append(f"[{fn_name}] {result}")
            except Exception as e:
                result = f"Error: {e}"
                logs.append(f"[{fn_name}] ERROR: {e}")
        else:
            result = f"Agent '{fn_name}' not found."
            logs.append(result)

        results.append({
            "tool_call_id": tc["id"],
            "role": "tool",
            "name": fn_name,
            "content": str(result)
        })
    return results, logs

# ── /chat endpoint ────────────────────────────────────────────────────────────

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True) or {}
    user_input = data.get("user_input", "").strip()
    history    = data.get("conversation_history", [])
    session_id = data.get("session_id") or str(uuid.uuid4())

    if not user_input:
        return jsonify({"error": "user_input is required"}), 400

    try:
        soul   = load_soul()
        agents = get_all_agents()
        tools  = [a.to_tool() for a in agents.values()] if agents else None

        messages = [{"role": "system", "content": soul}]
        messages += [m for m in history if m.get("role") in ("user", "assistant", "tool")]
        messages.append({"role": "user", "content": user_input})

        all_logs = []
        # Up to 3 tool-call rounds
        for _ in range(3):
            response = call_copilot(messages, tools=tools)
            choice   = response["choices"][0]
            msg      = choice["message"]
            messages.append(msg)

            if choice.get("finish_reason") == "tool_calls" and msg.get("tool_calls"):
                tool_results, logs = run_tool_calls(msg["tool_calls"], agents)
                all_logs.extend(logs)
                messages.extend(tool_results)
            else:
                break

        reply = msg.get("content") or ""
        return jsonify({
            "response": reply,
            "session_id": session_id,
            "agent_logs": "\n".join(all_logs)
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# ── /health endpoint ──────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), "index.html")

@app.route("/login", methods=["POST"])
def login():
    """Start GitHub device code OAuth flow."""
    try:
        data = start_device_code_login()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/login/poll", methods=["POST"])
def login_poll():
    """Poll for completed device code authorization."""
    try:
        token = poll_device_code()
        if token:
            # Validate against Copilot
            try:
                get_copilot_token()
                return jsonify({"status": "ok", "message": "Authenticated with GitHub Copilot!"})
            except Exception:
                return jsonify({"status": "ok", "message": "Authenticated (Copilot validation pending)"})
        return jsonify({"status": "pending"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/models", methods=["GET"])
def list_models():
    """List available models and current selection."""
    return jsonify({"models": AVAILABLE_MODELS, "current": MODEL})

@app.route("/models/set", methods=["POST"])
def set_model():
    """Change the active model."""
    global MODEL
    data = request.get_json(force=True) or {}
    new_model = data.get("model", "").strip()
    valid_ids = [m["id"] for m in AVAILABLE_MODELS]
    if new_model not in valid_ids:
        return jsonify({"error": f"Unknown model. Available: {valid_ids}"}), 400
    MODEL = new_model
    return jsonify({"model": MODEL})

@app.route("/repos", methods=["GET"])
def list_repos():
    """List connected repos and their agents."""
    result = []
    for url, info in _connected_repos.items():
        manifest = info.get("manifest", {})
        enabled = info.get("enabled_agents", set())
        agents = []
        for a in manifest.get("agents", []):
            agents.append({
                "id": a["id"],
                "name": a.get("name", a["id"]),
                "description": a.get("description", ""),
                "enabled": a["id"] in enabled,
            })
        result.append({
            "url": url,
            "repo": manifest.get("repository", url),
            "agents": agents,
            "enabled_count": len(enabled),
        })
    return jsonify({"repos": result})

@app.route("/repos/connect", methods=["POST"])
def connect_repo():
    """Connect a remote repo and fetch its agent manifest."""
    data = request.get_json(force=True) or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "url is required"}), 400
    try:
        manifest = _fetch_repo_manifest(url)
        normalized = _normalize_repo_url(url)
        _connected_repos[normalized] = {
            "manifest": manifest,
            "enabled_agents": set(),
        }
        _save_repos()
        agents = [{"id": a["id"], "name": a.get("name", a["id"]),
                    "description": a.get("description", ""), "enabled": False}
                   for a in manifest.get("agents", [])]
        return jsonify({"repo": normalized, "agents": agents})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/repos/disconnect", methods=["POST"])
def disconnect_repo():
    """Disconnect a repo and unload its agents."""
    data = request.get_json(force=True) or {}
    url = _normalize_repo_url(data.get("url", ""))
    info = _connected_repos.pop(url, None)
    if info:
        manifest = info.get("manifest", {})
        for agent_id in list(info.get("enabled_agents", [])):
            _uninstall_remote_agent(agent_id, manifest)
    _save_repos()
    return jsonify({"status": "ok"})

@app.route("/repos/toggle", methods=["POST"])
def toggle_agent():
    """Enable or disable a remote agent."""
    data = request.get_json(force=True) or {}
    url = _normalize_repo_url(data.get("url", ""))
    agent_id = data.get("agent_id", "")
    enable = data.get("enable", True)

    info = _connected_repos.get(url)
    if not info:
        return jsonify({"error": f"Repo '{url}' not connected"}), 400

    manifest = info.get("manifest", {})
    enabled = info.get("enabled_agents", set())

    try:
        if enable and agent_id not in enabled:
            names = _install_remote_agent(url, agent_id, manifest)
            enabled.add(agent_id)
            _save_repos()
            return jsonify({"status": "enabled", "loaded": names})
        elif not enable and agent_id in enabled:
            _uninstall_remote_agent(agent_id, manifest)
            enabled.discard(agent_id)
            _save_repos()
            return jsonify({"status": "disabled"})
        return jsonify({"status": "no_change"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/health", methods=["GET"])
def health():
    try:
        copilot_token, endpoint = get_copilot_token()
        agents  = get_all_agents()
        soul_ok = os.path.exists(SOUL_PATH)
        return jsonify({
            "status": "ok",
            "model":  MODEL,
            "soul":   SOUL_PATH if soul_ok else "missing",
            "agents": list(agents.keys()),
            "copilot": "✓",
            "endpoint": endpoint,
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\n🧠 RAPP Brainstem starting on http://localhost:{PORT}")
    print(f"   Soul:   {SOUL_PATH}")
    print(f"   Agents: {AGENTS_PATH}")
    print(f"   Model:  {MODEL}")
    print(f"   Auth:   GitHub Copilot API (via gh CLI)\n")
    load_soul()
    load_agents()
    app.run(host="0.0.0.0", port=PORT, debug=False)
