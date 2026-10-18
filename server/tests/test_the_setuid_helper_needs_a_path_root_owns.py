"""Chrome's setuid helper is made setuid root only where root alone could
have put it.

In a container given SYS_ADMIN, server/chrome.sh, which runs as root at
every start, makes the sandbox helper of the Chrome in use setuid root. The
Chrome in use is named by what is in /browser, and /browser belonged to pp,
so code running as pp could plant a folder there with a file of its own as
the helper, which chrome.sh gave to root and made setuid. That was root,
holding SYS_ADMIN besides, at the next start (found in review before 0.56.0
and reproduced). Now /browser is root's, given back by the entrypoint for a
volume an older image made, and chrome.sh never gives a file to root. It
sets the bit only on a plain file with one name, of root's user and group,
in folders that root alone owns and that are no links, from /browser down.

The tests that run chrome.sh's own functions need root on Linux, to give
the folders real owners, and skip anywhere else. server/smoke.py checks the
same in the image.
"""
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[1]
VERSION = "154.0.8037.97-1"
# The image's pp, the user everything but the entrypoint runs as.
PP = 1000

needs_root = pytest.mark.skipif(
    not (sys.platform.startswith("linux") and os.geteuid() == 0
         and shutil.which("sh") and shutil.which("stat")),
    reason="gives folders owners other than this user's, which needs root on Linux")


def functions(script: str) -> str:
    """Every function chrome.sh defines, and nothing it runs."""
    out, inside = [], False
    for line in script.splitlines():
        if not inside and re.match(r"^[a-z_]+\(\) \{", line):
            out.append(line)
            inside = not line.rstrip().endswith("}")
        elif inside:
            out.append(line)
            inside = line != "}"
    return "\n".join(out) + "\n"


def start(browser: Path, in_use: str = VERSION, sys_admin: bool = True):
    """chrome.sh's readable step for the Chrome in use, as each start runs
    it, with the volume at `browser` and SYS_ADMIN held or not."""
    script = (SERVER / "chrome.sh").read_text(encoding="utf-8")
    body = ("set -eu\n" + functions(script)
            + 'BROWSER="$1"\nSETUID_SANDBOX="$2"\nreadable "$3"\n')
    return subprocess.run(["sh", "-c", body, "chrome.sh", str(browser),
                           "1" if sys_admin else "0", in_use],
                          capture_output=True, text=True, timeout=60)


def owned(path: Path, uid: int = 0, gid: int = 0, mode: int = 0o755) -> None:
    os.chown(path, uid, gid, follow_symlinks=False)
    os.chmod(path, mode)


def chrome(browser: Path, version: str = VERSION) -> Path:
    """A Chrome in the volume as chrome.sh unpacks one, root's throughout,
    with its helper setuid as the package ships it. Answers the helper."""
    folder = browser / version / "opt" / "google" / "chrome"
    folder.mkdir(parents=True)
    (folder / "chrome").write_bytes(b"#!/bin/sh\nexit 0\n")
    helper = folder / "chrome-sandbox"
    helper.write_bytes(b"\x7fELF the helper")
    for path in (browser, browser / version, browser / version / "opt",
                 browser / version / "opt" / "google", folder, folder / "chrome"):
        owned(path)
    owned(helper, mode=0o4755)
    return helper


@pytest.fixture
def volume(tmp_path):
    browser = tmp_path / "browser"
    browser.mkdir()
    helper = chrome(browser)
    os.symlink(VERSION, browser / "current")
    return browser, helper


def setuid_files(top: Path) -> list:
    """Every file under top with its setuid bit, links never followed."""
    found = []
    for folder, dirs, files in os.walk(top, followlinks=False):
        for name in dirs + files:
            path = Path(folder) / name
            if os.lstat(path).st_mode & stat.S_ISUID:
                found.append(str(path))
    return found


def _pp_version_folder(browser, helper):
    os.chown(browser / VERSION, PP, PP)
    return "%s belongs to user %d, not to root" % (browser / VERSION, PP)


def _pp_helper(browser, helper):
    owned(helper, PP, PP, 0o4755)
    return "%s belongs to user %d, not to root" % (helper, PP)


def _helper_of_pps_group(browser, helper):
    owned(helper, 0, PP, 0o4755)
    return "%s belongs to group %d, not to root" % (helper, PP)


def _group_writable_folder(browser, helper):
    os.chmod(browser / VERSION / "opt" / "google", 0o775)
    return "users other than root may write to %s" % (browser / VERSION / "opt" / "google")


def _world_writable_folder(browser, helper):
    os.chmod(browser / VERSION / "opt", 0o777)
    return "users other than root may write to %s" % (browser / VERSION / "opt")


def _writable_helper(browser, helper):
    os.chmod(helper, 0o4757)
    return "users other than root may write to %s" % helper


def _linked_folder(browser, helper):
    # The helper's folder moved elsewhere, root's and all, and a link left.
    elsewhere = browser.parent / "elsewhere"
    elsewhere.mkdir()
    owned(elsewhere)
    folder = helper.parent
    folder.rename(elsewhere / "chrome")
    os.symlink(elsewhere / "chrome", folder)
    return "%s is a link or not a folder" % folder


def _linked_helper(browser, helper):
    # A link is never followed, so the file it names is left as it was.
    elsewhere = browser.parent / "chrome-sandbox"
    helper.rename(elsewhere)
    os.chmod(elsewhere, 0o755)
    os.symlink(elsewhere, helper)
    return "%s is a link or not a plain file" % helper


def _second_name(browser, helper):
    os.link(helper, browser.parent / "kept")
    return "%s has 2 names, where it may have only one" % helper


def _pp_browser_volume(browser, helper):
    os.chown(browser, PP, PP)
    return "%s belongs to user %d, not to root" % (browser, PP)


REFUSED = {
    "a version folder of pp's": _pp_version_folder,
    "a helper of pp's": _pp_helper,
    "a helper of pp's group": _helper_of_pps_group,
    "a folder its group may write to": _group_writable_folder,
    "a folder anyone may write to": _world_writable_folder,
    "a helper anyone may write to": _writable_helper,
    "a folder that is a link": _linked_folder,
    "a helper that is a link": _linked_helper,
    "a helper with a second name": _second_name,
    "a browser volume of pp's": _pp_browser_volume,
}


@needs_root
@pytest.mark.parametrize("case", sorted(REFUSED))
def test_the_helper_is_not_made_setuid_on_a_path_pp_could_have_touched(volume, case):
    browser, helper = volume
    why = REFUSED[case](browser, helper)
    r = start(browser)
    assert r.returncode == 0, r.stdout + r.stderr
    # Not set, and taken off any copy that had it, the one in use included.
    assert setuid_files(browser.parent) == [], case
    said = [line for line in r.stdout.splitlines() if "setuid sandbox helper" in line]
    assert said == ["[chrome] The container has SYS_ADMIN, but Chrome's setuid sandbox "
                    "helper is not set up, since %s." % why], said


@needs_root
def test_a_helper_root_alone_could_have_put_there_is_made_setuid(volume):
    browser, helper = volume
    older = chrome(browser, "153.0.7999.1-1")
    os.chmod(helper, 0o755)
    r = start(browser)
    assert r.returncode == 0, r.stdout + r.stderr
    st = os.lstat(helper)
    assert (st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode)) == (0, 0, 0o4755)
    # Only the Chrome in use keeps it, never an older one beside it.
    assert setuid_files(browser.parent) == [str(helper)]
    assert not os.lstat(older).st_mode & stat.S_ISUID
    assert ("[chrome] The container has SYS_ADMIN, so Chrome's setuid sandbox helper is "
            "set up, for a kernel without user namespaces.") in r.stdout.splitlines()


@needs_root
def test_without_sys_admin_no_copy_keeps_the_bit(volume):
    browser, helper = volume
    chrome(browser, "153.0.7999.1-1")
    r = start(browser, sys_admin=False)
    assert r.returncode == 0, r.stdout + r.stderr
    assert setuid_files(browser.parent) == []
    assert "setuid" not in r.stdout


def test_chrome_sh_never_gives_a_file_to_root():
    """The bit was set after a chown to root, which made whatever was there
    root's. No line chrome.sh runs changes an owner now."""
    script = (SERVER / "chrome.sh").read_text(encoding="utf-8")
    run = [line for line in script.splitlines() if not line.lstrip().startswith("#")]
    assert not [line for line in run if "chown" in line]
    helpers = functions(script)
    setuid = helpers[helpers.index("sandbox_helpers() {"):]
    assert setuid.index('why=$(may_be_setuid "$1")') < setuid.index("chmod 4755")
    # Every copy loses the bit before the one in use may get it.
    assert setuid.index("chmod u-s,g-s") < setuid.index("chmod 4755")


def test_the_browser_volume_is_roots_and_only_its_top_folder_is_given_back():
    """A new volume takes its owner from the image's /browser, which stays
    root's. A volume an older image made has its top folder given back to
    root before chrome.sh runs, and never what is inside it, which would
    make anything pp put there root's."""
    dockerfile = (SERVER / "Dockerfile").read_text(encoding="utf-8")
    to_pp = [line for line in dockerfile.splitlines() if "chown" in line]
    assert to_pp == [" && chown pp:pp /data /profiles /config"]
    entrypoint = (SERVER / "entrypoint.sh").read_text(encoding="utf-8")
    given = entrypoint.index("chown 0:0 /browser && chmod 0755 /browser")
    assert given < entrypoint.index("/opt/paperpull/server/chrome.sh")
    assert not re.search(r"chown -R[^\n]*/browser", entrypoint)
