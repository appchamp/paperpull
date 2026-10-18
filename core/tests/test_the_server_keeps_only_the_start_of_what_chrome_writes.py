"""PaperPull Server keeps only the start of what its Chrome writes.

The sign-in step reads what Chrome writes while it starts, for the lines of a
Chrome that could not start its sandbox (#110). On the server that went into
a file with no name in the container's /tmp, which Chrome went on writing to
for as long as its window stayed open, days on a server, and nothing bounded
it. Now Chrome writes into a pipe whose other end a small helper holds for as
long as anything holding Chrome's end does. It keeps the first 64 kB and
reads the rest into nothing (browser._KeptStart).

Measured with Chrome 154 in the server image, as pp under the server's
seccomp profile. The sign-in step ends seconds after its window opens. When
the reader of the pipe was gone, Chrome's own processes went on, since each
ignores SIGPIPE, but both of its crashpad handlers catch it, and they ended
at the first crash of a page, which they write two lines about. Truncating
the file once instead freed what was written so far, and every later write
took disk again, with O_APPEND or without. So the stand-ins here die of a
write that does not go through, as those handlers do.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import browser  # noqa: E402

LINE = ("[1018/120942.677970:FATAL:sandbox/linux/suid/client/setuid_sandbox_host.cc:172] "
        "The SUID sandbox helper binary was found, but is not configured correctly.")

# What a stand-in for Chrome runs first. A write that does not go through
# ends it, killed by SIGPIPE on Linux and macOS as crashpad's handlers were,
# or with the error on Windows.
DIES_OF_A_LOST_WRITE = (
    "import os, signal, sys, time\n"
    "if hasattr(signal, 'SIGPIPE'):\n"
    "    signal.signal(signal.SIGPIPE, signal.SIG_DFL)\n")


@pytest.fixture
def said():
    kept = browser._KeptStart.begin()
    assert kept is not None, "the helper did not start"
    yield kept
    kept.close()
    try:
        kept.helper.wait(timeout=30)
    except subprocess.TimeoutExpired:
        kept.helper.kill()
        raise AssertionError("the helper outlived every end of Chrome's") from None


def chrome(said, code: str, *args, **kw) -> subprocess.Popen:
    """A process standing in for Chrome, started on the end Chrome is
    handed, which this process then closes, as the sign-in step does."""
    kw.setdefault("stdin", subprocess.DEVNULL)
    proc = subprocess.Popen([sys.executable, "-I", "-S", "-c", DIES_OF_A_LOST_WRITE + code,
                             *args], stdout=subprocess.DEVNULL, stderr=said.write_end, **kw)
    os.close(said.write_end)
    said.write_end = None
    return proc


def test_only_the_start_is_kept_however_much_chrome_writes(said):
    wrote = chrome(said, "os.write(2, sys.argv[1].encode() + bytes([10]))\n"
                         "for _ in range(64):\n"
                         "    os.write(2, b'x' * 65536)\n", LINE)
    assert wrote.wait(timeout=60) == 0, "a write of Chrome's did not go through"
    said.helper.wait(timeout=60)
    st = os.fstat(said.log.fileno())
    assert st.st_size == said.KEEP == 65536, st.st_size
    if hasattr(st, "st_blocks"):
        assert st.st_blocks * 512 <= said.KEEP + 8192, st.st_blocks
    kept = said.read()
    assert kept.startswith(LINE) and len(kept) == said.KEEP
    assert any(mark in kept for mark in browser.SERVER_NO_SANDBOX)


def test_every_write_goes_through_once_the_sign_in_step_is_done_with_it(said):
    """The sign-in step closes its ends and ends, and Chrome writes on for
    days. Here it writes 4 MB only after both of this process's ends are
    closed."""
    wrote = chrome(said, "sys.stdin.read()\n"
                         "for _ in range(64):\n"
                         "    os.write(2, b'y' * 65536)\n", stdin=subprocess.PIPE)
    said.close()
    wrote.stdin.close()     # only now does it write
    assert wrote.wait(timeout=60) == 0, \
        "a write of Chrome's did not go through, rc %s" % wrote.returncode


def test_the_helper_lasts_as_long_as_anything_holding_chromes_end(said, tmp_path):
    """Chrome's first process is not the last to hold the end. Its zygote
    and crashpad's handlers hold it too, and may write after it has ended."""
    go = tmp_path / "go"
    late = ("import os, sys, time\n"
            "while not os.path.exists(sys.argv[1]):\n"
            "    time.sleep(0.05)\n"
            "os.write(2, b'late' + bytes([10]))\n")
    wrote = chrome(said, "import subprocess\n"
                         "os.write(2, b'early' + bytes([10]))\n"
                         "subprocess.Popen([sys.executable, '-I', '-S', '-c', sys.argv[1],"
                         " sys.argv[2]], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,"
                         " stderr=2)\n", late, str(go))
    try:
        assert wrote.wait(timeout=60) == 0
        time.sleep(1.0)
        assert said.helper.poll() is None, "the helper ended while a process held Chrome's end"
    finally:
        go.write_text("go", encoding="utf-8")
    said.helper.wait(timeout=60)
    assert said.read() == "early\nlate\n"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads /proc")
def test_the_helper_holds_only_its_three_ends_in_a_session_of_its_own(said):
    """Holding Chrome's writing end too, it would never end. Holding the
    sign-in step's stdout, the panel's Login would wait for it. In the sign-in
    step's session, whatever ends that could end it."""
    os.write(said.write_end, b"x")
    for _ in range(200):
        if said.read() == "x":
            break
        time.sleep(0.05)
    assert said.read() == "x", "the helper never read what was written"
    pid = said.helper.pid
    assert sorted(int(n) for n in os.listdir("/proc/%d/fd" % pid)) == [0, 1, 2]
    assert os.readlink("/proc/%d/fd/0" % pid).startswith("pipe:")
    with open("/proc/%d/fdinfo/0" % pid, encoding="ascii") as f:
        flags = int(next(ln for ln in f if ln.startswith("flags:")).split()[1], 8)
    assert flags & 3 == os.O_RDONLY, "the helper holds the writing end"
    log = os.fstat(said.log.fileno())
    held = os.stat("/proc/%d/fd/1" % pid)
    assert (held.st_dev, held.st_ino) == (log.st_dev, log.st_ino)
    assert os.readlink("/proc/%d/fd/2" % pid) == "/dev/null"
    assert os.getsid(pid) == pid
