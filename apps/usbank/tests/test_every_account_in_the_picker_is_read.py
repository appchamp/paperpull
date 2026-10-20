"""U.S. Bank's account picker is read whole, and the list is read under each
account it offers (#106).

The tester's account picker is a native select holding a placeholder,
"Choose an account", and the accounts. The app looked only for a button
or a combobox to open, found none, and took the picker's whole text for
the name of one account, placeholder and every account included. So a
walk read one account where the page had three, and the download never
chose the account its statement was listed under, since choosing did
nothing on a picker with no button. The page also draws its pickers and
its list a moment after it opens, and a Pilot read it before that, found
no list, and went on to read the page's text instead. Everything here is
invented.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import storage  # noqa: F401  binds this provider's AppSpec
import usbank_site as site
from usbank_pages import BUSINESS, CARD, CHECKING, PLACEHOLDER, STATEMENTS, show


def _chosen(page):
    return page.evaluate("() => { const s = document.querySelector("
                         "\"[data-testid='account-dropdown'] select\");"
                         " return s.options[s.selectedIndex].text; }")


def test_the_picker_reads_every_account_and_not_its_placeholder(page):
    show(page)
    assert list(site.account_options(page)) == [CHECKING, CARD, BUSINESS]


def test_the_account_on_show_is_the_one_chosen_not_the_whole_picker(page):
    show(page)
    assert site.account_name(page) == BUSINESS
    show(page, chosen="")
    assert site.account_name(page) == ""


def test_choosing_an_account_chooses_it_in_the_picker(page):
    show(page)
    assert site.select_account(page, CARD) is True
    assert _chosen(page) == CARD
    assert site.read_rows(page, CARD)[0]["account"] == CARD


def test_an_account_the_picker_does_not_offer_is_never_taken_as_chosen(page):
    show(page)
    assert site.select_account(page, "Other Card ...9999") is False
    assert _chosen(page) == BUSINESS


def test_options_with_no_values_are_chosen_by_their_place(page):
    """Every option's value is empty, the prompt's too, so choosing by value
    would choose the prompt."""
    show(page, blank_values=True)
    assert list(site.account_options(page)) == [CHECKING, CARD, BUSINESS]
    assert site.select_account(page, CARD) is True
    assert _chosen(page) == CARD


def test_a_picker_on_an_account_is_no_prompt_whatever_its_value(page):
    """A picker showing an account, with no list drawn yet, is waited on,
    and one showing its prompt is not, though neither option has a value."""
    picker = ("<!doctype html><meta charset='utf-8'><div data-testid='account-dropdown'>"
              "<select><option value=''>Choose an account</option>"
              "<option value=''%s>Visa Platinum ...2222</option></select></div>"
              "<div data-testid='list-of-statements'></div>")
    page.set_content(picker % " selected")
    assert site._wait_for_list(page, 1000) is False
    page.set_content(picker % "")
    assert site._wait_for_list(page, 1000) is True


def test_a_choice_the_picker_does_not_keep_is_not_taken(page, monkeypatch):
    """The picker goes back to the account before as soon as another is
    chosen, so the list is still the one before's."""
    monkeypatch.setattr(site, "REDRAW_MS", 1500)
    show(page, locked=(CARD,))
    assert site.select_account(page, CARD) is False
    assert _chosen(page) == BUSINESS


def test_a_picker_that_moves_money_is_never_read_or_set(page):
    show(page)
    page.evaluate("() => { const s = document.getElementById('account-select');"
                  " s.id = 'transfer-from-account'; }")
    assert list(site.account_options(page)) == []
    assert site.account_name(page) == ""
    assert site.select_account(page, CARD) is False
    assert _chosen(page) == BUSINESS


def test_two_accounts_of_one_name_are_neither_chosen(page):
    show(page, accounts=(CHECKING, CARD, CARD))
    assert site.select_account(page, CARD) is False
    assert _chosen(page) == PLACEHOLDER


def test_the_list_is_read_under_every_account_and_every_year(page):
    show(page)
    got = site.usbank_collect_structured(page)
    listed = sorted((r["account"], r["date"]) for r in got)
    want = sorted((acct, site.parse_date(d)) for acct, years in STATEMENTS.items()
                  for dates in years.values() for d in dates)
    assert listed == want
    for r in got:
        assert r["listed_under"] == r["account"], r
    assert got.whole is True
    assert sorted(got.years) == ["2030", "2031"]


def test_a_picker_on_its_placeholder_is_walked_too(page):
    """The picker starts on its placeholder, the list shows nothing until an
    account is chosen, and the one account it offers is still chosen."""
    show(page, accounts=(CHECKING,), chosen="")
    got = site.usbank_collect_structured(page)
    assert sorted(r["date"] for r in got) == ["2030-12-13", "2031-09-13", "2031-10-13"]


def test_a_year_picker_that_draws_after_the_list_is_waited_for(page):
    """The list and the account picker are there at once, and the year
    picker a second and a half later, as a tester's Pilot met it (#116)."""
    show(page, year_delay_ms=1500)
    got = site.usbank_collect_structured(page)
    assert len(got) == ALL
    assert sorted(got.years) == ["2030", "2031"]


def test_an_option_held_back_that_is_no_prompt_leaves_the_walk_not_whole(page):
    """The picker offers an option that names no account. Its accounts are
    read, and the walk is not taken for every account there is."""
    show(page, accounts=(CHECKING, CARD, BUSINESS, "All accounts"))
    got = site.usbank_collect_structured(page)
    assert {r["listed_under"] for r in got} == {CHECKING, CARD, BUSINESS}
    assert got.whole is False


def test_a_list_that_draws_after_its_pickers_is_waited_for(page):
    """The pickers are there at once and the list a second and a half later,
    on a picker already showing the one account, so nothing is chosen and
    no choice waits for the list."""
    show(page, accounts=(CHECKING,), chosen=CHECKING, list_delay_ms=1500)
    got = site.usbank_collect_structured(page)
    assert sorted(r["date"] for r in got) == ["2030-12-13", "2031-09-13", "2031-10-13"]


def test_a_page_that_draws_late_is_waited_for(page):
    """The pickers and the list come a second and a half after the page
    opens, as the tester's did, and are read when they come."""
    show(page, delay_ms=1500)
    got = site.usbank_collect_structured(page)
    assert {r["account"] for r in got} == {CHECKING, CARD, BUSINESS}


def test_a_list_that_redraws_late_after_a_choice_is_read_for_that_account(page):
    """The list goes blank when another account is chosen and comes back a
    second later. What is read for an account is that account's list,
    never the one before it still on the page."""
    show(page, delay_ms=1000)
    got = site.usbank_collect_structured(page)
    for r in got:
        assert r["account"] == r["listed_under"], r
    assert len(got) == sum(len(d) for y in STATEMENTS.values() for d in y.values())


ALL = sum(len(d) for y in STATEMENTS.values() for d in y.values())


def _each_under_its_own(got):
    for r in got:
        assert site._last_four(r["account"]) == site._last_four(r["listed_under"]), r


@pytest.mark.parametrize("redraw", ["keep", "overlay"])
def test_a_list_left_on_show_until_the_new_one_comes_is_waited_past(page, redraw):
    """The page keeps the old account's list on show, or draws a loading
    note over it, until the new list comes a second later."""
    show(page, redraw=redraw, delay_ms=1000)
    got = site.usbank_collect_structured(page)
    _each_under_its_own(got)
    assert len(got) == ALL
    assert got.whole is True


def test_an_old_list_that_stays_is_never_taken_for_the_new_account(page, monkeypatch):
    """The new list takes longer than the app waits, and the sections name no
    account, so nothing on the page says the list is still the old one's.
    One page a test, since a page's timers outlive set_content."""
    monkeypatch.setattr(site, "REDRAW_MS", 1000)
    show(page, redraw="keep", delay_ms=4000, unnamed=True)
    assert site._wait_for_list(page)
    assert site.select_account(page, CARD) is False


def test_a_list_that_grows_from_an_empty_one_is_taken(page, monkeypatch):
    """The account on show has nothing this year, and its sections name no
    account, so the card's list holds all of the old one's words and more."""
    monkeypatch.setattr(site, "REDRAW_MS", 3000)
    empty_now = dict(STATEMENTS, **{BUSINESS: {"2031": [], "2030": []}})
    show(page, statements=empty_now, redraw="keep", delay_ms=1000, unnamed=True)
    assert site._wait_for_list(page)
    assert site.select_account(page, CARD) is True
    assert [r["date"] for r in site.read_rows(page, CARD)] == ["2031-10-09"]


def test_a_walk_never_reads_an_old_list_that_stays_as_the_new_accounts(page, monkeypatch):
    monkeypatch.setattr(site, "REDRAW_MS", 1000)
    show(page, redraw="keep", delay_ms=4000, unnamed=True)
    got = site.usbank_collect_structured(page)
    assert got.whole is False
    own = {acct: {site.parse_date(d) for dates in years.values() for d in dates}
           for acct, years in STATEMENTS.items()}
    for r in got:
        assert r["date"] in own[r["listed_under"]], r


def test_a_section_of_another_account_on_show_is_read_under_its_own(page):
    """The business card's section is drawn under every account chosen. A
    list showing another account's section is not the chosen account's
    alone, so no year judges a record."""
    show(page, also=BUSINESS)
    got = site.usbank_collect_structured(page)
    _each_under_its_own(got)
    assert len(got) == ALL
    assert got.years == () and got.whole is False


def test_a_heading_naming_the_account_another_way_is_the_same_account(page):
    show(page, names={CARD: "Visa Platinum Card ...2222"})
    got = site.usbank_collect_structured(page)
    card = [r for r in got if r["listed_under"] == CARD]
    assert sorted(r["date"] for r in card) == ["2030-11-09", "2031-10-09"]
    assert {r["account"] for r in card} == {"Visa Platinum Card ...2222"}
    assert got.whole is True


def test_a_year_the_picker_did_not_take_is_not_read_as_drawn(page):
    """The 2029 choice does not take, so the empty 2030 list is still on show
    when 2029 is read."""
    years = {"2031": ["October 13, 2031"], "2030": [], "2029": ["December 13, 2029"]}
    show(page, accounts=(CHECKING,), chosen=CHECKING, statements={CHECKING: years},
         stuck=("2029",))
    got = site.usbank_collect_structured(page)
    assert [r["date"] for r in got] == ["2031-10-13"]
    assert got.years == ("2030", "2031")


@pytest.mark.parametrize("html, year", [
    ("<div data-testid='year-filter'>Statement year2031</div>", "2031"),
    ("<div data-testid='year-filter'>Statement year 2031</div>", "2031"),
    ("<div data-testid='year-filter'>2031 2030</div>", ""),
    ("<div data-testid='year-filter'>Statement year</div>", ""),
], ids=["run together", "spaced", "two years", "none"])
def test_the_year_on_show_is_read_from_the_filter_when_the_picker_shows_none(page, html, year):
    page.set_content("<!doctype html><meta charset='utf-8'>" + html)
    assert site._year_on_show(page) == year


def test_a_year_with_a_statement_it_could_not_date_is_not_read_as_drawn(page):
    odd = dict(STATEMENTS, **{CHECKING: {"2031": ["October 13, 2031", "the latest"],
                                         "2030": ["December 13, 2030"]}})
    show(page, statements=odd)
    got = site.usbank_collect_structured(page)
    assert got.years == ("2030",)


def test_a_picker_with_a_button_judges_no_record(page):
    """A picker opened by a button reads back no choice and waits for no
    list, so a walk of it is never whole."""
    page.set_content("""<!doctype html><meta charset='utf-8'><body>
      <div data-testid="account-dropdown">
        <button aria-expanded="false" aria-label="Choose a card"
                onclick="document.getElementById('cards').hidden = false">
          Account Visa Platinum ...2222</button>
        <ul id="cards" role="listbox" hidden>
          <li role="option">Visa Platinum ...2222</li><li role="option">Business Card ...3333</li>
        </ul></div></body>""")
    got = site.account_options(page)
    assert list(got) == [CARD, BUSINESS]
    assert got.whole is False


def test_a_heading_that_follows_the_picker_before_its_rows_is_not_their_account(page):
    """The headings name the new account at once, and the rows under them
    are the old account's for two seconds more."""
    show(page, redraw="heading", delay_ms=2000)
    got = site.usbank_collect_structured(page)
    own = {acct: {site.parse_date(d) for dates in years.values() for d in dates}
           for acct, years in STATEMENTS.items()}
    for r in got:
        assert r["date"] in own[r["listed_under"]], r
    assert len(got) == ALL


def test_a_list_that_showed_nothing_is_no_old_list_to_wait_past(page, monkeypatch):
    """The account on show has no statement this year, and the page says so
    in a note with no section, as it does for the card."""
    nothing_now = dict(STATEMENTS, **{BUSINESS: {"2031": [], "2030": []},
                                      CARD: {"2031": [], "2030": ["November 9, 2030"]}})
    monkeypatch.setattr(site, "REDRAW_MS", 1000)
    show(page, statements=nothing_now, bare_empty=True)
    assert site._wait_for_list(page, 1000) is False
    assert site.select_account(page, CARD) is True


def test_the_year_picker_is_never_read_as_a_statement(page):
    """The list is on the page with no section in it, still drawing. The
    year picker's button names a year, and a notice above the list names a
    statement's day. Neither is a row of the list."""
    page.set_content("<!doctype html><meta charset='utf-8'><main data-testid='document-view'>"
                     "<p>Your statement is ready. <a href='#' aria-label='View October 13, "
                     "2031 statement'>View</a></p>"
                     "<div data-testid='year-filter'><button id='exp_button_year-filter-select'>"
                     "Statement year 2031</button></div>"
                     "<div data-testid='list-of-statements'></div></main>")
    assert site.read_rows(page, CARD) == []


def test_an_empty_list_is_read_again_before_it_is_taken_as_empty(monkeypatch):
    """The first read of a year finds the list empty while it loads, and the
    second finds its statement."""
    row = {"documentId": "", "date": "2031-10-09", "title": "Statement", "account": CARD,
           "kind": "statement", "occurrence": 0, "ambiguous": False}
    reads = [site._read([], drawn=True, heads=(CARD,)), site._read([row], drawn=True, heads=(CARD,))]

    class Page:
        def wait_for_timeout(self, ms):
            pass

    monkeypatch.setattr(site, "ensure_statements", lambda pg: True)
    monkeypatch.setattr(site, "_wait_for_list", lambda pg, ms=None: True)
    monkeypatch.setattr(site, "account_options", lambda pg: site._read([CARD], whole=True))
    monkeypatch.setattr(site, "period_options", lambda pg: ["2031"])
    monkeypatch.setattr(site, "select_period", lambda pg, y: True)
    monkeypatch.setattr(site, "_year_on_show", lambda pg: "2031")
    monkeypatch.setattr(site, "download_controls_shown", lambda pg: 0)
    monkeypatch.setattr(site, "read_rows", lambda pg, acct: reads.pop(0))
    got = site.usbank_collect_structured(Page())
    assert [r["date"] for r in got] == ["2031-10-09"]


def test_a_heading_whose_digits_are_no_offered_account_is_kept_unjudged(page):
    """The card's section names last four digits the picker shows for no
    account. Its rows are the card's, and its years judge nothing."""
    show(page, names={CARD: "Visa Platinum ...9999"})
    got = site.usbank_collect_structured(page)
    assert sorted(r["date"] for r in got if r["listed_under"] == CARD) == ["2030-11-09",
                                                                          "2031-10-09"]
    assert got.whole is False


def test_another_account_is_one_the_picker_offers():
    offered = [CHECKING, CARD, BUSINESS]
    assert site._another_account(BUSINESS, CARD, offered)
    assert not site._another_account("Visa Platinum ...9999", CARD, offered)
    assert not site._another_account("Visa Platinum Card ...2222", CARD, offered)
    assert not site._another_account("Statements", CARD, offered)


def test_a_walk_that_could_not_choose_an_account_is_not_whole(page, monkeypatch):
    show(page)
    real = site.select_account
    monkeypatch.setattr(site, "select_account",
                        lambda pg, label: False if label == CARD else real(pg, label))
    got = site.usbank_collect_structured(page)
    assert CARD not in {r["account"] for r in got}
    assert got.whole is False


def test_the_page_text_reading_never_walks_the_placeholder(page):
    show(page)
    _sel, accounts = site.account_select(page)
    assert PLACEHOLDER not in accounts
    assert accounts == [CHECKING, CARD, BUSINESS]


@pytest.mark.parametrize("label", ["Select an account", "Choose an account", "-- Pick one --"])
def test_a_placeholder_is_never_an_account(label):
    assert not site.is_card_control(label)
