"""Each account's statement is listed, kept, named and taken as its own (#96).

An E*TRADE sign-in can hold several accounts, and the documents list shows
each document's account in a column of its own. The list's own
answer, searchItems, carries it as displayMultipleAccounts. Discovery read
it, put it through the redaction meant for diagnostic files, which turns a
masked "...1234" into "...####", and then dropped it, so no record, file
name or index row said which account a statement was from. Two accounts'
statements of one title and day were one document, and of two rows naming
it the download refused both, or took whichever one the page showed.

Now the label is kept whole in the record, the key holds the masked digits
it ends with, a sign-in of several accounts puts the label in the file name
and the index's Document Summary, and the download takes only the link
naming its own account, by its masked tail. For a sign-in of one account,
records kept before move to the key the account gives them, so nothing
saved is fetched again and every name stays. With several, the list alone
cannot tell which account a record kept before holds, so its saved PDF is
read, and the record moves to its account only when the file shows that
account's digits as an account number and no other listed account's digits
at all. Anything else stays as it is, and each account's statement of it
is taken again under a name that says the account.

Everything here is invented.
"""
import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import etrade_docs
import etrade_site as site
from paperpull_core import doc_types, naming, pressing, receipt_pdf, renaming, testkit
from paperpull_core import storage as core_storage
from paperpull_core.models import State

DAY = "2025-08-31"
SHORT = "08/31/25"
BROKERAGE = "Brokerage Statement"
RETIREMENT = "Retirement Statement"
FIRST = "Invented Brokerage -1111"
SECOND = "Invented Roth IRA -2222"


def _entry(title, account, guid, day=DAY):
    return {"documentGuid": guid, "documentId": "id-" + guid, "documentTypeName": "STATEMENTS",
            "documentTitle": title, "documentDate": day + "T00:00:00.000Z",
            "displayMultipleAccounts": account}


def _raw(title, account, guid, day=DAY):
    raw = site.RawDoc(title=title, account=account, date_text=day, kind="statement")
    raw.guid = "%s|id-%s" % (guid, guid)
    return raw


# --- usermetadata account map (#96) ---------------------------------------------

KEY1 = "1111-11-11-11.11.11.111111"
KEY2 = "2222-22-22-22.22.22.222222"
METADATA_BODY = {
    "accountList": [
        {"keyAccount": KEY1, "accountDisplayValue": FIRST},
        {"keyAccount": KEY2, "accountDisplayValue": SECOND},
        {"keyAccount": "9999-xx", "accountDisplayValue": "Closed Account - 9999"},
    ]
}


def test_accounts_from_metadata_returns_key_to_label_map():
    """Each accountList entry's keyAccount maps to its accountDisplayValue."""
    result = site._accounts_from_metadata(METADATA_BODY)
    assert result == {
        KEY1: FIRST,
        KEY2: SECOND,
        "9999-xx": "Closed Account - 9999",
    }


def test_accounts_from_metadata_tolerates_bad_input():
    assert site._accounts_from_metadata(None) == {}
    assert site._accounts_from_metadata({}) == {}
    assert site._accounts_from_metadata({"accountList": "not a list"}) == {}
    assert site._accounts_from_metadata({"accountList": [None, 42, {}]}) == {}
    # Entry with empty key or empty label is skipped.
    assert site._accounts_from_metadata({"accountList": [
        {"keyAccount": "", "accountDisplayValue": FIRST},
        {"keyAccount": KEY1, "accountDisplayValue": ""},
    ]}) == {}


def _entry_with_key(title, key_account_no, display_multiple="", guid="g1"):
    """A searchItems entry carrying keyAccountNo."""
    e = _entry(title, display_multiple, guid)
    e["keyAccountNo"] = key_account_no
    return e


def test_docs_from_api_uses_key_account_no_when_account_map_is_loaded(monkeypatch):
    """When _ACCOUNT_MAP is loaded from usermetadata, keyAccountNo resolves
    the label even though displayMultipleAccounts is empty (#96)."""
    monkeypatch.setattr(site, "_ACCOUNT_MAP", {KEY1: FIRST, KEY2: SECOND})
    got = site._docs_from_api({"defaultDocumentList": [
        _entry_with_key(BROKERAGE, KEY1, "", "g1"),
        _entry_with_key(BROKERAGE, KEY2, "", "g2"),
    ]})
    assert [d["account"] for d in got] == [FIRST, SECOND]


def test_docs_from_api_falls_back_to_display_multiple_accounts(monkeypatch):
    """When keyAccountNo is absent or not in the map, displayMultipleAccounts
    is still used, so existing single-account installs keep working."""
    monkeypatch.setattr(site, "_ACCOUNT_MAP", {})
    got = site._docs_from_api({"defaultDocumentList": [
        _entry(BROKERAGE, FIRST, "g1"),
        _entry(BROKERAGE, SECOND, "g2"),
    ]})
    assert [d["account"] for d in got] == [FIRST, SECOND]


def test_docs_from_api_prefers_key_account_no_over_display_multiple_accounts(monkeypatch):
    """The usermetadata label wins when both are present and disagree."""
    monkeypatch.setattr(site, "_ACCOUNT_MAP", {KEY1: FIRST})
    got = site._docs_from_api({"defaultDocumentList": [
        _entry_with_key(BROKERAGE, KEY1, "Some Other Label", "g1"),
    ]})
    assert got[0]["account"] == FIRST


def test_account_map_is_cleared_between_discover_runs(monkeypatch):
    """_ACCOUNT_MAP is cleared at the start of collect_download_docs, so
    stale metadata from a previous run never leaks into the next."""
    # Prime the map, then run collect_download_docs with an empty page response.
    real_map = {KEY1: FIRST}
    monkeypatch.setattr(site, "_ACCOUNT_MAP", real_map)
    for name in ("_LISTED", "_LISTED_TITLES", "_LISTED_ACCOUNTS", "_LISTED_DOCS"):
        monkeypatch.setattr(site, name, {})
    monkeypatch.setattr(site, "_PAGED", [])

    def capturing(page, capture):
        return True  # page returned nothing
    monkeypatch.setattr(site, "goto_docs_capturing", capturing)
    monkeypatch.setattr(site, "widen_date_filter", lambda page, wider, trace=None: False)
    monkeypatch.setattr(site, "expand_all", lambda page: None)
    monkeypatch.setattr(site, "scroll_full_page", lambda page: None)
    monkeypatch.setattr(site, "_bill_controls", lambda page: _FakeControls())
    site.collect_download_docs(None)
    assert real_map == {}  # mutated in-place by clear()


class _FakeControls:
    def count(self):
        return 0


# --- what the list says ---------------------------------------------------------

def test_the_list_keeps_each_accounts_label_whole():
    """The masked digits are what say which account it is, and the
    redaction for diagnostic files masked them again."""
    got = site._docs_from_api({"defaultDocumentList": [
        _entry(BROKERAGE, "Invented  Brokerage ...1111", "g1"), _entry(BROKERAGE, SECOND, "g2")]})
    assert [d["account"] for d in got] == ["Invented Brokerage ...1111", SECOND]
    assert [d["guid"] for d in got] == ["g1|id-g1", "g2|id-g2"]


def _lists_of_this_test(monkeypatch):
    """What discovery reads into the lists' module state stays with the
    test that reads it."""
    for name in ("_LISTED", "_LISTED_TITLES", "_LISTED_ACCOUNTS", "_LISTED_DOCS"):
        monkeypatch.setattr(site, name, {})


def test_two_accounts_statements_of_one_day_are_both_listed(monkeypatch):
    """Kept by date and title alone, the second account's was dropped."""
    _lists_of_this_test(monkeypatch)
    body ={"defaultDocumentList": [_entry(BROKERAGE, FIRST, "g1"), _entry(BROKERAGE, SECOND, "g2")]}

    def capturing(page, capture):
        capture.append(body)
        return True
    monkeypatch.setattr(site, "goto_docs_capturing", capturing)
    monkeypatch.setattr(site, "widen_date_filter", lambda page, wider, trace=None: False)
    docs = site.collect_download_docs(None)
    assert [(d.title, d.account) for d in docs] == [(BROKERAGE, FIRST), (BROKERAGE, SECOND)]
    assert [d.guid for d in docs] == ["g1|id-g1", "g2|id-g2"]
    assert site._LISTED_ACCOUNTS[(DAY, "brokerage statement")] == {FIRST.lower(), SECOND.lower()}
    assert "Invented" not in json.dumps(site.DISCOVERY_TRACE)


@pytest.mark.parametrize("label, tails", [
    ("Invented Brokerage -1111", ["1111"]),
    ("Invented Brokerage - 1111", ["1111"]),
    ("Individual ...1111", ["1111"]),
    ("Invented Card (...1111)", ["1111"]),
    ("Kids 2031 Fund ****1111", ["1111"]),
    ("Invented Brokerage -1111, Invented Roth IRA -2222", ["1111", "2222"]),
    ("Joint Account", []),
    ("Account 1111", []),
])
def test_an_account_is_known_by_the_masked_digits_its_label_ends_with(label, tails):
    assert site.account_tails(label) == tails


def test_a_nickname_changed_on_etrade_keeps_the_key():
    """The words before the digits are a nickname a person can change, and a
    key that moved with it would take every statement again."""
    def key(account):
        return etrade_docs.Document(category="Statement", date=DAY, title=BROKERAGE,
                                    account=account).key
    assert key(FIRST) == key("A Name Changed Later -1111") == "Statement:%s:%s:1111" % (DAY, BROKERAGE)
    assert key(FIRST) != key("Invented Brokerage -3333")
    assert key("Joint Account").endswith(":Joint Account")


# --- discovery, through the app's own path --------------------------------------

@pytest.fixture
def app(tmp_path, monkeypatch):
    """The app's own discovery, with the page's list stood in for."""
    a = etrade_docs.App.__new__(etrade_docs.App)
    a.args = SimpleNamespace(start_date=None, end_date=None, redownload=False, dry_run=False,
                             max_docs=None, type=None, year=None, apply=False)
    a.config = {"output_dir": str(tmp_path), "document_types": ["Statement", "Tax Document"],
                "min_pdf_bytes": 2000, "max_path_length": 240, "owner": "",
                "delay_min_seconds": 0, "delay_max_seconds": 0}
    a.paths = storage.Paths(tmp_path)
    a.paths.ensure()
    a.progress = storage.JsonStore(a.paths.progress_json, a.paths.backups)
    a.discovery = storage.JsonStore(a.paths.discovery_json, a.paths.backups)
    a.progress.load()
    a.discovery.load()
    a.index_csv = storage.CsvFile(a.paths.document_index_csv, storage.DOCUMENT_INDEX_COLUMNS,
                                  a.paths.backups)
    a.rules = doc_types.load_rules()
    a.stats = {"skipped_out_of_scope": 0, "discovered": 0, "failed": 0}
    a.page = lambda: None
    a.check_session = lambda page: None
    monkeypatch.setattr(site, "goto_documents", lambda page: True)
    listed: list = []
    monkeypatch.setattr(site, "collect_download_docs", lambda page: list(listed))

    def discover(*raws):
        listed[:] = raws
        a.cmd_discover(quiet=True)
        return a
    a.listing = discover
    return a


def _name(rec):
    return storage.build_pdf_filename(rec["date"], rec["summary"], "", record=rec)


def test_each_accounts_statement_of_one_day_is_its_own_record_and_name(app):
    app.listing(_raw(BROKERAGE, FIRST, "g1"), _raw(BROKERAGE, SECOND, "g2"))
    recs = sorted(app.discovery.data.values(), key=lambda r: r["account"])
    assert [r["account"] for r in recs] == [FIRST, SECOND], app.discovery.data
    assert len({etrade_docs.Document.from_dict(r).key for r in recs}) == 2
    assert [r["guid"] for r in recs] == ["g1|id-g1", "g2|id-g2"]
    assert [r["summary"] for r in recs] == ["Account Statement - " + FIRST, "Account Statement - " + SECOND]
    assert [_name(r) for r in recs] == ["%s ETRADE Account Statement - %s.pdf" % (DAY, FIRST),
                                        "%s ETRADE Account Statement - %s.pdf" % (DAY, SECOND)]
    assert [naming.fields_of(r)["account"] for r in recs] == [FIRST, SECOND]


def test_a_sign_in_of_one_account_keeps_the_names_it_had(app):
    app.listing(_raw(BROKERAGE, FIRST, "g1"), _raw(BROKERAGE, FIRST, "g3", day="2025-07-31"))
    recs = list(app.discovery.data.values())
    assert [r["account"] for r in recs] == [FIRST, FIRST]
    assert {r["summary"] for r in recs} == {"Account Statement"}
    assert _name(recs[0]) == "%s ETRADE Account Statement.pdf" % DAY
    assert naming.fields_of(recs[0])["account"] == FIRST


# --- records kept before ---------------------------------------------------------

def _legacy_key(title, day=DAY):
    return "Statement:%s:%s:Unnamed" % (day, title)


def _key(title, tail, day=DAY):
    return "Statement:%s:%s:%s" % (day, title, tail)


def _saved_before(app, title, name, day=DAY, done=True, prints=None):
    """A statement the app listed and saved before #96, under the key with
    no account, "Unnamed", its file on disk and its index row. The file is
    a PDF whose text is the lines `prints` when given, and otherwise one
    that does not open, which no account can be read from."""
    doc = etrade_docs.Document(title=title, category="Statement", summary="Account Statement",
                               date=day, confidence="High", source_url=site.BILLING_URL)
    assert doc.key == _legacy_key(title, day)
    path = app.paths.folder_for("Statement") / name
    if prints is not None:
        path.write_bytes(testkit.text_pdf(prints))
    if done:
        if prints is None:
            path.write_bytes(b"%PDF-1.4\n% invented\n" + b"0" * 2100)
        doc.pdf_path, doc.pdf_filename = str(path), path.name
        doc.downloaded_ok = True
        doc.state = State.COMPLETED.value
        app._write_row(doc, "Downloaded", "Completed")
    else:
        if prints is not None:
            doc.pdf_path, doc.pdf_filename = str(path), path.name
        doc.state = State.NEEDS_MANUAL_REVIEW.value
    app.progress.data[doc.key] = doc.to_dict()
    app.discovery.data[doc.key] = dict(doc.to_dict(), state=doc.state)
    app.progress.save()
    app.discovery.save()
    return path


def test_a_statement_saved_before_moves_to_its_accounts_key_and_is_never_taken_again(app):
    """A sign-in of one account. Every record moves to the key its account
    gives it, keeps what it was, and no file is renamed."""
    july = _saved_before(app, BROKERAGE, "2025-07-31 ETRADE Account Statement.pdf", day="2025-07-31")
    august = _saved_before(app, BROKERAGE, "%s ETRADE Account Statement.pdf" % DAY)
    app.listing(_raw(BROKERAGE, FIRST, "g1"), _raw(BROKERAGE, FIRST, "g3", day="2025-07-31"))
    for day, path in (("2025-07-31", july), (DAY, august)):
        assert _legacy_key(BROKERAGE, day) not in app.progress.data
        assert _legacy_key(BROKERAGE, day) not in app.discovery.data
        rec = app.progress.data[_key(BROKERAGE, "1111", day)]
        assert (rec["downloaded_ok"], rec["state"], rec["pdf_path"]) == (True, "Completed", str(path))
        assert (rec["account"], rec["summary"]) == (FIRST, "Account Statement")
    assert all(app._already_done(d) for d in app._select())
    assert len(app._select()) == 2
    result = renaming.run_for(app, apply_changes=True, say=lambda *_a: None)
    assert result.renamed == 0 and july.exists() and august.exists()
    backups = sorted(p.name.split(".")[0] for p in app.paths.backups.iterdir())
    assert "progress" in backups and "discovery" in backups


def test_a_history_moved_with_minimal_moves_the_same(app):
    """--minimal keeps no title or date in a record, so it is moved by its
    key alone."""
    app.progress.data[_legacy_key(BROKERAGE)] = {"state": "Completed", "downloaded_ok": True,
                                                 "pdf_path": ""}
    app.listing(_raw(BROKERAGE, FIRST, "g1"))
    assert app.progress.data[_key(BROKERAGE, "1111")]["downloaded_ok"] is True
    assert app._already_done(etrade_docs.Document.from_dict(app.discovery.data[_key(BROKERAGE, "1111")]))


def test_several_accounts_records_kept_before_stay_and_each_statement_is_taken_again(app):
    """The reporter's case. Two accounts' statements of one day with titles
    of their own were both saved, named alike, " (2)" telling them apart.
    With more than one account, the list does not say which account a
    record kept before holds, and these files do not read, so nothing
    proves it. Each stays done under its old key and its file keeps its
    name, and each account's statement is taken again under a name that
    says the account (review of #96)."""
    brokerage = _saved_before(app, BROKERAGE, "%s ETRADE Account Statement.pdf" % DAY)
    retirement = _saved_before(app, RETIREMENT, "%s ETRADE Account Statement (2).pdf" % DAY)
    before = json.loads(json.dumps(app.progress.data))
    app.listing(_raw(BROKERAGE, FIRST, "g1"), _raw(RETIREMENT, SECOND, "g2"))
    assert app.progress.data == before
    taken = sorted((d.account, _name(d.to_dict())) for d in app._select() if not app._already_done(d))
    assert taken == [(FIRST, "%s ETRADE Account Statement - %s.pdf" % (DAY, FIRST)),
                     (SECOND, "%s ETRADE Account Statement - %s.pdf" % (DAY, SECOND))]
    result = renaming.run_for(app, apply_changes=True, say=lambda *_a: None)
    assert result.renamed == 0 and brokerage.exists() and retirement.exists()


def test_lists_that_leave_one_accounts_statement_out_credit_nothing_to_another(app):
    """The review's case. Before #96 two accounts' Brokerage Statements of a
    day were one record, saved once with either account's PDF. These lists
    leave the second account's August and July statements out and show its
    June Retirement Statement. Moved to the first account's key, the record
    kept before would mark the first account's statement saved when it may
    hold the second's. These files do not read, so nothing moves (the PDF
    cases are below)."""
    days = ("2025-08-31", "2025-07-31", "2025-06-30")
    for day in days:
        _saved_before(app, BROKERAGE, "%s ETRADE Account Statement.pdf" % day, day=day)
    _saved_before(app, RETIREMENT, "2025-06-30 ETRADE Account Statement (2).pdf", day="2025-06-30")
    before = json.loads(json.dumps(app.progress.data))
    app.listing(_raw(BROKERAGE, FIRST, "a1", day="2025-08-31"), _raw(BROKERAGE, FIRST, "a2", day="2025-07-31"),
                _raw(RETIREMENT, SECOND, "b3", day="2025-06-30"), _raw(BROKERAGE, FIRST, "a3", day="2025-06-30"))
    assert app.progress.data == before
    taken = sorted((d.date, d.title, d.account) for d in app._select() if not app._already_done(d))
    assert taken == sorted([(day, BROKERAGE, FIRST) for day in days] + [("2025-06-30", RETIREMENT, SECOND)])


def test_two_accounts_with_one_masked_tail_never_share_a_key(app):
    """Their tails cannot tell them apart, so each is keyed by its whole
    label, and each is counted as an account of its own."""
    twin = "Invented Roth IRA -1111"
    app.listing(_raw(BROKERAGE, FIRST, "g1"), _raw(BROKERAGE, twin, "g2"))
    assert sorted(app.discovery.data) == sorted([_key(BROKERAGE, FIRST), _key(BROKERAGE, twin)])
    assert sorted(r["summary"] for r in app.discovery.data.values()) == [
        "Account Statement - " + FIRST, "Account Statement - " + twin]


def test_two_accounts_sharing_digits_on_one_day_keep_two_keys_and_a_label_with_none_adds_none(app, caplog):
    """The one case the digits cannot keep two keys apart, two labels with
    one tail on documents of the same date and title, beside a tax form
    whose label shows no digits. That label is no account of its own."""
    caplog.set_level(logging.INFO)
    twin = "Invented Roth IRA -1111"
    app.listing(_raw(BROKERAGE, FIRST, "g1"), _raw(BROKERAGE, twin, "g2"),
                _raw("Form 1099 Composite", "Multiple Accounts", "g3", day="2025-02-16"))
    assert {_key(BROKERAGE, FIRST), _key(BROKERAGE, twin)} <= set(app.discovery.data)
    said = " ".join(r.getMessage() for r in caplog.records)
    assert "2 account(s)" in said, said


# Forty characters two accounts' labels can share before they differ.
PREFIX = "Invented Individual Brokerage Account Fo"


def test_two_accounts_sharing_last_four_and_first_forty_characters_keep_two_keys(app):
    """The release review's case. The key kept a twin's label cut to forty
    characters and its last four, so these two had one key, and the second
    one's statement was recorded under the first one's summary."""
    assert len(PREFIX) == 40
    first, second = PREFIX + "r Trading -1111", PREFIX + "r Savings -1111"
    app.listing(_raw(BROKERAGE, first, "g1"), _raw(BROKERAGE, second, "g2"))
    recs = sorted(app.discovery.data.values(), key=lambda r: r["account"])
    assert [r["account"] for r in recs] == [second, first], app.discovery.data
    assert [r["summary"] for r in recs] == ["Account Statement - " + r["account"] for r in recs]
    names = [_name(r) for r in recs]
    assert "Savings -1111" in names[0] and "Trading -1111" in names[1], names
    # A label too long to keep whole keeps its start and a digest of all of
    # it, the same on every run, and different for any other label.
    long_one = PREFIX * 3 + " -1111"
    part = etrade_docs.whole_label_key(long_one)
    assert len(part) <= etrade_docs.WHOLE_LABEL_LIMIT and part == etrade_docs.whole_label_key(long_one)
    assert part != etrade_docs.whole_label_key(PREFIX * 3 + "x -1111")


def test_an_existing_record_is_never_relabeled_to_another_account(app):
    """A listed document under a record's key that names another account
    stops the list, and the record keeps its account. The same account
    worded another way, its digits the same, still takes the new wording."""
    twin = "Invented Roth IRA -1111"
    app.listing(_raw(BROKERAGE, FIRST, "g1"), _raw(BROKERAGE, twin, "g2"))
    key = _key(BROKERAGE, FIRST)
    app.discovery.data[key]["account"] = "Invented Brokerage Other -1111"
    with pytest.raises(pressing.Stop):
        app.listing(_raw(BROKERAGE, FIRST, "g1"), _raw(BROKERAGE, twin, "g2"))
    assert app.discovery.data[key]["account"] == "Invented Brokerage Other -1111"

    app.discovery.data.clear()
    app.listing(_raw(BROKERAGE, "Old Nickname -1111", "g1"))
    app.listing(_raw(BROKERAGE, FIRST, "g1"))
    assert [r["account"] for r in app.discovery.data.values()] == [FIRST]


def test_one_account_worded_two_ways_moves_its_history_one_to_one(app):
    """The second review's case. Older documents keep the nickname the
    account had then. Same digits on documents that never share a date and
    title are one account, keyed by the digits, so its history moves and
    nothing is taken again or renamed."""
    old = "Old Nickname -1111"
    days = ("2025-06-30", "2025-07-31", "2025-08-31")
    files = [_saved_before(app, BROKERAGE, "%s ETRADE Account Statement.pdf" % day, day=day) for day in days]
    app.listing(_raw(BROKERAGE, old, "g1", day=days[0]), _raw(BROKERAGE, old, "g2", day=days[1]),
                _raw(BROKERAGE, FIRST, "g3", day=days[2]))
    for day, path in zip(days, files):
        rec = app.progress.data[_key(BROKERAGE, "1111", day)]
        assert (rec["downloaded_ok"], rec["pdf_path"], rec["summary"]) == (True, str(path), "Account Statement")
    assert not [d for d in app._select() if not app._already_done(d)]
    result = renaming.run_for(app, apply_changes=True, say=lambda *_a: None)
    assert result.renamed == 0 and all(p.exists() for p in files)


def test_a_label_with_no_digits_beside_an_accounts_own_keeps_it_one_account(app):
    """A tax form labeled "Multiple Accounts" made a sign-in of one account
    count as two, so its history was not moved and was taken again."""
    days = ("2025-07-31", "2025-08-31")
    for day in days:
        _saved_before(app, BROKERAGE, "%s ETRADE Account Statement.pdf" % day, day=day)
    app.listing(_raw(BROKERAGE, FIRST, "g1", day=days[0]), _raw(BROKERAGE, FIRST, "g2", day=days[1]),
                _raw("Form 1099 Composite", "Multiple Accounts", "g3", day="2025-02-16"))
    taken = [(d.title, d.summary) for d in app._select() if not app._already_done(d)]
    assert taken == [("Form 1099 Composite", "1099 Tax Form")], taken


@pytest.mark.parametrize("done", [False, True])
def test_a_title_and_day_two_accounts_share_is_left_where_it_is(app, done):
    """Which account's statement a record of both kept cannot be told from
    the list, or from a file that does not read, so it stays, and each
    account's statement is listed under its own key.
    Not done, the listing's own record of both goes, since a download of
    it found two rows naming it and refused on every run."""
    _saved_before(app, BROKERAGE, "%s ETRADE Account Statement.pdf" % DAY, done=done)
    before = dict(app.progress.data[_legacy_key(BROKERAGE)])
    app.listing(_raw(BROKERAGE, FIRST, "g1"), _raw(BROKERAGE, SECOND, "g2"))
    assert app.progress.data[_legacy_key(BROKERAGE)] == before
    assert (_legacy_key(BROKERAGE) in app.discovery.data) is done
    taken = sorted(d.account for d in app._select() if not app._already_done(d))
    assert taken == [FIRST, SECOND]


@pytest.mark.parametrize("old_done", [True, False])
def test_a_finished_record_wins_a_key_both_want(app, old_done):
    _saved_before(app, BROKERAGE, "%s ETRADE Account Statement.pdf" % DAY, done=old_done)
    new_key = _key(BROKERAGE, "1111")
    app.progress.data[new_key] = {"category": "Statement", "date": DAY, "title": BROKERAGE,
                                  "account": FIRST, "state": "Completed" if not old_done else "Failed",
                                  "downloaded_ok": not old_done}
    app.progress.save()
    app.listing(_raw(BROKERAGE, FIRST, "g1"))
    assert _legacy_key(BROKERAGE) not in app.progress.data
    assert app.progress.data[new_key]["downloaded_ok"] is True


def test_a_review_copy_with_its_file_wins_a_key_over_a_failed_attempt(app):
    """A record kept before, set aside for review with a PDF that validates,
    is done to the run (_already_done) and not to keys.is_done. Compared by
    keys.is_done alone, the failed attempt under its account's key stayed,
    the review copy's record went with its file left behind, and the
    statement was taken again (review of 0.56.1)."""
    path = _saved_before(app, BROKERAGE, "%s ETRADE Account Statement.pdf" % DAY, done=False,
                         prints=_statement("Account Number: XXXX-1111"))
    new_key = _key(BROKERAGE, "1111")
    app.progress.data[new_key] = {"category": "Statement", "date": DAY, "title": BROKERAGE,
                                  "account": FIRST, "state": "Failed", "downloaded_ok": False}
    app.progress.save()
    app.listing(_raw(BROKERAGE, FIRST, "g1"))
    assert _legacy_key(BROKERAGE) not in app.progress.data
    rec = app.progress.data[new_key]
    assert (rec["state"], rec["pdf_path"]) == (State.NEEDS_MANUAL_REVIEW.value, str(path))
    assert [d.account for d in app._select() if not app._already_done(d)] == []
    assert path.exists()


# --- records kept before, moved by what their own PDF shows ----------------------
#
# The promise made on #96. For a sign-in of several accounts, each saved
# PDF is read for its account's last digits, and an old record moves to its
# account only when the file shows that account and no other.

THIRD = "Invented IRA -2025"
TWIN = "Invented Roth IRA -1111"

# How a statement might print the first account's number, all accepted.
SHOWS_FIRST = [
    ["Account Number: XXXX-1111"],
    ["Account Number:", "6789-1111"],
    ["Invented Brokerage ...1111"],
    ["Account ending in 1111"],
    ["ACCT # ****1111"],
    ["Account Number: 6789-1111", "Invented Brokerage XXXX1111"],
]


def _statement(*lines):
    """The lines of an invented statement, around what names its account."""
    return ["Invented Securities", "Brokerage Statement", "August 1 - 31"] + list(lines) + [
        "Total value $12,345.67", "Page 1 of 1"]


def _both_on_one_day(app):
    """The reporter's case. Two accounts' Brokerage Statements of one day,
    which before #96 were one record, saved once."""
    return app.listing(_raw(BROKERAGE, FIRST, "g1"), _raw(BROKERAGE, SECOND, "g2"))


def _still_where_it_was(app, before):
    assert app.progress.data[_legacy_key(BROKERAGE)] == before
    taken = sorted(d.account for d in app._select() if not app._already_done(d))
    assert taken == [FIRST, SECOND], taken


@pytest.mark.parametrize("prints", SHOWS_FIRST, ids=lambda p: p[-1])
def test_a_statement_saved_before_moves_to_the_account_its_pdf_shows(app, prints):
    path = _saved_before(app, BROKERAGE, "%s ETRADE Account Statement.pdf" % DAY,
                         prints=_statement(*prints))
    _both_on_one_day(app)
    assert _legacy_key(BROKERAGE) not in app.progress.data
    assert _legacy_key(BROKERAGE) not in app.discovery.data
    rec = app.progress.data[_key(BROKERAGE, "1111")]
    assert (rec["downloaded_ok"], rec["state"], rec["pdf_path"]) == (True, "Completed", str(path))
    assert (rec["account"], rec["guid"]) == (FIRST, "g1|id-g1")
    # The summary the list gives a sign-in of several accounts, so the
    # record reads as one listed now.
    assert rec["summary"] == "Account Statement - " + FIRST
    assert app.discovery.data[_key(BROKERAGE, "1111")]["summary"] == rec["summary"]
    assert app.discovery.data[_key(BROKERAGE, "1111")]["account"] == FIRST
    # Only the second account's statement is left to take, and the file
    # was neither renamed nor moved.
    taken = [d.account for d in app._select() if not app._already_done(d)]
    assert taken == [SECOND], taken
    assert path.exists() and sorted(p.name for p in path.parent.iterdir()) == [path.name]
    backups = sorted(p.name.split(".")[0] for p in app.paths.backups.iterdir())
    assert "progress" in backups and "discovery" in backups


def test_the_second_accounts_statement_moves_to_the_second_account(app):
    path = _saved_before(app, RETIREMENT, "%s ETRADE Account Statement (2).pdf" % DAY,
                         prints=_statement("Account Number: XXXX-2222"))
    _saved_before(app, BROKERAGE, "%s ETRADE Account Statement.pdf" % DAY,
                  prints=_statement("Account Number: XXXX-1111"))
    app.listing(_raw(BROKERAGE, FIRST, "g1"), _raw(RETIREMENT, SECOND, "g2"))
    assert app.progress.data[_key(RETIREMENT, "2222")]["pdf_path"] == str(path)
    assert app.progress.data[_key(RETIREMENT, "2222")]["account"] == SECOND
    assert app.progress.data[_key(BROKERAGE, "1111")]["account"] == FIRST
    assert not [d for d in app._select() if not app._already_done(d)]


def test_a_moved_statement_is_skipped_as_done_and_renamed_with_its_account(app, monkeypatch):
    """Discover never renames the file. A Rename with the default pattern
    then plans the name a statement of that account downloaded now has,
    and so does one with {account}."""
    path = _saved_before(app, BROKERAGE, "%s ETRADE Account Statement.pdf" % DAY,
                         prints=_statement("Account Number: XXXX-1111"))
    _both_on_one_day(app)
    assert path.exists() and sorted(p.name for p in path.parent.iterdir()) == [path.name]
    first = next(d for d in app._select() if d.account == FIRST)
    pressed: list = []
    app.download_one = lambda page, d, filename: pressed.append(d.account)
    app._on_its_site = lambda: None
    app._delay = lambda *a, **k: None
    app.stats["skipped_completed"] = 0
    app.process([first])
    assert pressed == [] and app.stats["skipped_completed"] == 1
    # The name a download of the first account's statement takes now.
    labeled = _name(app.discovery.data[_key(BROKERAGE, "1111")])
    assert labeled == "%s ETRADE Account Statement - %s.pdf" % (DAY, FIRST)
    said: list = []
    assert renaming.run_for(app, apply_changes=False, say=said.append).renamed == 0
    assert "  %s" % path.name in said and "    -> %s" % labeled in said, said
    assert path.exists()
    with monkeypatch.context() as m:
        m.setattr(core_storage, "_FILENAME_PATTERN", "{date} {account} {summary}")
        said.clear()
        renaming.run_for(app, apply_changes=False, say=said.append)
        assert "    -> %s %s Account Statement - %s.pdf" % (DAY, FIRST, FIRST) in said, said
    assert renaming.run_for(app, apply_changes=True, say=lambda *_a: None).renamed == 1
    assert not path.exists() and (path.parent / labeled).exists()
    assert app.progress.data[_key(BROKERAGE, "1111")]["pdf_path"] == str(path.parent / labeled)


def test_a_second_discover_moves_nothing_more(app):
    _saved_before(app, BROKERAGE, "%s ETRADE Account Statement.pdf" % DAY,
                  prints=_statement("Account Number: XXXX-1111"))
    _saved_before(app, RETIREMENT, "%s ETRADE Account Statement (2).pdf" % DAY,
                  prints=_statement("No account printed here"))
    _both_on_one_day(app)
    progress, discovery = json.dumps(app.progress.data), json.dumps(app.discovery.data)
    backups = sorted(p.name for p in app.paths.backups.iterdir())
    _both_on_one_day(app)
    assert json.dumps(app.progress.data) == progress
    assert sorted(p.name for p in app.paths.backups.iterdir()) == backups
    assert sorted(json.loads(discovery)) == sorted(app.discovery.data)


@pytest.mark.parametrize("prints", [
    ["Account Number: XXXX-1111", "Transfer to Account Number: XXXX-2222"],
    ["Account Number: XXXX-1111", "Transfer to 2222"],
    ["Brokerage Statement for 2025", "Interest 1111"],
    ["Brokerage Statement", "No account number printed"],
    ["SSN XXX-XX-1111", "Recipient TIN XXXXX1111"],
    ["Total $1111.00", "1-800-555-1111"],
], ids=["both accounts", "the other's digits on their own", "bare numbers", "none",
        "a tax id", "an amount and a phone"])
def test_a_pdf_that_does_not_show_one_account_alone_stays(app, prints):
    """Both accounts, the other's digits anywhere at all, no account, or
    digits only as a number of their own, a year, an amount, a phone number
    or a tax id, never as an account number."""
    _saved_before(app, BROKERAGE, "%s ETRADE Account Statement.pdf" % DAY,
                  prints=_statement(*prints))
    before = dict(app.progress.data[_legacy_key(BROKERAGE)])
    _both_on_one_day(app)
    _still_where_it_was(app, before)


def test_a_year_that_is_another_accounts_digits_leaves_it(app):
    """A third account ends in 2025. A bare year is never taken for its
    account number, and is still another listed account's digits in the
    file, so the first account's statement stays where it was."""
    _saved_before(app, BROKERAGE, "%s ETRADE Account Statement.pdf" % DAY,
                  prints=_statement("Account Number: XXXX-1111", "Statement period 2025"))
    before = dict(app.progress.data[_legacy_key(BROKERAGE)])
    app.listing(_raw(BROKERAGE, FIRST, "g1"), _raw(BROKERAGE, SECOND, "g2"),
                _raw(RETIREMENT, THIRD, "g3", day="2025-07-31"))
    assert app.progress.data[_legacy_key(BROKERAGE)] == before
    assert site.tails_printed("Statement period 2025", [THIRD]) == set()


@pytest.mark.parametrize("where", ["that day", "another day"])
def test_two_accounts_sharing_their_digits_are_never_told_apart_by_them(app, where):
    _saved_before(app, BROKERAGE, "%s ETRADE Account Statement.pdf" % DAY,
                  prints=_statement("Account Number: XXXX-1111"))
    before = dict(app.progress.data[_legacy_key(BROKERAGE)])
    if where == "that day":
        app.listing(_raw(BROKERAGE, FIRST, "g1"), _raw(BROKERAGE, TWIN, "g2"),
                    _raw(BROKERAGE, SECOND, "g4"))
    else:
        app.listing(_raw(BROKERAGE, FIRST, "g1"), _raw(BROKERAGE, SECOND, "g4"),
                    _raw(RETIREMENT, FIRST, "g5", day="2025-07-31"),
                    _raw(RETIREMENT, TWIN, "g6", day="2025-07-31"))
    assert app.progress.data[_legacy_key(BROKERAGE)] == before


def test_a_statement_of_an_account_beside_two_sharing_digits_still_moves(app):
    """The twins' digits nowhere in the file, so it is not either twin's,
    and it shows the third account's alone."""
    path = _saved_before(app, BROKERAGE, "%s ETRADE Account Statement.pdf" % DAY,
                         prints=_statement("Account Number: XXXX-2222"))
    app.listing(_raw(BROKERAGE, FIRST, "g1"), _raw(BROKERAGE, TWIN, "g2"),
                _raw(BROKERAGE, SECOND, "g4"))
    assert app.progress.data[_key(BROKERAGE, "2222")]["pdf_path"] == str(path)


def test_an_unfinished_record_is_never_moved(app):
    _saved_before(app, BROKERAGE, "%s ETRADE Account Statement.pdf" % DAY, done=False,
                  prints=_statement("Account Number: XXXX-1111"))
    before = dict(app.progress.data[_legacy_key(BROKERAGE)])
    _both_on_one_day(app)
    assert app.progress.data[_legacy_key(BROKERAGE)] == before
    assert _key(BROKERAGE, "1111") not in app.progress.data


@pytest.mark.parametrize("damage, why", [
    ("deleted", etrade_docs.NO_FILE), ("no path", etrade_docs.NO_FILE),
    ("broken", etrade_docs.UNREADABLE), ("no text", etrade_docs.UNREADABLE),
    ("too small", etrade_docs.UNREADABLE)])
def test_a_missing_or_broken_pdf_leaves_the_record(app, caplog, damage, why):
    path = _saved_before(app, BROKERAGE, "%s ETRADE Account Statement.pdf" % DAY,
                         prints=_statement("Account Number: XXXX-1111"))
    if damage == "deleted":
        path.unlink()
    elif damage == "no path":
        app.progress.data[_legacy_key(BROKERAGE)]["pdf_path"] = ""
    elif damage == "broken":
        path.write_bytes(b"%PDF-1.4\n" + b"not a pdf at all " * 300)
    elif damage == "no text":
        path.write_bytes(testkit.sample_pdf())
    else:
        path.write_bytes(path.read_bytes()[:900])
    before = dict(app.progress.data[_legacy_key(BROKERAGE)])
    caplog.set_level(logging.INFO)
    _both_on_one_day(app)
    _still_where_it_was(app, before)
    said = " ".join(r.getMessage() for r in caplog.records)
    assert "1 left as they were, 1 for %s" % why in said, said


def test_digits_of_an_account_the_lists_leave_out_that_day_credit_nobody(app):
    """The review's case once more, with a PDF. The lists give the day's
    Brokerage Statement to the first account alone, and the file kept
    before shows the second account's digits. It is never moved to the
    first account."""
    _saved_before(app, BROKERAGE, "%s ETRADE Account Statement.pdf" % DAY,
                  prints=_statement("Account Number: XXXX-2222"))
    before = dict(app.progress.data[_legacy_key(BROKERAGE)])
    app.listing(_raw(BROKERAGE, FIRST, "g1"), _raw(RETIREMENT, SECOND, "g2", day="2025-07-31"))
    assert app.progress.data[_legacy_key(BROKERAGE)] == before
    assert _key(BROKERAGE, "1111") not in app.progress.data


def test_an_account_listed_without_digits_that_day_leaves_it(app):
    _saved_before(app, BROKERAGE, "%s ETRADE Account Statement.pdf" % DAY,
                  prints=_statement("Account Number: XXXX-1111"))
    before = dict(app.progress.data[_legacy_key(BROKERAGE)])
    app.listing(_raw(BROKERAGE, FIRST, "g1"), _raw(BROKERAGE, "Joint Account", "g2"),
                _raw(RETIREMENT, SECOND, "g3", day="2025-07-31"))
    assert app.progress.data[_legacy_key(BROKERAGE)] == before


def test_a_statement_already_taken_again_stays_and_its_file_is_not_read(app, monkeypatch):
    """0.53.0 took each account's statement again. The record kept before
    stays, and its file is not read on every Discover."""
    _saved_before(app, BROKERAGE, "%s ETRADE Account Statement.pdf" % DAY,
                  prints=_statement("Account Number: XXXX-1111"))
    before = dict(app.progress.data[_legacy_key(BROKERAGE)])
    for account, tail in ((FIRST, "1111"), (SECOND, "2222")):
        app.progress.data[_key(BROKERAGE, tail)] = {"category": "Statement", "date": DAY,
                                                    "title": BROKERAGE, "account": account,
                                                    "state": "Completed", "downloaded_ok": True}
    read: list = []
    monkeypatch.setattr(receipt_pdf, "pdf_text", lambda path: read.append(path) or "")
    _both_on_one_day(app)
    assert app.progress.data[_legacy_key(BROKERAGE)] == before
    assert read == []


def test_a_finished_record_of_its_account_keeps_its_place(app):
    """The first account's statement was taken again and the second's was
    not. The file kept before shows the first, so it stays."""
    _saved_before(app, BROKERAGE, "%s ETRADE Account Statement.pdf" % DAY,
                  prints=_statement("Account Number: XXXX-1111"))
    before = dict(app.progress.data[_legacy_key(BROKERAGE)])
    again = {"category": "Statement", "date": DAY, "title": BROKERAGE, "account": FIRST,
             "state": "Completed", "downloaded_ok": True, "pdf_path": "elsewhere.pdf"}
    app.progress.data[_key(BROKERAGE, "1111")] = dict(again)
    _both_on_one_day(app)
    assert app.progress.data[_legacy_key(BROKERAGE)] == before
    assert app.progress.data[_key(BROKERAGE, "1111")] == again


def test_a_closed_accounts_statement_naming_a_listed_one_in_a_transfer_stays(app, caplog):
    """The review's case. The record kept before holds the statement of an
    account the lists no longer name, closed, ending 2222. Its PDF prints
    its own number and a transfer to the listed account ending 1111, the
    only listed account it shows. It was moved to 1111, whose own statement
    of that day was then never taken."""
    _saved_before(app, BROKERAGE, "%s ETRADE Account Statement.pdf" % DAY,
                  prints=_statement("Account Number: XXXX-2222",
                                    "Transfer to Individual XXXX-1111 $500.00"))
    before = dict(app.progress.data[_legacy_key(BROKERAGE)])
    caplog.set_level(logging.INFO)
    app.listing(_raw(BROKERAGE, FIRST, "g1"), _raw(RETIREMENT, "Invented Joint -3333", "g3"))
    assert app.progress.data[_legacy_key(BROKERAGE)] == before
    assert _key(BROKERAGE, "1111") not in app.progress.data
    taken = [d.account for d in app._select() if not app._already_done(d) and d.title == BROKERAGE]
    assert taken == [FIRST], taken
    said = " ".join(r.getMessage() for r in caplog.records)
    assert "1 for %s" % etrade_docs.OTHER_NUMBER in said, said


@pytest.mark.parametrize("own", [
    "Invented Closed -2222",
    "SSN XXX-XX-5555 Account Number: XXXX-2222",
], ids=["its label's shape", "after a masked tax id"])
def test_a_closed_accounts_number_in_another_shape_still_keeps_it_where_it_is(app, caplog, own):
    """The second review's cases. The closed account's own number printed
    in the shape of a label, or labeled as an account's just after a masked
    tax id, was not counted, so the transfer to the listed account ending
    1111 was the only account the statement showed, and it moved there."""
    _saved_before(app, BROKERAGE, "%s ETRADE Account Statement.pdf" % DAY,
                  prints=_statement(own, "Transfer to %s $500.00" % FIRST))
    before = dict(app.progress.data[_legacy_key(BROKERAGE)])
    caplog.set_level(logging.INFO)
    app.listing(_raw(BROKERAGE, FIRST, "g1"), _raw(RETIREMENT, "Invented Joint -3333", "g3"))
    assert app.progress.data[_legacy_key(BROKERAGE)] == before
    assert _key(BROKERAGE, "1111") not in app.progress.data


@pytest.mark.parametrize("valid", [True, False], ids=["a review copy", "a file that does not open"])
def test_a_record_under_its_accounts_key_naming_a_file_keeps_it(app, caplog, valid):
    """The review's case. A Needs Manual Review copy under the account's
    key, which _already_done counts as done while its PDF validates and
    keys.is_done does not, was replaced by the record kept before, and its
    file was left with no record. A record naming any file that is there
    keeps its key."""
    _saved_before(app, BROKERAGE, "%s ETRADE Account Statement.pdf" % DAY,
                  prints=_statement("Account Number: XXXX-1111"))
    before = dict(app.progress.data[_legacy_key(BROKERAGE)])
    review = app.paths.manual_review / "review.pdf"
    review.write_bytes(testkit.text_pdf(_statement("Account Number: XXXX-1111")) if valid
                       else b"%PDF-1.4 not one")
    copy = {"category": "Statement", "date": DAY, "title": BROKERAGE, "account": FIRST,
            "state": State.NEEDS_MANUAL_REVIEW.value if valid else State.FAILED.value,
            "pdf_path": str(review), "notes": "invented"}
    app.progress.data[_key(BROKERAGE, "1111")] = dict(copy)
    app.progress.save()
    caplog.set_level(logging.INFO)
    _both_on_one_day(app)
    assert app.progress.data[_key(BROKERAGE, "1111")] == copy
    assert app.progress.data[_legacy_key(BROKERAGE)] == before
    assert review.exists()
    said = " ".join(r.getMessage() for r in caplog.records)
    assert "1 for %s" % etrade_docs.HOLDS_A_FILE in said, said


def test_a_failed_attempt_under_its_accounts_key_gives_way(app):
    """As adopt_account_keys does, a finished record wins a key over one
    that is not."""
    path = _saved_before(app, BROKERAGE, "%s ETRADE Account Statement.pdf" % DAY,
                         prints=_statement("Account Number: XXXX-1111"))
    app.progress.data[_key(BROKERAGE, "1111")] = {"category": "Statement", "date": DAY,
                                                  "title": BROKERAGE, "account": FIRST,
                                                  "state": "Failed", "downloaded_ok": False}
    _both_on_one_day(app)
    rec = app.progress.data[_key(BROKERAGE, "1111")]
    assert (rec["downloaded_ok"], rec["pdf_path"]) == (True, str(path))


def test_a_history_moved_with_minimal_moves_by_its_pdf_too(app):
    """--minimal keeps state, downloaded_ok and pdf_path, which is all this
    reads off a record."""
    path = app.paths.folder_for("Statement") / ("%s ETRADE Account Statement.pdf" % DAY)
    path.write_bytes(testkit.text_pdf(_statement("Account Number: XXXX-2222")))
    app.progress.data[_legacy_key(BROKERAGE)] = {"state": "Completed", "downloaded_ok": True,
                                                 "pdf_path": str(path)}
    _both_on_one_day(app)
    assert app.progress.data[_key(BROKERAGE, "2222")]["pdf_path"] == str(path)
    assert [d.account for d in app._select() if not app._already_done(d)] == [FIRST]


def test_a_sign_in_of_one_account_still_moves_without_reading(app, monkeypatch):
    """Unchanged. With one account every record moves by its key, and no
    PDF is read."""
    _saved_before(app, BROKERAGE, "%s ETRADE Account Statement.pdf" % DAY,
                  prints=_statement("Account Number: XXXX-9999"))
    read: list = []
    monkeypatch.setattr(receipt_pdf, "pdf_text", lambda path: read.append(path) or "")
    app.listing(_raw(BROKERAGE, FIRST, "g1"))
    assert app.progress.data[_key(BROKERAGE, "1111")]["downloaded_ok"] is True
    assert read == []


def test_what_is_logged_is_counts_and_fixed_words(app, caplog):
    caplog.set_level(logging.INFO)
    _saved_before(app, BROKERAGE, "%s ETRADE Account Statement.pdf" % DAY,
                  prints=_statement("Zanzibar Account Number: XXXX-1111"))
    _saved_before(app, RETIREMENT, "%s ETRADE Account Statement (2).pdf" % DAY,
                  prints=_statement("Zanzibar Account Number: XXXX-1111 XXXX-2222"))
    _saved_before(app, BROKERAGE, "2025-07-31 ETRADE Account Statement.pdf", day="2025-07-31",
                  done=False, prints=_statement("Zanzibar"))
    app.listing(_raw(BROKERAGE, FIRST, "g1"), _raw(RETIREMENT, SECOND, "g2"),
                _raw(BROKERAGE, FIRST, "g3", day="2025-07-31"))
    said = " ".join(r.getMessage() for r in caplog.records)
    assert "1 saved record(s) kept before 0.53.0 moved" in said, said
    assert "2 left as they were" in said and "1 for more than one account's digits" in said, said
    assert "1 for not done" in said, said
    for leaked in ("Invented", "1111", "2222", "Roth", "Zanzibar", "XXXX", "Statement.pdf"):
        assert leaked not in said, (leaked, said)


# --- how a statement prints an account -------------------------------------------

LABELS = [FIRST, SECOND, THIRD]


@pytest.mark.parametrize("text", [
    "Account Number: XXXX-1111", "Account Number: 6789-1111", "ACCOUNT NO. 1111", "Acct #1111",
    "Account: ****1111", "Invented Brokerage ...1111", "INVENTED BROKERAGE - 1111",
    "account ending in 1111", "ending in XXXX1111", "**** 1111", "####1111", "(...1111)",
    "…1111", "--1111", "XXXX1111", "•••• 1111", "6789-1111",
])
def test_an_account_number_ending_in_the_digits_is_printed(text):
    assert site.tails_printed("Invented Securities " + text + " Page 1", LABELS) == {"1111"}


@pytest.mark.parametrize("text", [
    "Statement period 01/01/2025 - 12/31/2025", "Total $1,111.00", "Total $1111.00",
    "SSN XXX-XX-1111", "Recipient TIN: XXXXX1111", "XX-XXX1111", "Account Summary 2024-2025",
    "1-800-387-1111", "(800) 387-1111", "** 2025 footnote", "Total .......... 2025",
    "Year End - 2025", "Account Number: 1111.00", "Account Number: 2025-08-31", "Interest 1111",
    "11112025", "For the year ending 2025", "Tax period ending in 2025",
])
def test_a_number_of_its_own_is_never_an_account(text):
    assert site.tails_printed(text, LABELS) == set()
    assert site.account_numbers_printed(text) == set()


def test_every_account_number_printed_is_found_listed_or_not():
    text = ("Account Number: XXXX-2222 Transfer to Individual XXXX-1111 $500.00 "
            "Linked bank ending in 9876 is no account's words, Card number ending in 4321, "
            "SSN XXX-XX-5555, Statement period 2024-2025, Page 1 of 3")
    assert site.account_numbers_printed(text) == {"2222", "1111", "4321"}
    assert site.account_numbers_printed("Account Number: 6789-1111") == {"1111"}
    # A label's shape, listed or not, and a number labeled as an account's
    # just after a masked tax id (the second review).
    assert site.account_numbers_printed("Invented Closed -2222 Transfer") == {"2222"}
    assert site.account_numbers_printed(
        "SSN XXX-XX-5555 Account Number: XXXX-2222") == {"2222"}
    assert site.account_numbers_printed("Account Number: 67891111") == {"67891111"}
    assert site.one_account("67891111", "1111") and site.one_account("111", "1111")
    assert not site.one_account("2222", "1111")


def test_a_tail_is_seen_wherever_it_ends_a_number():
    assert site.tails_seen("Statement period 2025, interest 1111.00, 32222", {"1111", "2222", "2025"}) \
        == {"1111", "2222", "2025"}
    assert site.tails_seen("Total $2,222.00, 1111 2", {"2222", "111"}) == {"111"}


# --- what is written down --------------------------------------------------------

def test_only_a_count_of_accounts_is_logged(app, caplog):
    caplog.set_level(logging.INFO)
    app.listing(_raw(BROKERAGE, FIRST, "g1"), _raw(BROKERAGE, SECOND, "g2"))
    said = " ".join(r.getMessage() for r in caplog.records)
    assert "2 account(s)" in said, said
    for leaked in ("Invented", "1111", "2222", "Roth"):
        assert leaked not in said, (leaked, said)


def test_a_failed_download_is_logged_by_its_date_and_title(app, caplog):
    """An error writing the file names its path, and a file's name says
    the account, so neither the key nor the error's words are logged."""
    app.listing(_raw(BROKERAGE, FIRST, "g1"), _raw(BROKERAGE, SECOND, "g2"))
    doc = next(d for d in app._select() if d.account == FIRST)

    def fails(page, d, filename):
        raise OSError(13, "invented failure", str(app.paths.folder_for("Statement") / filename))
    app._on_its_site = lambda: None
    app.download_one = fails
    app._delay = lambda *a, **k: None
    caplog.set_level(logging.INFO)
    app.process([doc])
    said = [r.getMessage() for r in caplog.records if "Failed on" in r.getMessage()]
    assert said and DAY in said[0] and BROKERAGE in said[0], said
    for leaked in (doc.key, "Invented", "1111"):
        assert leaked not in caplog.text, (leaked, caplog.text)


def test_the_pilot_report_names_a_document_by_its_date_kind_and_title(app, capsys):
    app.listing(_raw(BROKERAGE, FIRST, "g1"))
    doc = app._select()[0]
    app._record(doc, State.FAILED, notes="invented")
    capsys.readouterr()
    app._pilot_report([doc])
    out = capsys.readouterr().out
    assert "%s Statement %s: Failed" % (DAY, BROKERAGE) in out, out
    assert doc.key not in out and "1111" not in out, out


def test_the_download_is_handed_the_documents_account(app, monkeypatch, tmp_path):
    app.listing(_raw(BROKERAGE, FIRST, "g1"))
    doc = app._select()[0]
    asked: list = []

    def download_bill(page, dl_dir, iso, out_path, title="", trace=None, **kw):
        asked.append(kw.get("account"))
        return False
    monkeypatch.setattr(site, "download_bill", download_bill)
    app._dl_dir = tmp_path / "dl"
    app.write_failure = lambda *a, **k: None
    app.stats["manual_review"] = 0
    app.download_one(SimpleNamespace(url=""), doc, "x.pdf")
    assert asked == [FIRST]


# --- the download takes only its own account's link ------------------------------

LISTENER = ("<script>window.hits = [];"
            "document.addEventListener('click', e => { const g = e.target.closest('[data-guid]');"
            " window.hits.push(g ? g.dataset.guid : e.target.tagName.toLowerCase());"
            " e.preventDefault(); }, true);</script>")

# The document's link in a web component, the way his table draws it, named
# "<title> PDF for <account>" unless the row says otherwise.
DOC_LINK_JS = """
<script>
class AcctLink extends HTMLElement {
  connectedCallback() {
    if (this.shadowRoot) return;
    const sr = this.attachShadow({mode: 'open'});
    const a = document.createElement('a');
    a.href = '#';
    a.textContent = this.dataset.title;
    if (this.dataset.label) a.setAttribute('aria-label', this.dataset.label);
    a.dataset.guid = this.dataset.guid;
    sr.appendChild(a);
  }
}
if (!customElements.get('acct-link')) customElements.define('acct-link', AcctLink);
</script>
"""


def _label(title, account):
    return "%s PDF for %s" % (title, account) if account else ""


def _table(rows):
    """Table rows shaped like his, the account in a column of its own and
    the link in a shadow root."""
    return "<table><tbody>%s</tbody></table>%s%s" % ("".join(
        "<tr><td>%s</td><td>%s</td><td><acct-link data-title='%s' data-label='%s' data-guid='%s'>"
        "</acct-link></td></tr>" % (SHORT, account, title, _label(title, named), guid)
        for title, account, named, guid in rows), DOC_LINK_JS, LISTENER)


def _divs(rows, shape="div"):
    """Rows that are list items or plain divs, the link in the light DOM."""
    tag, outer = ("li", "ul") if shape == "li" else ("div", "div")
    return "<%s>%s</%s>%s" % (outer, "".join(
        "<%s class='doc'><span>%s</span> <span><a href='#' data-guid='%s'%s>%s</a></span> <span>%s</span></%s>"
        % (tag, SHORT, guid, " aria-label='%s'" % _label(title, named) if named else "", title, account, tag)
        for title, account, named, guid in rows), outer, LISTENER)


BOTH = [(BROKERAGE, FIRST, FIRST, "g-first"), (BROKERAGE, SECOND, SECOND, "g-second")]


@pytest.fixture(scope="module")
def browser():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        b = driver.chromium.launch(headless=True)
    except Exception as e:                       # no browser on this machine
        pytest.skip("no browser to drive: %s" % e)
    yield b
    b.close()
    driver.stop()


@pytest.fixture
def page(browser):
    pg = browser.new_page()
    yield pg
    pg.close()


@pytest.fixture
def run(monkeypatch, tmp_path):
    """Stands in for the catch. It presses the element the way the real
    catch does and remembers where the press landed, and a press landing
    on a guid in `brings` hands over that guid's PDF."""
    hits: list = []
    brings: set = set()
    monkeypatch.setattr(site, "goto_documents", lambda pg: True)
    monkeypatch.setattr(site, "expand_all", lambda pg: None)

    def fake(pg, el, label, out_path, trace=None, dl_dir=None, pressed=None, unsure=None):
        before = len(pg.evaluate("window.hits"))
        try:
            el.click(timeout=3000)
        except Exception as e:
            hits.append("click failed " + type(e).__name__)
            return False
        landed = pg.evaluate("window.hits")[before:]
        hits.extend(landed)
        handed = [h for h in landed if h in brings]
        if handed:
            Path(out_path).write_bytes(b"%PDF-1.4\n% invented " + handed[0].encode() + b"\n%%EOF\n")
            return True
        return False
    monkeypatch.setattr(site, "_catch_pdf", fake)

    def download(pg, account, title=BROKERAGE):
        out = tmp_path / "Statements" / "document.pdf"
        trace: list = []
        got = site.download_bill(pg, tmp_path / "dl", DAY, out, title, trace, account=account)
        return got, out, trace
    return hits, brings, download


def _lists(monkeypatch, *accounts, title=BROKERAGE, titles=None):
    """What the lists the page loaded held on DAY."""
    monkeypatch.setattr(site, "_LISTED", {DAY: len(accounts)})
    monkeypatch.setattr(site, "_LISTED_TITLES", {DAY: set(titles or [title])})
    monkeypatch.setattr(site, "_LISTED_ACCOUNTS", {(DAY, title.lower()): {a.lower() for a in accounts}},
                        raising=False)
    monkeypatch.setattr(site, "_LISTED_DOCS", {(DAY, title.lower()): len(accounts)}, raising=False)


def _says_no_account(trace):
    text = json.dumps(trace)
    for leaked in ("Invented", "1111", "2222", "Roth"):
        assert leaked not in text, (leaked, text)


@pytest.mark.parametrize("shape", ["table", "div", "li"])
@pytest.mark.parametrize("account, guid", [(FIRST, "g-first"), (SECOND, "g-second")])
def test_each_account_takes_the_link_naming_its_own_account(page, run, monkeypatch, shape, account, guid):
    """Both rows name the document, so it used to be refused, or the one
    row the page showed was taken whichever account's it was."""
    _lists(monkeypatch, FIRST, SECOND)
    page.set_content(_table(BOTH) if shape == "table" else _divs(BOTH, shape))
    hits, brings, download = run
    brings.update({"g-first", "g-second"})
    got, out, trace = download(page, account)
    assert got and hits == [guid], (hits, trace)
    assert guid.encode() in out.read_bytes()
    _says_no_account(trace)


@pytest.mark.parametrize("shape", ["table", "div", "li"])
def test_a_row_that_names_no_account_is_refused_when_two_accounts_share_the_day(
        page, run, monkeypatch, shape):
    """The lists held both accounts' statements, and the one row the page
    shows names the document with no account, so it may be either one's.
    It was taken as the only row naming the document."""
    _lists(monkeypatch, FIRST, SECOND)
    rows = [(BROKERAGE, SECOND, "", "g-second")]
    page.set_content(_table(rows) if shape == "table" else _divs(rows, shape))
    hits, brings, download = run
    brings.update({"g-first", "g-second"})
    got, out, trace = download(page, FIRST)
    assert not got and not out.exists() and hits == [], hits
    _says_no_account(trace)


@pytest.mark.parametrize("shape", ["table", "div", "li"])
def test_the_only_row_shown_is_never_taken_for_another_account(page, run, monkeypatch, shape):
    """The lists held both accounts' statements, and the page shows only the
    second's, the first on another page of the list."""
    _lists(monkeypatch, FIRST, SECOND)
    rows = BOTH[1:]
    page.set_content(_table(rows) if shape == "table" else _divs(rows, shape))
    hits, brings, download = run
    brings.update({"g-first", "g-second"})
    got, out, trace = download(page, FIRST)
    assert not got and not out.exists() and hits == [], hits


@pytest.mark.parametrize("shape", ["table", "div", "li"])
def test_a_link_naming_another_account_is_never_taken_even_alone(page, run, monkeypatch, shape):
    """The lists gave the day to the first account alone, and the one link
    the page shows names the second."""
    _lists(monkeypatch, FIRST)
    rows = BOTH[1:]
    page.set_content(_table(rows) if shape == "table" else _divs(rows, shape))
    hits, brings, download = run
    brings.update({"g-first", "g-second"})
    got, out, trace = download(page, FIRST)
    assert not got and hits == [], hits


@pytest.mark.parametrize("shape", ["table", "div", "li"])
def test_one_accounts_links_that_name_no_account_are_still_taken(page, run, monkeypatch, shape):
    """The positive twin. With the day the lists gave this account alone, a
    link naming the document with no account is still its own, as before."""
    _lists(monkeypatch, FIRST)
    rows = [(BROKERAGE, FIRST, "", "g-first")]
    page.set_content(_table(rows) if shape == "table" else _divs(rows, shape))
    hits, brings, download = run
    brings.add("g-first")
    got, out, trace = download(page, FIRST)
    assert got and hits == ["g-first"], (hits, trace)


def test_each_step_chooses_by_the_account_on_its_own(page, monkeypatch, tmp_path):
    """The row link, the control and the row walk each read the account, so
    none of them takes the other account's link when an earlier one
    passes it by."""
    _lists(monkeypatch, FIRST, SECOND)
    monkeypatch.setattr(site, "_FOR", {"date": DAY, "title": BROKERAGE.lower(), "account": SECOND.lower()},
                        raising=False)

    def guid(el):
        return el.evaluate("e => (e.closest('[data-guid]') || e).dataset.guid || ''")
    page.set_content(_table(BOTH))
    el, _label_ = site._row_link_for(page, DAY, BROKERAGE, [])
    assert el is not None and guid(el) == "g-second"
    page.set_content(_divs(BOTH))
    el, _label_ = site._control_for(page, DAY, BROKERAGE, [])
    assert el is not None and guid(el) == "g-second"
    pressed: list = []
    monkeypatch.setattr(site, "_catch_pdf", lambda pg, el, *a, **k: pressed.append(guid(el)) or True)
    page.set_content(_divs(BOTH, "li"))
    assert site._try_every_way(page, tmp_path, DAY, tmp_path / "out.pdf", BROKERAGE, [])
    assert pressed == ["g-second"]


# --- the account as a link writes it ----------------------------------------------

SHAPES = ["table", "div", "li"]


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("day", ["alone", "shared"])
@pytest.mark.parametrize("named", ["Invented Brokerage - 1111", "INDIVIDUAL BROKERAGE -1111",
                                   "Invented Brokerage ...1111"])
def test_a_link_writing_the_account_another_way_is_still_its_own(page, run, monkeypatch, shape, day, named):
    """Nothing says a link writes the account exactly as the list does. It
    was compared whole, so a link spacing, capitalizing or masking it
    another way was refused, and every statement would have gone to
    review (review of #96). The masked tails decide."""
    if day == "alone":
        _lists(monkeypatch, FIRST)
        rows = [(BROKERAGE, FIRST, named, "g-first")]
    else:
        _lists(monkeypatch, FIRST, SECOND)
        rows = [(BROKERAGE, SECOND, SECOND, "g-second"), (BROKERAGE, FIRST, named, "g-first")]
    page.set_content(_table(rows) if shape == "table" else _divs(rows, shape))
    hits, brings, download = run
    brings.update({"g-first", "g-second"})
    got, out, trace = download(page, FIRST)
    assert got and hits == ["g-first"], (hits, trace)


@pytest.mark.parametrize("shape", SHAPES)
def test_two_accounts_with_one_tail_are_told_apart_by_their_whole_labels(page, run, monkeypatch, shape):
    twin = "Invented Roth IRA -1111"
    _lists(monkeypatch, FIRST, twin)
    rows = [(BROKERAGE, FIRST, "Invented Brokerage - 1111", "g-first"),
            (BROKERAGE, twin, "INVENTED ROTH IRA - 1111", "g-twin")]
    page.set_content(_table(rows) if shape == "table" else _divs(rows, shape))
    hits, brings, download = run
    brings.update({"g-first", "g-twin"})
    got, out, trace = download(page, twin)
    assert got and hits == ["g-twin"], (hits, trace)


# --- a row of another account the lists left out ------------------------------------

@pytest.mark.parametrize("shape", SHAPES)
def test_a_row_showing_another_accounts_tail_is_never_taken_when_its_link_names_none(
        page, run, monkeypatch, shape):
    """The review's case. The lists gave the day to the first account
    alone, leaving the second's statement out, and the page shows only the
    second's row, its link naming no account. It was saved as the first's."""
    _lists(monkeypatch, FIRST)
    rows = [(BROKERAGE, SECOND, "", "g-second")]
    page.set_content(_table(rows) if shape == "table" else _divs(rows, shape))
    hits, brings, download = run
    brings.update({"g-first", "g-second"})
    got, out, trace = download(page, FIRST)
    assert not got and not out.exists() and hits == [], (hits, trace)
    _says_no_account(trace)


@pytest.mark.parametrize("shape", SHAPES)
def test_a_row_showing_another_accounts_label_is_never_taken_when_neither_shows_digits(
        page, run, monkeypatch, shape):
    """Labels with no masked digits, the other account named by the lists
    on another day."""
    joint, family = "Joint Account", "Family Joint"
    monkeypatch.setattr(site, "_LISTED", {DAY: 1, "2025-07-31": 1})
    monkeypatch.setattr(site, "_LISTED_TITLES", {DAY: {BROKERAGE}, "2025-07-31": {BROKERAGE}})
    monkeypatch.setattr(site, "_LISTED_ACCOUNTS", {(DAY, BROKERAGE.lower()): {joint.lower()},
                                                   ("2025-07-31", BROKERAGE.lower()): {family.lower()}},
                        raising=False)
    rows = [(BROKERAGE, family, "", "g-family")]
    page.set_content(_table(rows) if shape == "table" else _divs(rows, shape))
    hits, brings, download = run
    brings.add("g-family")
    got, out, trace = download(page, joint)
    assert not got and hits == [], (hits, trace)


# --- a document the list gives no account ------------------------------------------
#
# The second report on #96, five accounts. The list can give a document no
# account, an empty displayMultipleAccounts. Every guard that reads the
# account passed such a document, so of several accounts' statements of
# one title and day, the one row the page showed was taken for it,
# whichever account's it was, and discovery kept one of them and dropped
# the rest.

_REAL_COLLECT = site.collect_download_docs


def _listing_of(monkeypatch, *bodies):
    """The documents discovery's own parse reads from searchItems answers,
    the first as the default list and the rest as wider ones."""
    first, wider = bodies[0], bodies[1:]
    _lists_of_this_test(monkeypatch)

    def capturing(page, capture):
        capture.append(first)
        return True

    def widen(page, more, trace=None):
        more.extend(wider)
        return bool(wider)
    monkeypatch.setattr(site, "goto_docs_capturing", capturing)
    monkeypatch.setattr(site, "widen_date_filter", widen)
    return _REAL_COLLECT(None)


def _body(*entries):
    return {"defaultDocumentList": list(entries)}


def _no_ids(title, day=DAY):
    """An entry of the list with no account and no ids of its own."""
    return {"documentTypeName": "STATEMENTS", "documentTitle": title, "documentDate": day + "T00:00:00.000Z"}


def test_five_accounts_statements_the_list_gave_no_account_are_five_records(app, monkeypatch):
    """They were one record, under the key of no account, and four were
    never listed."""
    raws = _listing_of(monkeypatch, _body(*[_entry(BROKERAGE, None, "g%d" % i) for i in range(5)]))
    assert len(raws) == 5 and len({r.entry for r in raws}) == 5
    app.listing(*raws)
    assert len(app.discovery.data) == 5, sorted(app.discovery.data)
    assert all(k.startswith(_legacy_key(BROKERAGE) + "#") for k in app.discovery.data), sorted(app.discovery.data)
    assert {r["account"] for r in app.discovery.data.values()} == {""}
    assert site._LISTED_DOCS[(DAY, "brokerage statement")] == 5
    assert site._LISTED_ACCOUNTS[(DAY, "brokerage statement")] == {""}


def test_statements_with_and_without_an_account_are_each_kept(app, monkeypatch):
    raws = _listing_of(monkeypatch, _body(
        _entry(BROKERAGE, FIRST, "g1"), _entry(BROKERAGE, SECOND, "g2"), _entry(BROKERAGE, None, "g3"),
        _entry(BROKERAGE, "", "g4"), _entry(RETIREMENT, None, "g5")))
    assert len(raws) == 5
    app.listing(*raws)
    keys = sorted(app.discovery.data)
    assert {_key(BROKERAGE, "1111"), _key(BROKERAGE, "2222"), _legacy_key(RETIREMENT)} <= set(keys), keys
    assert len([k for k in keys if k.startswith(_legacy_key(BROKERAGE) + "#")]) == 2, keys
    assert len(keys) == 5


def test_entries_with_no_ids_are_told_apart_by_their_place_and_counted_once_across_lists(monkeypatch):
    """The default list and a wider one both hold the two entries."""
    both = _body(_no_ids(BROKERAGE), _no_ids(BROKERAGE))
    raws = _listing_of(monkeypatch, both, both)
    assert sorted(r.entry for r in raws) == ["#1", "#2"]


@pytest.mark.parametrize("ids", [True, False], ids=["with ids", "with none"])
def test_a_sign_in_of_one_account_the_list_gives_no_account_keeps_every_key(app, monkeypatch, ids):
    """One document of each date and title, so nothing is added to its key,
    and what it saved before stays saved and is not taken again."""
    days = ("2025-07-31", DAY)
    for day in days:
        _saved_before(app, BROKERAGE, "%s ETRADE Account Statement.pdf" % day, day=day)
    before = json.loads(json.dumps(app.progress.data))
    entries = [_entry(BROKERAGE, None, "g-" + day, day=day) if ids else _no_ids(BROKERAGE, day=day)
               for day in days]
    raws = _listing_of(monkeypatch, _body(*entries))
    assert [r.entry for r in raws] == ["", ""]
    app.listing(*raws)
    assert app.progress.data == before
    assert sorted(app.discovery.data) == sorted(_legacy_key(BROKERAGE, day) for day in days)
    assert [d for d in app._select() if not app._already_done(d)] == []


def _lists_no_label(monkeypatch, n=2):
    """What the lists held on DAY when they gave its `n` Brokerage
    Statements no account."""
    monkeypatch.setattr(site, "_LISTED", {DAY: n})
    monkeypatch.setattr(site, "_LISTED_TITLES", {DAY: {BROKERAGE}})
    monkeypatch.setattr(site, "_LISTED_ACCOUNTS", {(DAY, BROKERAGE.lower()): {""}})
    monkeypatch.setattr(site, "_LISTED_DOCS", {(DAY, BROKERAGE.lower()): n})


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("labels", ["two accounts", "no labels"])
@pytest.mark.parametrize("rows", ["one of two shown", "a bare title shown", "both shown"])
def test_a_document_of_no_account_is_never_taken_on_a_day_its_title_is_shared(
        page, run, monkeypatch, shape, labels, rows):
    """The lists held two documents of its date and title, with accounts or
    with none. The one row the page showed was taken for it, whichever
    account's it was, and with two shown both were refused."""
    if labels == "two accounts":
        _lists(monkeypatch, FIRST, SECOND)
    else:
        _lists_no_label(monkeypatch)
    shown = {"one of two shown": BOTH[1:], "a bare title shown": [(BROKERAGE, SECOND, "", "g-second")],
             "both shown": BOTH}[rows]
    page.set_content(_table(shown) if shape == "table" else _divs(shown, shape))
    hits, brings, download = run
    brings.update({"g-first", "g-second"})
    got, out, trace = download(page, "")
    assert not got and not out.exists() and hits == [], (hits, trace)
    assert [t["why"] for t in trace if "why" in t] == [site.SHARED_WITH_NO_ACCOUNT], trace
    _says_no_account(trace)


@pytest.mark.parametrize("shape", SHAPES)
def test_a_document_of_no_account_the_lists_held_alone_that_day_is_still_taken(page, run, monkeypatch, shape):
    """The positive twin, a sign-in of one account the list gives no
    account."""
    _lists_no_label(monkeypatch, n=1)
    rows = [(BROKERAGE, "", "", "g-only")]
    page.set_content(_table(rows) if shape == "table" else _divs(rows, shape))
    hits, brings, download = run
    brings.add("g-only")
    got, out, trace = download(page, "")
    assert got and hits == ["g-only"], (hits, trace)


@pytest.mark.parametrize("shape", SHAPES)
def test_the_one_row_naming_its_account_is_refused_when_the_page_shows_fewer_than_the_lists_gave(
        page, run, monkeypatch, shape):
    """The lists held both accounts' statements and the page shows only the
    second's, so the rows it shows are not every document of the day. With
    both shown each account's is taken
    (test_each_account_takes_the_link_naming_its_own_account)."""
    _lists(monkeypatch, FIRST, SECOND)
    rows = BOTH[1:]
    page.set_content(_table(rows) if shape == "table" else _divs(rows, shape))
    hits, brings, download = run
    brings.update({"g-first", "g-second"})
    got, out, trace = download(page, SECOND)
    assert not got and not out.exists() and hits == [], (hits, trace)
    assert site.FEWER_NAMED in {t.get("why") for t in trace}, trace
    _says_no_account(trace)


def test_each_step_counts_the_rows_the_lists_gave(page, monkeypatch, tmp_path):
    """The row link, the control and the row walk each count the rows naming
    the document, so none of them takes the one row shown when an earlier
    one refuses it."""
    _lists(monkeypatch, FIRST, SECOND)
    monkeypatch.setattr(site, "_FOR", {"date": DAY, "title": BROKERAGE.lower(), "account": SECOND.lower()},
                        raising=False)
    trace: list = []
    page.set_content(_table(BOTH[1:]))
    assert site._row_link_for(page, DAY, BROKERAGE, trace) == (None, "")
    page.set_content(_divs(BOTH[1:]))
    assert site._control_for(page, DAY, BROKERAGE, trace) == (None, "")
    pressed: list = []
    monkeypatch.setattr(site, "_catch_pdf", lambda pg, el, *a, **k: pressed.append(el) or True)
    page.set_content(_divs(BOTH[1:], "li"))
    assert not site._try_every_way(page, tmp_path, DAY, tmp_path / "out.pdf", BROKERAGE, trace)
    assert pressed == []
    assert [t["way"] for t in trace if t.get("why") == site.FEWER_NAMED] == ["row link", "control", "row by date"]


# --- what the docs side does with what is saved, and with a refusal -----------------

def _taking(app, monkeypatch, handed):
    """download_one with the site layer handing over handed[account] as
    the PDF of each document, and what it wrote down."""
    failures: list = []

    def download_bill(page, dl_dir, iso, out_path, title="", trace=None, account=""):
        Path(out_path).write_bytes(handed[account])
        return True
    monkeypatch.setattr(site, "download_bill", download_bill)
    app._dl_dir = app.paths.root / "dl"
    app.write_failure = lambda *a, **k: failures.append(a)
    app._journal = SimpleNamespace(checkpoint=lambda *a, **k: None, op=lambda *a, **k: None)
    app.stats.update(manual_review=0, duplicate_filenames=0, validation_failures=0, new_files=[], dates=[],
                     statements=0, tax_documents=0, insurance_documents=0, other=0)

    def take(doc):
        app.download_one(SimpleNamespace(url=""), doc,
                         storage.build_pdf_filename(doc.date, doc.summary, "", record=doc))
        return app.progress.data[doc.key]
    return take, failures


def _doc_of(app, account, title=BROKERAGE):
    return next(d for d in app._select() if d.account == account and d.title == title)


def test_a_document_of_no_account_on_a_shared_day_goes_to_manual_review_and_nothing_is_pressed(app, monkeypatch):
    raws = _listing_of(monkeypatch, _body(_entry(BROKERAGE, None, "g1"), _entry(BROKERAGE, None, "g2")))
    app.listing(*raws)
    take, failures = _taking(app, monkeypatch, {})
    pressed: list = []
    monkeypatch.setattr(site, "download_bill", _REAL_DOWNLOAD)
    monkeypatch.setattr(site, "_row_link_for", lambda *a, **k: pressed.append(a) or (None, ""))
    for doc in app._select():
        rec = take(doc)
        assert (rec["state"], rec.get("downloaded_ok", False)) == ("Needs Manual Review", False), rec
        assert etrade_docs.App.NO_ACCOUNT in rec["notes"]
    assert pressed == [] and app.stats["manual_review"] == 2
    assert failures and failures[0] == ("choose the document", "the list gave the document no account")
    assert not any(app.paths.folder_for("Statement").iterdir())
    attempt = json.loads((app.paths.diagnostics / "download-attempt.json").read_text(encoding="utf-8"))
    assert site.SHARED_WITH_NO_ACCOUNT in json.dumps(attempt)


_REAL_DOWNLOAD = site.download_bill


def test_a_pdf_the_same_as_another_records_of_that_day_is_set_aside(app, monkeypatch):
    """Two accounts' records of one day handed one PDF. The second is that
    same document taken again, and was kept as its own."""
    app.listing(_raw(BROKERAGE, FIRST, "g1"), _raw(RETIREMENT, SECOND, "g2"))
    same = testkit.text_pdf(_statement("Account Number: XXXX-2222"))
    take, failures = _taking(app, monkeypatch, {FIRST: same, SECOND: same})
    second = take(_doc_of(app, SECOND, RETIREMENT))
    assert second["downloaded_ok"] is True and Path(second["pdf_path"]).exists()
    first = take(_doc_of(app, FIRST))
    assert (first["state"], first.get("downloaded_ok")) == ("Needs Manual Review", False), first
    assert etrade_docs.App.SAME_PDF in first["notes"]
    assert Path(first["pdf_path"]).parent == app.paths.manual_review and Path(first["pdf_path"]).exists()
    assert app.progress.data[_key(RETIREMENT, "2222")] == second
    assert failures == [("save the document", "two documents gave the same file")]
    # Set aside, it is not taken again on the next run while its copy is there.
    assert app._already_done(_doc_of(app, FIRST))


def test_a_pdf_the_same_as_a_file_saved_before_digests_were_kept_is_set_aside(app, monkeypatch):
    path = _saved_before(app, RETIREMENT, "%s ETRADE Account Statement.pdf" % DAY,
                         prints=_statement("Account Number: XXXX-1111"))
    app.listing(_raw(BROKERAGE, FIRST, "g1"), _raw(RETIREMENT, FIRST, "g2"))
    assert not app.progress.data[_key(RETIREMENT, "1111")].get("pdf_sha256")
    take, _failures = _taking(app, monkeypatch, {FIRST: path.read_bytes()})
    rec = take(_doc_of(app, FIRST))
    assert rec["state"] == "Needs Manual Review" and etrade_docs.App.SAME_PDF in rec["notes"], rec


def test_two_different_pdfs_of_one_day_are_both_kept(app, monkeypatch):
    app.listing(_raw(BROKERAGE, FIRST, "g1"), _raw(BROKERAGE, SECOND, "g2"))
    take, _failures = _taking(app, monkeypatch, {FIRST: testkit.text_pdf(_statement("Account Number: XXXX-1111")),
                                                 SECOND: testkit.text_pdf(_statement("Account Number: XXXX-2222"))})
    assert all(take(_doc_of(app, a))["downloaded_ok"] is True for a in (FIRST, SECOND))


def test_a_statement_taken_again_the_same_as_the_record_kept_before_is_kept(app, monkeypatch):
    """0.53.0 takes each account's statement of a day again beside the
    record kept before, which held one of them. The one whose bytes are that
    file's is that account's, and is kept."""
    old = _saved_before(app, BROKERAGE, "%s ETRADE Account Statement.pdf" % DAY,
                        prints=_statement("No account printed"))
    _both_on_one_day(app)
    take, _failures = _taking(app, monkeypatch, {FIRST: old.read_bytes()})
    assert take(_doc_of(app, FIRST))["downloaded_ok"] is True


def test_a_record_whose_file_was_deleted_holds_nothing_against_the_file_now_under_its_name(app, monkeypatch):
    """Files are deleted once imported elsewhere, and the next statement of
    that name takes it. The record kept before still names it."""
    gone = _saved_before(app, RETIREMENT, "%s ETRADE Account Statement.pdf" % DAY)
    gone.unlink()
    app.listing(_raw(BROKERAGE, FIRST, "g1"), _raw(RETIREMENT, FIRST, "g2"))
    take, _failures = _taking(app, monkeypatch, {FIRST: testkit.text_pdf(_statement("Invented"))})
    rec = take(_doc_of(app, FIRST))
    assert rec["downloaded_ok"] is True and rec["pdf_path"] == str(gone), rec


def test_a_second_accounts_file_says_whose_it_is_when_the_pattern_leaves_the_account_out(app, monkeypatch):
    """It was told apart by " (2)", which says nothing about which account's
    it is. Rename tells it apart the same way."""
    monkeypatch.setattr(core_storage, "_FILENAME_PATTERN", "{date:yyyy-mm-dd} {kind}")
    app.listing(_raw(BROKERAGE, FIRST, "g1"), _raw(BROKERAGE, SECOND, "g2"))
    take, _failures = _taking(app, monkeypatch, {FIRST: testkit.text_pdf(_statement("Account Number: XXXX-1111")),
                                                 SECOND: testkit.text_pdf(_statement("Account Number: XXXX-2222"))})
    first, second = take(_doc_of(app, FIRST)), take(_doc_of(app, SECOND))
    assert Path(second["pdf_path"]).name == Path(first["pdf_path"]).stem + " 2222.pdf", (first, second)
    assert second["told_apart"] == "2222"
    folder = app.paths.folder_for("Statement")
    names = sorted(p.name for p in folder.iterdir())
    app.args.apply = True
    app.cmd_rename()
    assert sorted(p.name for p in folder.iterdir()) == names


def test_a_file_told_apart_by_a_number_before_keeps_its_name(app):
    """A sign-in of one account, two statements of one day saved before
    #96, the second as " (2)". Its record now holds the account, whose
    digits the download tells a file apart by today, and Rename leaves
    the name it was saved under."""
    files = [_saved_before(app, BROKERAGE, "%s ETRADE Account Statement.pdf" % DAY),
             _saved_before(app, RETIREMENT, "%s ETRADE Account Statement (2).pdf" % DAY)]
    app.listing(_raw(BROKERAGE, FIRST, "g1"), _raw(RETIREMENT, FIRST, "g2"))
    assert app.progress.data[_key(RETIREMENT, "1111")]["account"] == FIRST
    app.args.apply = True
    app.cmd_rename()
    assert all(p.exists() for p in files)
