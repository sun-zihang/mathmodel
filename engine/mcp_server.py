"""MCP stdio server: mounts this agent inside ZCode as the `mathmodel` server.

ZCode's own harness spends its built-in quota on the reasoning loop, so nothing
here touches ZCode's credential store. The agent's autonomy contract lives in
core.SYSTEM; this file is only the transport.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import Agent, TOOLS_DOC, Kernel          # noqa: E402
from providers import pick_route  # noqa: E402
from session import Session                        # noqa: E402

SERVER_INFO = {"name": "mathmodel", "version": "0.1.0"}

# Where ZCode told us to keep data; falls back to ./out under the project.
DATA_DIR = os.environ.get("MATHMODEL_DATA_DIR") or os.path.join(os.getcwd(), "out")
# ZCODE_PLUGIN_ROOT is the plugin root; the modules live in <root>/engine. Keep
# them distinct -- pointing PYTHONPATH at the root instead of the engine dir is
# how "import tools_modelling" fails with the kernel alive and well.
PLUGIN_ROOT = os.environ.get("MATHMODEL_PLUGIN_ROOT") or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))
ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
MAX_STEPS = int(os.environ.get("MATHMODEL_MAX_STEPS", "60"))

_kernel = Kernel(blast_radius=os.environ.get("MATHMODEL_BLAST_RADIUS"),
                 workspace=os.getcwd())
# tools_modelling lives in this plugin's engine dir, which the host's cwd is not.
os.environ["PYTHONPATH"] = os.pathsep.join(
    [ENGINE_DIR] + ([p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]))


def _session(task, route):
    try:
        return Session(os.path.join(DATA_DIR, "sessions"), task=task[:400],
                       provider=route.name if route else "",
                       model=route.model if route else "")
    except OSError:
        return None


def _tool_defs():
    defs = []
    for name, desc in TOOLS_DOC:
        defs.append({
            "name": name,
            "description": desc + " (operator-authorised, no confirmation step)",
            "inputSchema": {"type": "object", "properties": {},
                            "additionalProperties": True},
        })
    defs.append({
        "name": "blast_radius",
        "description": ("Report where code actually executes: host (no guard "
                        "rails) or container (refused if docker is missing). "
                        "Read-only; set it via ZCode plugin config."),
        "inputSchema": {"type": "object", "properties": {}},
    })
    # the headline capability: run a whole bounded task headlessly
    defs.insert(0, {
        "name": "run_task",
        "description": (
            "Execute a complete mathematical-modelling task headlessly: plan, "
            "solve numerically, validate, plot, write up. Returns the final "
            "report text plus the transcript path. No interactive confirmation "
            "anywhere in the loop."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "the problem / instruction"},
                "max_steps": {"type": "integer", "default": MAX_STEPS},
                "model": {"type": "string",
                          "description": "model id for the chosen route"},
            },
            "required": ["task"],
        },
    })
    return defs


def _recorder(sess):
    """Adapt core's on_event(kind, step, text) to Session.event(kind, **kw).

    Wiring them directly would raise TypeError on the first act, so a run would
    die after doing all the work and before writing any of it down.
    """
    if sess is None:
        return None

    def emit(kind, step=None, text=None):
        sess.event(kind, step=step, text=(text or "")[:20000])

    return emit


def _call(name, args):
    if name == "run_task":
        route = pick_route(args.get("model"))
        if route is None:
            return ("no model route has credentials here. Set one of "
                    "OPENAI_API_KEY / ZAI_API_KEY / BIGMODEL_API_KEY in plugin "
                    "config, or start the jet-hub gateway.")
        steps = int(args.get("max_steps") or MAX_STEPS)
        sess = _session(args["task"], route)
        agent = Agent(route, kernel=_kernel, max_steps=steps,
                      on_event=_recorder(sess))
        agent.session = sess
        try:
            report = agent.run(args["task"])
        except Exception as exc:
            if sess:
                sess.event("fatal", error=f"{type(exc).__name__}: {exc}")
            raise
        if sess:
            sess.event("final", text=report[:20000])
            sess.event("summary", **sess.summary())
            return report + f"\n\n[transcript: {sess.path}]"
        return report

    if name == "blast_radius":
        return (f"blast_radius={_kernel.blast_radius} workspace={_kernel.workspace} "
                f"data_dir={DATA_DIR}\n"
                + ("host: code runs here with no guard rails"
                   if _kernel.blast_radius != "container"
                   else "container: run_python is refused outright if docker is absent"))

    for tname, _ in TOOLS_DOC:
        if tname == name:
            # One shared agent built the normal way. The previous Agent.__new__
            # bypassed __init__ and only worked while nothing else in it was
            # touched -- fragile in exactly the way that hides a bug.
            return _tool_agent()._tool(name, args)
    return f"[unknown tool {name}]"


_tool_agent_cache = {}


def _tool_agent():
    if "a" not in _tool_agent_cache:
        _tool_agent_cache["a"] = Agent(None, kernel=_kernel, max_steps=MAX_STEPS)
    return _tool_agent_cache["a"]


def main():
    def send(obj):
        # write() returns the character count, which is truthy -- an
        # "write(...) or flush()" one-liner therefore NEVER flushes, and the
        # client blocks on readline forever. Keep them as separate statements.
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue
        mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}

        if method == "initialize":
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO}})
        elif method in ("notifications/initialized", "initialized"):
            pass
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": mid, "result": {"tools": _tool_defs()}})
        elif method == "tools/call":
            try:
                txt = _call(params.get("name"), params.get("arguments") or {})
            except Exception as exc:                       # surface, never hang
                txt = f"[error] {type(exc).__name__}: {exc}"
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": str(txt)}]}})
        elif method == "ping":
            send({"jsonrpc": "2.0", "id": mid, "result": {}})
        elif mid is not None:
            send({"jsonrpc": "2.0", "id": mid,
                  "error": {"code": -32601, "message": f"no method {method}"}})


if __name__ == "__main__":
    main()
