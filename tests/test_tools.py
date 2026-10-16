"""Regression tests. Run:  python test_tools.py

The two solver paths (scipy / pure simplex) must agree on BOTH the optimum and
the shadow prices -- they previously disagreed on sign, which is invisible in a
demo and fatal in a report.
"""
from __future__ import annotations

import os
import sys

# Explicit and OS-correct: the earlier one-liner keyed on "/" and so did nothing
# on Windows, where __file__ uses backslashes -- it only ever worked because the
# script happened to sit beside the module. Now they live in sibling dirs.
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "engine"))
OUT_DIR = os.path.join(HERE, "out")

import tools_modelling as tm  # noqa: E402

PASS, FAIL = 0, 0


def check(name, got, want, tol=1e-6):
    global PASS, FAIL
    ok = _close(got, want, tol)
    print(("  ok   " if ok else "  FAIL ") + name)
    if not ok:
        print(f"        got  {got}\n        want {want}")
        FAIL += 1
    else:
        PASS += 1


def _close(a, b, tol):
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= tol * max(1.0, abs(b))
    return a == b


def _no_scipy():
    for m in [k for k in sys.modules if k.startswith("scipy")]:
        del sys.modules[m]
    sys.modules["scipy"] = None
    sys.modules["scipy.optimize"] = None


def _with_scipy():
    for m in [k for k in sys.modules if k.startswith("scipy")]:
        del sys.modules[m]


# ---------------------------------------------------------------- LP
PROFIT = [3, 4]
A = [[2, 1], [1, 3], [1, 1]]
B = [100, 90, 60]

print("LP optimum (the statement problem)")
r = tm.solve_lp_max(PROFIT, A, B)
check("scipy x", r["x"], [42.0, 16.0])
check("scipy max profit", r["max_objective"], 190.0)
check("scipy shadow prices", r["marginals"], [1.0, 1.0, 0.0])
check("scipy slack", r["slack"], [0.0, 0.0, 2.0])

print("\nPure simplex must agree with scipy (optimum AND dual signs)")
_no_scipy()
s = tm.solve_lp_max(PROFIT, A, B)
check("simplex solver used", s["solver"], "simplex(pure)")
check("simplex x", s["x"], [42.0, 16.0])
check("simplex max profit", s["max_objective"], 190.0)
check("simplex shadow prices == scipy's", s["marginals"], r["marginals"])
_with_scipy()

print("\nmin-form contract: solve_lp minimises, duals follow that form")
_no_scipy()
mn = tm.solve_lp([-3, -4], A, B)
_with_scipy()
ms = tm.solve_lp([-3, -4], A, B)
check("simplex min fun", mn["fun"], ms["fun"])
check("simplex min marginals sign-match", mn["marginals"], ms["marginals"])

# ---------------------------------------------------------------- shadow trap
print("\nShadow-price scope (the classic report error)")
sp = tm.shadow_price_analysis(PROFIT, A, B, row=0, delta=10)
check("local marginal u1", sp["local_marginal"], 1.0)
check("naive 10*u1", sp["naive_product"], 10.0)
check("REALISED gain is only 5", sp["realised_gain"], 5.0)
check("naive product is flagged wrong", sp["naive_product_is_wrong"], True)
check("valid increase upto", sp["valid_increase_upto"], 5.0)
check("new objective at +10", sp["base"]["max_objective"] + sp["realised_gain"], 195.0)

print("\nIn-scope change must NOT be flagged")
sp2 = tm.shadow_price_analysis(PROFIT, A, B, row=0, delta=3)
check("delta 3 realised", sp2["realised_gain"], 3.0)
check("delta 3 naive ok", sp2["naive_product_is_wrong"], False)

# ---------------------------------------------------------------- numerics
print("\nNumerics")
check("bisect", tm.bisect(lambda x: x ** 2 - 2, 1, 2)["root"], 2 ** 0.5)
check("newton", tm.newton(lambda x: x ** 2 - 2, lambda x: 2 * x, 1.0)["root"], 2 ** 0.5)
traj = tm.rk4(lambda t, y: [-y[0]], [1.0], 0, 1, n=200)
check("rk4 exp decay", traj[-1][1][0], 2.718281828 ** -1, 1e-4)

print("\nStats")
d = tm.describe([2, 4, 4, 4, 5, 5, 7, 9])
check("mean", d["mean"], 5.0)
check("median", d["median"], 4.5)
# Q1=4.0 Q3=5.5 -> IQR 1.5, cross-checked against numpy.quantile. "exclusive"
# (statistics' own default) would give 2.5; the method is pinned and reported.
check("iqr (inclusive, == numpy)", d["iqr"], 1.5)
check("quantile method declared", d["quantile_method"], "inclusive")
o = tm.ols([1, 2, 3, 4], [2, 4, 6, 8])
check("ols slope", o["slope"], 2.0)
check("ols r2", o["r2"], 1.0)
check("pearson", tm.pearson([1, 2, 3], [1, 2, 3])["r"], 1.0)

print("\nDegenerate inputs must degrade, not crash")
check("describe empty", tm.describe([])["n"], 0)
check("ols no variance", tm.ols([1, 1, 1], [1, 2, 3])["ok"], False)
check("infeasible LP reported", tm.solve_lp_max([1, 1], [[1, 1]], [-5])["ok"], False)

print("\nSensitivity + plotting")
sens = tm.sensitivity(lambda k: 100 * k ** 0.5, 1.0)
check("sensitivity rows", len(sens["rows"]), 5)
p = tm.plot([0, 1, 2, 3], [0, 1, 4, 9], path=os.path.join(OUT_DIR, "fig.png"))
check("plot wrote a real png", os.path.exists(os.path.join(OUT_DIR, "fig.png")), True)
check("plot returned ascii fallback", bool(p["ascii"]), True)
check("ascii plot has rows", p["ascii"].count("\n") >= 8, True)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
