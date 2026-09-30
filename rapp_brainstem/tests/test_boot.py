"""
Boot-time GC pause (brainstem.py). Run as the server, GC is paused while the libraries
and routes load, then those permanent objects are frozen and GC resumes before any
agent code runs or any request is served. Imported as a module, GC is never touched.
Hermetic: runs a copy in a temp dir with no auth and no network, and never binds a port.

    python3 -m pytest tests/test_boot.py -v
"""
import gc
import json
import os
import shutil
import subprocess
import sys
import textwrap

import brainstem as bs

# Runs brainstem.py exactly as `python brainstem.py` does, recording the GC state when
# requests/flask are first imported and when the server would start (Flask.run is
# replaced by a recorder, so no port is ever bound).
_PROBE = textwrap.dedent("""
    import builtins, gc, json, runpy

    seen = {}
    real_import = builtins.__import__

    def spy(name, globals=None, locals=None, fromlist=(), level=0):
        first = level == 0 and name in ("requests", "flask") and name not in seen
        if first:
            seen[name] = gc.isenabled()
        module = real_import(name, globals, locals, fromlist, level)
        if first and name == "flask":
            def run(self, *args, **kwargs):
                seen["run"] = {"enabled": gc.isenabled(), "frozen": gc.get_freeze_count()}
            module.Flask.run = run
        return module

    builtins.__import__ = spy
    runpy.run_path("brainstem.py", run_name="__main__")
    print("PROBE " + json.dumps(seen))
""")

_PROBE_AGENT = textwrap.dedent("""
    import gc

    from agents.basic_agent import BasicAgent

    print("GC_AT_AGENT_LOAD", gc.isenabled())


    class GcProbeAgent(BasicAgent):
        def __init__(self):
            self.name = "GcProbe"
            self.metadata = {"name": self.name, "description": "Records GC state.",
                             "parameters": {"type": "object", "properties": {}}}
            super().__init__(name=self.name, metadata=self.metadata)

        def perform(self, **kwargs):
            return "ok"
""")


def _run_as_server(tmp_path):
    root = tmp_path / "rapp_brainstem"
    (root / "agents").mkdir(parents=True)
    for name in ("brainstem.py", "local_storage.py", "soul.md", "VERSION"):
        shutil.copy2(os.path.join(bs._BASE_DIR, name), root / name)
    shutil.copy2(os.path.join(bs._BASE_DIR, "agents", "basic_agent.py"), root / "agents")
    (root / "agents" / "gc_probe_agent.py").write_text(_PROBE_AGENT, encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    closed = "http://127.0.0.1:9"  # a stray request fails fast instead of reaching GitHub
    # Blank values also keep any stray .env above tmp_path from changing the outcome.
    env = {"HOME": str(home), "PATH": os.pathsep.join([os.path.dirname(sys.executable), "/usr/bin", "/bin"]),
           "GITHUB_TOKEN": "", "GITHUB_MODEL": "", "AGENTS_PATH": "", "LANG": "en_US.UTF-8",
           "PYTHONUNBUFFERED": "1",
           "HTTPS_PROXY": closed, "HTTP_PROXY": closed, "https_proxy": closed, "http_proxy": closed}
    if os.name == "nt":
        env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", "")
    done = subprocess.run([sys.executable, "-c", _PROBE], cwd=root, env=env, capture_output=True,
                          text=True, encoding="utf-8", timeout=120)
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-2000:]
    probe = [line for line in done.stdout.splitlines() if line.startswith("PROBE ")]
    assert probe, done.stdout[-2000:]
    return json.loads(probe[-1][len("PROBE "):]), done.stdout


def test_server_boot_pauses_gc_while_libraries_load_then_resumes(tmp_path):
    seen, out = _run_as_server(tmp_path)
    assert seen["requests"] is False and seen["flask"] is False
    # Back on, with the startup objects frozen, before the server would listen.
    assert seen["run"]["enabled"] is True
    assert seen["run"]["frozen"] > 0
    # Agent code (the startup load_agents sweep) already runs with normal GC.
    assert "GC_AT_AGENT_LOAD True" in out
    assert "GC_AT_AGENT_LOAD False" not in out
    assert "Agent loaded: GcProbe" in out
    # Startup still degrades as before with no auth: defaults kept, server started.
    assert "Could not fetch models (using defaults)" in out
    assert "Model:  gpt-4o" in out


def test_importing_brainstem_never_touches_gc():
    # Tests and tools import the module; only `python brainstem.py` pauses GC.
    assert bs.__name__ == "brainstem"
    assert gc.isenabled()
    assert gc.get_freeze_count() == 0
