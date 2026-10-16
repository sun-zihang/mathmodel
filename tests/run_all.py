"""Run every check as its own subprocess, exactly as CI would."""
import os
import subprocess
import sys

env = dict(os.environ, PYTHONUTF8="1")
CHECKS = [
    ("unit", ["tests/test_tools.py"]),
    ("manifest", ["tests/test_manifest.py"]),
    ("mcp smoke", ["tests/test_smoke.py"]),
    ("promises", ["tests/test_promises.py"]),
    ("scipy-free", ["tests/check_no_scipy.py"]),
    ("gate selftest", ["tests/check_secrets.py", "--selftest"]),
    ("gate HEAD", ["tests/check_secrets.py", "--gate"]),
    ("gate worktree", ["tests/check_secrets.py", "--worktree", "--gate"]),
]

fails = []
for label, args in CHECKS:
    r = subprocess.run([sys.executable] + args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    tail = (r.stdout or r.stderr).strip().splitlines()
    last = tail[-1][:64] if tail else ""
    mark = "OK  " if r.returncode == 0 else "FAIL"
    if r.returncode:
        fails.append(label)
    print(f"  {mark} {label:15} rc={r.returncode}  {last}")

print("\nALL GREEN" if not fails else f"\nFAILED: {fails}")
sys.exit(1 if fails else 0)
