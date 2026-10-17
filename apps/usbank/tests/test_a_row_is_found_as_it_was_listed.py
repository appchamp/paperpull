"""The download finds a statement's row the way the list read it (#106).

The list takes a statement's date from its Download button's label with
parse_period_date, which also reads a month and a year alone. The download
looked for the row again with a pattern of its own that wanted the exact
day, so on a page whose labels name only the month, or write the day as
"15th", every statement listed was then not found, and a tester's Pilot
stopped on the first one before any press, with every part of the list on
the page. Now the row is read the same way both times. Everything here is
invented.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import usbank_site as site


def _list(*labels, heading="Checking statements"):
    rows = "".join("<li class='download-items'><span>%s</span>"
                   "<button aria-label='Download %s statement'>Download</button></li>"
                   % (label, label) for label in labels)
    return ("<!doctype html><meta charset='utf-8'><div data-testid='list-of-statements'>"
            "<div class='document-list'><h3>%s</h3><ul>%s</ul></div></div>" % (heading, rows))


@pytest.fixture(scope="module")
def browser():
    pw = pytest.importorskip("playwright.sync_api")
    driver = pw.sync_playwright().start()
    try:
        b = driver.chromium.launch(headless=True)
    except Exception as e:                       # no browser on this machine
        driver.stop()
        pytest.skip("no browser to drive: %s" % e)
    yield b
    b.close()
    driver.stop()


@pytest.fixture
def page(browser):
    pg = browser.new_page()
    yield pg
    pg.close()


@pytest.mark.parametrize("labels, wanted", [
    (("September 2031", "August 2031"), "September 2031"),
    (("September 15th, 2031", "August 15th, 2031"), "August 15th, 2031"),
    (("Sep 30, 2031", "Aug 31, 2031"), "Aug 31, 2031"),
], ids=["month and year only", "an ordinal day", "the exact day, as before"])
def test_every_row_the_list_read_is_found_again(page, labels, wanted):
    page.set_content(_list(*labels))
    listed = {r["date"]: r for r in site.read_rows(page, "Checking")}
    assert len(listed) == len(labels)
    for date in listed:
        button, aria = site.find_row_control(page, date)
        assert button is not None, (date, labels)
    date = site.row_date("Download %s statement" % wanted)
    _button, aria = site.find_row_control(page, date)
    assert aria == "Download %s statement" % wanted


def test_two_rows_read_as_one_date_are_neither_pressed(page):
    page.set_content(_list("September 2031", "September 30, 2031"))
    assert site.find_row_control(page, "2031-09-30") == (None, "")


def test_a_date_no_row_reads_as_finds_nothing(page):
    page.set_content(_list("September 2031"))
    assert site.find_row_control(page, "2031-08-31") == (None, "")
