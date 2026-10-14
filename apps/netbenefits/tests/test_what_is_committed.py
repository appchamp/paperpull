"""What this app's own files say, and what of a run is never committed.

The repository is public. A plan list a run keeps holds the site's own plan
and employer numbers in its addresses, so git ignores it wherever a run
writes it, and the account named in this app's README is invented, as the
tests' plans are."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
REPO = APP.parents[1]

# The employers and plans the tests and the README invent.
INVENTED = {"ABC", "North-Star Medical Group", "Lakeside College of Arts"}


def test_the_readmes_live_run_names_only_invented_employers():
    text = re.sub(r"\s+", " ", (APP / "README.md").read_text(encoding="utf-8"))
    found = re.search(r"saved 39 combined (.+?) statements and 39 (.+?) statements", text)
    assert found, "the README no longer says what the live run saved"
    assert set(found.groups()) <= INVENTED, found.groups()


@pytest.mark.skipif(shutil.which("git") is None or not (REPO / ".git").exists(),
                    reason="not a git checkout")
@pytest.mark.parametrize("name", ["plans.json", "plans.json.bak", "plans.json.pre-fix",
                                  "out/plans.json"])
def test_a_kept_plan_list_is_never_committed(name):
    path = (APP / name).relative_to(REPO).as_posix()
    said = subprocess.run(["git", "check-ignore", "-q", "--no-index", path], cwd=REPO)
    assert said.returncode == 0, "%s is not ignored" % path
