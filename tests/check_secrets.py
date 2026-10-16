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


# Single source of truth for the scanner's own synthetic strings. selftest() must
# fire on these; the history waiver may only ever excuse a substring of these.
# Together that means widening the waiver requires editing fixtures the tests
# depend on -- there is no table to quietly append a real secret to.
SELFTEST_FIXTURES = [
    "export GH=ghp_" + "A" * 36,
    'OPENAI_API_KEY = "sk-' + "b" * 32 + '"',
    "aws_access_key_id = AKIA" + "Q" * 16,
    "--" + "BEGIN RSA PRIV" + "ATE KEY--",
    "auth" + "orization: Bearer " + "eyJz" * 8,
    "eyJ" + "hbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" + "." + "eyJ" + "zdWIiOiIxMjM0NTY3ODkwIn0",
    'api' + '_key = "s3cr3t-value-long-enough"',
    "host work-lap" + "top-9931 up",
]
_b = chr(92)
SELFTEST_FIXTURES += [
    "C:" + _b + "Users" + _b + "alice",
    "D:" + _b + _b + "Users" + _b + _b + '"bob"',
    "D:" + _b + _b + "Users" + _b + _b + "bob" + _b + "proj",
    "C:" + _b + "Documents" + _b + "carol" + _b + "x",
]


def selftest():
    """Prove the patterns fire, and that clean lines do not. A gate that always
    prints 0 is theatre."""
    # Fixtures live at module scope (SELFTEST_FIXTURES) so the history waiver and
    # the firing proof read the exact same strings. Literal fixtures here once made
    # the pushed repo trip its own gate.
    bad = 0
    for label, pat in PATTERNS.items():
        fired = any(re.search(pat, f) and not BENIGN.search(f)
                    for f in SELFTEST_FIXTURES)
        print(("  ok   " if fired else "  FAIL ") + f"pattern fires: {label}")
        bad += 0 if fired else 1
    # BOTH slash counts must be asserted for the path shapes: testing only the
    # doubled form is what let a single-backslash pattern pass selftest while
    # being blind to real JSON output.
    for label in ("windows local user path", "absolute drive path",
                  "machine hostname shape"):
        fired = any(re.search(WHO[label], f, re.I) for f in SELFTEST_FIXTURES)
        print(("  ok   " if fired else "  FAIL ") + f"PII fires: {label}")
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

    # The waiver is only defensible if it demonstrably cannot mute a real secret.
    # Assert the negative, or "derived, not listed" is just a comment.
    real_looking = "ghp_" + "R" * 36                      # not any fixture's substring
    cases = [
        ("refuses an unknown snippet in an old commit",
         waivable("229ca74a79e9a9b9380f9e4a4cf16b9ca4844852", "tests/check_secrets.py",
                  real_looking), False),
        ("refuses HEAD even for a fixture string",
         waivable("HEAD", "tests/check_secrets.py", SELFTEST_FIXTURES[0]), False),
        ("refuses the working tree",
         waivable("worktree", "tests/check_secrets.py", SELFTEST_FIXTURES[0]), False),
        ("refuses another file, even old",
         waivable("229ca74a79e9a9b9380f9e4a4cf16b9ca4844852", "engine/core.py",
                  SELFTEST_FIXTURES[0]), False),
        ("waives a real fixture string in an old commit",
         waivable("229ca74a79e9a9b9380f9e4a4cf16b9ca4844852", "tests/check_secrets.py",
                  SELFTEST_FIXTURES[0]), True),
    ]
    for desc, got, want in cases:
        fired = got == want
        print(("  ok   " if fired else "  FAIL ") + f"waiver {desc}")
        bad += 0 if fired else 1

    print(f"\n{'PASS' if not bad else 'FAIL'}: selftest {bad} problem(s)")
    sys.exit(1 if bad else 0)


def blobs():
    """(origin, path, text) triples.

    HEAD by default; --all-history covers every commit, because a public repo
    publishes its history and a token in commit 1 stays leaked after commit 2
    deletes it from the tree. --worktree scans the files on disk instead, which
    is what you want BEFORE committing -- an audit that can only ever describe
    the past cannot stop you pushing a secret; it can only report one.
    """
    if "--worktree" in sys.argv:
        out = []
        # --others --exclude-standard matters: a gate limited to TRACKED files
        # skipped exactly the new files about to be committed and pushed, which
        # is the one moment a publish gate has to work. Ignored files stay out.
        for line in subprocess.run(
                ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                capture_output=True, text=True).stdout.splitlines():
            try:
                with open(line, encoding="utf-8", errors="replace") as fh:
                    out.append(("worktree", line, fh.read()))
            except OSError as e:
                print(f"  ?? unreadable {line}: {e}")
        return out
    if "--all-history" in sys.argv:
        seen, pairs = set(), []
        for commit in subprocess.run(["git", "log", "--all", "--format=%H"],
                                     capture_output=True, text=True).stdout.split():
            for line in subprocess.run(["git", "ls-tree", "-r", "--name-only", commit],
                                       capture_output=True, text=True).stdout.splitlines():
                if (commit, line) not in seen:
                    seen.add((commit, line))
                    pairs.append((commit, line))
        return [(c, p, subprocess.run(["git", "show", f"{c}:{p}"],
                 capture_output=True, text=True, encoding="utf-8",
                 errors="replace").stdout) for c, p in pairs]
    return [("HEAD", p, subprocess.run(
        ["git", "show", f"HEAD:{p}"], capture_output=True, text=True,
        encoding="utf-8", errors="replace").stdout) for p in subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "HEAD"],
        capture_output=True, text=True, check=True).stdout.split()]


def waivable(origin, path, snippet):
    """Excuse the scanner's own synthetic fixtures, and nothing else.

    A gate that is red by default trains people to skip it; one that says "these
    were inspected, here is why they are inert" stays trustworthy. But an
    allowlist of paths and labels is a mute button -- it would swallow any new
    secret on an allowed path, and one such table once contained literal
    patterns, so the waiver itself tripped the gate.

    So the rule is derived, not listed:
      * only inside this file,
      * only in an OLD commit (never HEAD, never the working tree),
      * only when the matched text is a substring of a SELFTEST_FIXTURE.

    Widening it therefore means editing the fixtures selftest() asserts against,
    and no live pattern is written anywhere in this file to be excused.
    """
    if path != "tests/check_secrets.py":
        return False
    if origin in ("HEAD", "worktree"):
        return False
    return bool(snippet) and any(snippet in f for f in SELFTEST_FIXTURES)


if "--selftest" in sys.argv:
    selftest()

hits = 0
waived = 0
targets = blobs()
for origin, path, text in targets:
    for line_no, line in enumerate(text.splitlines(), 1):
        # No keyword exemptions: a real secret sharing a line with the word
        # re.compile used to be waved past. History waiver is per-match and
        # derived above, not per-line.
        for label, pat in PATTERNS.items():
            if BENIGN.search(line):
                continue
            for m in re.finditer(pat, line):
                if waivable(origin, path, m.group(0)):
                    waived += 1
                    continue
                hits += 1
                print(f"  CRED {label}: {origin}:{path}:{line_no}: {m.group(0)[:52]!r}")
        for label, pat in WHO.items():
            for m in re.finditer(pat, line, re.I):
                if waivable(origin, path, m.group(0)):
                    waived += 1
                    continue
                hits += 1
                print(f"  PII  {label}: {origin}:{path}:{line_no}: {m.group(0)[:52]!r}")

if waived:
    # Recomputable, not asserted: the reader can check the machine name the
    # fixture does NOT match, and see exactly which fixtures were excused.
    print(f"\n  waived {waived} finding(s) -- this file's own selftest fixtures in "
          f"historical commits.")
    print(f"  host identity check: real COMPUTERNAME={os.environ.get('COMPUTERNAME', '?')}"
          f" vs fixture hostname "
          f"{[f for f in SELFTEST_FIXTURES if 'top-' in f][0]!r}")
    print("  to change this verdict, edit SELFTEST_FIXTURES (selftest() depends "
          "on them); this file contains no allowlist to append to.")

print(f"\n{len(targets)} blobs scanned, {hits} unresolved match(es)"
      + (f", {waived} waived" if waived else ""))
if "--gate" in sys.argv:
    sys.exit(1 if hits else 0)
