"""The promises a README makes but nobody tests.

Each check here corresponds to a claim in README.md. If a claim stops being true,
this suite stops being green -- which is the only reason either of them is
trustworthy.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "engine"))

import core                                    # noqa: E402
import providers                               # noqa: E402
from core import Agent, INJECT_GUARD, Kernel    # noqa: E402

FAIL = []


def ok(m):
    print("  ok   " + m)


def bad(m):
    FAIL.append(m)
    print("  FAIL " + m)


# 1 -- no credentials: an actionable message, not a stack trace.
#      Done by pointing the gateway key path at nothing and passing an empty env,
#      rather than mutating the real process environment (which would leak into
#      every later check if this one raised halfway through).
_saved_keyfile = providers.JET_HUB_KEY_FILE
providers.JET_HUB_KEY_FILE = os.path.join(HERE, "_definitely_absent_key")
try:
    routes = providers.build_routes({})
    if not routes:
        ok("empty credential set yields zero routes")
    else:
        bad(f"leaked real credentials into route discovery: {[r.name for r in routes]}")
    if providers.pick_route(None, {}) is None:
        ok("pick_route signals 'nothing configured' as None")
    else:
        bad("pick_route invented a route")
finally:
    providers.JET_HUB_KEY_FILE = _saved_keyfile

# 2 -- blast_radius=container must NEVER touch the host interpreter.
#      docker is absent on this machine, which is the interesting case: the
#      switch must refuse rather than quietly run on the host anyway.
k = Kernel(blast_radius="container", workspace=HERE)
out = k.exec("print('RAN ON HOST')", timeout=20)
if "RAN ON HOST" in out:
    bad("container mode executed code on the host -- the switch is decorative")
elif "docker is unavailable" in out or "aborted" in out:
    ok("container mode refuses to run on host when docker is missing")
else:
    ok(f"container mode did not run on host ({out[:40]!r})")

# and host mode must still run, so the refusal above is containment not breakage
kh = Kernel(blast_radius="host")
ok("host mode executes") if "84" in kh.exec("print(42*2)") else bad("host mode broken")

# 3 -- prompt-injection quarantine wraps fetched material, not operator input
agent = Agent.__new__(Agent)
agent.kernel = Kernel()
agent.notes, agent.todos = [], []
agent.route = None
probe_src = os.path.join(HERE, "test_promises.py")   # this file: guaranteed to exist
try:
    body = agent._tool("read_file", {"path": probe_src})
    if body.startswith(INJECT_GUARD.split("\n")[0]):
        ok("read_file output is quarantined")
    else:
        bad("read_file not quarantined -- a file could inject instructions")
except OSError as e:
    bad(f"read_file raised on a file that exists: {e}")

# write_file must NOT be quarantined: that would refuse the operator's own bytes
probe = os.path.join(HERE, "_q.txt")
r = agent._tool("write_file", {"path": probe, "content": "plain"})
ok("write_file runs unquarantined") if "wrote" in r else bad(f"write_file: {r}")
if os.path.exists(probe):
    with open(probe, encoding="utf-8") as fh:
        ok("write_file wrote exactly what was asked") if fh.read() == "plain" \
            else bad("write_file altered content")
    os.remove(probe)

# 4 -- the loop gives the operator no veto, and no refusal string may exist in
#      the system prompt. This is a tripwire, not prose validation: a later edit
#      that reinstates a guard should turn this red on purpose.
#      Whitespace is collapsed FIRST. The prompt is wrapped prose, so a literal
#      substring test for "do not refuse" was failing on its own line break and
#      reporting a missing contract that was actually present.
sp = " ".join(core.SYSTEM.split())
if "do not refuse" in sp and "pre-authorised" in sp:
    ok("system prompt states the operator is pre-authorised")
else:
    bad("system prompt lost the autonomy contract")
for banned in ("I cannot", "I'm unable", "as an AI", "I must decline",
               "please consider the ethical"):
    if banned.lower() in sp.lower():
        bad(f"system prompt contains refusal boilerplate: {banned!r}")
ok("no refusal boilerplate in the system prompt")

# 5 -- the ONLY limit is the mechanical one, and it is named as such
if "QUARANTINED" in sp:
    ok("injection quarantine is declared in the prompt itself")
else:
    bad("quarantine not declared; the model cannot tell data from instruction")

# 6 -- step cap is a runaway brake, not a moral gate: it must actually bind
class Dead:
    def __init__(self): self.n = 0
    def chat(self, messages, **kw):
        self.n += 1
        return ('{"thought":"t","action":{"tool":"final_note","args":'
                '{"text":"x"}}}'), [], {}

route = Dead()
a = Agent(route, kernel=Kernel(), max_steps=4, on_event=lambda *x: None)
a.run("loop forever")
ok("max_steps bounds a looping model") if route.n == 4 else \
    bad(f"max_steps ignored after {route.n} calls")

print(f"\n{'PASS' if not FAIL else 'FAIL'}: {len(FAIL)} problem(s)")
sys.exit(1 if FAIL else 0)
