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


def _section(labels, heading="Checking statements", tail=" statement"):
    rows = "".join("<li class='download-items'><span>%s</span>"
                   "<button data-guid='b%d' aria-label='Download %s%s'>Download</button></li>"
                   % (label, i, label, tail) for i, label in enumerate(labels))
    return ("<div class='document-list'><h3 data-guid='h-%s'>%s</h3><ul>%s</ul></div>"
            % (heading.split()[0].lower(), heading, rows))


def _list(*labels, heading="Checking statements"):
    return _page(_section(labels, heading))


def _page(*sections):
    return ("<!doctype html><meta charset='utf-8'><div data-testid='list-of-statements'>%s</div>"
            % "".join(sections))


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
    (("September 1st, 2031", "September 2nd, 2031", "September 3rd, 2031",
      "September 22nd, 2031"), "September 22nd, 2031"),
    (("September 15, 2031", "September 30, 2031"), "September 15, 2031"),
], ids=["month and year only", "an ordinal day", "the exact day, as before",
        "every ordinal ending", "two days of one month"])
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


def test_a_twin_the_guard_refuses_still_stops_the_press(page):
    """Two rows read as one date whatever the guard says of either, so the
    one the guard passes is not taken as the only one."""
    page.set_content(_page(_section(["September 30, 2031"]),
                           _section(["September 30, 2031"], "Savings statements",
                                    tail=" statement and pay")))
    assert site.find_row_control(page, "2031-09-30") == (None, "")


def test_a_row_of_another_accounts_section_is_not_taken(page):
    page.set_content(_page(_section(["September 30, 2031"], "Visa Signature ...1111 statements"),
                           _section(["September 30, 2031"], "Visa Platinum ...2222 statements")))
    one = site.account_in_heading("Visa Signature ...1111 statements")
    if not one:
        pytest.skip("these headings do not read as card accounts here")
    _button, aria = site.find_row_control(page, "2031-09-30", one)
    assert aria == "Download September 30, 2031 statement"
    assert site.find_row_control(page, "2031-09-30") == (None, "")


def test_a_button_that_would_not_answer_is_never_taken_for_no_twin(page, monkeypatch):
    """The first of two twins does not answer, so the second is not pressed
    as the only one, and the list says it could not read the whole."""
    from paperpull_core.testkit import stall_reads
    page.set_content(_list("September 2031", "September 30, 2031"))
    stall_reads(monkeypatch, {"b0"}, locator=("get_attribute",))
    assert site.find_row_control(page, "2031-09-30") == (None, "")
    with pytest.raises(site.RowUnread):
        site.read_rows(page, "Checking")


def test_a_heading_that_would_not_answer_is_never_taken_for_no_section(page, monkeypatch):
    from paperpull_core.testkit import stall_reads
    page.set_content(_page(_section(["August 2031"], "Savings statements"),
                           _section(["September 30, 2031"])))
    stall_reads(monkeypatch, {"h-savings"}, locator=("inner_text",))
    assert site.find_row_control(page, "2031-09-30") == (None, "")
