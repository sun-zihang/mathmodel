"""Modelling toolset the agent imports inside run_python.

Kept dependency-light: everything degrades to stdlib if scipy/pulp are absent,
because a competition machine frequently will not have them and "pip install"
mid-task is a network gamble.
"""

from __future__ import annotations

import json
import math
import os
import statistics


# ---------------- linear / integer programming ----------------

def _clean(v, digits=10):
    """Solver output is float64 and carries ~1e-14 residuals.

    Both leak into the report if passed through: numpy scalars serialise to
    strings under json.dump(default=str), and 4.999999999999943 reads as a
    different number than 5. Flatten to python floats and snap genuine
    round-numbers, without touching values that really are 4.9999.
    """
    if isinstance(v, bool):
        return v
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    if math.isnan(f) or math.isinf(f):
        return f
    r = round(f, digits)
    if r != f and abs(f - round(f)) < 1e-9 * max(1.0, abs(f)):
        return float(round(f))
    return r


def _scrub(obj):
    if isinstance(obj, dict):
        return {k: _scrub(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_scrub(v) for v in obj]
    return _clean(obj) if isinstance(obj, (int, float)) and not isinstance(obj, bool) else obj


def solve_lp(c, A=None, b=None, Aeq=None, beq=None, bounds=None, integrality=None):
    """max or min a linear objective under linear constraints.

    Signature follows scipy (it MINIMISES). To MAXIMISE profit, pass
    negated coefficients and call ``solve_lp_max`` instead -- that one does the
    negation and the sign flip for you, which is where LP reports usually go
    wrong.

    Returns the primal solution AND ``marginals`` (dual values = shadow prices)
    for every <= row. The marginals are the whole point of a sensitivity
    question; scipy computes them, so we surface them rather than making the
    caller re-solve.
    """
    n = len(c)
    try:
        from scipy.optimize import linprog
        res = linprog(c, A_ub=A, b_ub=b, A_eq=Aeq, b_eq=beq,
                      bounds=bounds or [(0, None)] * n, method="highs")
        if not res.success:
            return {"ok": False, "why": res.message, "status": res.status}
        out = {"ok": True, "x": list(res.x), "fun": res.fun, "solver": "scipy.highs"}
        # scipy keeps duals nested per constraint block, NOT on the result root.
        # Reading res.marginals silently yields nothing and the shadow-price
        # question then gets answered by re-solving -- so read the right field.
        ineq = getattr(res, "ineqlin", None)
        if ineq is not None and len(getattr(ineq, "marginals", [])):
            out["marginals"] = list(ineq.marginals)     # dual of each A row (min form)
            out["marginal_rows"] = list(range(len(ineq.marginals)))
        eq = getattr(res, "eqlin", None)
        if eq is not None and len(getattr(eq, "marginals", [])):
            out["eq_marginals"] = list(eq.marginals)
        if getattr(res, "slack", None) is not None:
            out["slack"] = list(ineq.residual) if ineq is not None else list(res.slack)
        return _scrub(out)
    except ImportError:
        pass

    if integrality and all(integrality):
        return _bnb_small(c, A, b, Aeq, beq, bounds, n)

    # No scipy: real simplex, so the agent still ships an optimum AND the
    # shadow prices instead of refusing on the machine that has neither.
    try:
        r = _simplex_max(_neg(c), A, b, bounds or [(0, None)] * n)
    except _LPInfeasible as e:
        return {"ok": False, "why": str(e), "solver": "simplex"}
    # _simplex_max reports duals of the MAX problem it solved; this function's
    # contract is the MIN problem (scipy convention). Without the flip, the two
    # solver paths return shadow prices of opposite sign -- which is precisely
    # the kind of bug that survives a demo and dies in a competition.
    if r.get("ok") and "marginals" in r:
        r["marginals"] = [-m for m in r["marginals"]]
    return _scrub(r)


def solve_lp_max(profit, A, b, Aeq=None, beq=None, bounds=None):
    """Maximise ``profit`` -- the form a modelling report actually wants.

    Negates internally, because both solver paths minimise. That negation also
    flips the duals: scipy reports the marginals of the MINIMISATION, so for a
    maximisation each ``<=`` row's shadow price is the negated value, and that
    positive number is "value of one more unit of this resource".

    Shadow prices are LOCAL to the current basis. They are only valid until some
    other constraint starts binding; multiplying one by a proposed increase is
    the classic report error. Use ``shadow_price_analysis``, which re-solves and
    reports the range over which the marginal actually holds.
    """
    n = len(profit)
    r = solve_lp(_neg(profit), A, b, Aeq, beq, bounds or [(0, None)] * n)
    if not r.get("ok"):
        return r
    r["max_objective"] = -r["fun"]
    if "marginals" in r:
        r["marginals"] = [-m for m in r["marginals"]]   # price of relaxing <= row
    del r["fun"]
    return r


class _LPInfeasible(Exception):
    pass


def _neg(v):
    return [-x for x in v]


def _simplex_max(c, A, b, bounds):
    """Big-M free tableau simplex for max c.x, A x <= b, x >= 0.

    Honest about its own limits: it handles the standard <= form with nonneg
    variables (i.e. almost every competition LP) and raises otherwise instead of
    silently returning something wrong.
    """
    if bounds and any((lo not in (0, None) and lo != 0) or hi is not None
                      for lo, hi in bounds):
        raise _LPInfeasible("pure simplex here covers x>=0 with finite-upper "
                            "bounds unsupported; install scipy")
    m, n = len(A), len(c)
    if any(bi < 0 for bi in b):
        raise _LPInfeasible("negative rhs; needs two-phase, install scipy")
    # tableau: [A | I | b] rows, objective row last
    T = [[float(A[i][j]) for j in range(n)] + [1.0 if k == i else 0.0 for k in range(m)]
         + [float(b[i])] for i in range(m)]
    obj = [-float(ci) for ci in c] + [0.0] * m + [0.0]
    basis = list(range(n, n + m))
    for _ in range(5000):
        piv_col = min(range(n + m), key=lambda j: obj[j])
        if obj[piv_col] >= -1e-12:
            x = [0.0] * n
            for i, bv in enumerate(basis):
                if bv < n:
                    x[bv] = T[i][-1]
            duals = [obj[n + i] for i in range(m)]
            return {"ok": True, "x": x, "fun": -obj[-1], "solver": "simplex(pure)",
                    "marginals": duals, "marginal_rows": list(range(m))}
        ratios = [(T[i][-1] / T[i][piv_col], i) for i in range(m) if T[i][piv_col] > 1e-12]
        if not ratios:
            raise _LPInfeasible("unbounded")
        _, piv_row = min(ratios)
        pv = T[piv_row][piv_col]
        T[piv_row] = [v / pv for v in T[piv_row]]
        for i in range(m):
            if i != piv_row and abs(T[i][piv_col]) > 1e-14:
                f = T[i][piv_col]
                T[i] = [a - f * bb for a, bb in zip(T[i], T[piv_row])]
        f = obj[piv_col]
        if abs(f) > 1e-14:
            obj = [a - f * bb for a, bb in zip(obj, T[piv_row])]
        basis[piv_row] = piv_col
    raise _LPInfeasible("iteration cap")


def _bnb_small(c, A, b, Aeq, beq, bounds, n, cap=200000):
    """Honest fallback: exhaustive search over integer boxes, only when the box
    is small enough to enumerate. Marks the result as enumerated, not solved."""
    grids = []
    for i in range(n):
        lo, hi = (bounds[i] if bounds else (0, 10))
        if lo is None or hi is None or hi - lo > 30:
            return {"ok": False, "why": f"var {i} range too wide to enumerate"}
        grids.append(range(int(lo), int(hi) + 1))
    best = None
    seen = 0
    import itertools
    for x in itertools.product(*grids):
        seen += 1
        if seen > cap:
            return {"ok": False, "why": f"enumeration hit {cap} cap; need a real solver"}
        if A and b and any(sum(ai * xi for ai, xi in zip(row, x)) > bi + 1e-9
                           for row, bi in zip(A, b)):
            continue
        if Aeq and beq and any(abs(sum(ai * xi for ai, xi in zip(row, x)) - bi) > 1e-9
                               for row, bi in zip(Aeq, beq)):
            continue
        fun = sum(ci * xi for ci, xi in zip(c, x))
        if best is None or fun < best[0]:
            best = (fun, x)
    if best is None:
        return {"ok": False, "why": "infeasible over the enumerated box"}
    return {"ok": True, "x": list(best[1]), "fun": best[0],
            "solver": f"enumeration ({seen} points) -- verify with a real solver"}


# ---------------- numerics ----------------

def newton(f, df, x0, tol=1e-12, iters=100):
    x = x0
    for _ in range(iters):
        fx = f(x)
        if abs(fx) < tol:
            return {"ok": True, "root": x, "residual": fx, "iters": _ + 1}
        d = df(x)
        if d == 0:
            return {"ok": False, "why": "zero derivative"}
        x -= fx / d
    return {"ok": False, "why": "did not converge", "last": x, "residual": f(x)}


def bisect(f, a, b, tol=1e-12, iters=200):
    fa, fb = f(a), f(b)
    if fa * fb > 0:
        return {"ok": False, "why": f"no sign change: f({a})={fa}, f({b})={fb}"}
    for i in range(iters):
        m = (a + b) / 2
        fm = f(m)
        if abs(fm) < tol or (b - a) / 2 < tol:
            return {"ok": True, "root": m, "iters": i + 1}
        if fa * fm < 0:
            b, fb = m, fm
        else:
            a, fa = m, fm
    return {"ok": True, "root": (a + b) / 2, "iters": iters}


def rk4(f, y0, t0, t1, n=1000):
    h = (t1 - t0) / n
    t, y = t0, list(y0) if isinstance(y0, (list, tuple)) else [y0]
    traj = [(t, list(y))]
    for _ in range(n):
        k1 = f(t, y)
        k2 = f(t + h / 2, [a + h * b / 2 for a, b in zip(y, k1)])
        k3 = f(t + h / 2, [a + h * b / 2 for a, b in zip(y, k2)])
        k4 = f(t + h, [a + h * b for a, b in zip(y, k3)])
        y = [a + h * (b + 2 * c + 2 * d + e) / 6
             for a, b, c, d, e in zip(y, k1, k2, k3, k4)]
        t += h
        traj.append((t, list(y)))
    return traj


# ---------------- stats the judges actually check ----------------

def describe(xs, label=""):
    xs = [x for x in xs if x is not None and not (isinstance(x, float) and math.isnan(x))]
    n = len(xs)
    if n == 0:
        return {"label": label, "n": 0}
    out = {
        "label": label, "n": n,
        "mean": statistics.fmean(xs),
        "median": statistics.median(xs),
        "sd": statistics.stdev(xs) if n > 1 else 0.0,
        "min": min(xs), "max": max(xs),
    }
    out["cv"] = out["sd"] / out["mean"] if out["mean"] else None
    if n >= 2:
        # "inclusive" (method 7) is the convention numpy.quantile, pandas, and
        # most Chinese textbooks use; statistics' own default is "exclusive"
        # (method 6) and quietly gives a different IQR. Pinning it here, and
        # reporting it, so two readers of the same table cannot get two numbers.
        q = statistics.quantiles(xs, n=4, method="inclusive")
        out.update(q1=q[0], q3=q[2], iqr=q[2] - q[0], quantile_method="inclusive")
    if n >= 3:
        out["skew"] = _skew(xs)
    return out


def _skew(xs):
    n = len(xs)
    m = statistics.fmean(xs)
    s = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    if s == 0:
        return 0.0
    return (n / ((n - 1) * (n - 2))) * sum(((x - m) / s) ** 3 for x in xs)


def pearson(xs, ys):
    n = len(xs)
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    den = math.sqrt(sum((a - mx) ** 2 for a in xs) * sum((b - my) ** 2 for b in ys))
    if den == 0:
        return {"ok": False, "why": "zero variance"}
    r = num / den
    if n > 2:
        t = r * math.sqrt((n - 2) / (1 - r * r)) if abs(r) < 1 else float("inf")
        return {"ok": True, "r": r, "r2": r * r, "t": t, "df": n - 2}
    return {"ok": True, "r": r, "r2": r * r}


def ols(xs, ys):
    """Simple least squares with the residuals the report needs."""
    n = len(xs)
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((a - mx) ** 2 for a in xs)
    sxy = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    if sxx == 0:
        return {"ok": False, "why": "no x variance"}
    b1 = sxy / sxx
    b0 = my - b1 * mx
    pred = [b0 + b1 * a for a in xs]
    res = [y - p for y, p in zip(ys, pred)]
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum(e * e for e in res)
    r2 = 1 - ss_res / ss_tot if ss_tot else None
    mse = ss_res / (n - 2) if n > 2 else None
    se_b1 = math.sqrt(mse / sxx) if mse and sxx else None
    return {"ok": True, "intercept": b0, "slope": b1, "r2": r2,
            "rmse": math.sqrt(ss_res / n), "residuals": res,
            "se_slope": se_b1,
            "t_slope": (b1 / se_b1) if se_b1 else None,
            "note": "n=%d; with small n report the CI, not just the point estimate" % n}


def shadow_price_analysis(profit, A, b, row, delta, bounds=None, sweep=25):
    """Where the shadow price stops being the answer.

    The classic report error: take the dual price and multiply by the proposed
    change. Dual prices are LOCAL -- they hold only until the basis changes, and
    competition problems are picked precisely so that the naive product is wrong.

    Returns the local marginal, the realised gain for ``delta``, the largest
    increase that still earns the full marginal, and a verdict sentence.
    """
    base = solve_lp_max(profit, A, b, bounds=bounds)
    if not base.get("ok"):
        return {"ok": False, "why": base.get("why")}
    local = base["marginals"][row]

    def obj_at(v):
        bb = list(b)
        bb[row] = v
        r = solve_lp_max(profit, A, bb, bounds=bounds)
        return r.get("max_objective") if r.get("ok") else None

    target = b[row] + delta
    realised = obj_at(target)
    gain = None if realised is None else realised - base["max_objective"]

    # Walk outward until the realised slope departs from the dual price.
    # The value function of an LP is piecewise-linear and concave in the rhs, so
    # "slope still equals the dual" is true on an initial interval and false
    # after it -- which makes it binary-searchable. A fixed grid was wrong here:
    # it reported the last grid point inside the range (4.8) instead of the
    # actual basis change (5.0).
    def earns_full(t):
        """True while the value function still rises exactly at the dual price.

        Compares gain(t) against local*t directly. The obvious-looking slope
        form, (gain(t))/t, is numerically undefined as t->0 and made this return
        0.0 for a problem whose true answer is 5.0.

        Tolerance is ABSOLUTE, not relative to local*t: the only error here is
        the solver's own residual (~1e-15), which does not scale with t. A
        relative tolerance let the search overshoot the real basis change by
        ~5e-6 and report 5.000005.
        """
        if t <= 0:
            return True
        g = obj_at(b[row] + t)
        if g is None:
            return False
        expect = local * t
        return abs((g - base["max_objective"]) - expect) <= 1e-9

    hi = max(abs(delta), 1.0) * 8
    if earns_full(hi):
        valid_upto = hi          # still valid past the probed horizon
    else:
        lo = 0.0                 # earns_full(0) is true by definition: bisect-safe
        for _ in range(max(sweep, 60)):
            mid = (lo + hi) / 2
            if earns_full(mid):
                lo = mid
            else:
                hi = mid
        valid_upto = lo

    naive = local * delta
    warn = gain is not None and abs(gain - naive) > 1e-6 * max(1.0, abs(naive))
    verdict = (
        f"影子价格 {local:g} 只在 A 增加不超过 {valid_upto:g} 吨的范围内成立。"
        + (f"题目给的 {delta:g} 吨已超出该范围，实际增益是 {gain:g} 而不是 {naive:g}；"
           f"直接相乘会高估 {naive - gain:g}。" if warn
           else f" {delta:g} 吨在范围内，{naive:g} 可以直接用。")
    )
    return _scrub({"ok": True, "local_marginal": local, "delta": delta,
                   "naive_product": naive, "realised_gain": gain,
                   "valid_increase_upto": valid_upto, "naive_product_is_wrong": warn,
                   "verdict": verdict, "base": base})


def sensitivity(base, param, deltas=(0.9, 0.95, 1.0, 1.05, 1.1)):
    """弹性表：判分最爱问「你这个结论稳不稳」。base 需返回单一标量指标。"""
    rows = []
    for d in deltas:
        try:
            rows.append({"delta": d, "param": param * d, "value": base(param * d)})
        except Exception as e:
            rows.append({"delta": d, "param": param * d,
                         "value": None, "error": f"{type(e).__name__}: {e}"})
    vals = [r["value"] for r in rows if isinstance(r["value"], (int, float))]
    spread = (max(vals) - min(vals)) if len(vals) >= 2 else None
    return {"rows": rows, "spread": spread,
            "robust": (spread is not None and min(vals) > 0
                       and abs(spread) < 0.2 * abs(sum(vals) / len(vals)))}


# ---------------- plotting: PNG when matplotlib exists, ASCII always ----------------

def ascii_plot(xs, ys, width=64, height=16, title="", marker="#"):
    """Terminal chart. Exists because a competition VM often has no matplotlib,
    and a figure in the report is not optional either way."""
    pts = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pts) < 2:
        return "[ascii_plot] need at least two points"
    x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
    y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
    if x1 == x0:
        x1 = x0 + 1
    if y1 == y0:
        y1 = y0 + 1
    grid = [[" "] * width for _ in range(height)]
    for x, y in pts:
        col = int(round((x - x0) / (x1 - x0) * (width - 1)))
        row = int(round((y1 - y) / (y1 - y0) * (height - 1)))
        grid[row][col] = marker
    lines = ([title] if title else [])
    for i, row in enumerate(grid):
        label = f"{y1 - i * (y1 - y0) / (height - 1):>9.3g} |"
        lines.append(label + "".join(row))
    lines.append(" " * 10 + "+" + "-" * width)
    lines.append(" " * 11 + f"{x0:<{width // 2}.3g}{x1:>{width - width // 2}.3g}")
    return "\n".join(lines)


def plot(xs, ys, path="out/fig.png", title="", xlabel="x", ylabel="y", kind="line"):
    """Write a real figure when matplotlib is installed; report honestly when not.

    Never silently returns nothing -- the caller gets the ASCII fallback text so
    the number still reaches the report.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return {"ok": False, "why": "matplotlib not installed",
                "ascii": ascii_plot(xs, ys, title=f"{title} [{xlabel} vs {ylabel}]")}
    fig, ax = plt.subplots(figsize=(6, 4), dpi=150)
    if kind == "bar":
        ax.bar(range(len(ys)), ys)
        ax.set_xticks(range(len(ys)))
        if xs and all(isinstance(v, str) for v in xs):
            ax.set_xticklabels(xs, rotation=30, ha="right")
    elif kind == "scatter":
        ax.scatter(xs, ys, s=14)
    else:
        ax.plot(xs, ys, marker="o", ms=3)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(alpha=.3)
    fig.tight_layout()
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
    return {"ok": True, "path": path,
            "ascii": ascii_plot(xs, ys if all(isinstance(v, (int, float)) for v in ys)
                                else range(len(ys)), title=title)}


def feval(expr, **vars):
    """sympy-backed evaluation so a formula from the write-up can be checked
    against a number instead of trusted. Returns None when it does not parse."""
    try:
        import sympy
        e = sympy.sympify(expr)
        return float(e.subs({k: sympy.Symbol(k) and v for k, v in vars.items()}))
    except Exception as e:
        return {"ok": False, "why": f"{type(e).__name__}: {e}"}

def table(rows, headers=None, align=None):
    rows = [[("" if v is None else (f"{v:.4f}" if isinstance(v, float) else str(v)))
             for v in r] for r in rows]
    headers = [str(h) for h in (headers or (range(len(rows[0])) if rows else []))]
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h)
              for i, h in enumerate(headers)]
    sep = "+".join("-" * (w + 2) for w in widths)
    out = [sep, "| " + " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers)) + " |", sep]
    for r in rows:
        out.append("| " + " | ".join(c.ljust(widths[i]) for i, c in enumerate(r)) + " |")
    out.append(sep)
    return "\n".join(out)


def save(obj, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2, default=str)
    return path
