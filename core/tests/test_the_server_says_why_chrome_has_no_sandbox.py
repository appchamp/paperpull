"""PaperPull Server says why Chrome has no sandbox on a host that cannot give it one.

Chrome builds its sandbox from user namespaces and a seccomp-bpf filter.
Synology DSM's kernel has neither, so the server's Chrome stopped the moment
it started, the Browser Screen stayed black, and a sign-in waited twenty
seconds, said a window had opened, to close every Chrome window and to
install Chrome or Edge (#110). The server now asks the kernel before Chrome
does (paperpull_core.host_sandbox), and a sign-in whose Chrome stopped
without its sandbox says that, and why. The sandbox itself is never turned
off or asked for less of. The desktop is untouched.

What the kernel answers was measured in the server's base image under
Docker, as an ordinary user. Docker's own profile refused the user
namespace with EPERM, seccomp-chrome.json let it through, and a profile
answering as a kernel built without user namespaces or the filter answers
gave EINVAL for each. The seccomp question was answered EFAULT wherever the
filter exists. Chrome 154 in the server image wrote the SUID helper line
and ended within a second whenever it had no user namespace.
"""
import errno
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import browser, host_sandbox  # noqa: E402
from paperpull_core.host_sandbox import Sandbox  # noqa: E402

# What /proc/self/status says in a container under a profile, as measured.
FILTERED = "Name:\tpython\nSeccomp:\t2\nSeccomp_filters:\t2\n"
# A kernel built without seccomp writes neither line.
NO_SECCOMP = "Name:\tpython\nNoNewPrivs:\t0\n"
# What Chrome 154 wrote, as measured, before it ended.
SUID = ("[11:11:1018/120942.677970:FATAL:sandbox/linux/suid/client/setuid_sandbox_host.cc"
        ":172] The SUID sandbox helper binary was found, but is not configured correctly. "
        "Rather than run without sandboxing I'm aborting now. You need to make sure that "
        "/browser/154.0.8037.97-1/opt/google/chrome/chrome-sandbox is owned by root and "
        "has mode 4755.\n"
        "[1018/120942.688418:ERROR:third_party/crashpad/crashpad/util/file/file_io_posix.cc"
        ":145] open /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq: No such file or "
        "directory (2)\n")

DSM = Sandbox("no", "no", "no-kernel")
REFUSED = Sandbox("refused", "yes", "applied")
WHOLE = Sandbox("yes", "yes", "applied")


# -- the host's answers, read -----------------------------------------------------------

@pytest.mark.parametrize("answer, userns", [
    (0, "yes"),
    (errno.EINVAL, "no"),
    (errno.EPERM, "refused"),
    (errno.EACCES, "refused"),
    (errno.ENOSPC, "limit"),
    (errno.EUSERS, "limit"),
    (errno.EBADF, "unknown"),
    (None, "unknown"),
])
def test_each_answer_to_the_user_namespace_is_read(answer, userns):
    assert host_sandbox.read({"userns": answer, "seccomp_bpf": errno.EFAULT},
                             FILTERED).userns == userns


def test_the_filter_is_there_when_the_kernel_could_not_read_the_missing_one():
    # A kernel before 5.9 writes no Seccomp_filters line, filter or not, so
    # only the child's answer can tell.
    older = "Name:\tpython\nSeccomp:\t2\n"
    assert host_sandbox.read({"seccomp_bpf": errno.EFAULT}, older).seccomp_bpf == "yes"
    assert host_sandbox.read({"seccomp_bpf": errno.EINVAL}, older).seccomp_bpf == "no"
    assert host_sandbox.read({"seccomp_bpf": errno.EINVAL}, FILTERED).seccomp_bpf == "no"


def test_without_the_childs_answer_the_status_lines_say_what_they_can():
    assert host_sandbox.read({}, FILTERED).seccomp_bpf == "yes"
    assert host_sandbox.read({}, NO_SECCOMP).seccomp_bpf == "no"
    assert host_sandbox.read({}, "Seccomp:\t0\n").seccomp_bpf == "unknown"
    assert host_sandbox.read({}, "") == host_sandbox.UNKNOWN
    assert host_sandbox.read(None, "") == host_sandbox.UNKNOWN


def test_the_containers_own_profile_is_said():
    assert host_sandbox.read({}, FILTERED).profile == "applied"
    assert host_sandbox.read({}, "Seccomp:\t0\nSeccomp_filters:\t0\n").profile == "none"
    assert host_sandbox.read({}, NO_SECCOMP).profile == "no-kernel"


def test_dsm_reads_as_no_user_namespaces_and_no_filter():
    found = host_sandbox.read({"userns": errno.EINVAL, "seccomp_bpf": errno.EINVAL}, NO_SECCOMP)
    assert found == DSM
    assert host_sandbox.stops_chrome(found)


# -- what is said ------------------------------------------------------------------------

def test_a_kernel_without_user_namespaces_is_said_in_plain_words():
    said = host_sandbox.problem(Sandbox("no", "yes", "applied"))
    assert said.startswith("This host's kernel has no user namespaces, so Chrome's sandbox "
                           "cannot start here, and PaperPull will not start Chrome without it.")
    assert host_sandbox.SECTION in said and '"On Synology" in SERVER.md' in said
    both = host_sandbox.problem(DSM)
    assert "no user namespaces and no seccomp-bpf filter" in both


def test_a_container_refused_them_is_pointed_at_its_profile():
    said = host_sandbox.problem(REFUSED)
    assert "may not make user namespaces" in said and "seccomp-chrome.json" in said
    assert host_sandbox.PROFILE_SECTION in said
    assert "user.max_user_namespaces is 0" in host_sandbox.problem(
        Sandbox("limit", "yes", "applied"))


def test_a_kernel_without_the_filter_alone_is_said_but_does_not_stop_chrome():
    found = Sandbox("yes", "no", "no-kernel")
    assert "no seccomp-bpf filter" in host_sandbox.problem(found)
    assert not host_sandbox.stops_chrome(found)


def test_nothing_is_said_of_a_host_that_has_both_or_cannot_be_told():
    assert host_sandbox.problem(WHOLE) == ""
    assert host_sandbox.problem(host_sandbox.UNKNOWN) == ""
    assert not host_sandbox.stops_chrome(WHOLE)
    assert not host_sandbox.stops_chrome(host_sandbox.UNKNOWN)


def test_the_start_says_it_in_one_line():
    for found in (DSM, REFUSED, WHOLE, host_sandbox.UNKNOWN, Sandbox("yes", "yes", "none")):
        line = host_sandbox.line(found)
        assert line.startswith("[sandbox] ") and "\n" not in line
    assert host_sandbox.line(DSM) == "[sandbox] " + host_sandbox.problem(DSM) + (
        " The kernel has no seccomp, so the container runs with no seccomp profile.")
    assert "can give Chrome its sandbox" in host_sandbox.line(WHOLE)
    assert "no seccomp profile at all" in host_sandbox.line(Sandbox("yes", "yes", "none"))
    assert "could not be told" in host_sandbox.line(host_sandbox.UNKNOWN)


# -- asking ------------------------------------------------------------------------------

def test_off_linux_nothing_is_asked(monkeypatch):
    def asked():
        raise AssertionError("the kernel was asked off Linux")
    monkeypatch.setattr(host_sandbox, "probe", asked)
    monkeypatch.setattr(host_sandbox.sys, "platform", "win32")
    host_sandbox.check.cache_clear()
    try:
        assert host_sandbox.check() == host_sandbox.UNKNOWN
    finally:
        host_sandbox.check.cache_clear()


@pytest.mark.parametrize("stdout", ["", "not json\n", "[1, 2]\n"])
def test_a_child_that_answers_nothing_usable_is_no_answer(monkeypatch, stdout):
    monkeypatch.setattr(host_sandbox.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout, ""))
    assert host_sandbox.probe() == {}


def test_the_childs_questions_are_python():
    compile(host_sandbox._PROBE, "<probe>", "exec")


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="asks a Linux kernel")
def test_on_linux_the_child_answers_both_questions():
    answer = host_sandbox.probe()
    assert set(answer) == {"userns", "seccomp_bpf"}, answer


# -- the server's sign-in ----------------------------------------------------------------

class _Ended:
    """Stands in for subprocess.Popen, a browser that wrote `says` to the
    stderr it was handed and has ended by the first look."""

    def __init__(self, says=""):
        self.says = says
        self.handed = []

    def __call__(self, cmd, stderr=None, **_kw):
        self.handed.append((cmd[0], stderr))
        if self.says and hasattr(stderr, "write"):
            stderr.write(self.says.encode("utf-8"))
            stderr.flush()
        return self

    def poll(self):
        return 1


@pytest.fixture
def port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    free = str(s.getsockname()[1])
    s.close()
    return free


@pytest.fixture
def server(monkeypatch):
    """The server's sign-in, with its one Chrome, a host check that answers
    what a test says, and no download ever offered."""
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    monkeypatch.delenv("PAPERPULL_GPU", raising=False)
    monkeypatch.setattr(browser.sys, "platform", "linux")
    monkeypatch.setattr(browser, "browser_candidates",
                        lambda prefer_real=False, mode=browser.AUTO:
                        [(browser.CHROME, "/usr/bin/google-chrome-stable")])
    monkeypatch.setattr(browser, "bundled_chromium_present", lambda: False)

    def no_download(*_a, **_k):
        raise AssertionError("the server offered a browser download")
    monkeypatch.setattr(browser, "fetch_bundled_chromium", no_download)
    found = {"host": WHOLE}
    monkeypatch.setattr(host_sandbox, "check", lambda: found["host"])
    return found


def said(capsys):
    return " ".join(capsys.readouterr().out.split())


def _looks(monkeypatch, timeout=None) -> list:
    """What the wait heard each time it asked whether the browser still
    ran, with its time cut to `timeout` when given."""
    asked = []
    real = browser.wait_for_debug_port

    def wait(port, timeout_=20.0, alive=None):
        def still_running():
            asked.append(alive())
            return asked[-1]
        return real(port, timeout or timeout_, alive=None if alive is None else still_running)
    monkeypatch.setattr(browser, "wait_for_debug_port", wait)
    return asked


def test_a_server_chrome_without_user_namespaces_says_why_at_once(
        monkeypatch, tmp_path, port, capsys, server):
    server["host"] = DSM
    monkeypatch.setattr(browser.subprocess, "Popen", _Ended(SUID))
    asked = _looks(monkeypatch)
    assert browser.open_signin_browser(tmp_path / "p", port, "https://bank.example/") is None
    assert asked and asked[-1] is False and asked.count(False) == 1, \
        "it waited for a port although Chrome had ended: %s" % asked
    words = said(capsys)
    assert "Google Chrome closed right after it started" in words
    assert "This host's kernel has no user namespaces and no seccomp-bpf filter" in words
    assert '"On Synology" in SERVER.md' in words
    for wrong in ("window opened", "Close every", "already running", "Install Chrome",
                  "install Chrome or Edge", "None of the browsers", "400 MB"):
        assert wrong not in words, wrong


def test_a_server_chrome_without_its_sandbox_says_so_when_the_host_check_found_nothing(
        monkeypatch, tmp_path, port, capsys, server):
    monkeypatch.setattr(browser.subprocess, "Popen", _Ended(SUID))
    _looks(monkeypatch)
    assert browser.open_signin_browser(tmp_path / "p", port, "https://bank.example/") is None
    words = said(capsys)
    assert "could not start its sandbox" in words and "self-test" in words
    assert "Close every" not in words and "Install Chrome" not in words


@pytest.mark.parametrize("line", ["No usable sandbox! Update your kernel",
                                  "Failed to move to new namespace: PID namespaces supported, "
                                  "Network namespace supported, but failed: errno = Operation "
                                  "not permitted"])
def test_each_of_chromes_words_for_it_is_heard(monkeypatch, tmp_path, port, capsys, server,
                                              line):
    server["host"] = REFUSED
    monkeypatch.setattr(browser.subprocess, "Popen", _Ended(line + "\n"))
    asked = _looks(monkeypatch)
    assert browser._launch("/usr/bin/google-chrome-stable", browser.CHROME, tmp_path / "p",
                           port, "https://bank.example/") is None
    assert asked.count(False) == 1, asked
    assert "seccomp-chrome.json is not applied" in said(capsys)


def test_a_server_chrome_that_said_nothing_known_on_a_host_without_them_is_still_named(
        monkeypatch, tmp_path, port, capsys, server):
    """Chrome's words may change. The host check alone still names the
    cause, once the wait is out, here cut to a second."""
    server["host"] = Sandbox("no", "yes", "none")
    monkeypatch.setattr(browser.subprocess, "Popen", _Ended("something new\n"))
    _looks(monkeypatch, timeout=1.0)
    assert browser._launch("/usr/bin/google-chrome-stable", browser.CHROME, tmp_path / "p",
                           port, "https://bank.example/") is None
    words = said(capsys)
    assert "This host's kernel has no user namespaces" in words
    assert "window opened" not in words and "Close every" not in words


def test_a_server_chrome_that_failed_otherwise_says_what_it_always_said_and_offers_nothing(
        monkeypatch, tmp_path, port, capsys, server):
    """A host with both, and a Chrome that ended for another reason. The
    wait runs its time, cut to a second, and says what it said before. Only
    the download offer, which never fits the server, is gone."""
    monkeypatch.setattr(browser.subprocess, "Popen", _Ended(
        "chrome: error while loading shared libraries: libnss3.so\n"))
    _looks(monkeypatch, timeout=1.0)
    assert browser.open_signin_browser(tmp_path / "p", port, "https://bank.example/") is None
    words = said(capsys)
    assert "The window opened, but no debugging port answered" in words
    assert "sandbox" not in words and "None of the browsers" not in words


def test_what_the_server_chrome_wrote_is_read_and_not_kept(monkeypatch, tmp_path, port, server):
    started = _Ended(SUID)
    monkeypatch.setattr(browser.subprocess, "Popen", started)
    browser._launch("/usr/bin/google-chrome-stable", browser.CHROME, tmp_path / "p", port,
                    "https://bank.example/")
    (_exe, handed), = started.handed
    assert handed is not subprocess.DEVNULL and handed.closed


@pytest.mark.skipif(os.name == "nt", reason="a shell script stands in for Chrome")
def test_a_real_process_that_ends_without_its_sandbox_on_the_server(
        monkeypatch, tmp_path, port, capsys, server):
    server["host"] = DSM
    (tmp_path / "said.txt").write_text(SUID, encoding="utf-8")
    exe = tmp_path / "google-chrome-stable"
    exe.write_text("#!/bin/sh\ncat '%s' >&2\nexit 133\n" % (tmp_path / "said.txt"),
                   encoding="utf-8")
    exe.chmod(0o755)
    monkeypatch.setattr(browser, "browser_candidates",
                        lambda prefer_real=False, mode=browser.AUTO:
                        [(browser.CHROME, str(exe))])
    asked = _looks(monkeypatch)
    assert browser.open_signin_browser(tmp_path / "p", port, "https://bank.example/") is None
    assert asked and asked.count(False) == 1, asked
    assert "no user namespaces" in said(capsys)


# -- the desktop, untouched --------------------------------------------------------------

def test_off_the_server_their_chrome_is_started_and_told_as_before(
        monkeypatch, tmp_path, port, capsys):
    """Their own Chrome on Linux still writes to nowhere, is waited for the
    old way, and is told to close every Chrome window. The host is never
    asked."""
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    monkeypatch.setattr(browser.sys, "platform", "linux")

    def asked():
        raise AssertionError("the desktop asked the host about Chrome's sandbox")
    monkeypatch.setattr(host_sandbox, "check", asked)
    started = _Ended(SUID)
    monkeypatch.setattr(browser.subprocess, "Popen", started)
    waits = []
    monkeypatch.setattr(browser, "wait_for_debug_port",
                        lambda port, timeout=20.0, **kw: waits.append(kw) or False)
    assert browser._launch("/x/google-chrome", browser.CHROME, tmp_path / "p", port,
                           "https://bank.example/") is None
    assert started.handed == [("/x/google-chrome", subprocess.DEVNULL)]
    assert waits == [{}]
    words = said(capsys)
    assert "Close every Google Chrome window" in words and "sandbox" not in words


def test_off_the_server_the_bundled_chromium_hears_only_its_own_words(
        monkeypatch, tmp_path, port, capsys):
    """The bundled Chromium on a Linux desktop ends the wait early on "No
    usable sandbox" alone, as before. The helper line the server's Chrome
    writes does not end it there."""
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    monkeypatch.setattr(browser.sys, "platform", "linux")
    monkeypatch.setattr(browser, "_real_browsers", lambda: [])
    monkeypatch.setattr(browser.subprocess, "Popen", _Ended(SUID))
    asked = _looks(monkeypatch, timeout=1.0)
    assert browser._launch("/x/chrome", browser.CHROMIUM, tmp_path / "p", port,
                           "https://bank.example/") is None
    assert asked and all(asked), "the desktop's wait was ended by the server's words"
    assert "The window opened, but no debugging port answered" in said(capsys)
