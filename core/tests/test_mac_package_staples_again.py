"""A staple that loses its connection to Apple is tried again.

On the Intel runner, as 0.56.0 was built, xcrun stapler staple of the disk
image failed twice and stapler validate once, each with exit 68 and
NSURLErrorDomain -1005, "The network connection was lost", from Apple's
ticket server. Nothing was wrong with the ticket, and a rerun of the job
passed. packaging/build_macos.py staples through staple(), which tries four
times with STAPLE_WAITS between them, and the workflow's validate step tries
the same way. The last failure still stops the build, so a ticket that is
really missing stops it as before.

Nothing here needs a Mac. The build's subprocess and sleep are stand-ins,
and the workflow's own step runs in bash against stand-ins for xcrun,
codesign, spctl and sleep.
"""
import ast
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
PACKAGING = REPO / "packaging"
WORKFLOW = REPO / ".github" / "workflows" / "build-macos.yml"
STEP = "What Gatekeeper will say"


@pytest.fixture()
def bm(monkeypatch):
    spec = importlib.util.spec_from_file_location("bm_staples", PACKAGING / "build_macos.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "say", lambda *a, **k: None)
    return mod


class Stapler:
    """subprocess and time as the build sees them, with stapler answering
    each try with the next of `codes` and every other program with 0."""

    def __init__(self, codes):
        self.codes = list(codes)
        self.calls = []
        self.waits = []

    def run(self, cmd, check=False, **_kw):
        cmd = [str(c) for c in cmd]
        self.calls.append(cmd)
        code = self.codes.pop(0) if cmd[:2] == ["xcrun", "stapler"] else 0
        if cmd[0] == "ditto":
            Path(cmd[-1]).write_bytes(b"")
        if check and code:
            raise subprocess.CalledProcessError(code, cmd)
        return subprocess.CompletedProcess(cmd, code)

    def install(self, monkeypatch, bm):
        monkeypatch.setattr(bm, "subprocess", SimpleNamespace(
            run=self.run, CalledProcessError=subprocess.CalledProcessError))
        monkeypatch.setattr(bm, "time", SimpleNamespace(sleep=self.waits.append))
        return self

    def staples(self):
        return [c for c in self.calls if c[:2] == ["xcrun", "stapler"]]


def test_the_waits_are_the_ones_asked_for(bm):
    assert bm.STAPLE_WAITS == (15, 30, 60)


def test_a_staple_that_loses_its_connection_is_tried_again(bm, monkeypatch, tmp_path):
    fake = Stapler([68, 68, 0]).install(monkeypatch, bm)
    dmg = tmp_path / "PaperPull-1.2.3-x86_64.dmg"
    bm.staple(dmg)
    assert fake.staples() == [["xcrun", "stapler", "staple", str(dmg)]] * 3
    assert fake.waits == [15, 30]


def test_a_staple_that_works_at_once_waits_for_nothing(bm, monkeypatch, tmp_path):
    fake = Stapler([0]).install(monkeypatch, bm)
    bm.staple(tmp_path / "x.dmg")
    assert len(fake.staples()) == 1 and fake.waits == []


def test_a_staple_that_fails_every_time_still_stops_the_build(bm, monkeypatch, tmp_path):
    fake = Stapler([68, 65, 68, 65]).install(monkeypatch, bm)
    with pytest.raises(subprocess.CalledProcessError) as stopped:
        bm.staple(tmp_path / "x.dmg")
    assert stopped.value.returncode == 65, "the last try's own code"
    assert len(fake.staples()) == 4
    assert fake.waits == [15, 30, 60]


def test_the_bundle_and_the_disk_image_are_both_stapled_with_tries_again(bm, monkeypatch,
                                                                       tmp_path):
    monkeypatch.setattr(bm, "DIST", tmp_path)
    monkeypatch.setattr(bm, "APP", tmp_path / "PaperPull.app")
    monkeypatch.setattr(bm, "_submit", lambda path, label: None)
    fake = Stapler([68, 0, 68, 0]).install(monkeypatch, bm)
    bm.notarize_app()
    dmg = tmp_path / "PaperPull-1.2.3-x86_64.dmg"
    bm.notarize(dmg)
    assert [c[-1] for c in fake.staples()] == [str(bm.APP)] * 2 + [str(dmg)] * 2
    assert fake.waits == [15, 15]


def test_nothing_in_the_build_staples_but_staple():
    """Every call that names stapler is inside staple(), so a staple added
    later cannot go round the tries."""
    tree = ast.parse((PACKAGING / "build_macos.py").read_text(encoding="utf-8"))
    outside = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef) or fn.name == "staple":
            continue
        for node in ast.walk(fn):
            if isinstance(node, ast.Constant) and node.value == "stapler":
                outside.append("%s line %d" % (fn.name, node.lineno))
    assert not outside, outside


# -- the workflow's validate ---------------------------------------------------

def _bash():
    """Git's bash on Windows, never the WSL one on PATH, whose paths differ."""
    if os.name == "nt":
        git_bash = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
        return str(git_bash) if git_bash.is_file() else None
    return shutil.which("bash")


def step_script(name: str = STEP) -> str:
    """The run: block of the step called `name`, as bash is handed it."""
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "- name: %s" % name)
    run = next(i for i in range(start + 1, len(lines)) if lines[i].strip() == "run: |")
    indent = None
    body = []
    for line in lines[run + 1:]:
        if line.strip() and indent is None:
            indent = len(line) - len(line.lstrip())
        if line.strip() and len(line) - len(line.lstrip()) < indent:
            break
        body.append(line[indent:] if line.strip() else "")
    return "\n".join(body).rstrip() + "\n"


# Stand-ins for the programs the step runs, as shell functions ahead of the
# step, since a function is found before anything on PATH and Git's bash on
# Windows puts its own sleep ahead of whatever PATH it is handed.
STAND_INS = """xcrun() {
  echo "$*" >> "$STUB_LOG"
  if [ "$(grep -cxF -- "$*" "$STUB_LOG")" -le "$FAILS" ]; then
    echo "The staple and validate action failed! Error 68." >&2
    return 68
  fi
}
codesign() { echo "codesign $*" >> "$STUB_LOG"; }
spctl() { echo "spctl $*" >> "$STUB_LOG"; }
sleep() { echo "sleep $*" >> "$STUB_LOG"; }
"""


def run_step(tmp_path, fails: int):
    """The step run as GitHub runs a bash step, with xcrun failing each of
    its validates `fails` times before it passes."""
    work = tmp_path / "work"
    (work / "dist" / "PaperPull.app").mkdir(parents=True)
    (work / "dist" / "PaperPull-1.2.3-x86_64.dmg").write_bytes(b"")
    script = tmp_path / "step.sh"
    script.write_text(STAND_INS + step_script(), encoding="utf-8", newline="\n")
    log = tmp_path / "calls.log"
    log.write_text("", encoding="utf-8")
    env = dict(os.environ, STUB_LOG=str(log).replace("\\", "/"), FAILS=str(fails))
    done = subprocess.run([_bash(), "--noprofile", "--norc", "-eo", "pipefail", str(script)],
                          cwd=str(work), env=env, capture_output=True, text=True, timeout=60)
    return done, log.read_text(encoding="utf-8").splitlines()


needs_bash = pytest.mark.skipif(_bash() is None, reason="needs bash")

APP = "stapler validate dist/PaperPull.app"
DMG = "stapler validate dist/PaperPull-1.2.3-x86_64.dmg"


@needs_bash
def test_the_workflow_validates_again_after_a_lost_connection(tmp_path):
    done, calls = run_step(tmp_path, fails=2)
    assert done.returncode == 0, done.stdout + done.stderr
    validates = [c for c in calls if not c.startswith(("codesign", "spctl"))]
    assert validates == [APP, "sleep 15", APP, "sleep 30", APP,
                         DMG, "sleep 15", DMG, "sleep 30", DMG], calls


@needs_bash
def test_the_workflow_still_fails_when_every_validate_does(tmp_path):
    done, calls = run_step(tmp_path, fails=9)
    assert done.returncode == 68, "stapler's own code, %d" % done.returncode
    validates = [c for c in calls if not c.startswith(("codesign", "spctl"))]
    assert validates == [APP, "sleep 15", APP, "sleep 30", APP, "sleep 60", APP], calls


@needs_bash
def test_the_workflow_validates_once_when_the_first_try_works(tmp_path):
    done, calls = run_step(tmp_path, fails=0)
    assert done.returncode == 0, done.stdout + done.stderr
    assert [c for c in calls if c.startswith("stapler") or c.startswith("sleep")] == [APP, DMG]
    assert sum(c.startswith("codesign") for c in calls) == 1
    assert sum(c.startswith("spctl") for c in calls) == 1


def test_the_workflow_waits_as_long_as_the_build_does(bm):
    """The step's waits are STAPLE_WAITS, so the two cannot drift apart."""
    script = step_script()
    assert "for wait in %s; do" % " ".join(map(str, bm.STAPLE_WAITS)) in script
