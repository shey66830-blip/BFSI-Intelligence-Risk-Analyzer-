"""
Context Guard — Documentation Drift Suite

Fails the build when the security gap register, the roadmap or the README describe
a system that no longer exists.

    cd backend && python test_documentation.py

Why this suite exists
--------------------
`SECURITY.md` shipped a gap register that said G-05 — the tamper-evident audit
chain — was a *blocking* gap. The chain had been implemented, endpoint and tests
and all, and had been sitting on disk. The register had drifted, and nothing in
the build could notice, because a document has no test.

This suite is that test. It encodes the invariants a reader silently assumes when
they trust these files:

    every gap id in the register is defined exactly once, with a legal status
    code that cites a gap id refers to one the register actually defines
    a control whose module claims to close a gap is installed and the register agrees
    a gap marked closed or partly closed has the evidence file its fix names
    the check counts printed in the docs are the counts the suites really report
    every local file the docs link to exists
    the roadmap's delivered marks point at code that is really there

How the counts are verified
--------------------------
Deliberately not by counting `check(` call sites. `test_rbac.py` and
`test_workflow.py` generate checks inside loops — 78 static calls report as 81,
199 report as 209 — so a static count would silently miss exactly the drift this
suite hunts. The four Python suites are therefore **run for real** and their
printed `N passed, 0 failed` is parsed. That costs about fifteen seconds and is
the only method that cannot lie. The frontend suite's tests are top-level and
statically countable, so that one is counted from source.

This suite does not add its own checks to the documented total: it exists to
verify the other counts, and a number that has to include its own verifier is a
number that cannot be computed honestly.

A note on side effects: verifying the counts means re-running the suites, which
reset demo state and clear sessions — the same effect as any full `npm test`.
"""

import os
import re
import subprocess
import sys
import time
from datetime import datetime

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BACKEND_DIR)

PASSED, FAILED = [], []

# Every gap id that has ever been defined, in order. A register that drops one of
# these — or invents one past the end without renaming this list — fails here.
EXPECTED_GAPS = [f"G-{i:02d}" for i in range(1, 20)]

STATUS_MARKS = {"✅": "Closed", "◐": "Partly", "⬜": "Open"}

# The evidence each non-open status rests on: (file relative to root, substring
# that must be in it). If you close a gap, its fix lands here — and if the fix is
# later removed while the register still claims it, this is where the build says so.
EVIDENCE = {
    "G-01": [("backend/security/cors.py", "ALLOWED_ORIGINS")],
    "G-02": [("backend/security/posture.py", "IS_PRODUCTION")],
    "G-04": [("backend/security/posture.py", "demo_mode")],
    "G-05": [("backend/services/audit.py", "def verify"),
             ("backend/services/audit.py", "entry_hash"),
             ("backend/routes/admin.py", "audit-integrity")],
    "G-07": [("backend/security/ratelimit.py", "Retry-After"),
             ("backend/security/ratelimit.py", "RATE_LIMIT_AUTH_ACCOUNT")],
    "G-08": [("backend/security/headers.py", "Content-Security-Policy"),
             ("backend/security/web/security-headers.conf", "Content-Security-Policy")],
    "G-10": [("backend/security/validation.py", "__proto__"),
             ("backend/security/classification.py", "PII_FIELDS")],
    "G-11": [("backend/security/classification.py", "RETENTION_DAYS"),
             ("backend/security/logguard.py", "def scrub")],
}

# How each security module is actually wired. The first run assumed every module
# exposes .apply() and is called in install() — false for two of them, and the
# check happily reported the truth as a failure. posture is boot-time
# (assert_posture, called from app.py), classification is a registry consumed by
# the test suite and has no request-path hook at all.
WIRING = {
    "cors": ("G-01", "apply"),
    "headers": ("G-08", "apply"),
    "validation": ("G-10", "apply"),
    "ratelimit": ("G-07", "apply"),
    "logguard": ("G-11", "apply"),
    "posture": ("G-02", "boot"),
    "classification": ("G-11", "registry"),
}

# Roadmap Track 1 phases and the code each ✅ mark points at.
PHASE_EVIDENCE = {
    "3": ("backend/services/evidence.py", "def provenance_block"),
    "4": ("backend/services/paging.py", "has_more"),
    "5": ("backend/services/backtest.py", "def "),
    "6": ("backend/services/audit.py", "entry_hash"),
    "7": ("backend/services/graph_engine.py", "MAX_HOPS_CAP"),
}

DOC_FILES = ["SECURITY.md", "ROADMAP.md", "README.md", "docs/security-architecture.md"]

NUMBER_WORDS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven",
                8: "eight", 9: "nine", 10: "ten"}


def check(label, condition, detail=""):
    if condition:
        PASSED.append(label)
        print(f"  PASS  {label}")
    else:
        FAILED.append(label)
        print(f"  FAIL  {label}  {detail}")


def read(path, normalize_line_endings=False):
    full = os.path.join(ROOT_DIR, path)
    if not os.path.exists(full):
        return None
    with open(full, encoding="utf-8") as handle:
        text = handle.read()
    if normalize_line_endings:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


def section(text, start_marker, end_marker=None):
    """The text from one heading to the next.

    The end marker `---` is matched as a whole line, because a substring search
    for `---` finds the `|---|---|` separator inside the very next markdown table
    and silently returns three lines of header. That exact bug made the legend
    check report the legend as missing the marks it documents.
    """
    begin = text.find(start_marker)
    if begin == -1:
        return ""
    after = begin + len(start_marker)
    if end_marker is None:
        return text[begin:]
    if end_marker == "---":
        match = re.compile(r"(?m)^---\s*$").search(text, after)
        return text[begin:match.start()] if match else text[begin:]
    end = text.find(end_marker, after)
    return text[begin:end] if end != -1 else text[begin:]


# ── 1 · Register structure ───────────────────────────────────────────────────


def register_statuses():
    """Parse §6 of SECURITY.md into {gap_id: (mark, word)}, plus parse errors."""
    register = read("SECURITY.md") or ""
    gaps = section(register, "## 6. Gap register", "## 7.")
    statuses, malformed = {}, []
    for line in gaps.split("\n"):
        # Closed and Partly carry a bolded word (✅ **Closed**); Open is bare
        # (⬜ Open). The regex must accept both or it silently drops every Open
        # row — which is exactly what happened on the first run, reporting
        # eleven open gaps as missing from a register that contains them.
        match = re.match(
            r"^\|\s*\*\*(G-\d{2})\*\*\s*\|\s*(✅|◐|⬜)\s*"
            r"(?:\*\*)?(Closed|Partly|Open)(?:\*\*)?\s*\|", line)
        if match:
            gap_id, mark, word = match.groups()
            if gap_id in statuses:
                malformed.append(f"{gap_id} is defined twice in the register tables")
            if STATUS_MARKS[mark] != word:
                malformed.append(f"{gap_id} pairs {mark} with {word}")
            statuses[gap_id] = (mark, word)
    return register, statuses, malformed


def check_register_structure():
    print("\n── Register structure ────────────────────────────────────────")
    register, statuses, malformed = register_statuses()

    check("the gap register section was found", bool(statuses) and not malformed,
          malformed or "no §6 table rows matched")
    check("every gap id is defined exactly once",
          sorted(statuses) == EXPECTED_GAPS,
          f"missing: {sorted(set(EXPECTED_GAPS) - set(statuses))}, "
          f"unexpected: {sorted(set(statuses) - set(EXPECTED_GAPS))}")

    if register:
        stray = sorted(set(re.findall(r"\bG-\d{2}\b", register)) - set(EXPECTED_GAPS))
        check("no gap id is referenced that was never defined", not stray, stray)

    opened = read("SECURITY.md") or ""
    legend = section(opened, "### Status legend", "---")
    used_marks = {mark for mark, _word in statuses.values()}
    check("the legend explains every status the register uses",
          bool(statuses) and used_marks <= {m for m in ("✅", "◐", "⬜") if m in legend},
          f"used={sorted(used_marks)} legend has "
          f"{[m for m in ('✅', '◐', '⬜') if m in legend]}")
    return statuses


# ── 2 · Code ↔ register ──────────────────────────────────────────────────────


def code_citations():
    """Every gap id cited anywhere under backend/, outside this suite."""
    cited = {}
    for base, _dirs, files in os.walk(BACKEND_DIR):
        if "__pycache__" in base:
            continue
        for name in files:
            if not name.endswith(".py") or name == "test_documentation.py":
                continue
            full = os.path.join(base, name)
            rel = os.path.relpath(full, ROOT_DIR).replace("\\", "/")
            with open(full, encoding="utf-8", errors="replace") as handle:
                ids = sorted(set(re.findall(r"\bG-\d{2}\b", handle.read())))
            if ids:
                cited[rel] = ids
    return cited


def check_code_against_register(statuses):
    print("\n── Code ↔ register ───────────────────────────────────────────")
    cited = code_citations()
    flat = sorted({gap for ids in cited.values() for gap in ids})

    check("code only cites gap ids the register defines",
          all(gap in statuses for gap in flat),
          [gap for gap in flat if gap not in statuses])

    uncited_open = [gap for gap, (mark, _w) in statuses.items()
                    if mark == "⬜" and gap in flat]
    check("no gap cited by code is still marked Open",
          not uncited_open,
          f"code claims {uncited_open} but the register says Open — reconcile one of them")

    init_src = read("backend/security/__init__.py") or ""
    app_src = read("backend/app.py") or ""
    for module, (gap, how) in sorted(WIRING.items()):
        src = read(f"backend/security/{module}.py") or ""
        imported = re.search(rf"\b{module}\b", init_src) is not None
        if how == "apply":
            wired = re.search(rf"\b{module}\.apply\(", init_src) is not None
            how_desc = "applied in install()"
        elif how == "boot":
            wired = "assert_posture" in app_src
            how_desc = "asserted at boot by app.py"
        else:
            wired = imported
            how_desc = "imported as the registry"
        check(f"{module}.py's role for {gap} is real: imported and {how_desc}",
              imported and wired and gap in statuses
              and statuses[gap][0] in {"✅", "◐"},
              f"imported={imported} wired={wired} "
              f"status={statuses.get(gap, ('missing', ''))[0]}")


# ── 3 · Evidence behind the statuses ─────────────────────────────────────────


def check_evidence(statuses):
    print("\n── Evidence behind the statuses ──────────────────────────────")
    for gap_id, requirements in sorted(EVIDENCE.items()):
        if gap_id not in statuses:
            check(f"{gap_id} evidence skipped — id not in register", False, "unknown id")
            continue
        mark = statuses[gap_id][0]
        missing = []
        for path, token in requirements:
            content = read(path)
            if content is None:
                missing.append(f"{path} (file missing)")
            elif token not in content:
                missing.append(f"{path} lacks {token!r}")
        check(f"{gap_id} marked {statuses[gap_id][1]} has its evidence on disk",
              mark == "⬜" or not missing,
              f"status={mark} missing={missing or 'none'}")


# ── 4 · The counts the docs print are the counts the suites report ──────────


def run_suite(filename):
    """Run one suite and parse its own reported result. Returns (passed, failed, tail)."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    started = time.time()
    proc = subprocess.run(
        [sys.executable, filename], cwd=BACKEND_DIR, capture_output=True,
        text=True, encoding="utf-8", errors="replace", env=env, timeout=600,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    match = re.search(r"(\d+) passed, (\d+) failed", output)
    tail = "\n".join(output.strip().split("\n")[-12:])
    if match is None:
        return None, None, tail or f"{filename} produced no summary (exit {proc.returncode})"
    return int(match.group(1)), int(match.group(2)), f"{time.time() - started:.1f}s"


def frontend_test_count():
    content = read("frontend/src/lib/format.test.js") or ""
    return len(re.findall(r"(?m)^test\(", content))


def check_counts():
    print("\n── Documented counts vs reported counts ──────────────────────")
    print("  (running the four Python suites for real — this is the slow part)")
    reported = {}
    for filename in ("test_rbac.py", "test_workflow.py",
                     "test_security.py", "test_security_controls.py"):
        passed, failed, tail = run_suite(filename)
        reported[filename] = passed
        check(f"{filename} passes and reports a count",
              passed is not None and failed == 0, tail)

    fmt = frontend_test_count()
    check("the frontend suite's tests are statically countable", fmt > 0, fmt)

    readme = read("README.md") or ""
    claims = {
        "test_rbac.py": re.search(r"test_rbac\.py[^(\n]*\((\d+) checks\)", readme),
        "test_workflow.py": re.search(r"test_workflow\.py[^(\n]*\((\d+) checks\)", readme),
        "test_security.py": re.search(r"test_security\.py[^(\n]*\((\d+) checks\)", readme),
        "test_security_controls.py": re.search(
            r"test_security_controls\.py[^(\n]*\((\d+) checks\)", readme),
    }
    for filename, match in claims.items():
        check(f"README's {filename} count matches the suite's own report",
              match is not None and reported.get(filename) is not None
              and int(match.group(1)) == reported[filename],
              f"README says {match.group(1) if match else 'nothing'}, "
              f"suite reported {reported.get(filename)}")

    register = read("SECURITY.md") or ""
    sec_row = re.search(r"`backend/test_security\.py`[^|]*\|\s*\*\*(\d+)\*\*\s*\|", register)
    ctrl_row = re.search(r"`backend/test_security_controls\.py`[^|]*\|\s*\*\*(\d+)\*\*\s*\|", register)
    # The total is written as `**114 checks total.**` with the period inside the
    # bold, so read the digits immediately before the word "checks".
    total = re.search(r"\*\*(\d+)\s*checks\s+total\b", register)
    expected_total = (reported.get("test_security.py") or 0) \
        + (reported.get("test_security_controls.py") or 0)
    check("the register's §8 counts match the suites",
          sec_row and ctrl_row and total
          and int(sec_row.group(1)) == (reported.get("test_security.py") or -1)
          and int(ctrl_row.group(1)) == (reported.get("test_security_controls.py") or -1)
          and int(total.group(1)) == expected_total,
          f"§8 says {sec_row.group(1) if sec_row else '?'}/"
          f"{ctrl_row.group(1) if ctrl_row else '?'}, total {total.group(1) if total else '?'}; "
          f"suites reported {reported.get('test_security.py')}/"
          f"{reported.get('test_security_controls.py')}, true total {expected_total}")
    return reported, fmt


# ── 5 · The runner and the suite list the docs describe ─────────────────────


def suite_files_in(text):
    """Every `file: '…'` value advertised by the runner, in declaration order.

    The runner hardcodes the list by name *and* by file, so a suite whose file is
    `test_documentation.py` but whose declared name is `docs` is still part of the
    product — and still part of the count. Read the actual `file:` values rather
    than assuming every suite's file begins with `test_`.
    """
    return re.findall(r"file: '([^']+\.py)'", text)


def check_runner(reported, fmt):
    print("\n── Runner and documented suite list ──────────────────────────")
    runner = read("scripts/test.mjs") or ""
    declared = suite_files_in(runner)
    has_frontend = "frontend/src/lib" in runner
    drift_registered = "test_documentation.py" in runner

    # Product suites are the suites a user asks the build to run, *except* the
    # drift suite itself. The drift suite guards the docs; it must not be counted
    # in the totals that it verifies.
    product_declared = sorted(f for f in declared if f != "test_documentation.py")
    product_on_disk = sorted(
        f for f in os.listdir(BACKEND_DIR)
        if f.startswith("test_") and f.endswith(".py")
        and f != "test_documentation.py")

    check("the runner declares every product suite that exists on disk",
          product_declared == product_on_disk,
          f"declared={product_declared} disk={product_on_disk}")
    check("the drift suite itself is registered, so drift fails the build",
          drift_registered)
    check("the runner runs the frontend suite", has_frontend)
    check("no product suite is declared twice",
          len(declared) - (1 if drift_registered else 0) == len(product_declared),
          f"declared={declared}")

    total_suites = len(product_declared) + (1 if has_frontend else 0)
    word = NUMBER_WORDS.get(total_suites, str(total_suites))
    readme = read("README.md") or ""
    roadmap = read("ROADMAP.md") or ""
    check(f"README describes all {total_suites} suites",
          f"all {word} suites" in readme or f"all {total_suites} suites" in readme,
          "npm test comment in README is stale")
    roadmap_counts = re.search(r"(\d+) suites, (\d+) checks", roadmap)
    documented_total = sum(v for v in reported.values() if v is not None) + fmt
    check("ROADMAP's suite count and check total match reality",
          roadmap_counts is not None
          and int(roadmap_counts.group(1)) == total_suites
          and int(roadmap_counts.group(2)) == documented_total,
          f"ROADMAP says {roadmap_counts.groups() if roadmap_counts else '?'}, "
          f"reality is ({total_suites}, {documented_total})")


# ── 6 · Local links resolve ──────────────────────────────────────────────────


def check_links():
    print("\n── Local links resolve ───────────────────────────────────────")
    broken = []
    for doc in DOC_FILES:
        content = read(doc)
        if content is None:
            broken.append(f"{doc} (the document itself is missing)")
            continue
        base = os.path.dirname(os.path.join(ROOT_DIR, doc))
        for target in re.findall(r"\]\(([^)#\s]+)\)", content):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            resolved = os.path.normpath(os.path.join(base, target))
            if not os.path.exists(resolved):
                broken.append(f"{doc} -> {target}")
    check("every local file the docs link to exists", not broken, broken[:8])


# ── 7 · Roadmap marks point at real code ────────────────────────────────────


def check_roadmap_marks():
    print("\n── Roadmap marks vs code ─────────────────────────────────────")
    roadmap = read("ROADMAP.md", normalize_line_endings=True) or ""
    # The Track 1 heading in this document is an em-dash document, not a bare
    # heading. Find the table block that lives under it rather than slicing on
    # a heading string that does not exist verbatim.
    track = section(roadmap, "### Track 1", "### Track 2")
    if not track.strip():
        # Fallback: find the table that starts at the Track 1 phase list.
        begin = roadmap.find("| # | Phase | Outcome | Status |")
        end = roadmap.find("### Track 2", begin)
        track = roadmap[begin:end] if begin != -1 and end != -1 else ""
    # Each Track 1 phase row is a markdown table row whose last cell begins
    # with the status mark. Read it as cells rather than a regex over the whole
    # row, because outcome text can itself contain pipe characters and because
    # of the line-ending normalisation above.
    marks = {}
    for line in track.splitlines():
        if not line.startswith("| ") or not re.match(r"^\| \d \|", line):
            continue
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 2:
            continue
        last = cells[-2]
        m = re.match(r"^(✅|◐|⏳)", last)
        if m and cells[1].isdigit():
            marks[cells[1]] = m.group(1)
    check("the Track 1 table was found with status marks", bool(marks), sorted(marks))

    for number, (path, token) in sorted(PHASE_EVIDENCE.items()):
        mark = marks.get(number)
        content = read(path)
        present = content is not None and token in content
        check(f"phase {number} {mark or 'absent'} has its code on disk",
              mark in ("✅", "◐") and present,
              f"{path} lacks {token!r}")

    # Phase 8 is delivered as "frontend harness done" but its CI/docker halves
    # are not — the register may describe it with a note after the mark rather
    # than a bare mark. Accept either form so a documented partial can never
    # quietly become "delivered" in the reader's head.
    def phase8_outcome():
        for line in track.split("\n"):
            if re.match(r"^\| 8 \| ", line):
                cells = [c.strip() for c in line.split("|")]
                last = cells[-2] if len(cells) >= 2 else ""
                return re.match(r"^(✅|◐)(?:\s|.)*$", last)
        return None

    p8 = phase8_outcome()
    check("phase 8 is described honestly (not silently marked delivered)",
          p8 is not None and p8.group(1) != "✅",
          f"phase 8 outcome cell = {p8.group(0) if p8 else 'not found'}")

    delivered = [n for n, m in marks.items() if m == "✅"]
    check("no phase is marked delivered without a status in the table",
          all(n in PHASE_EVIDENCE or n == "8" for n in delivered),
          f"delivered={delivered}")


def main():
    print("── Documentation drift ───────────────────────────────────────")
    print(f"  {datetime.utcnow().isoformat()} · verifying the docs against the code")

    statuses = check_register_structure()
    check_code_against_register(statuses)
    check_evidence(statuses)
    reported, fmt = check_counts()
    check_runner(reported, fmt)
    check_links()
    check_roadmap_marks()

    print("\n" + "═" * 62)
    print(f"  {len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("  Failures:")
        for failure in FAILED:
            print(f"    - {failure}")
    print("═" * 62)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
