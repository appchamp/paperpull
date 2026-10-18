"""The self-test says why Chrome did not start when its sandbox is why.

On Synology DSM the self-test said only "Chrome did not open a debugging
port", followed by the last three lines Chrome wrote, which were crashpad's
noise about CPU frequency files, and never printed its sandbox line at all
(#110). Measured in the server image with Chrome 154, the line that says why
came first and was cut off. Now a sandbox line comes before the port, and
names the cause the host check found (paperpull_core.host_sandbox), or says
it was the sandbox when Chrome's own words do. A Chrome that failed for any
other reason is said as it always was.
"""
import sys
import types
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))

import selftest  # noqa: E402
from paperpull_core import host_sandbox  # noqa: E402
from paperpull_core.host_sandbox import Sandbox  # noqa: E402

SUID = ("[11:11:1018/120942.677970:FATAL:sandbox/linux/suid/client/setuid_sandbox_host.cc"
        ":172] The SUID sandbox helper binary was found, but is not configured correctly. "
        "Rather than run without sandboxing I'm aborting now.\n"
        "[1018/120942.688418:ERROR:third_party/crashpad/crashpad/util/file/file_io_posix.cc"
        ":145] open /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq: No such file\n")


@pytest.fixture
def run(monkeypatch):
    """browser_checks with a Chrome that wrote `said` and opened no port, a
    host check that answers `host`, and no Playwright needed. Answers the
    rows it printed."""
    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.sync_playwright = lambda: (_ for _ in ()).throw(AssertionError("attached"))
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)

    def go(said, host):
        def start_chrome(profile):
            raise selftest.NotStarted("Chrome did not open a debugging port. It said: x", said)
        monkeypatch.setattr(selftest, "start_chrome", start_chrome)
        monkeypatch.setattr(host_sandbox, "check", lambda: host)
        selftest.results.clear()
        selftest.browser_checks()
        rows = list(selftest.results)
        selftest.results.clear()
        return rows
    return go


def test_a_host_without_user_namespaces_is_named_before_the_port(run):
    rows = run(SUID, Sandbox("no", "no", "no-kernel"))
    assert [(name, ok) for name, ok, _ in rows] == [("sandbox", False), ("browser", False)]
    detail = rows[0][2]
    assert "no user namespaces and no seccomp-bpf filter" in detail
    assert '"On Synology" in SERVER.md' in detail


def test_a_container_refused_them_is_pointed_at_its_profile(run):
    rows = run("", Sandbox("refused", "yes", "applied"))
    assert rows[0][0] == "sandbox" and "seccomp-chrome.json" in rows[0][2]


def test_a_host_without_the_filter_is_named_too(run):
    rows = run("", Sandbox("yes", "no", "no-kernel"))
    assert rows[0][0] == "sandbox" and "no seccomp-bpf filter" in rows[0][2]


def test_chromes_own_words_say_it_was_the_sandbox_when_the_host_check_found_nothing(run):
    rows = run(SUID, Sandbox("yes", "yes", "applied"))
    assert rows[0][0] == "sandbox" and not rows[0][1]
    assert "could not start its sandbox" in rows[0][2]


def test_a_chrome_that_failed_otherwise_is_said_as_before(run):
    rows = run("chrome: error while loading shared libraries: libnss3.so\n",
               Sandbox("yes", "yes", "applied"))
    assert rows == [("browser", False,
                     "NotStarted: Chrome did not open a debugging port. It said: x")]


def test_the_sandbox_problem_comes_from_the_core(monkeypatch):
    monkeypatch.setattr(host_sandbox, "check", lambda: Sandbox("no", "yes", "applied"))
    assert selftest.sandbox_problem() == host_sandbox.problem(Sandbox("no", "yes", "applied"))
    monkeypatch.setattr(host_sandbox, "check", lambda: Sandbox("yes", "yes", "applied"))
    assert selftest.sandbox_problem() == ""


def test_the_containers_start_says_it_once_as_pp_and_goes_on():
    """start.sh runs as pp, the user Chrome runs as, since entrypoint.sh
    hands it over, and the line comes before the panel starts. A check that
    fails never stops the start."""
    start = (SERVER / "start.sh").read_text(encoding="utf-8")
    said = start.index("python -m paperpull_core.host_sandbox || true")
    assert said < start.index("exec python -m uvicorn")
    assert "--reuid=pp" in (SERVER / "entrypoint.sh").read_text(encoding="utf-8")
    dockerfile = (SERVER / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY core /opt/paperpull/core" in dockerfile
    assert "pip install --no-cache-dir --no-deps --no-build-isolation /opt/paperpull/core" in dockerfile
