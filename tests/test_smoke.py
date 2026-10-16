"""Protocol smoke test: drive the MCP server exactly as ZCode would.

Self-locating (no relative script paths, no host assumptions) and it asserts the
three things that actually break a plugin in production:

  * the server answers initialize/tools/list
  * state persists across calls (the persistent kernel is the whole design)
  * an unknown tool and a bad method return an error, not a hang

Run:  python tests/test_smoke.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ENGINE = os.path.join(ROOT, "engine")
SERVER = os.path.join(ENGINE, "mcp_server.py")
FAIL = []


def ok(msg):
    print("  ok   " + msg)


def bad(msg):
    FAIL.append(msg)
    print("  FAIL " + msg)


env = dict(os.environ,
           PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
           MATHMODEL_PLUGIN_ROOT=ROOT,
           MATHMODEL_DATA_DIR=os.path.join(ROOT, ".testdata"),
           MATHMODEL_MAX_STEPS="5",
           MATHMODEL_BLAST_RADIUS="host",
           MATHMODEL_PROVIDER_PREFER="jethub")
p = subprocess.Popen([sys.executable, SERVER], stdin=subprocess.PIPE,
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                     text=True, encoding="utf-8", bufsize=1, env=env, cwd=ROOT)


def call(obj, timeout=90):
    p.stdin.write(json.dumps(obj) + "\n")
    p.stdin.flush()
    line = p.stdout.readline()
    if not line:
        raise RuntimeError("server died: " + (p.stderr.read() or "")[:600])
    return json.loads(line)


def notify(obj):
    p.stdin.write(json.dumps(obj) + "\n")
    p.stdin.flush()


def run(code):
    return call({"jsonrpc": "2.0", "id": 99, "method": "tools/call",
                 "params": {"name": "run_python", "arguments": {"code": code}}}
                )["result"]["content"][0]["text"].strip()


try:
    r = call({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                         "clientInfo": {"name": "smoke", "version": "0"}}})
    if r["result"]["serverInfo"]["name"] == "mathmodel":
        ok("initialize handshake")
    else:
        bad("wrong serverInfo: " + str(r))
    notify({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

    tools = call({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
    names = [t["name"] for t in tools]
    for need in ("run_task", "run_python", "blast_radius"):
        (ok if need in names else bad)(f"advertises {need}")
    if all(t.get("inputSchema", {}).get("type") == "object" for t in tools):
        ok("every tool has an object inputSchema")
    else:
        bad("a tool is missing a valid inputSchema")

    # engine importable from the injected plugin root, not from the host cwd
    out = run("import tools_modelling as tm;"
              "print(tm.solve_lp_max([3,4],[[2,1],[1,3],[1,1]],[100,90,60])['max_objective'])")
    (ok if out.strip() == "190.0" else bad)(f"solve via MCP -> {out[:60]}")

    # the persistent namespace is the design; if this fails, multi-step work fails
    run("shared = 61")
    out = run("print(shared * 2)")
    (ok if out.strip() == "122" else bad)(f"state persisted across calls -> {out[:40]}")

    out = run("1/0")
    (ok if "ZeroDivisionError" in out else bad)("exceptions are surfaced, not swallowed")

    br = call({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
               "params": {"name": "blast_radius", "arguments": {}}}
              )["result"]["content"][0]["text"]
    (ok if "host" in br and ".testdata" in br
        else bad)(f"blast_radius reports real config -> {br[:70]}")

    err = call({"jsonrpc": "2.0", "id": 4, "method": "nonexistent/method"})
    (ok if "error" in err else bad)("unknown method returns a JSON-RPC error")

    bad_call = call({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                     "params": {"name": "no_such_tool", "arguments": {}}})
    (ok if "unknown tool" in bad_call["result"]["content"][0]["text"]
        else bad)("unknown tool reports instead of crashing")
finally:
    p.stdin.close()
    try:
        p.wait(timeout=15)
        ok("clean shutdown on stdin close")
    except subprocess.TimeoutExpired:
        p.kill()
        bad("server would not exit when stdin closed (ZCode would leak a process)")

print(f"\n{'PASS' if not FAIL else 'FAIL'}: {len(FAIL)} problem(s)")
sys.exit(1 if FAIL else 0)
