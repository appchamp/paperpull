"""Every test file starts with no lists read, the way a run does.

What the lists the page loaded held is module state the download reads,
how many documents each date carried, their titles, their accounts and how
many of each title (#96). Discovery fills it, and a file whose tests run
discovery left it filled for the files after it, so a download test that
set only some of it read a count another file's lists gave its day. Each
file now starts with it empty, and a file's own discovery, one its fixture
runs once for every test, stays for that file's tests.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401,E402  binds this provider's AppSpec
import etrade_site  # noqa: E402

LISTS = ("_LISTED", "_LISTED_TITLES", "_LISTED_ACCOUNTS", "_LISTED_DOCS")


def _forget():
    for name in LISTS:
        getattr(etrade_site, name).clear()


@pytest.fixture(scope="module", autouse=True)
def no_lists_read():
    _forget()
    yield
    _forget()
