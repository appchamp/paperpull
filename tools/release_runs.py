"""Which workflow run a release may take, for tools/release.sh.

    gh run list --workflow <name> --commit <sha> --json <FIELDS> \\
        | python tools/release_runs.py pick <name> <sha> <tag>

prints the id of the run to take, or "wait" while none has succeeded and
one is still going, and exits 1 saying why when none ever will.

A release publishes what its tag's commit built and passed, so every run
taken here is one for exactly that commit. A package run must also be the
build of the tag itself, as the package workflows run on a tag push. A Tests
run may be the one on main or the one on the tag, since both test the
commit, but never a pull request's, which tests that commit merged with
another.
"""
from __future__ import annotations

import json
import sys

FIELDS = "databaseId,name,headSha,headBranch,event,status,conclusion"
PACKAGES = ("Windows package", "macOS package")
TESTS = "Tests"


def candidates(runs: list, name: str, sha: str, tag: str) -> list:
    mine = [r for r in runs if r.get("name") == name and r.get("headSha") == sha]
    if name in PACKAGES:
        return [r for r in mine if r.get("headBranch") == tag]
    return [r for r in mine if r.get("event") in ("push", "workflow_dispatch")]


def pick(runs: list, name: str, sha: str, tag: str) -> tuple[str, str]:
    """("take", id), ("wait", why) or ("stop", why)."""
    if name not in PACKAGES + (TESTS,):
        return "stop", "%s is not a workflow a release waits for" % name
    mine = candidates(runs, name, sha, tag)
    if not mine:
        return "stop", "no %s run for %s at %s" % (name, tag, sha)
    passed = [r for r in mine if r.get("status") == "completed" and r.get("conclusion") == "success"]
    if passed:
        return "take", str(max(int(r["databaseId"]) for r in passed))
    going = [r for r in mine if r.get("status") != "completed"]
    if going:
        return "wait", "%s run %s is %s" % (name, going[0].get("databaseId"), going[0].get("status"))
    ended = ", ".join("%s %s" % (r.get("databaseId"), r.get("conclusion") or "?") for r in mine)
    return "stop", "no %s run for %s at %s succeeded (%s)" % (name, tag, sha, ended)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 4 or argv[0] != "pick":
        print("usage: python tools/release_runs.py pick <workflow> <commit> <tag>,"
              " with gh's list of runs on standard input", file=sys.stderr)
        return 2
    _, name, sha, tag = argv
    try:
        runs = json.loads(sys.stdin.read() or "[]")
    except ValueError:
        print("the list of %s runs did not read as JSON" % name, file=sys.stderr)
        return 1
    if not isinstance(runs, list):
        print("the list of %s runs is not a list" % name, file=sys.stderr)
        return 1
    verdict, said = pick([r for r in runs if isinstance(r, dict)], name, sha, tag)
    if verdict == "stop":
        print(said, file=sys.stderr)
        return 1
    print(said if verdict == "take" else "wait")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
