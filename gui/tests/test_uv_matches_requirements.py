"""gui/pyproject.toml asks for everything the requirements.txt files do, so
`uv sync` builds the same gui/.venv that setup-all does with pip (#108).

uv makes the environment match pyproject.toml exactly, removing whatever it
does not list. An app that gains a dependency in its requirements.txt alone
would have it installed by setup-all and then taken away again by the next
`uv sync`. The reverse drift, a package only pyproject.toml asks for, would
make a uv environment pass where a pip one fails.
"""
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

REPO = Path(__file__).resolve().parents[2]
PYPROJECT = REPO / "gui" / "pyproject.toml"

# Installed from ../core rather than from a requirements.txt line.
THE_CORE = "paperpull-core"


def _floor(req: Requirement):
    """The lowest version a requirement accepts, None when it sets none."""
    floors = [Version(s.version) for s in req.specifier if s.operator in (">=", "==", "~=")]
    return max(floors, default=None)


def _requirements_files():
    return [REPO / "gui" / "requirements.txt", *sorted(REPO.glob("apps/*/requirements.txt"))]


def _asked_by_requirements():
    """{package: [(file, requirement), ...]} across every requirements.txt."""
    asked = {}
    for path in _requirements_files():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            req = Requirement(line)
            asked.setdefault(canonicalize_name(req.name), []).append((path, req))
    return asked


def _asked_by_pyproject():
    """{package: requirement} across the dependencies and every group."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    lines = list(data["project"]["dependencies"])
    for group in data.get("dependency-groups", {}).values():
        lines.extend(group)
    return {canonicalize_name(Requirement(line).name): Requirement(line) for line in lines}


def test_every_package_a_requirements_file_asks_for_is_in_pyproject():
    missing = sorted(
        f"{name} (from {path.relative_to(REPO).as_posix()})"
        for name, where in _asked_by_requirements().items()
        if name not in _asked_by_pyproject()
        for path, _ in where[:1]
    )
    assert not missing, "add these to gui/pyproject.toml: " + ", ".join(missing)


def test_every_package_in_pyproject_is_asked_for_by_a_requirements_file():
    extra = sorted(set(_asked_by_pyproject()) - set(_asked_by_requirements()) - {THE_CORE})
    assert not extra, "only gui/pyproject.toml asks for these: " + ", ".join(extra)


def test_pyproject_asks_for_at_least_the_highest_version_any_app_needs():
    """playwright>=1.44 in pyproject would let uv install a version older than
    the >=1.51 three apps ask for."""
    pyproject = _asked_by_pyproject()
    too_low = []
    for name, where in _asked_by_requirements().items():
        if name not in pyproject:
            continue
        path, highest = max(where, key=lambda pr: _floor(pr[1]) or Version("0"))
        need, have = _floor(highest), _floor(pyproject[name])
        if need and (have is None or have < need):
            too_low.append(f"{name}>={need} (from {path.relative_to(REPO).as_posix()}), "
                           f"pyproject has {pyproject[name]}")
    assert not too_low, "raise these in gui/pyproject.toml: " + "; ".join(too_low)
