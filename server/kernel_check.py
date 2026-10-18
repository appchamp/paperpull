"""Whether this kernel can give Chrome the second layer of its sandbox.

    python /opt/paperpull/server/kernel_check.py

Chrome's sandbox on Linux has two layers. The first, the namespace sandbox
or the setuid helper in its place, shuts each page in a room of its own. The
second is a seccomp filter, which leaves a page that has been taken over no
way to make most of the kernel's calls. That second layer needs the
kernel's seccomp, and some kernels are built without it, Synology's 4.4
kernels among them. Chrome starts there all the same, with half its
sandbox, and says so only on chrome://sandbox. PaperPull never starts a
browser without its whole sandbox, so entrypoint.sh asks this first, and
the container does not start on such a kernel.

The kernel is asked the way Chrome asks it. A filter installed from an
address of nothing is refused with EFAULT by a kernel that has seccomp's
filter mode, which looked at the address, and with EINVAL by one that does
not. Nothing is installed either way. Any other answer is taken as no.

It exits 0 when the kernel has the filter, and 1 saying what to do when it
has not.
"""
from __future__ import annotations

import ctypes
import errno
import sys

PR_SET_SECCOMP = 22
SECCOMP_MODE_FILTER = 2

REFUSED = (
    "This machine's kernel was built without seccomp, the filter that is the "
    "second layer of Chrome's sandbox. Chrome would start here with half its "
    "sandbox, and PaperPull never starts a browser without the whole of it, so "
    "PaperPull Server does not start on this machine. Some NAS kernels are built "
    "this way, Synology's 4.4 kernels among them, see \"On a Synology NAS\" in "
    "SERVER.md.")


def has_seccomp_filter(prctl) -> bool:
    """Whether the kernel has seccomp's filter mode. prctl takes prctl's five
    arguments and returns (result, errno)."""
    result, err = prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, None, 0, 0)
    return result == -1 and err == errno.EFAULT


def libc_prctl(option, arg2, arg3, arg4, arg5):
    """prctl itself, each argument passed at its full width, since an int
    passed as one would leave the upper half of arg2 to chance."""
    libc = ctypes.CDLL(None, use_errno=True)
    ctypes.set_errno(0)
    result = libc.prctl(ctypes.c_int(option), ctypes.c_ulong(arg2), ctypes.c_void_p(arg3),
                        ctypes.c_ulong(arg4), ctypes.c_ulong(arg5))
    return result, ctypes.get_errno()


def main() -> int:
    if not sys.platform.startswith("linux"):
        print("kernel_check.py asks a Linux kernel, inside the container.", file=sys.stderr)
        return 1
    if has_seccomp_filter(libc_prctl):
        return 0
    print(REFUSED, file=sys.stderr, flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
