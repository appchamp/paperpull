"""The Windows and macOS packages carry the same CPython from the same
python-build-standalone release, each archive checked against its published
SHA-256, and install every package from a lock that holds each file's hash.

The Windows package was built on python.org's embeddable CPython 3.12.10,
the last 3.12 with Windows binaries there, so no later 3.12 security fix
could reach it. Both packages installed lower bounds (playwright>=1.44 and
so on), whatever PyPI held on the day, and the Windows build ran get-pip.py
as downloaded, with nothing checking a byte of either.
"""
import hashlib
import importlib.util
import io
import re
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PACKAGING = REPO / "packaging"


def _load(name, path):
    sys.path.insert(0, str(PACKAGING))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def bw(monkeypatch, tmp_path):
    mod = _load("bw_python", PACKAGING / "build_windows.py")
    monkeypatch.setattr(mod, "DIST", tmp_path / "dist")
    monkeypatch.setattr(mod, "STAGE", tmp_path / "dist" / "PaperPull")
    monkeypatch.setattr(mod, "say", lambda *a, **k: None)
    return mod


@pytest.fixture()
def bm(monkeypatch):
    mod = _load("bm_python", PACKAGING / "build_macos.py")
    monkeypatch.setattr(mod, "say", lambda *a, **k: None)
    return mod


@pytest.fixture()
def lock_tool():
    return _load("lock_tool", PACKAGING / "lock.py")


def _builders(bw, bm):
    return ((bw, "windows"), (bm, "macos"))


# -- one Python, from one release ----------------------------------------------

def test_both_packages_carry_the_same_python_from_the_same_release(bw, bm):
    assert bw.PY_VERSION == bm.PY_VERSION
    assert bw.PBS_TAG == bm.PBS_TAG
    assert bw.PY_VERSION.startswith("3.12.")
    for mod, _ in _builders(bw, bm):
        for arch in mod.ARCHES:
            assert mod.triple(arch).startswith(mod.ARCHES[arch] + "-")


def test_each_python_archive_is_fetched_against_its_own_published_digest(bw, bm, monkeypatch):
    every = list(bw.PBS_SHA256.values()) + list(bm.PBS_SHA256.values())
    assert all(re.fullmatch(r"[0-9a-f]{64}", d) for d in every)
    assert len(set(every)) == len(every), "one archive each, no digest copied to another"

    class Fetched(Exception):
        pass

    for mod, system in _builders(bw, bm):
        assert set(mod.PBS_SHA256) == set(mod.ARCHES)
        asked = []

        def fake_fetch(url, dest, sha256=""):
            asked.append((url, dest.name, sha256))
            raise Fetched()

        monkeypatch.setattr(mod, "fetch", fake_fetch)
        for arch in mod.ARCHES:
            monkeypatch.setattr(mod, "ARCH", arch)
            with pytest.raises(Fetched):
                mod.stage_python()
            name = "cpython-%s+%s-%s-install_only_stripped.tar.gz" % (
                mod.PY_VERSION, mod.PBS_TAG, mod.triple(arch))
            assert asked[-1] == (
                "https://github.com/astral-sh/python-build-standalone/releases/download/%s/%s"
                % (mod.PBS_TAG, name), name, mod.PBS_SHA256[arch]), (system, arch)
        assert len(asked) == len(mod.ARCHES), "%s fetches one file per build" % system


def test_nothing_is_fetched_from_bootstrap_or_without_a_digest():
    for name in ("build_windows.py", "build_macos.py"):
        source = (PACKAGING / name).read_text(encoding="utf-8")
        assert "get-pip" not in source and "bootstrap.pypa.io" not in source, name
        assert "python.org/ftp" not in source, name
        calls = [line for line in source.splitlines()
                 if re.search(r"\bfetch\(", line) and not line.lstrip().startswith("def fetch(")]
        assert calls, name
        for call in calls:
            assert "sha256=" in call, (name, call)


def _fake_archive(path: Path) -> str:
    """A python-build-standalone archive in miniature, every name the
    builder keeps or prunes, and its digest."""
    names = {
        "python/python.exe": b"MZ", "python/pythonw.exe": b"MZ",
        "python/python312.dll": b"MZ", "python/python3.dll": b"MZ",
        "python/vcruntime140.dll": b"MZ", "python/LICENSE.txt": b"license",
        "python/DLLs/_socket.pyd": b"MZ", "python/DLLs/_ssl.pyd": b"MZ",
        "python/DLLs/_testcapi.pyd": b"MZ", "python/DLLs/_ctypes_test.pyd": b"MZ",
        "python/DLLs/_tkinter.pyd": b"MZ", "python/DLLs/tcl86t.dll": b"MZ",
        "python/DLLs/tk86t.dll": b"MZ",
        "python/Lib/os.py": b"", "python/Lib/venv/__init__.py": b"",
        "python/Lib/ensurepip/_bundled/pip-25.0.1-py3-none-any.whl": b"PK",
        "python/Lib/tkinter/__init__.py": b"", "python/Lib/idlelib/idle.py": b"",
        "python/Lib/turtledemo/__main__.py": b"", "python/Lib/turtle.py": b"",
        "python/Lib/site-packages/README.txt": b"",
        "python/Lib/site-packages/pip/__init__.py": b"",
        "python/tcl/tcl8.6/init.tcl": b"", "python/include/Python.h": b"",
        "python/libs/python312.lib": b"", "python/Scripts/.empty": b"",
    }
    with tarfile.open(path, "w:gz") as t:
        for name, data in names.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_staged_python_reads_only_its_own_folders_and_drops_what_it_never_needs(bw, monkeypatch):
    cache = bw.DIST / "cache"
    cache.mkdir(parents=True)
    digest = _fake_archive(cache / bw.pbs_asset())
    monkeypatch.setitem(bw.PBS_SHA256, bw.ARCH, digest)
    py = bw.stage_python()
    pydir = bw.STAGE / "python"
    assert py == pydir / "python.exe"
    # The ._pth file beside the DLL is what makes Python ignore PYTHONPATH,
    # PYTHONHOME and the current folder. Its name must be the DLL's.
    pth = pydir / "python312._pth"
    assert pth.read_text(encoding="utf-8").splitlines() == [
        "DLLs", "Lib", "Lib\\site-packages", "import site"]
    assert (pydir / "Lib" / "site-packages" / "sitecustomize.py").is_file()
    for kept in ("python.exe", "python312.dll", "DLLs/_socket.pyd", "DLLs/_ssl.pyd",
                 "Lib/os.py", "Lib/site-packages/pip/__init__.py", "Scripts"):
        assert (pydir / kept).exists(), kept
    for gone in ("tcl", "include", "libs", "Lib/tkinter", "Lib/idlelib", "Lib/turtledemo",
                 "Lib/turtle.py", "Lib/ensurepip", "Lib/venv", "DLLs/_tkinter.pyd",
                 "DLLs/tcl86t.dll", "DLLs/tk86t.dll", "DLLs/_testcapi.pyd",
                 "DLLs/_ctypes_test.pyd"):
        assert not (pydir / gone).exists(), gone


def test_an_installer_upgrade_replaces_the_bundled_python_whole(bw):
    """Inno Setup copies over an install without removing anything, so an
    upgrade from the embeddable build would keep its files, and a package
    that moved down a version would leave both versions' metadata."""
    bw.DIST.mkdir(parents=True)
    iss = bw.write_inno_script().read_text(encoding="utf-8")
    section = iss.split("[InstallDelete]", 1)[1].split("\n[", 1)[0]
    entries = [line for line in section.splitlines() if line.startswith("Type:")]
    assert entries == ['Type: filesandordirs; Name: "{app}\\python"']
    assert iss.index("[InstallDelete]") < iss.index("[Files]")


def test_a_damaged_archive_is_never_unpacked(bw, monkeypatch):
    cache = bw.DIST / "cache"
    cache.mkdir(parents=True)
    _fake_archive(cache / bw.pbs_asset())
    monkeypatch.setitem(bw.PBS_SHA256, bw.ARCH, "0" * 64)
    with pytest.raises(SystemExit):
        bw.stage_python()
    assert not (bw.STAGE / "python").exists()
    assert not (cache / bw.pbs_asset()).exists(), "deleted, so the next build fetches it again"


class _Ran:
    def __init__(self, stdout="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, "", returncode


def test_the_build_refuses_a_python_that_is_not_the_one_it_names(bw, bm, monkeypatch, tmp_path):
    """Each smoke test asks the packaged Python which it is before anything
    else, and stops on any answer but PY_VERSION."""
    for mod, system in _builders(bw, bm):
        asked = []

        def run(cmd, **kw):
            asked.append(cmd)
            if "platform.python_version()" in " ".join(cmd):
                return _Ran("3.12.10\n")
            return _Ran("ok\n")

        monkeypatch.setattr(subprocess, "run", run)
        with pytest.raises(SystemExit) as stop:
            mod.smoke_test(tmp_path / "python")
        assert "3.12.10" in str(stop.value) and mod.PY_VERSION in str(stop.value), system
        assert len(asked) == 1, "%s stopped at the first question" % system
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _Ran(bw.PY_VERSION + "\n"))
    assert bw.check_python_version(tmp_path / "python", bw.PY_VERSION) == bw.PY_VERSION


# -- every package from the hashed lock ----------------------------------------

def _record_installs(bw, monkeypatch):
    ran = []

    def run(cmd, **kw):
        cmd = [str(c) for c in cmd]
        ran.append((cmd, kw.get("env")))
        if "wheel" in cmd:
            out = Path(cmd[cmd.index("-w") + 1])
            (out / "paperpull_core-0.1.6-py3-none-any.whl").write_bytes(b"PK")
        if cmd[-2:] == ["list", "--format=freeze"]:
            return _Ran("pip==26.2.1\nsetuptools==84.0.0\nplaywright==1.63.0\n")
        return _Ran()

    monkeypatch.setattr(subprocess, "run", run)
    return ran


def test_every_package_comes_from_the_lock_and_nothing_else_is_fetched(bw, monkeypatch, tmp_path):
    ran = _record_installs(bw, monkeypatch)
    py = tmp_path / "python" / "python.exe"
    lock = tmp_path / "requirements-windows-x64.txt"
    bw.install_locked(py, lock)
    assert all(cmd[0] == str(py) for cmd, _ in ran), "only the staged Python runs pip"
    installs = [cmd for cmd, _ in ran if "install" in cmd]
    first = installs[0]
    assert "--require-hashes" in first and first[first.index("-r") + 1] == str(lock)
    assert first[first.index("--only-binary") + 1] == ":all:"
    wheel = next(cmd for cmd, _ in ran if "wheel" in cmd)
    assert "--no-build-isolation" in wheel and "--no-deps" in wheel, "no build backend fetched"
    core = installs[1]
    assert "--no-deps" in core and "--no-index" in core
    assert core[-1].endswith(".whl")
    assert len(installs) == 2, "nothing installed by name"
    assert any(cmd[-1] == "check" for cmd, _ in ran)
    uninstall = next(cmd for cmd, _ in ran if "uninstall" in cmd)
    assert {"pip", "setuptools"} <= set(uninstall)


def test_a_package_set_that_does_not_fit_together_stops_the_build(bw, monkeypatch, tmp_path):
    ran = _record_installs(bw, monkeypatch)
    real = subprocess.run

    def run(cmd, **kw):
        if [str(c) for c in cmd][-1] == "check":
            return _Ran("paperpull-core 0.1.6 requires pypdf, which is not installed.\n", 1)
        return real(cmd, **kw)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(SystemExit) as stop:
        bw.install_locked(tmp_path / "python.exe", tmp_path / "lock.txt")
    assert "requires pypdf" in str(stop.value)
    assert not any("uninstall" in cmd for cmd, _ in ran)


def test_each_build_installs_its_own_systems_and_architectures_lock(bw, bm, monkeypatch, tmp_path):
    for mod, system in _builders(bw, bm):
        got = []
        monkeypatch.setattr(mod, "install_locked",
                            lambda py, lock, env=None: got.append((lock, env)))
        for arch in mod.ARCHES:
            monkeypatch.setattr(mod, "ARCH", arch)
            mod.install_packages(tmp_path / "python")
            assert got[-1][0] == PACKAGING / ("requirements-%s-%s.txt" % (system, arch))
            assert got[-1][0].is_file(), got[-1][0]
    assert got[-1][1]["PYTHONNOUSERSITE"] == "1", "the Mac build keeps the user's packages out"


# -- the locks ------------------------------------------------------------------

def _direct_pins() -> dict:
    out = {}
    for line in (PACKAGING / "requirements.in").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            m = re.fullmatch(r"([A-Za-z0-9_.-]+)(\[[^\]]+\])?==(\S+)", line)
            assert m, "every requirement is pinned to one version: %r" % line
            out[_norm(m.group(1))] = m.group(3)
    return out


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _lock_entries(text: str) -> dict:
    """{package: (version, [hashes])} from a pip requirements file with hashes."""
    out, current = {}, None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.fullmatch(r"([A-Za-z0-9_.-]+)==(\S+) \\", line)
        h = re.fullmatch(r"\s+--hash=sha256:([0-9a-f]{64})( \\)?", line)
        if m:
            current = _norm(m.group(1))
            assert current not in out, "%s twice" % current
            out[current] = (m.group(2), [])
        elif h and current:
            out[current][1].append(h.group(1))
        else:
            raise AssertionError("a line pip would read as something other than a pin: %r" % line)
    return out


def test_every_lock_pins_every_package_with_its_hashes(bw, bm, lock_tool):
    direct = _direct_pins()
    assert {"playwright", "pypdf", "fastapi", "uvicorn", "openpyxl", "pdfplumber",
            "anyio", "setuptools"} <= set(direct)
    for mod, system in _builders(bw, bm):
        for arch in mod.ARCHES:
            text = mod.lock_file(arch).read_text(encoding="utf-8")
            entries = _lock_entries(text)
            assert all(hashes for _, hashes in entries.values()), (system, arch)
            for name, version in direct.items():
                assert entries.get(name, (None,))[0] == version, (system, arch, name)
            # pypdf[crypto] brought its cryptography in, as the core asks.
            assert "cryptography" in entries and "cffi" in entries, (system, arch)
            head = text.split("\n", 4)[:4]
            assert any(mod.PY_VERSION in line for line in head), (system, arch)
            assert any(mod.triple(arch) in line for line in head), (system, arch)
            assert any(lock_tool.AS_OF in line for line in head), (system, arch)
            if system == "macos":
                assert any("macOS %s" % mod.MACOS_MIN in line for line in head), arch


def test_the_desktop_packages_and_the_server_image_pin_the_same_versions():
    server = _lock_entries("\n".join(
        line for line in (REPO / "server" / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if not line.startswith("--only-binary")))
    for name, version in _direct_pins().items():
        if name in server:
            assert server[name][0] == version, name


def test_the_lock_tool_resolves_each_lock_for_its_own_platform(bw, bm, lock_tool, monkeypatch):
    targets = lock_tool.targets()
    want = {mod.lock_file(a) for mod, _ in _builders(lock_tool.build_windows, lock_tool.build_macos)
            for a in mod.ARCHES}
    assert {t["lock"] for t in targets} == want and len(targets) == len(want)
    monkeypatch.setenv("UV_INDEX_URL", "https://example.invalid/simple")
    monkeypatch.setenv("MACOSX_DEPLOYMENT_TARGET", "15.0")
    for t in targets:
        cmd = lock_tool.command(["uv"], t)
        assert cmd[cmd.index("--python-platform") + 1] == t["platform"]
        assert cmd[cmd.index("--python-version") + 1] == bw.PY_VERSION
        assert cmd[cmd.index("--only-binary") + 1] == ":all:"
        assert cmd[cmd.index("--exclude-newer") + 1] == lock_tool.AS_OF
        assert "--generate-hashes" in cmd
        env = lock_tool.environment(t)
        assert "UV_INDEX_URL" not in env and env["UV_NO_CONFIG"] == "1"
        if t["platform"].endswith("apple-darwin"):
            assert env["MACOSX_DEPLOYMENT_TARGET"] == bm.MACOS_MIN
        else:
            assert "MACOSX_DEPLOYMENT_TARGET" not in env


def test_the_lock_tool_writes_every_lock_or_none(lock_tool, monkeypatch, tmp_path):
    targets = []
    for i, t in enumerate(lock_tool.targets()):
        t = dict(t, lock=tmp_path / ("lock-%d.txt" % i))
        t["lock"].write_text("the old lock\n", encoding="utf-8")
        targets.append(t)
    monkeypatch.setattr(lock_tool, "targets", lambda: targets)
    monkeypatch.setattr(lock_tool, "install_uv", lambda folder: ["uv"])
    answers = {t["platform"]: "x==1 \\\n    --hash=sha256:%s\n" % ("a" * 64) for t in targets}
    answers[targets[2]["platform"]] = None
    monkeypatch.setattr(lock_tool, "resolve", lambda uv, t: answers[t["platform"]])
    assert lock_tool.main([]) == 1
    assert all(t["lock"].read_text(encoding="utf-8") == "the old lock\n" for t in targets)

    answers[targets[2]["platform"]] = "x==1 \\\n    --hash=sha256:%s\n" % ("b" * 64)
    assert lock_tool.main(["--check"]) == 1, "every lock differs from what it would write"
    assert all(t["lock"].read_text(encoding="utf-8") == "the old lock\n" for t in targets)
    assert lock_tool.main([]) == 0
    assert lock_tool.main(["--check"]) == 0
    assert targets[2]["lock"].read_text(encoding="utf-8").endswith("b" * 64 + "\n")
