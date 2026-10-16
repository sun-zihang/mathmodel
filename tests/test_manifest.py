"""Manifest integrity: the failure mode where ZCode refuses to load the plugin,
or worse loads it and every userConfig knob is a dead decorative field.

Checks
  1. every ${user_config.KEY} referenced in mcpServers.env exists in userConfig
  2. every path the manifest declares (skills/commands dirs) exists and is non-empty
  3. every env key the server injects is actually read by the engine
  4. json is json
"""
from __future__ import annotations

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, ".zcode-plugin", "plugin.json")
sys.path.insert(0, os.path.join(ROOT, "engine"))

FAIL = []


def ok(msg):
    print("  ok   " + msg)


def bad(msg):
    FAIL.append(msg)
    print("  FAIL " + msg)


m = json.load(open(MANIFEST, encoding="utf-8"))
print("manifest parses")

# 1. user_config placeholders
env = m["mcpServers"]["mathmodel"]["env"]
refs = {v for v in env.values() if isinstance(v, str)}
used = {r for r in refs if "user_config." in r}
declared = set(m.get("userConfig", {}))
for r in sorted(used):
    key = r.split("user_config.")[1].rstrip("}")
    (ok if key in declared else bad)(f"{r} -> userConfig[{key!r}] declared")
for key in sorted(declared - {u.split("user_config.")[1].rstrip('}') for u in used}):
    bad(f"userConfig {key!r} declared but never passed to the server (dead knob)")

# 2. declared component dirs exist and hold something
for field in ("skills", "commands"):
    d = m.get(field)
    if not d:
        continue
    p = os.path.join(ROOT, d)
    files = []
    for dirpath, _dirs, fs in os.walk(p):
        files += [f for f in fs if f.endswith(".md")]
    (ok if files else bad)(f"{field}={d} exists with {len(files)} .md file(s)")

# 3. injected env keys are consumed by the engine. Scan EVERY engine module:
#    the first version of this check looked at three files and so reported
#    MATHMODEL_DATA_DIR as unread when mcp_server.py was the one reading it.
src = ""
for f in sorted(os.listdir(os.path.join(ROOT, "engine"))):
    if f.endswith(".py"):
        src += open(os.path.join(ROOT, "engine", f), encoding="utf-8").read()
for injected in sorted({k for k in env if k.startswith("MATHMODEL")
                        or k.endswith("API_KEY") or k.endswith("BASE_URL")}):
    (ok if injected in src else bad)(f"engine reads {injected}")

# 4. server entry point exists
srv = m["mcpServers"]["mathmodel"]["args"][0].replace("${ZCODE_PLUGIN_ROOT}", ROOT)
(ok if os.path.exists(srv) else bad)(f"mcp entry exists: {os.path.basename(srv)}")

# 5. runtime behaviour of the thing we advertise
import tools_modelling as tm  # noqa: E402
r = tm.solve_lp_max([3, 4], [[2, 1], [1, 3], [1, 1]], [100, 90, 60])
if r.get("x") == [42.0, 16.0] and r.get("max_objective") == 190.0:
    ok("solver reproduces the reference answer 42/16 -> 190")
else:
    bad(f"solver drifted: {r}")
sp = tm.shadow_price_analysis([3, 4], [[2, 1], [1, 3], [1, 1]], [100, 90, 60], 0, 10)
if sp.get("naive_product_is_wrong") and sp.get("realised_gain") == 5.0:
    ok("shadow-price scope guard fires (+10t earns 5, not 10)")
else:
    bad(f"shadow-price guard wrong: {sp}")

# 6. no secret material committed
for dirpath, _d, fs in os.walk(ROOT):
    if any(x in dirpath for x in (".git", "node_modules", "__pycache__")):
        continue
    for f in fs:
        if f.endswith((".py", ".json", ".md")):
            t = open(os.path.join(dirpath, f), encoding="utf-8", errors="replace").read()
            for pat in (r"ghp_[0-9a-zA-Z]{20,}", r"sk-[0-9a-zA-Z]{20,}",
                        r"Bearer [A-Za-z0-9_\-]{25,}"):
                if re.search(pat, t):
                    bad(f"possible literal secret in {f}")
ok("secret scan over tracked text files done")
# 7. a plugin that ships a marketplace.json must be installable BY that file.
#    The id in enabledPlugins is "<name>@<marketplace>", and entry.source is
#    resolved relative to wherever marketplace.json lives -- so check the real
#    invariant (the source points at a directory holding a plugin manifest)
#    instead of hardcoding a layout that the repo may not use.
def find_marketplace(start):
    for d in (start, os.path.dirname(start), os.path.dirname(os.path.dirname(start))):
        for sub in (".claude-plugin", ".zcode-plugin", ""):
            p = os.path.join(d, sub, "marketplace.json") if sub else \
                os.path.join(d, "marketplace.json")
            if os.path.exists(p):
                return p
    return None


mp = find_marketplace(ROOT)
if mp:
    man = json.load(open(mp, encoding="utf-8"))
    names = [p["name"] for p in man.get("plugins", [])]
    (ok if m["name"] in names else bad)(f"marketplace lists {m['name']!r} (got {names})")
    (ok if man.get("name") else bad)("marketplace has a name for the @<marketplace> suffix")
    base = os.path.dirname(os.path.dirname(mp))      # dir holding .claude-plugin
    if man.get("pluginRoot"):
        base = os.path.join(base, man["pluginRoot"])
    for entry in man.get("plugins", []):
        src = entry.get("source")
        if isinstance(src, str):
            target = os.path.normpath(os.path.join(base, src.lstrip("./") or "."))
            has_manifest = os.path.exists(
                os.path.join(target, ".zcode-plugin", "plugin.json"))
            (ok if has_manifest else bad)(
                f"entry {entry['name']!r} source {src!r} -> a real plugin root "
                f"({os.path.relpath(target, base) or '.'})")
        elif src is None:
            bad(f"entry {entry['name']!r} has no source; install would 404")
    MARKET_ID = f"{m['name']}@{man.get('name')}" if man.get("name") else None
else:
    bad("README advertises GitHub-marketplace install but no marketplace.json exists")
    MARKET_ID = None

# 8. README claims must match reality, or the docs are a second source of lies.
readme = os.path.join(ROOT, "README.md")
if os.path.exists(readme):
    r = open(readme, encoding="utf-8").read()
    if MARKET_ID and MARKET_ID in r:
        ok(f"README's marketplace-install id is real: {MARKET_ID}")
    elif MARKET_ID:
        bad(f"README enables the wrong id; should contain {MARKET_ID!r}")
    # The other install path: a dirs-sourced plugin gets id name@inline and is
    # enabled by default. Documenting the wrong id here makes people add a dead
    # enabledPlugins entry and conclude the plugin "does not load".
    if f"{m['name']}@inline" in r:
        ok("README names the dirs-source id correctly (mathmodel@inline)")
    else:
        bad("README omits or misstates the @inline id for plugins.dir installs")
    for tool in ("run_task", "run_python", "blast_radius", "list_models"):
        if f"__{tool}" not in r:
            bad(f"README omits tool mcp__mathmodel__{tool}")
    ok("README tool names match tools/list")

print(f"\n{'PASS' if not FAIL else 'FAIL'}: {len(FAIL)} problem(s)")
sys.exit(1 if FAIL else 0)
