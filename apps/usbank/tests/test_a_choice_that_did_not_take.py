"""An account whose choice did not take is never taken as chosen after it
(review of 0.56.1).

A choice of account whose list took over REDRAW_MS to come, or whose
picker went back, was refused. The picker could then show that account
while the list still held the rows of the one before, and the next choice
of it was taken at once, because the picker showed it. On a list whose
headings name no account, a row of the same date as the one wanted was
then pressed and its statement saved as this account's. A list that came
late could also be read as the next account's. Now a choice that did not
take is noted in the page, the statements page is opened again, and an
account the picker shows is taken as chosen only on a page holding no such
note. The plain picker is chosen by the page's own label for the option,
so an option list drawn again in between cannot put another account where
the one wanted was. Everything here is invented.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import storage  # noqa: F401  binds this provider's AppSpec
import usbank_site as site
from usbank_pages import BUSINESS, CARD, CHECKING, page_html, show

# The checking account and the card each have a statement of October 13.
# Every account's years differ, so no two lists look alike.
SHARED = {
    CHECKING: {"2031": ["October 13, 2031"], "2030": ["December 13, 2030"]},
    CARD: {"2031": ["October 13, 2031", "September 9, 2031"], "2030": ["November 9, 2030"]},
    BUSINESS: {"2031": ["October 2, 2031"], "2030": ["December 2, 2030"]},
}


@pytest.fixture(autouse=True)
def short_redraw(monkeypatch):
    """A list that has not come in a second and a half has not come."""
    monkeypatch.setattr(site, "REDRAW_MS", 1500)


@pytest.fixture
def pressed(monkeypatch):
    """Whose row each press took, read off the row's own Download button,
    and nothing saved."""
    took: list = []

    def press(page, ctx, button, label, date, out_path):
        took.append(button.get_attribute("data-acct"))
        return False
    monkeypatch.setattr(site, "_press_and_capture", press)
    return took


def _download(page, tmp_path, account, date):
    out = tmp_path / "Statements" / ("%s statement.pdf" % date)
    return site.usbank_download(page, page.context, account, date, out)


def _serve(page, *pages):
    """The made-up page at the statements page's own address, as U.S.
    Bank's site, so it can be loaded again. Each load gets the next of
    `pages`, the last one from then on. The loads, in order."""
    loads: list = []

    def answer(route):
        if route.request.resource_type != "document":
            route.fulfill(status=404, body="")
            return
        html = pages[min(len(loads), len(pages) - 1)]
        loads.append(route.request.url)
        route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)
    page.route("https://onlinebanking.usbank.com/**", answer)
    page.goto(site.URLS["documents"])
    return loads


def _stuck_on_the_card(**kw):
    """The checking account on show, headings naming no account, and the
    card's list held back once it is chosen, the checking account's rows
    kept on show meanwhile."""
    return page_html(**dict(dict(statements=SHARED, chosen=CHECKING, unnamed=True,
                                 redraw="keep", held=(CARD,)), **kw))


def test_an_account_whose_choice_did_not_take_is_not_taken_as_chosen_on_its_picker(
        page, tmp_path, pressed):
    """The review's case, on a page that cannot be loaded again. The picker
    shows the card while the list holds the checking account's rows. The
    card's statement of October 13 pressed the checking account's row of
    that date, and would have saved it as the card's."""
    show(page, statements=SHARED, chosen=CHECKING, unnamed=True, redraw="keep", held=(CARD,))
    first = _download(page, tmp_path, CARD, "2031-09-09")
    assert first.step == "choose the account"
    assert site.account_name(page) == CARD
    second = _download(page, tmp_path, CARD, "2031-10-13")
    assert pressed == []
    assert second.step == "choose the account"


def test_the_page_is_opened_again_and_the_next_choice_of_the_account_takes(
        page, tmp_path, pressed):
    loads = _serve(page, _stuck_on_the_card(), _stuck_on_the_card(held=()))
    first = _download(page, tmp_path, CARD, "2031-09-09")
    assert first.step == "choose the account"
    assert len(loads) == 2
    _download(page, tmp_path, CARD, "2031-10-13")
    assert pressed == [CARD]


def test_a_list_that_comes_late_is_never_read_as_the_next_accounts(page, monkeypatch):
    """The card's list comes once the walk has given it up and chosen the
    business card, just before the business card's rows are read. Read
    then, the card's statements were listed as the business card's, and a
    download of one would press the card's row."""
    _serve(page, _stuck_on_the_card(chosen=""))
    real = site.read_rows

    def read(pg, account, *a, **kw):
        if account == BUSINESS:
            pg.evaluate("() => window.deliverHeld()")
        return real(pg, account, *a, **kw)
    monkeypatch.setattr(site, "read_rows", read)
    listed = site.usbank_collect_structured(page)
    assert sorted((r["listed_under"], r["date"]) for r in listed) == [
        (BUSINESS, "2030-12-02"), (BUSINESS, "2031-10-02"),
        (CHECKING, "2030-12-13"), (CHECKING, "2031-10-13")]


def test_an_option_list_drawn_again_before_the_choice_still_chooses_the_one_asked_for(
        page, monkeypatch):
    """The picker's options come back in another order between reading them
    and choosing. Chosen by its place, the business card was chosen for the
    card and the choice refused."""
    show(page, chosen=CHECKING)
    real = site._mark_sections

    def mark_then_move(pg):
        real(pg)
        pg.evaluate("() => { const s = document.getElementById('account-select');"
                    " s.appendChild(s.options[1]); }")
    monkeypatch.setattr(site, "_mark_sections", mark_then_move)
    assert site.select_account(page, CARD)
    assert site.account_name(page) == CARD
    assert {r["date"] for r in site.read_rows(page, CARD)} == {"2031-10-09"}


def test_a_choice_that_took_lets_the_account_on_show_be_taken_again(page):
    """After one that did not take, a choice of another account that did
    clears the note, so its next statement does not choose it again."""
    _serve(page, _stuck_on_the_card())
    assert not site.select_account(page, CARD)
    assert site.select_account(page, BUSINESS)
    page.evaluate("() => { window.changes = 0; document.getElementById('account-select')"
                  ".addEventListener('change', () => { window.changes += 1; }); }")
    assert site.select_account(page, BUSINESS)
    assert page.evaluate("() => window.changes") == 0


def test_a_page_that_will_not_open_again_takes_no_choice(page, tmp_path, pressed):
    """The card's choice did not take on a page that cannot be loaded again.
    The business card chosen after it cleared the note, and the card's list
    came then and was pressed as the business card's (review)."""
    show(page, statements=SHARED, chosen=CHECKING, unnamed=True, redraw="keep", held=(CARD,))
    assert not site.select_account(page, CARD)
    assert not site.select_account(page, BUSINESS)
    page.evaluate("() => window.deliverHeld()")
    got = _download(page, tmp_path, BUSINESS, "2031-10-13")
    assert got.step == "choose the account"
    assert pressed == []


def test_a_walk_that_does_not_look_at_the_list_leaves_the_page_to_be_opened_again(page):
    """The walk that reads the page's text when the pickers give nothing
    sets each account with no look at whether the list followed. The next
    choice, of the account it ended on included, opens the page again."""
    loads = _serve(page, page_html(statements=SHARED, chosen=CHECKING))
    site.usbank_collect(page)
    assert site._choice_unsure(page) is True
    assert site.account_name(page) == BUSINESS
    assert site.select_account(page, BUSINESS)
    assert len(loads) == 2
    assert site._choice_unsure(page) is False


def test_labels_the_page_reads_as_one_are_chosen_by_place(page):
    """Two options whose own labels differ only in their spaces. Playwright
    takes them for one when it chooses by label, and chose the first."""
    show(page, chosen=CHECKING)
    page.evaluate("() => { const o = document.getElementById('account-select').options;"
                  " o[1].label = 'Invented card'; o[2].label = 'Invented  card'; }")
    assert site.select_account(page, CARD)
    assert site.account_name(page) == CARD


def test_the_account_on_show_is_chosen_again_on_a_page_that_will_not_say(page, monkeypatch):
    """A page that will not say whether it holds the note is not taken at
    its picker's word."""
    show(page, chosen=CHECKING)
    page.evaluate("() => { window.changes = 0; document.getElementById('account-select')"
                  ".addEventListener('change', () => { window.changes += 1; }); }")
    monkeypatch.setattr(site, "_choice_unsure", lambda pg: None)
    site.select_account(page, CHECKING)
    assert page.evaluate("() => window.changes") == 1


def test_a_page_that_will_not_hold_the_note_is_not_chosen_on(page, monkeypatch):
    show(page, chosen=CHECKING)
    monkeypatch.setattr(site, "_note_choice", lambda pg, unsure: False)
    assert not site.select_account(page, CARD)
    assert site.account_name(page) == CHECKING
