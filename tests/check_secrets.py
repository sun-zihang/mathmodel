"""Pre-publish sweep over committed content, not the working directory.

Working-tree checks miss what is only in git history; this reads blobs at HEAD
(or, with --all-history, in every commit) so publishing cannot leak something a
test never looked at.

Two classes, because the obvious one is not the only one:
  * credential-shaped literals -- a leaked token is unrecoverable once public
  * identity literals -- Windows user paths, hostnames, absolute paths that name
    a person. Not a vulnerability, just not something to publish unasked.

--selftest exists because a scanner that prints "0 matches" without ever having
fired is indistinguishable from a clean repo. It proves each pattern can fire and
that benign lines do not trip them; the empty-regex bug this caught once made the
whole PII pass report a clean 0 while scanning nothing.
"""
import os
import re
import subprocess
import sys

PATTERNS = {
    "github token": r"gh[pousr]_[0-9A-Za-z]{20,}|github_pat_[0-9A-Za-z_]{20,}",
    "openai-style key": r"sk-[0-9A-Za-z]{20,}",
    "aws key id": r"AKIA[0-9A-Z]{16}",
    "private key block": r"BEGIN [A-Z ]*PRIVATE KEY",
    "bearer literal": r"Bearer\s+[A-Za-z0-9_\-\.=]{25,}",
    "jwt": r"eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}",
    "inline api key assignment": r"(?i)(api[_-]?key|secret|password|passwd|token)\s*[:=]\s*[\"'][^\"']{16,}[\"']",
}
# Values that are legitimately long and non-secret.
BENIGN = re.compile(r"(sha256|digest|FNV|fnv1a|example|placeholder|your[-_]|\.\.\.|xxx|PATTERNS)", re.I)

# Identity shapes. Overridable so no operator's actual username is hardcoded into
# a public repo -- that would itself be the thing this looks for.
WHO = {
    # Backslash counts are tolerated 1-2 because a JSON config writes the escaped
    # form (two literal backslashes) while python source and plain text write one.
    # A single-backslash pattern silently misses the JSON case -- which is exactly
    # where an absolute local path tends to be committed. An earlier version also
    # doubled the backslashes in BOTH pattern and fixture, so both were wrong
    # together and the selftest passed: a self-consistent scanner is not a correct
    # one. The selftest below asserts both forms, not just the one it likes.
    "windows local user path": r"\\{1,2}Users\\{1,2}(?!\$|\{|\[|\*)",
    "absolute drive path": r"[A-Za-z]:\\{1,2}(?:Users|Documents)\\{1,2}[\w.\-]+",
    "machine hostname shape": r"\b[a-z]+-[a-z]+-\d+\b",
}
# An empty regex matches at every position, so a missing env var once injected a
# pattern that hit every line -- and the loop's skip guard turned the whole pass
# into a silent "0 matches". Never add empty patterns.
extra = [e for e in (x.strip() for x in re.split(
    r"[,;|]", os.environ.get("PUBLISH_EXTRA_PATTERNS", ""))) if e]
for i, e in enumerate(extra):
    WHO[f"operator-supplied #{i}"] = e


def selftest():
    """Prove the patterns fire, and that clean lines do not. A gate that always
    prints 0 is theatre."""
    cases = {
        "github token": "export GH=ghp_" + "A" * 36,
        "openai-style key": 'OPENAI_API_KEY = "sk-' + "b" * 32 + '"',
        "aws key id": "aws_access_key_id = AKIA" + "Q" * 16,
        "private key block": "-----BEGIN RSA PRIVATE KEY-----",
        "bearer literal": "authorization: Bearer " + "eyJz" * 8,
        "jwt": ("eyJ" + "hbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
                + "." + "eyJ" + "zdWIiOiIxMjM0NTY3ODkwIn0"),
        "inline api key assignment": 'api_key = "s3cr3t-value-long-enough"',
    }
    bad = 0
    for label, line in cases.items():
        fired = bool(re.search(PATTERNS[label], line)) and not BENIGN.search(line)
        print(("  ok   " if fired else "  FAIL ") + f"pattern fires: {label}")
        bad += 0 if fired else 1
    # Fixtures are built from chr(92) rather than written out: once this file is
    # committed, a literal Windows-path example in the source would match its own
    # pattern and the scan would flag its own test data. Concatenation keeps the
    # gate strict without a blanket self-exemption.
    #
    # BOTH slash counts are asserted. Testing only the doubled form is what let a
    # single-backslash pattern pass selftest while blind to real JSON output.
    bs = chr(92)
    pii_cases = {
        "windows local user path": [("plain text, one sep", "C:" + bs + "Users" + bs + "alice"),
                                     ("JSON escaped, two seps", 'D:\\' + bs + 'Users' + bs + '"bob"')],
        "absolute drive path": [("plain, with tail", "D:" + bs + bs + "Users" + bs + bs + "bob" + bs + "proj"),
                                ("single sep form", "C:" + bs + "Documents" + bs + "carol" + bs + "x")],
        "machine hostname shape": [("hostname in prose", "host work-laptop-9931 up")],
    }
    for label, cases in pii_cases.items():
        for desc, line in cases:
            fired = bool(re.search(WHO[label], line, re.I))
            print(("  ok   " if fired else "  FAIL ") + f"PII fires: {label} [{desc}]")
            bad += 0 if fired else 1
    for line in ["contextWindow = 1000000  # sha256 digest example placeholder",
                 "def solve_lp_max(profit, A, b):",
                 "ok   solver reproduces 190"]:
        tripped = [l for l, p in PATTERNS.items()
                   if re.search(p, line) and not BENIGN.search(line)]
        if tripped:
            print(f"  FAIL false positive {tripped} on: {line[:44]!r}")
            bad += 1
    print("  ok   benign lines do not trip it")
    print(f"\n{'PASS' if not bad else 'FAIL'}: selftest {bad} problem(s)")
    sys.exit(1 if bad else 0)


def blobs():
    """(commit, path) pairs. --all-history covers every commit, because a public
    repo publishes its history and a token in commit 1 stays leaked after commit
    2 deletes it from the tree."""
    if "--all-history" in sys.argv:
        seen, pairs = set(), []
        for commit in subprocess.run(["git", "log", "--all", "--format=%H"],
                                     capture_output=True, text=True).stdout.split():
            for line in subprocess.run(["git", "ls-tree", "-r", "--name-only", commit],
                                       capture_output=True, text=True).stdout.splitlines():
                if (commit, line) not in seen:
                    seen.add((commit, line))
                    pairs.append((commit, line))
        return pairs
    return [("HEAD", p) for p in subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "HEAD"],
        capture_output=True, text=True, check=True).stdout.split()]


if "--selftest" in sys.argv:
    selftest()

hits = 0
targets = blobs()
for commit, path in targets:
    blob = subprocess.run(["git", "show", f"{commit}:{path}"],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    if blob.returncode != 0:
        print(f"  ?? unreadable {path}")
        continue
    for line_no, line in enumerate(blob.stdout.splitlines(), 1):
        # Only this file gets an exemption, and only on lines that define rules.
        # A blanket "skip anything mentioning re.compile" would let a secret hide
        # on such a line: a silent false negative is far worse than one noisy
        # false positive in a publish gate.
        if path.endswith("tests/check_secrets.py") and any(
                k in line for k in ("PATTERNS", "WHO = {", "re.compile", 'r"')):
            continue
        for label, pat in PATTERNS.items():
            if BENIGN.search(line):
                continue
            for m in re.finditer(pat, line):
                hits += 1
                print(f"  CRED {label}: {path}:{line_no}: {m.group(0)[:52]!r}")
        for label, pat in WHO.items():
            for m in re.finditer(pat, line, re.I):
                hits += 1
                print(f"  PII  {label}: {path}:{line_no}: {m.group(0)[:52]!r}")

print(f"\n{len(targets)} blobs scanned, {hits} match(es)")
if "--gate" in sys.argv:
    sys.exit(1 if hits else 0)
