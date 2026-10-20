"""A run presses only statements its own list read, and a list read whole
puts aside what it no longer shows (#106).

A tester's Pilot read the page's text when the pickers came late, and made
three records out of chunks of the page, its header, a whole account's
section and a section holding two statements, dated with a date of some
other row. Each found no row to press. Run All then read the pickers fine
and still pressed those same three again, since a run took every record
ever listed, and every run after it did the same and wrote the same three
rows into the Document Index again. Now Pilot and Run All press only what
the run's own list read, and a list read whole through every account and
year marks a record it no longer shows No Longer Listed, so Resume leaves
it too. When the pickers read nothing while the page shows statements to
download, the run stops with a failure file rather than read the page's
text. Driven through the app's own commands, against a made-up page in a
real browser. Everything here is invented.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import storage  # noqa: F401  binds this provider's AppSpec
import usbank_docs
import usbank_site as site
from paperpull_core import listing
from paperpull_core.models import State
from paperpull_core.testkit import sample_pdf
from usbank_pages import BUSINESS, CARD, CHECKING, STATEMENTS, show

# The three records the page's text made, shaped as the tester described
# them. A header, a whole account's section with its one date taken out of
# the title, and a section holding two statements dated with the other's
# date.
BOGUS = [
    {"title": "MY DOCUMENTS Statements All documents will open as PDFs. Account "
              "Choose an account %s %s" % (CHECKING, CARD),
     "account": CHECKING, "date": "2031-10-13"},
    {"title": "%s statements View Download" % CHECKING, "account": CHECKING,
     "date": "2031-10-13"},
    {"title": "%s statements January 12, 2031 View Download" % CARD, "account": CARD,
     "date": "2031-10-09"},
]

# Every statement the page lists, as a press is asked for it. A record the
# page's text made carries a chunk of the page for its title, so it is told
# apart from the statement of the same day by that.
LISTED = sorted((acct, site.parse_date(d), "Statement") for acct, years in STATEMENTS.items()
                for dates in years.values() for d in dates)


# Records the pickers made in an earlier run, of statements still listed
# under an account this run's walk may not read.
PICKERS_OWN = [{"title": "Statement", "account": CARD, "date": "2031-10-09"},
               {"title": "Statement", "account": CARD, "date": "2030-11-09"}]


@pytest.fixture
def make_app(tmp_path, monkeypatch):
    pressed = []

    def press(_page, _ctx, account, date, *_a, title="", **_kw):
        pressed.append((account, date, title))
        return False

    def build(pg, *argv, start=""):
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({
            "owner": "Test Person", "output_dir": str(tmp_path / "out"),
            "profile_dir": str(tmp_path / "profile"), "cdp_url": "",
            "document_types": ["Statement"], "default_start_date": start,
            "min_pdf_bytes": 2000, "max_path_length": 240,
            "delay_min_seconds": 0, "delay_max_seconds": 0, "pilot_count": 5}),
            encoding="utf-8")
        args = usbank_docs.build_parser().parse_args(["--config", str(cfg), "--yes", *argv])
        app = usbank_docs.App(args)
        app._work_page = pg
        monkeypatch.setattr(app, "page", lambda: pg)
        monkeypatch.setattr(app, "_on_its_site", lambda: pg)
        monkeypatch.setattr(app, "check_session", lambda *_a, **_kw: None)
        return app

    monkeypatch.setattr(site, "usbank_download", press)
    build.pressed = pressed
    return build


def _seed(app, records, state=State.NEEDS_MANUAL_REVIEW, **more):
    """Records an earlier version's run left, in the state it left them. That
    version kept no label a statement was read under."""
    keys = []
    for r in records:
        app._record_usbank_doc(dict(r))
        doc = next(usbank_docs.Document.from_dict(v) for v in app.discovery.data.values()
                   if v["title"] == r["title"] and v["date"] == r["date"])
        for k, v in more.items():
            setattr(doc, k, v)
        app._record(doc, state, notes="from an earlier run")
        keys.append(doc.key)
    for key in keys:
        for store in (app.discovery, app.progress):
            (store.data.get(key) or {}).pop("listed_under", None)
    app.discovery.save()
    app.progress.save()
    return keys


def _states(app, keys):
    return [(app.progress.get(k) or {}).get("state") or app.discovery.get(k)["state"]
            for k in keys]


def test_run_all_presses_only_statements_its_own_list_read(page, make_app):
    show(page)
    seeded = make_app(page)
    _seed(seeded, BOGUS)
    app = make_app(page, "--all")
    app.cmd_run("all")
    assert sorted(make_app.pressed) == LISTED


def test_a_pilot_presses_only_statements_its_own_list_read(page, make_app):
    show(page)
    _seed(make_app(page), BOGUS)
    app = make_app(page, "--pilot")
    app.cmd_pilot()
    pressed = make_app.pressed
    assert len(pressed) == 5
    assert set(pressed) <= set(LISTED)


def test_a_list_read_whole_puts_aside_what_it_no_longer_shows(page, make_app):
    show(page)
    keys = _seed(make_app(page), BOGUS)
    app = make_app(page, "--discover")
    app.cmd_discover()
    assert _states(app, keys) == [State.NO_LONGER_LISTED.value] * 3
    listed = [k for k in app.discovery.data if k not in keys]
    assert len(listed) == len(LISTED)
    assert set(_states(app, listed)) == {State.DISCOVERED.value}
    assert listing.last(app) == listing.COMPLETE


def test_resume_after_such_a_list_leaves_what_it_put_aside(page, make_app, tmp_path):
    show(page)
    _seed(make_app(page), BOGUS)
    make_app(page, "--discover").cmd_discover()
    index_csv = tmp_path / "out" / "U.S. Bank Document Index.csv"
    rows_before = index_csv.read_text(encoding="utf-8") if index_csv.exists() else ""
    make_app(page, "--resume").cmd_resume()
    assert sorted(make_app.pressed) == LISTED
    index = index_csv.read_text(encoding="utf-8")
    for bogus in BOGUS:
        assert index.count(bogus["title"][:30]) == rows_before.count(bogus["title"][:30])


def test_a_saved_statement_is_never_put_aside(page, make_app, tmp_path):
    show(page)
    saved = tmp_path / "out" / "Statements" / "2031-08-13 saved.pdf"
    saved.parent.mkdir(parents=True, exist_ok=True)
    saved.write_bytes(sample_pdf())
    old = {"title": "Statement", "account": CHECKING, "date": "2031-08-13"}
    keys = _seed(make_app(page), [old], State.COMPLETED, downloaded_ok=True,
                 pdf_path=str(saved))
    kept = _seed(make_app(page), [dict(old, date="2031-07-13")], State.NEEDS_MANUAL_REVIEW,
                 pdf_path=str(saved))
    app = make_app(page, "--discover")
    app.cmd_discover()
    assert _states(app, keys) == [State.COMPLETED.value]
    assert _states(app, kept) == [State.NEEDS_MANUAL_REVIEW.value]
    assert saved.exists()


def test_a_year_the_pickers_do_not_offer_is_not_judged(page, make_app):
    show(page)
    keys = _seed(make_app(page), [{"title": "Statement", "account": CARD, "date": "2029-11-09"}])
    app = make_app(page, "--discover")
    app.cmd_discover()
    assert _states(app, keys) == [State.NEEDS_MANUAL_REVIEW.value]


def test_a_scoped_list_judges_only_its_own_part(page, make_app):
    show(page)
    keys = _seed(make_app(page), BOGUS + [{"title": "Statement", "account": CARD,
                                           "date": "2030-06-09"}])
    app = make_app(page, "--discover", "--year", "2031")
    app.cmd_discover()
    assert _states(app, keys) == [State.NO_LONGER_LISTED.value] * 3 + \
        [State.NEEDS_MANUAL_REVIEW.value]


def test_a_record_before_the_start_date_is_not_judged(page, make_app):
    show(page)
    keys = _seed(make_app(page), [{"title": "Older statements chunk", "account": CARD,
                                   "date": "2031-02-09"}])
    app = make_app(page, "--discover", start="2031-09-01")
    app.cmd_discover()
    assert _states(app, keys) == [State.NEEDS_MANUAL_REVIEW.value]


def test_a_list_that_could_not_choose_an_account_puts_nothing_aside(page, make_app, monkeypatch):
    show(page)
    keys = _seed(make_app(page), PICKERS_OWN)
    real = site.select_account
    monkeypatch.setattr(site, "select_account",
                        lambda pg, label: False if label == CARD else real(pg, label))
    app = make_app(page, "--discover")
    app.cmd_discover()
    assert _states(app, keys) == [State.NEEDS_MANUAL_REVIEW.value] * 2


def test_records_of_the_page_text_are_put_aside_by_a_walk_not_whole(page, make_app, monkeypatch):
    """The pickers never make a record titled with a chunk of the page, so a
    walk that read statements puts those aside though it could not choose
    the card (#117). Resume then never presses one, where one of the
    tester's had saved a statement a second time under a (2) name."""
    show(page)
    keys = _seed(make_app(page), BOGUS)
    real = site.select_account
    monkeypatch.setattr(site, "select_account",
                        lambda pg, label: False if label == CARD else real(pg, label))
    app = make_app(page, "--discover")
    app.cmd_discover()
    assert _states(app, keys) == [State.NO_LONGER_LISTED.value] * 3
    make_app(page, "--resume").cmd_resume()
    assert sorted(make_app.pressed) == [r for r in LISTED if r[0] != CARD]


def test_a_run_whose_list_was_not_whole_still_presses_only_what_it_read(
        page, make_app, monkeypatch):
    """Nothing the pickers made is put aside by a list that could not choose
    the card, and the run still never presses the card's records, which
    this run's list did not read."""
    show(page)
    _seed(make_app(page), PICKERS_OWN)
    real = site.select_account
    monkeypatch.setattr(site, "select_account",
                        lambda pg, label: False if label == CARD else real(pg, label))
    make_app(page, "--all").cmd_run("all")
    assert sorted(make_app.pressed) == [r for r in LISTED if r[0] != CARD]


def test_discover_says_when_an_account_could_not_be_chosen(page, make_app, monkeypatch,
                                                          capsys):
    show(page)
    real = site.select_account
    monkeypatch.setattr(site, "select_account",
                        lambda pg, label: False if label == CARD else real(pg, label))
    make_app(page, "--discover").cmd_discover()
    assert "1 account(s) in U.S. Bank's account picker could not be chosen" in capsys.readouterr().out


def test_resume_leaves_a_statement_a_later_list_no_longer_showed(page, make_app):
    """The card's October statement was listed by this version, and a later
    list read whole no longer shows it."""
    show(page)
    make_app(page, "--discover").cmd_discover()
    show(page, statements=dict(STATEMENTS, **{CARD: {"2031": [], "2030": ["November 9, 2030"]}}))
    app = make_app(page, "--discover")
    app.cmd_discover()
    gone = [k for k, v in app.discovery.data.items() if v["date"] == "2031-10-09"]
    assert _states(app, gone) == [State.NO_LONGER_LISTED.value]
    make_app(page, "--resume").cmd_resume()
    assert sorted(make_app.pressed) == [r for r in LISTED if r[1] != "2031-10-09"]


def test_a_list_that_read_nothing_puts_nothing_aside(page, make_app):
    """Every account and year drew its list and none held a statement, so
    the page's text was read in its place, and nothing is judged by it."""
    empty = {acct: {"2031": [], "2030": []} for acct in STATEMENTS}
    show(page, statements=empty)
    keys = _seed(make_app(page), [{"title": "Statement", "account": CARD, "date": "2031-10-09"}],
                 State.DISCOVERED)
    app = make_app(page, "--discover")
    app.cmd_discover()
    assert _states(app, keys) == [State.DISCOVERED.value]


def test_a_statement_listed_again_keeps_the_label_it_was_read_under(page, make_app):
    show(page)
    keys = _seed(make_app(page), [{"title": "Statement", "account": CARD, "date": "2031-10-09"}],
                 State.DISCOVERED)
    assert "listed_under" not in make_app(page).discovery.get(keys[0])
    app = make_app(page, "--discover")
    app.cmd_discover()
    assert app.discovery.get(keys[0])["listed_under"] == CARD


def test_a_list_that_never_drew_for_an_account_puts_nothing_aside(page, make_app, monkeypatch):
    """A list that never came is not a list with nothing in it, so the walk
    is not whole and nothing is judged by it."""
    monkeypatch.setattr(site, "REDRAW_MS", 1500)
    show(page, never=(CARD,))
    keys = _seed(make_app(page), PICKERS_OWN)
    app = make_app(page, "--discover")
    app.cmd_discover()
    assert _states(app, keys) == [State.NEEDS_MANUAL_REVIEW.value] * 2


def test_a_statement_put_aside_and_listed_again_is_taken_again(page, make_app):
    show(page, statements=dict(STATEMENTS, **{CARD: {"2031": [], "2030": ["November 9, 2030"]}}))
    real = {"title": "Statement", "account": CARD, "date": "2031-10-09"}
    keys = _seed(make_app(page), [real], State.DISCOVERED)
    make_app(page, "--discover").cmd_discover()
    assert _states(make_app(page), keys) == [State.NO_LONGER_LISTED.value]
    show(page)
    app = make_app(page, "--all")
    app.cmd_run("all")
    assert (CARD, "2031-10-09", "Statement") in make_app.pressed
    assert _states(app, keys) != [State.NO_LONGER_LISTED.value]


def test_statements_the_pickers_cannot_read_stop_the_run_rather_than_the_page_text(
        page, make_app, monkeypatch, tmp_path):
    """The list's sections are headed in words the app does not take for a
    statements section, so the pickers read nothing while the page shows a
    Download button for every statement."""
    show(page, heading=" statement history")

    def page_text(_pg):
        raise AssertionError("the page's text was read")

    monkeypatch.setattr(site, "usbank_collect", page_text)
    app = make_app(page, "--pilot")
    with pytest.raises(SystemExit):
        app.cmd_pilot()
    assert app.discovery.data == {}
    assert make_app.pressed == []
    assert listing.last(app) == listing.STOPPED
    files = list((tmp_path / "out" / "Diagnostics").glob("failure-*.json"))
    assert len(files) == 1
    report = json.loads(files[0].read_text(encoding="utf-8"))
    assert report["step"] == "read the statement list"
    assert report["reason"] == "the pickers read no statement the page shows"
    assert report["extra"]["listing"]["download_controls"] > 0
