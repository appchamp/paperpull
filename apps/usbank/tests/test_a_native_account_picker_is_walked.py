"""An account picker drawn as a plain <select> is walked like the other (#106).

The list and the download looked in the account dropdown for a button that
opens a menu. A tester's page draws the picker as a plain <select>, so the
list took the text of every option run together for one account and read
only the account on show, and the download, finding no button, took the
account it was asked for as chosen without choosing it, and looked for that
account's statements under another account's heading. Every statement of
every other account then stopped with no Download control. Everything here
is invented.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import usbank_site as site

ACCOUNTS = {
    "Checking ...1111": ["October 13, 2031"],
    "Visa ...2222": ["October 9, 2031", "January 12, 2031"],
    "Business Visa ...3333": ["October 6, 2031", "September 4, 2031"],
}


def _section(account, labels):
    rows = "".join("<li class='download-items'><span>%s</span>"
                   "<button aria-label='Download %s statement'>Download</button></li>"
                   % (label, label) for label in labels)
    return ("<div class='document-list'><h3>%s statements</h3><ul>%s</ul></div>"
            % (account, rows))


def _page(shown="Business Visa ...3333"):
    options = "<option value=''>Choose an account</option>" + "".join(
        "<option value='a%d'%s>%s</option>" % (i, " selected" if a == shown else "", a)
        for i, a in enumerate(ACCOUNTS))
    sections = {"a%d" % i: _section(a, labels)
                for i, (a, labels) in enumerate(ACCOUNTS.items())}
    return ("<!doctype html><meta charset='utf-8'>"
            "<div data-testid='account-dropdown'><label for='acct'>Account</label>"
            "<select id='acct'>%s</select></div>"
            "<div data-testid='list-of-statements'></div>"
            "<script>const S = %s; const sel = document.getElementById('acct');"
            "function draw() { document.querySelector(\"[data-testid='list-of-statements']\")"
            ".innerHTML = S[sel.value] || ''; }"
            "sel.addEventListener('change', draw); draw();</script>"
            % (options, __import__("json").dumps(sections)))


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
def page(browser, monkeypatch):
    # The page answers at once, so the waits made for the real site are not.
    monkeypatch.setattr(site, "dismiss_timeout", lambda page: None)
    pg = browser.new_page()
    pg.set_content(_page())
    yield pg
    pg.close()


def test_each_account_of_a_plain_picker_is_one_option(page):
    assert site.account_options(page) == list(ACCOUNTS)


def test_the_account_on_show_is_the_one_chosen_not_every_option(page):
    assert site.account_name(page) == "Business Visa ...3333"


def test_choosing_an_account_shows_its_statements(page):
    assert site.select_account(page, "Visa ...2222")
    assert site.account_name(page) == "Visa ...2222"
    assert {r["date"] for r in site.read_rows(page, "Visa ...2222")} == {
        "2031-10-09", "2031-01-12"}


def test_the_list_reads_every_account(page):
    listed = {(r["account"], r["date"]) for r in site.usbank_collect_structured(page)}
    assert listed == {
        ("Checking ...1111", "2031-10-13"),
        ("Visa ...2222", "2031-10-09"), ("Visa ...2222", "2031-01-12"),
        ("Business Visa ...3333", "2031-10-06"), ("Business Visa ...3333", "2031-09-04"),
    }


def test_a_statement_of_an_account_not_on_show_is_found_to_press(page):
    assert site.select_account(page, "Checking ...1111")
    _button, aria = site.find_row_control(page, "2031-10-13", "Checking ...1111")
    assert aria == "Download October 13, 2031 statement"


def test_an_account_the_picker_does_not_offer_is_not_taken_as_chosen(page):
    assert not site.select_account(page, "Savings ...4444")
    assert site.account_name(page) == "Business Visa ...3333"


@pytest.mark.parametrize("label, wanted", [
    ("Visa ...2222", 1),
    ("  Visa   ...2222 ", 1),
    ("Visa ...3333", -1),
    ("Visa", -1),
], ids=["the whole label", "spaces aside", "a part of another's label", "a name alone"])
def test_only_the_whole_label_is_the_account(label, wanted):
    assert site._option_index(["Choose an account", "Visa ...2222",
                               "Business Visa ...3333"], label) == wanted


def test_two_options_of_one_label_are_neither_chosen():
    assert site._option_index(["Visa ...2222", "Visa ...2222"], "Visa ...2222") == -1


def test_a_picker_that_reads_as_a_money_control_is_never_set(page):
    page.set_content(_page().replace("<label for='acct'>Account</label>",
                                     "<label for='acct'>Transfer from account</label>"))
    site.select_account(page, "Visa ...2222")
    assert page.locator("#acct").input_value() == "a2"
