"""Every action a workflow runs is named by its full commit, with the version
it is beside it, and Dependabot proposes their updates.

A tag is whatever its owner points it at today, and these workflows sign
the Windows package with the release environment's Azure credential, sign
and notarize the Mac bundle with its certificate, and push the server image.
A commit cannot be moved. The workflows are read as text, since the Python
that runs this suite may have no YAML parser.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((REPO / ".github" / "workflows").glob("*.yml"))
PINNED = re.compile(r"[\w.-]+/[\w.-]+(/[\w./-]+)?@[0-9a-f]{40} # v\d+\.\d+\.\d+")


def _uses():
    for wf in WORKFLOWS:
        for n, line in enumerate(wf.read_text(encoding="utf-8").splitlines(), 1):
            m = re.match(r"\s*(-\s+)?uses:\s*(.+?)\s*$", line)
            if m:
                yield wf.name, n, m.group(2)


def test_every_action_is_named_by_its_commit_and_version():
    found = list(_uses())
    assert {name for name, _, _ in found} == {wf.name for wf in WORKFLOWS}, "every workflow uses actions"
    for name, n, ref in found:
        assert PINNED.fullmatch(ref), "%s:%d %s" % (name, n, ref)


def test_one_action_is_at_one_commit_everywhere():
    """Two versions of the same action is a half-done update."""
    seen = {}
    for name, n, ref in _uses():
        action, at = ref.split("@", 1)
        seen.setdefault(action, set()).add(at)
    assert all(len(at) == 1 for at in seen.values()), seen


def test_dependabot_proposes_the_actions_updates():
    text = (REPO / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    block = text.split("package-ecosystem: github-actions", 1)[1].split("package-ecosystem:", 1)[0]
    assert re.search(r"directory: /\s*$", block, re.M), "the root, which takes in .github/workflows"
    assert "interval: weekly" in block


def test_each_package_workflow_checks_the_python_it_installed():
    """The packaged interpreter is asked its version on the runner, after
    the build, against the version the builder names."""
    win = (REPO / ".github" / "workflows" / "build-windows.yml").read_text(encoding="utf-8")
    mac = (REPO / ".github" / "workflows" / "build-macos.yml").read_text(encoding="utf-8")
    assert "build_windows.PY_VERSION" in win and 'python\\python.exe") -c "import platform' in win
    assert "build_macos.PY_VERSION" in mac and 'test "$have" = "$want"' in mac
