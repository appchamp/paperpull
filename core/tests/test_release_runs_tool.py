"""tools/release.sh publishes only what the tag's own commit built and
passed. It waits for a Tests run of that commit, takes the package runs
built from the tag at that commit, and reads each run's commit again before
downloading a file from it.

It waited only for the two package runs, found by the tag's name alone, so
a commit whose Tests run was red could be published once its packages
built, and a tag pushed again from another commit could hand over an older
run's files.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import release_runs  # noqa: E402

SHA = "a" * 40
OTHER = "b" * 40
TAG = "v9.9.9"


def run(id, name, sha=SHA, branch=TAG, event="push", status="completed", conclusion="success"):
    return {"databaseId": id, "name": name, "headSha": sha, "headBranch": branch,
            "event": event, "status": status, "conclusion": conclusion}


# -- which run -------------------------------------------------------------------

def test_a_passed_run_of_the_tags_commit_is_taken():
    for name in ("Tests", "Windows package", "macOS package"):
        assert release_runs.pick([run(7, name)], name, SHA, TAG) == ("take", "7")


def test_a_run_of_any_other_commit_is_never_taken():
    """Even the newest and a passed one, the case of a tag pushed again."""
    runs = [run(9, "Windows package", sha=OTHER), run(8, "Windows package", conclusion="failure")]
    assert release_runs.pick(runs, "Windows package", SHA, TAG)[0] == "stop"
    runs = [run(9, "Tests", sha=OTHER, branch="main")]
    assert release_runs.pick(runs, "Tests", SHA, TAG)[0] == "stop"


def test_a_package_run_must_be_the_build_of_the_tag():
    runs = [run(5, "macOS package", branch="main")]
    assert release_runs.pick(runs, "macOS package", SHA, TAG)[0] == "stop"


def test_tests_on_main_or_on_the_tag_count_and_a_pull_requests_do_not():
    assert release_runs.pick([run(3, "Tests", branch="main")], "Tests", SHA, TAG) == ("take", "3")
    pr = [run(4, "Tests", branch="some-branch", event="pull_request")]
    assert release_runs.pick(pr, "Tests", SHA, TAG)[0] == "stop"


def test_a_red_tests_run_stops_the_release_and_says_so():
    runs = [run(6, "Tests", conclusion="failure"), run(5, "Tests", branch="main", conclusion="cancelled")]
    verdict, said = release_runs.pick(runs, "Tests", SHA, TAG)
    assert verdict == "stop" and "6 failure" in said and "5 cancelled" in said


def test_a_run_still_going_is_waited_for_unless_one_already_passed():
    going = [run(6, "Tests", status="in_progress", conclusion=None)]
    assert release_runs.pick(going, "Tests", SHA, TAG)[0] == "wait"
    failed_then_rerun = [run(6, "Tests", status="queued", conclusion=None),
                         run(5, "Tests", branch="main", conclusion="failure")]
    assert release_runs.pick(failed_then_rerun, "Tests", SHA, TAG)[0] == "wait"
    passed = going + [run(5, "Tests", branch="main")]
    assert release_runs.pick(passed, "Tests", SHA, TAG) == ("take", "5")


def test_another_workflow_is_never_taken_for_one_of_these():
    runs = [run(2, "Server image")]
    assert release_runs.pick(runs, "Tests", SHA, TAG)[0] == "stop"
    assert release_runs.pick(runs, "Server image", SHA, TAG)[0] == "stop"


def test_the_command_reads_gh_s_list_and_answers_on_standard_output(capsys, monkeypatch):
    import io
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps([run(11, "Tests")])))
    assert release_runs.main(["pick", "Tests", SHA, TAG]) == 0
    assert capsys.readouterr().out.strip() == "11"
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    assert release_runs.main(["pick", "Tests", SHA, TAG]) == 1
    monkeypatch.setattr(sys, "stdin", io.StringIO("[]"))
    assert release_runs.main(["pick", "Tests", SHA, TAG]) == 1
    assert "no Tests run" in capsys.readouterr().err


# -- release.sh with a stand-in gh -------------------------------------------------

FAKE_GH = r'''
import json, os, sys
scene = json.load(open(os.environ["FAKE_GH_SCENE"], encoding="utf-8"))
with open(os.environ["FAKE_GH_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(sys.argv[1:]) + "\n")
args = sys.argv[1:]
if args[:2] == ["auth", "status"]:
    sys.exit(0)
if args[0] == "api":
    print(scene["github_tag_sha"])
    sys.exit(0)
if args[:2] == ["run", "list"]:
    name = args[args.index("--workflow") + 1]
    print(json.dumps(scene["runs"].get(name, [])))
    sys.exit(0)
if args[:2] == ["run", "view"]:
    print(scene["view"].get(args[2], scene["tag_sha"]))
    sys.exit(0)
if args[:2] == ["run", "download"]:
    folder = os.path.join(args[args.index("-D") + 1], "artifact")
    os.makedirs(folder, exist_ok=True)
    open(os.path.join(folder, "downloaded.txt"), "w").write(args[2])
    sys.exit(0)
sys.exit(9)
'''


def _bash():
    if os.name == "nt":
        git_bash = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
        return str(git_bash) if git_bash.is_file() else None
    return shutil.which("bash")


needs_bash = pytest.mark.skipif(_bash() is None or shutil.which("git") is None,
                                reason="needs Git's bash and git")


def _checkout(tmp_path: Path) -> tuple[Path, str]:
    """A checkout holding the release tools, its notes and an annotated tag."""
    root = tmp_path / "checkout"
    (root / "tools").mkdir(parents=True)
    for name in ("release.sh", "release_runs.py", "release_assets.py"):
        shutil.copy2(REPO / "tools" / name, root / "tools" / name)
    (root / ".release").mkdir()
    (root / ".release" / "notes-9.9.9.md").write_text("notes\n", encoding="utf-8")
    git = ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
           "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "release"], check=True)
    subprocess.run([*git, "tag", "-a", TAG, "-m", TAG], check=True)
    sha = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True,
                         check=True).stdout.strip()
    return root, sha


def _release(tmp_path, scene_for):
    root, sha = _checkout(tmp_path)
    scene = scene_for(sha)
    scene.setdefault("github_tag_sha", sha)
    scene.setdefault("view", {})
    scene["tag_sha"] = sha
    (tmp_path / "scene.json").write_text(json.dumps(scene), encoding="utf-8")
    (tmp_path / "fake_gh.py").write_text(FAKE_GH, encoding="utf-8")
    py = sys.executable.replace("\\", "/")
    gh = tmp_path / "gh"
    gh.write_text('#!/usr/bin/env bash\nexec "%s" "%s" "$@"\n'
                  % (py, str(tmp_path / "fake_gh.py").replace("\\", "/")), encoding="utf-8", newline="\n")
    gh.chmod(0o755)
    env = dict(os.environ, GH=str(gh).replace("\\", "/"), PY=py,
               FAKE_GH_SCENE=str(tmp_path / "scene.json"), FAKE_GH_LOG=str(tmp_path / "gh.log"))
    done = subprocess.run([_bash(), str(root / "tools" / "release.sh"), "9.9.9"], cwd=str(root),
                          env=env, capture_output=True, text=True, timeout=120)
    calls = [json.loads(line) for line in (tmp_path / "gh.log").read_text(encoding="utf-8").splitlines()]
    return done, calls, sha


def _downloads(calls):
    return [c[2] for c in calls if c[:2] == ["run", "download"]]


def _good(sha, **over):
    runs = {"Tests": [run(100, "Tests", sha=sha, branch="main")],
            "Windows package": [run(200, "Windows package", sha=sha)],
            "macOS package": [run(300, "macOS package", sha=sha)]}
    runs.update(over)
    return {"runs": runs}


@needs_bash
def test_release_sh_takes_each_run_for_the_tags_commit(tmp_path):
    done, calls, sha = _release(tmp_path, _good)
    assert _downloads(calls) == ["200", "300"], done.stderr
    lists = [c for c in calls if c[:2] == ["run", "list"]]
    assert [c[c.index("--workflow") + 1] for c in lists] == ["Tests", "Windows package", "macOS package"]
    assert all(c[c.index("--commit") + 1] == sha for c in lists)
    # Each run's commit is read again by its id before its files come down.
    views = [c[2] for c in calls if c[:2] == ["run", "view"]]
    assert views == ["100", "200", "300"]
    assert not any(c[:2] == ["release", "create"] for c in calls)
    # The stand-in downloads hold no checksums, so it stops there, unpublished.
    assert done.returncode != 0 and "SHA256SUMS" in done.stderr


@needs_bash
def test_release_sh_downloads_nothing_from_a_commit_whose_tests_failed(tmp_path):
    done, calls, _ = _release(tmp_path, lambda sha: _good(
        sha, Tests=[run(100, "Tests", sha=sha, conclusion="failure")]))
    assert done.returncode == 1
    assert "no Tests run" in done.stderr and "100 failure" in done.stderr
    assert _downloads(calls) == [] and not any(c[0] == "release" for c in calls)


@needs_bash
def test_release_sh_takes_no_package_run_built_from_another_commit(tmp_path):
    done, calls, _ = _release(tmp_path, lambda sha: _good(
        sha, **{"Windows package": [run(200, "Windows package", sha=OTHER)]}))
    assert done.returncode == 1 and "no Windows package run" in done.stderr
    assert _downloads(calls) == []


@needs_bash
def test_release_sh_reads_the_run_s_commit_again_before_its_files(tmp_path):
    """The list said this commit, and the run itself says another."""
    def scene(sha):
        s = _good(sha)
        s["view"] = {"300": OTHER}
        return s
    done, calls, _ = _release(tmp_path, scene)
    assert done.returncode == 1 and "macOS package run 300 is for " + OTHER in done.stderr
    assert _downloads(calls) == ["200"], "the Mac run's files never came down"


@needs_bash
def test_release_sh_stops_when_github_s_tag_names_another_commit(tmp_path):
    done, calls, _ = _release(tmp_path, lambda sha: dict(_good(sha), github_tag_sha=OTHER))
    assert done.returncode == 1 and "on GitHub" in done.stderr
    assert not any(c[:2] == ["run", "list"] for c in calls)
