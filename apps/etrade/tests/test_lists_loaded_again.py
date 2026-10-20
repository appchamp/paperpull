"""A list loaded again lists the same documents once, and every page of it
is read (#96, after 0.56.0).

0.56.0 told apart documents the list gave no account by the list's own ids
for each, documentGuid and documentId. A tester showed both change every
time the list loads. The default list and each period's list hold the same
statements under new ids, so each came out of discovery once for every list
holding it, and again on every Discover. A date of two statements held ten
records on his sign-in, and Run All saved the copies of one of them as
"Statement (3)" to "(6)", since its PDF differs by a byte or two each time
it is made. Such a document is now told apart by its place among those of
its date and title, which the next load gives it again, and the next
Discover folds the records 0.56.0 kept under the ids into one for each
document, taking nothing again.

The page asks searchItems for one page of a period's list at a time, and
the answer counts the whole list, numFound. Discovery read the first page
alone. Each later page is now asked the way the page asked for the first,
and a list that cannot be read to its end leaves the listing unread, so the
run says so and stops before it takes anything, and no record moves.

Everything here is invented.
"""
import hashlib
import itertools
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import etrade_docs
import etrade_site as site
from paperpull_core import doc_types, listing
from paperpull_core.models import State

DAY = "2026-09-30"
BANK = "Bank Statement"
SINGLE = "Single Account Statement"
_ids = itertools.count(1)


def _entry(title, day=DAY, account=""):
    """One entry of a searchItems answer, with ids no other load gives, the
    way E*TRADE's change on every load."""
    n = next(_ids)
    return {"documentGuid": "{guid-%d}" % n, "documentId": "x&rowId=060124-17%011d" % n,
            "documentTypeName": "STATEMENTS", "documentTitle": title,
            "documentDate": day + "T00:00:00.000Z", "displayMultipleAccounts": account}


def _list(*entries, counted=True):
    body = {"defaultDocumentList": list(entries)}
    if counted:
        body["numFound"] = str(len(entries))
    return body


def _his_month(day=DAY):
    """A month of the tester's, a cash account's Bank Statement and a
    brokerage account's Single Account Statement, neither with an account
    in the list."""
    return [_entry(BANK, day), _entry(SINGLE, day)]


def _forget_lists(monkeypatch):
    for name in ("_LISTED", "_LISTED_TITLES", "_LISTED_ACCOUNTS", "_LISTED_DOCS"):
        monkeypatch.setattr(site, name, {})


_REAL_COLLECT = site.collect_download_docs


def _discovered(monkeypatch, first, *wider):
    """What discovery's own parse makes of searchItems answers, the first as
    the default list and the rest as the periods' lists."""
    _forget_lists(monkeypatch)

    def capturing(page, capture):
        capture.append(first)
        return True

    def widen(page, more, trace=None):
        more.extend(wider)
        return bool(wider)
    monkeypatch.setattr(site, "goto_docs_capturing", capturing)
    monkeypatch.setattr(site, "widen_date_filter", widen)
    return _REAL_COLLECT(None)


def _legacy_key(title, day=DAY):
    return "Statement:%s:%s:Unnamed" % (day, title)


def _key_by_ids(title, ids, day=DAY):
    """The key 0.56.0 gave a document the list gave no account when another
    such document shared its date and title, by the list's ids for it."""
    return etrade_docs.Document(category="Statement", date=day, title=title, entry=ids).key


# --- the same statements in every list, under new ids each time ---------------

def test_the_default_list_and_a_periods_list_give_each_statement_once(monkeypatch):
    """Each list gives the month's two statements under ids of its own. They
    came out as four documents, each told apart by its ids, and so shared."""
    raws = _discovered(monkeypatch, _list(*_his_month()), _list(*_his_month()), _list(*_his_month()))
    assert sorted((r.title, r.entry) for r in raws) == [(BANK, ""), (SINGLE, "")]
    assert raws.unread == ()


def test_two_statements_of_one_title_and_day_keep_their_places_when_the_ids_change(monkeypatch):
    """Two accounts' statements of one title and day the list gives no
    account, loaded twice. Their places are the same both times."""
    raws = _discovered(monkeypatch, _list(_entry(SINGLE), _entry(SINGLE)),
                       _list(_entry(SINGLE), _entry(SINGLE)))
    assert sorted(r.entry for r in raws) == ["#1", "#2"]


@pytest.fixture
def app(tmp_path, monkeypatch):
    """The app's own discovery, with the page's lists stood in for by
    searchItems answers that discovery's own parse reads."""
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
    a.failures = []
    a.write_failure = lambda step, reason, *more, **kw: a.failures.append((step, reason))
    monkeypatch.setattr(site, "goto_documents", lambda page: True)

    def discover(*bodies):
        raws = _discovered(monkeypatch, *bodies)
        monkeypatch.setattr(site, "collect_download_docs", lambda page: raws)
        a.cmd_discover(quiet=True)
        return a
    a.listing = discover
    return a


def _left_to_take(app):
    return sorted((d.date, d.title) for d in app._select() if not app._already_done(d))


def test_a_second_discover_adds_no_record_for_statements_it_already_listed(app):
    """His Discover and then his Run All each added four records for the
    month's two statements."""
    app.listing(_list(*_his_month()), _list(*_his_month()))
    first = sorted(app.discovery.data)
    assert first == [_legacy_key(BANK), _legacy_key(SINGLE)]
    app.listing(_list(*_his_month()), _list(*_his_month()), _list(*_his_month()))
    assert sorted(app.discovery.data) == first


def test_two_statements_of_one_title_and_day_stay_two_records_on_every_discover(app):
    for _ in range(3):
        app.listing(_list(_entry(SINGLE), _entry(SINGLE)), _list(_entry(SINGLE), _entry(SINGLE)))
    keys = sorted(app.discovery.data)
    assert len(keys) == 2 and all(k.startswith(_legacy_key(SINGLE) + "#") for k in keys), keys


# --- what 0.56.0 kept under the ids, folded on the next Discover ---------------

def _record(app, title, key, name=None, state=State.COMPLETED, folder=None, at="2026-10-19T14:00:00",
            ids=""):
    """A record of the month's statement under `key`, its file `name` saved
    in `folder` (the Statement folder unless given), the way a Run All
    left it, in progress and in discovery."""
    doc = etrade_docs.Document(title=title, category="Statement", summary="Account Statement",
                               date=DAY, confidence="High", source_url=site.BILLING_URL, entry=ids)
    assert doc.key == key
    doc.discovered_at = at
    doc.state = state.value
    if name:
        path = (folder or app.paths.folder_for("Statement")) / name
        path.write_bytes(b"%PDF-1.4\n% invented " + name.encode() + b"\n" + b"0" * 2100)
        doc.pdf_path, doc.pdf_filename = str(path), path.name
    if state == State.COMPLETED:
        doc.downloaded_ok = True
    app.progress.data[key] = doc.to_dict()
    app.discovery.data[key] = dict(doc.to_dict())
    return doc


def _his_records(app):
    """His sign-in after 0.56.0. The month's statements saved on Oct 15
    under the key of no account, then under the ids, from today's Discover
    and Run All, two copies of the Bank Statement in Manual Review, the
    Single Account Statement saved again as "(3)" and "(4)", and records
    discovery left that nothing took."""
    review = app.paths.manual_review
    _record(app, BANK, _legacy_key(BANK), "2026-09-30 Statement.pdf", at="2026-10-15T09:00:00")
    _record(app, SINGLE, _legacy_key(SINGLE), "2026-09-30 Statement (2).pdf", at="2026-10-15T09:00:00")
    for n, (title, name, state, folder) in enumerate([
            (BANK, "2026-09-30 Statement.pdf", State.NEEDS_MANUAL_REVIEW, review),
            (BANK, "2026-09-30 Statement (2).pdf", State.NEEDS_MANUAL_REVIEW, review),
            (SINGLE, "2026-09-30 Statement (3).pdf", State.COMPLETED, None),
            (SINGLE, "2026-09-30 Statement (4).pdf", State.COMPLETED, None),
            (BANK, None, State.DISCOVERED, None),
            (SINGLE, None, State.DISCOVERED, None)]):
        ids = "{old-%d}|x&rowId=060124-1760%09d" % (n, n)
        _record(app, title, _key_by_ids(title, ids), name, state, folder, ids=ids)
    app.progress.save()
    app.discovery.save()


def test_the_records_kept_under_the_ids_fold_into_one_for_each_statement(app):
    _his_records(app)
    before = {k: dict(v) for k, v in app.progress.data.items() if k in (_legacy_key(BANK), _legacy_key(SINGLE))}
    files = sorted(p.name for p in app.paths.root.rglob("*.pdf"))
    app.listing(_list(*_his_month()), _list(*_his_month()))
    assert sorted(app.discovery.data) == [_legacy_key(BANK), _legacy_key(SINGLE)]
    assert sorted(app.progress.data) == [_legacy_key(BANK), _legacy_key(SINGLE)]
    for key, rec in before.items():
        assert app.progress.data[key]["pdf_path"] == rec["pdf_path"]
        assert app.progress.data[key]["downloaded_ok"] is True
    assert _left_to_take(app) == []
    # No file is touched. He deletes the copies himself.
    assert sorted(p.name for p in app.paths.root.rglob("*.pdf")) == files
    backups = {p.name.split(".")[0] for p in app.paths.backups.iterdir()}
    assert {"progress", "discovery"} <= backups


@pytest.mark.parametrize("second_at", ["2026-10-19T15:00:00", "2026-10-19T14:00:00"],
                         ids=["listed later", "listed together"])
def test_a_sign_in_that_began_on_0_56_0_keeps_the_statement_it_saved(app, second_at):
    """No record under the key of no account. The first copy saved takes
    that key, holding nothing of the ids, and is never fetched again. Of
    two one Discover listed together, the one whose file has no number."""
    ids = ["{a}|x&rowId=060124-1760000000001", "{b}|x&rowId=060124-1760000000002",
           "{c}|x&rowId=060124-1760000000003"]
    _record(app, SINGLE, _key_by_ids(SINGLE, ids[0]), None, State.DISCOVERED, ids=ids[0],
            at="2026-10-19T13:00:00")
    _record(app, SINGLE, _key_by_ids(SINGLE, ids[2]), "2026-09-30 Statement (2).pdf", ids=ids[2],
            at=second_at)
    _record(app, SINGLE, _key_by_ids(SINGLE, ids[1]), "2026-09-30 Statement.pdf", ids=ids[1],
            at="2026-10-19T14:00:00")
    app.listing(_list(_entry(SINGLE)), _list(_entry(SINGLE)))
    assert sorted(app.progress.data) == sorted(app.discovery.data) == [_legacy_key(SINGLE)]
    rec = app.progress.data[_legacy_key(SINGLE)]
    assert Path(rec["pdf_path"]).name == "2026-09-30 Statement.pdf" and rec["entry"] == ""
    assert etrade_docs.Document.from_dict(app.discovery.data[_legacy_key(SINGLE)]).key == _legacy_key(SINGLE)
    assert _left_to_take(app) == []


def test_on_a_day_two_statements_share_their_title_only_records_holding_nothing_go(app):
    """Which of the two each record holds cannot be told. A record holding a
    saved statement or a file stays as it is, and one holding nothing goes."""
    ids = ["{d}|x&rowId=060124-1760000000004", "{e}|x&rowId=060124-1760000000005",
           "{f}|x&rowId=060124-1760000000006"]
    _record(app, SINGLE, _key_by_ids(SINGLE, ids[0]), None, State.NEEDS_MANUAL_REVIEW, ids=ids[0])
    _record(app, SINGLE, _key_by_ids(SINGLE, ids[1]), "2026-09-30 Statement.pdf",
            State.NEEDS_MANUAL_REVIEW, app.paths.manual_review, ids=ids[1])
    _record(app, SINGLE, _key_by_ids(SINGLE, ids[2]), "2026-09-30 Statement (2).pdf", ids=ids[2])
    app.listing(_list(_entry(SINGLE), _entry(SINGLE)))
    assert _key_by_ids(SINGLE, ids[0]) not in app.progress.data
    assert {_key_by_ids(SINGLE, ids[1]), _key_by_ids(SINGLE, ids[2])} <= set(app.progress.data)


def test_a_record_of_a_document_the_lists_no_longer_give_stays(app):
    ids = "{g}|x&rowId=060124-1760000000007"
    _record(app, SINGLE, _key_by_ids(SINGLE, ids, ), "2026-09-30 Statement.pdf", ids=ids)
    app.listing(_list(_entry(BANK)))
    assert _key_by_ids(SINGLE, ids) in app.progress.data


@pytest.mark.parametrize("key, record, legacy", [
    (_key_by_ids(SINGLE, "{h}|x"), {"entry": "{h}|x", "account": ""}, _legacy_key(SINGLE)),
    # --minimal keeps no entry, and the key alone says what it is.
    (_key_by_ids(SINGLE, "{h}|x"), {"state": "Completed", "downloaded_ok": True}, _legacy_key(SINGLE)),
    # A place among documents sharing a date and title is today's key.
    (_key_by_ids(SINGLE, "#2"), {"entry": "#2", "account": ""}, ""),
    (_key_by_ids(SINGLE, "#2"), {"state": "Completed"}, ""),
    # The key of no account itself, an account's key, and a whole label's.
    (_legacy_key(SINGLE), {"account": ""}, ""),
    ("Statement:%s:%s:1111" % (DAY, SINGLE), {"account": "Invented Brokerage -1111"}, ""),
    (etrade_docs.Document(category="Statement", date=DAY, title=SINGLE, account="Invented " * 12,
                          whole_label=True).key, {"account": "Invented " * 12}, ""),
])
def test_what_a_record_kept_under_the_ids_looks_like(key, record, legacy):
    assert etrade_docs.keyed_by_ids(key, record) == legacy


# --- a list not read to its end ------------------------------------------------

def _not_whole(monkeypatch, app, *entries, why=site.PAGE_REFUSED):
    raws = _discovered(monkeypatch, _list(*(entries or _his_month())))
    raws.unread = (why,)
    monkeypatch.setattr(site, "collect_download_docs", lambda page: raws)


def test_a_discover_whose_list_was_not_read_to_its_end_stops_and_moves_nothing(app, monkeypatch):
    _his_records(app)
    before = json.loads(json.dumps(app.progress.data))
    _not_whole(monkeypatch, app)
    with pytest.raises(SystemExit):
        app.cmd_discover(quiet=True)
    assert app.progress.data == before
    assert listing.last(app) == listing.STOPPED
    assert app.failures == [("read the documents list", site.PAGE_REFUSED)]


def test_a_list_not_read_to_its_end_moves_no_saved_statement_to_an_account(app, monkeypatch):
    """A sign-in whose lists name one account moves what it saved before #96
    to that account's key. Lists missing a page may name one account of
    several, so the move waits for lists read whole."""
    account = "Invented Brokerage -1111"
    _record(app, SINGLE, _legacy_key(SINGLE), "2026-09-30 Statement.pdf")
    before = json.loads(json.dumps(app.progress.data))
    _not_whole(monkeypatch, app, _entry(SINGLE, account=account))
    with pytest.raises(SystemExit):
        app.cmd_discover(quiet=True)
    assert app.progress.data == before
    app.listing(_list(_entry(SINGLE, account=account)))
    assert sorted(app.progress.data) == ["Statement:%s:%s:1111" % (DAY, SINGLE)]


def test_a_discover_whose_lists_were_read_whole_is_noted_whole(app):
    app.listing(_list(*_his_month()))
    assert listing.last(app) == listing.COMPLETE and app.failures == []


def test_pilot_run_all_and_resume_take_nothing_from_a_list_not_read_to_its_end(app, monkeypatch, capsys):
    """The download chooses a row by what the lists said, and lists missing a
    page can say a date holds one document when it holds two (review)."""
    _his_records(app)
    _not_whole(monkeypatch, app)
    taken: list = []
    app.process = lambda docs, dry_run=False: taken.extend(d.title for d in docs)
    app._pilot_report = lambda docs: None
    app.config["pilot_count"] = 5
    for run in (app.cmd_pilot, lambda: app.cmd_run("dry-run"), app.cmd_resume):
        with pytest.raises(SystemExit):
            run()
    assert taken == []
    assert "downloads nothing" in " ".join(capsys.readouterr().out.split())


# --- a record told apart by its entry, on a day no longer shared ---------------

def _taking(app):
    """process() with the download stood in for, and what it took."""
    taken: list = []
    app._on_its_site = lambda: None
    app._delay = lambda factor=1.0: None
    app.download_one = lambda page, doc, filename: taken.append(doc.key)
    app.stats.update(skipped_completed=0)
    return taken


def test_two_place_records_holding_nothing_go_when_the_lists_give_one(app):
    """The reviewer's case. The lists gave two statements of one title and
    day with no account, and the download refused both. A later Discover
    gives one."""
    app.listing(_list(_entry(SINGLE), _entry(SINGLE)))
    for rec in app.discovery.data.values():
        rec["state"] = State.NEEDS_MANUAL_REVIEW.value
    app.listing(_list(_entry(SINGLE)))
    assert sorted(app.discovery.data) == [_legacy_key(SINGLE)]
    taken = _taking(app)
    app.process(app._select())
    assert taken == [_legacy_key(SINGLE)]


@pytest.mark.parametrize("kept", ["a place holding a review copy", "ids the lists no longer give"])
def test_a_record_told_apart_by_its_entry_is_never_taken_once_its_day_is_not_shared(app, kept):
    """Taken, the one row the page shows was saved once for each such record,
    the reported copies again."""
    if kept == "a place holding a review copy":
        key = _key_by_ids(SINGLE, "#2")
        _record(app, SINGLE, key, "2026-09-30 Statement.pdf", State.NEEDS_MANUAL_REVIEW,
                app.paths.manual_review, ids="#2")
        app.paths.manual_review.joinpath("2026-09-30 Statement.pdf").write_bytes(b"not a pdf")
        listed = _list(_entry(SINGLE))
    else:
        key = _key_by_ids(SINGLE, "{z}|x", day="2026-06-30")
        doc = etrade_docs.Document(title=SINGLE, category="Statement", summary="Account Statement",
                                   date="2026-06-30", entry="{z}|x")
        app.discovery.data[key] = doc.to_dict()
        listed = _list(_entry(SINGLE))
    app.listing(listed)
    assert key in app.discovery.data
    taken = _taking(app)
    app.process(app._select())
    assert taken == [_legacy_key(SINGLE)]


def test_records_of_a_day_still_shared_go_on_to_the_download_which_refuses_them(app):
    app.listing(_list(_entry(SINGLE), _entry(SINGLE)))
    taken = _taking(app)
    app.process(app._select())
    assert len(taken) == 2


# --- every page, through the request the page made ----------------------------

class _Response:
    """What a listener hears, the answer and the request that asked, with
    the headers the page's script sent and those the network sent."""

    def __init__(self, url, body, headers, network=None, method="POST"):
        network = dict(headers, **(network or {}))
        self.request = SimpleNamespace(url=url, method=method, post_data=json.dumps(body),
                                       all_headers=lambda: dict(network), headers=dict(headers))


API = "https://ext-web.etrade.com/etaz/api/adsal/accountdocs/v2/searchItems?RequestID=7&SeqID=1"


def test_a_later_page_is_asked_with_the_headers_the_page_sent():
    """The page's own, less what the browser sets itself. What the network
    added would make the later page ask the server's leave first, which the
    page's own request never did."""
    asked = site._asked_of(_Response(API, {"TimeFrame": "2025", "pageNum": 1}, {
        "content-type": "text/plain", "x-invented-token": "t", "sec-ch-ua": "x", "user-agent": "x",
        "referer": "x"}, network={":authority": "ext-web.etrade.com", "cookie": "invented=1",
                                  "cache-control": "no-cache", "pragma": "no-cache"}))
    assert asked["headers"] == {"content-type": "text/plain", "x-invented-token": "t"}
    assert asked["cookie"] is True and asked["body"] == {"TimeFrame": "2025", "pageNum": 1}
    assert site._asked_of(_Response(API, {"pageNum": 1}, {"content-type": "text/plain"}))["cookie"] is False
    assert site._asked_of(_Response(API, {"pageNum": 1}, {}, method="GET")) == {}


class _Page:
    """A tab on the documents page whose in-page fetch answers each page
    number with `answer`."""

    def __init__(self, answer, url="https://us.etrade.com/etx/pxy/accountdocs#/documents"):
        self.answer = answer
        self.url = url
        self.asked = []
        self.paused = []

    def wait_for_timeout(self, ms):
        self.paused.append(ms)

    def evaluate(self, js, arg):
        url, headers, body, credentials = arg
        self.asked.append(body)
        return self.answer(body)


def test_a_later_page_is_never_asked_from_a_tab_on_another_site():
    """The page's own headers would go with it, to that site's scripts."""
    page = _Page(lambda body: pytest.fail("asked"), url="https://invented.example/documents")
    first = _first(4)
    assert site._later_pages(page, _asked(), first) == (first, 1, site.PAGE_UNREAD)


def _first(total, size=2):
    return dict(_list(*[_entry(SINGLE, "2025-%02d-28" % (12 - i)) for i in range(size)]),
                numFound=str(total))


def _asked(page_num=1):
    return {"url": API, "body": {"TimeFrame": "2025", "pageNum": page_num}, "headers": {},
            "cookie": False}


def _answer_of(pages):
    def answer(body):
        got = pages.get(int(body["pageNum"]))
        if isinstance(got, int):
            return {"status": got, "url": API, "data": None}
        return {"status": 200, "url": API, "data": got}
    return answer


def test_every_later_page_is_read_into_the_one_list():
    page = _Page(_answer_of({2: _list(_entry(SINGLE, "2025-10-31"), _entry(SINGLE, "2025-09-30")),
                             3: _list(_entry(BANK, "2025-09-30"))}))
    body, pages, why = site._later_pages(page, _asked(), _first(5))
    assert (pages, why) == (3, "")
    assert [b["pageNum"] for b in page.asked] == [2, 3]
    assert page.paused == [site.PAGE_PAUSE_MS] * 2
    assert all(b["TimeFrame"] == "2025" for b in page.asked)
    assert len(body["defaultDocumentList"]) == 5 and body["numFound"] == "5"


def test_a_page_number_written_as_a_word_of_digits_is_asked_the_same_way():
    page = _Page(_answer_of({1: _list(_entry(BANK, "2025-01-31"))}))
    body, pages, why = site._later_pages(page, _asked("0"), _first(3))
    assert [b["pageNum"] for b in page.asked] == ["1"] and (pages, why) == (2, "")


@pytest.mark.parametrize("pages, why", [
    ({2: 500}, site.PAGE_REFUSED),
    ({2: 0}, site.PAGE_UNREAD),
    ({2: {"error": "invented"}}, site.PAGE_UNREAD),
    ({2: {"defaultDocumentList": []}}, site.PAGE_EMPTY),
], ids=["refused", "no answer", "no list", "empty"])
def test_a_later_page_that_does_not_come_leaves_the_list_unread(pages, why):
    first = _first(4)
    body, read, got = site._later_pages(_Page(_answer_of(pages)), _asked(), first)
    assert (read, got) == (1, why)
    assert body["defaultDocumentList"] == first["defaultDocumentList"]


def test_a_page_number_the_list_does_not_hear_is_caught():
    """The same first page again, under new ids. Added, each statement on it
    would have been listed twice, and told apart by its place."""
    first = _first(4)
    again = _list(*[dict(e, documentGuid="{new}") for e in first["defaultDocumentList"]])
    body, read, why = site._later_pages(_Page(_answer_of({2: again})), _asked(), first)
    assert (read, why) == (1, site.PAGE_REPEATED)
    assert len(body["defaultDocumentList"]) == 2


def test_more_documents_than_the_list_counted_keeps_the_first_page_alone():
    first = _first(3)
    page = _Page(_answer_of({2: _list(_entry(BANK, "2025-03-31"), _entry(BANK, "2025-02-28"))}))
    assert site._later_pages(page, _asked(), first) == (first, 1, site.TOO_MANY)


def test_a_list_of_more_pages_than_are_read_says_so(monkeypatch):
    monkeypatch.setattr(site, "MAX_PAGES", 3)
    page = _Page(lambda body: {"status": 200, "url": API,
                               "data": _list(_entry(BANK, "2024-%02d-28" % int(body["pageNum"])))})
    _body, read, why = site._later_pages(page, _asked(), _first(50))
    assert (read, why) == (3, site.TOO_MANY_PAGES)


@pytest.mark.parametrize("asked", [
    {}, {"url": API, "body": {"TimeFrame": "2025"}},
    {"url": "https://ext-web.etrade.com.invented.example/etaz/api/adsal/accountdocs/v2/searchItems",
     "body": {"pageNum": 1}},
], ids=["nothing", "no page number", "off etrade"])
def test_a_list_whose_request_cannot_be_asked_again_is_unread(asked):
    page = _Page(lambda body: pytest.fail("asked"))
    assert site._later_pages(page, asked, _first(4))[1:] == (1, site.NO_REQUEST)


def test_a_list_with_documents_and_no_count_is_unread_and_one_with_neither_is_whole():
    page = _Page(lambda body: pytest.fail("asked"))
    assert site._later_pages(page, _asked(), _list(_entry(BANK), counted=False))[1:] == (1, site.NO_COUNT)
    assert site._later_pages(page, _asked(), {"defaultDocumentList": []})[1:] == (1, "")
    assert site._later_pages(page, _asked(), _first(2))[1:] == (1, "")
    for count in (2, 2.0, " 2 "):
        assert site._later_pages(page, _asked(), dict(_first(2), numFound=count))[1:] == (1, "")
    for count in (2.5, True, "two", -1):
        assert site._later_pages(page, _asked(), dict(_first(2), numFound=count))[1:] == (1, site.NO_COUNT)


# --- in a real browser -----------------------------------------------------------
#
# A page that asks searchItems for the first page of its list the way the
# tester's recording showed, a POST to ext-web.etrade.com with the period and
# pageNum in a JSON body, and an answer of two documents a page, new ids on
# every load, and numFound counting the whole list.

PAGE = """<!doctype html><html><body><table><tbody id="rows"></tbody></table>
<script>
fetch("%s", {method: "POST", headers: {"Content-Type": "text/plain"},
             body: JSON.stringify({TimeFrame: "Last 90 Days", pageNum: 1})})
  .then(r => r.json()).then(b => {
    for (const d of b.defaultDocumentList) {
      const tr = document.createElement("tr");
      tr.innerHTML = "<td>" + d.documentDate + "</td><td><a href='#'>" + d.documentTitle + "</a></td>";
      document.getElementById("rows").appendChild(tr);
    }
  });
</script></body></html>""" % API

LISTED = [(BANK, "2026-09-30"), (SINGLE, "2026-09-30"), (BANK, "2026-08-31"),
          (SINGLE, "2026-08-31"), (BANK, "2026-07-31")]


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


ELSEWHERE = "https://ext-web.etrade.com/etaz/api/adsal/elsewhere"
_CORS = {"access-control-allow-origin": "*"}


def _discover_in(browser, lists=None, page=PAGE, refuse_page=None, redirect_page=None):
    """Discovery of `page`, its lists two documents a page, `lists` giving
    each period's documents. Returns the documents, every list request
    with the period and page it asked for, the trace, and every request
    sent on to ELSEWHERE."""
    lists = lists or {"Last 90 Days": LISTED}
    seen, elsewhere = [], []

    def answer(route):
        req = route.request
        if req.method != "POST":
            return route.fulfill(status=204, headers=_CORS)
        if req.url.startswith(ELSEWHERE):
            elsewhere.append(req.url)
            return route.fulfill(status=200, content_type="application/json", headers=_CORS,
                                 body=json.dumps(_list(_entry(BANK, "2026-01-31"))))
        sent = json.loads(req.post_data or "{}")
        n, period = int(sent.get("pageNum") or 1), sent.get("TimeFrame")
        seen.append((period, n))
        if n == refuse_page:
            return route.fulfill(status=503, headers=_CORS, body="")
        if n == redirect_page:
            return route.fulfill(status=302, headers=dict(_CORS, location=ELSEWHERE), body="")
        listed = lists.get(period, [])
        body = dict(_list(*[_entry(t, d) for t, d in listed[(n - 1) * 2:n * 2]]), numFound=str(len(listed)))
        route.fulfill(status=200, content_type="application/json", headers=_CORS, body=json.dumps(body))
    ctx = browser.new_context()
    try:
        ctx.route("https://us.etrade.com/**", lambda r: r.fulfill(status=200, content_type="text/html",
                                                                  body=page))
        ctx.route("https://ext-web.etrade.com/**", answer)
        docs = site.collect_download_docs(ctx.new_page())
        return docs, seen, list(site.DISCOVERY_TRACE), elsewhere
    finally:
        ctx.close()


def test_discovery_reads_every_page_of_the_list(browser):
    """It read the first two documents and finished clean. The later pages
    it asked for come into the one list, never as lists of their own."""
    docs, seen, trace, _elsewhere = _discover_in(browser)
    assert sorted((d.title, d.date_text) for d in docs) == sorted(LISTED)
    assert docs.unread == () and all(d.entry == "" for d in docs)
    assert seen == [("Last 90 Days", 1), ("Last 90 Days", 2), ("Last 90 Days", 3)]
    assert trace[0]["note"] == "default list" and trace[0]["lists"] == 1
    result = trace[-1]
    assert (result["pages"], result["lists_of_more_than_one_page"], result["not_read_to_the_end"]) == (3, 1, [])
    assert site._LISTED["2026-09-30"] == 2 and site._LISTED["2026-07-31"] == 1


def test_a_later_page_refused_in_the_browser_leaves_the_listing_unread(browser):
    docs, seen, trace, _elsewhere = _discover_in(browser, refuse_page=3)
    assert docs.unread == (site.PAGE_REFUSED,)
    assert sorted((d.title, d.date_text) for d in docs) == sorted(LISTED[:4])
    assert trace[-1]["not_read_to_the_end"] == [site.PAGE_REFUSED]
    # Fixed words, counts and dates, and nothing of the list's.
    assert "rowId" not in json.dumps(trace) and "guid" not in json.dumps(trace)


def test_a_later_page_sent_elsewhere_is_never_followed(browser):
    docs, seen, trace, elsewhere = _discover_in(browser, redirect_page=2)
    assert elsewhere == [] and docs.unread == (site.PAGE_UNREAD,)
    assert sorted((d.title, d.date_text) for d in docs) == sorted(LISTED[:2])


# The period picker the tester's recording showed (test_period_picker.py),
# whose Apply asks for the first page of the chosen period's list.
PICKER_PAGE = """<!doctype html><html><body>
<form id="filters">
  <button type="button" id="picker" aria-label="Timeframe ,  Last 90 Days"
          aria-haspopup="listbox">Last 90 Days</button>
  <div role="listbox" id="list" style="display:none">
    <div role="option">Last 90 Days</div>
    <div role="option">2025</div>
  </div>
  <button type="submit">Apply</button>
</form>
<table><tbody id="rows"></tbody></table>
<script>
let current = "Last 90 Days", pending = null;
const picker = document.getElementById("picker");
const list = document.getElementById("list");
picker.addEventListener("click", () => {
  list.style.display = list.style.display === "none" ? "block" : "none";
});
for (const o of list.querySelectorAll("[role=option]")) {
  o.addEventListener("click", () => { pending = o.textContent.trim(); list.style.display = "none"; });
}
function search(tf) {
  return fetch("%s", {method: "POST", headers: {"Content-Type": "text/plain"},
                      body: JSON.stringify({TimeFrame: tf, pageNum: 1})})
    .then(r => r.json()).then(b => {
      const rows = document.getElementById("rows");
      rows.innerHTML = "";
      for (const d of b.defaultDocumentList) {
        const tr = document.createElement("tr");
        tr.innerHTML = "<td>" + d.documentDate + "</td><td><a href='#'>" + d.documentTitle + "</a></td>";
        rows.appendChild(tr);
      }
    });
}
document.getElementById("filters").addEventListener("submit", (e) => {
  e.preventDefault();
  if (pending) { current = pending; pending = null; }
  picker.setAttribute("aria-label", "Timeframe ,  " + current);
  picker.textContent = current;
  search(current);
});
search(current);
</script></body></html>""" % API

YEAR = [(BANK, "2025-12-31"), (SINGLE, "2025-12-31"), (BANK, "2025-11-30")]


def test_a_period_the_picker_applies_is_read_to_its_last_page(browser):
    docs, seen, trace, _elsewhere = _discover_in(
        browser, {"Last 90 Days": [(BANK, "2026-09-30")], "2025": YEAR}, page=PICKER_PAGE)
    assert seen == [("Last 90 Days", 1), ("2025", 1), ("2025", 2)]
    assert sorted((d.title, d.date_text) for d in docs) == sorted(YEAR + [(BANK, "2026-09-30")])
    chosen = next(t for t in trace if t.get("note") == "period chosen")
    assert (chosen["period"], chosen["lists"], chosen["pages"], chosen["not_read_to_the_end"]) == \
        ("2025", 1, [2], [])
    assert docs.unread == ()


def test_the_digest_of_a_place_is_never_the_digest_of_ids():
    assert hashlib.sha256(b"#1").hexdigest()[:12] in etrade_docs._PLACES
