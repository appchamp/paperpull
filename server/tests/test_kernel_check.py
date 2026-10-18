"""The container does not start on a kernel that cannot give Chrome its
seccomp filter, the second layer of its sandbox.

Synology's 4.4 kernels are built without seccomp, and Chrome started there
with half its sandbox, measured on a DiskStation (chrome://sandbox, layer 1
SUID, seccomp off). kernel_check.py asks the kernel the way Chrome does, and
entrypoint.sh asks it before anything else that matters.
"""
import errno
import sys
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))

import kernel_check  # noqa: E402


def kernel(err, result=-1):
    seen = []

    def prctl(*args):
        seen.append(args)
        return result, err
    return prctl, seen


def test_a_kernel_that_looked_at_the_address_has_the_filter():
    prctl, seen = kernel(errno.EFAULT)
    assert kernel_check.has_seccomp_filter(prctl)
    # PR_SET_SECCOMP, SECCOMP_MODE_FILTER, and an address of nothing.
    assert seen == [(22, 2, None, 0, 0)]


@pytest.mark.parametrize("err", [errno.EINVAL, errno.EPERM, errno.EACCES, errno.ENOSYS, 0])
def test_any_other_answer_is_no(err):
    assert not kernel_check.has_seccomp_filter(kernel(err)[0])


def test_a_filter_somehow_installed_is_not_taken_for_yes():
    assert not kernel_check.has_seccomp_filter(kernel(0, result=0)[0])


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="asks a Linux kernel")
def test_this_kernel_answers_as_chrome_would_find_it():
    """Every Linux kernel a test runs on has seccomp's filter mode, so the
    real prctl, at its full argument widths, has to say yes."""
    assert kernel_check.has_seccomp_filter(kernel_check.libc_prctl)


def test_the_container_asks_before_it_fetches_chrome():
    entry = (SERVER / "entrypoint.sh").read_text(encoding="utf-8")
    ask = entry.index("if ! python /opt/paperpull/server/kernel_check.py; then\n  exit 1\nfi")
    assert ask < entry.index("if ! /opt/paperpull/server/chrome.sh; then")
    assert ask < entry.index("exec setpriv")
    copied = [line for line in (SERVER / "Dockerfile").read_text(encoding="utf-8").splitlines()
              if line.startswith("COPY server/entrypoint.sh")]
    assert copied and "server/kernel_check.py" in copied[0]


def test_the_refusal_says_where_to_read_more_in_the_house_punctuation():
    assert '"On a Synology NAS" in SERVER.md' in kernel_check.REFUSED
    assert "### On a Synology NAS" in (SERVER.parent / "SERVER.md").read_text(encoding="utf-8")
    assert ";" not in kernel_check.REFUSED and "—" not in kernel_check.REFUSED
