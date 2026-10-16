"""Fallbacks on a machine with NO optional dependencies.

CI runs this in a stdlib-only environment. It exists because "graceful
degradation" is the kind of claim that is true in a docstring and false in code:
if the pure-simplex path or the ASCII-plot path has a bug, only an interpreter
without scipy will find it -- a machine WITH scipy never takes those branches.

Run directly (assumes scipy/matplotlib are absent):
    python tests/check_no_scipy.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "engine"))

for blocked in ("scipy", "numpy", "matplotlib", "pandas", "sympy"):
    sys.modules[blocked] = None  # type: ignore[assignment]

import tools_modelling as tm  # noqa: E402

fails = []


def want(label, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + label + (f"  {detail}" if not cond else ""))
    if not cond:
        fails.append(label)


try:
    import scipy  # noqa: F401
    print("  SKIP scipy is importable; this check only means something without it")
    sys.exit(0)
except ImportError:
    pass

r = tm.solve_lp_max([3, 4], [[2, 1], [1, 3], [1, 1]], [100, 90, 60])
want("pure simplex is used", str(r.get("solver", "")).startswith("simplex"), r.get("solver"))
want("optimum still correct", r.get("max_objective") == 190.0, r.get("max_objective"))
want("x still correct", r.get("x") == [42.0, 16.0], r.get("x"))
want("shadow prices still present", r.get("marginals") == [1.0, 1.0, 0.0], r.get("marginals"))

sp = tm.shadow_price_analysis([3, 4], [[2, 1], [1, 3], [1, 1]], [100, 90, 60], 0, 10)
want("scope guard works without scipy",
     sp.get("naive_product_is_wrong") and sp.get("realised_gain") == 5.0,
     f"{sp.get('realised_gain')}/{sp.get('naive_product')}")

p = tm.plot([0, 1, 2, 3], [0, 1, 4, 9], path=os.path.join(HERE, "out", "no.png"))
want("plot degrades to ASCII instead of crashing", p.get("ok") is False and bool(p.get("ascii")))
want("ASCII chart has axes", p.get("ascii", "").count("|") > 8)

want("describe works stdlib-only", tm.describe([1, 2, 3, 4])["iqr"] == 1.5)
want("rk4 works stdlib-only", abs(tm.rk4(lambda t, y: [-y[0]], [1.0], 0, 1, 100)[-1][1][0] - 0.3678794) < 1e-4)

print(f"\n{'PASS' if not fails else 'FAIL'}: {len(fails)} problem(s)")
sys.exit(1 if fails else 0)
