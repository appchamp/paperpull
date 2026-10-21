"""Each statement's account, from its keyAccountNo and the page's account
list, and a statement listed on a later page taken there (#96, after
0.56.2).

A tester read the live page, labels and shapes only. displayMultipleAccounts,
the field the app read the account from, is an empty string on every
document, so no account was ever read. Each document carries keyAccountNo
instead, one value per account, which is no account number and does not
change when the account is renamed, and the page loads its account list
beside the documents, GET usermetadata, whose accountList gives each
keyAccount the label the Account column shows, "words - ####". Discovery
now catches that answer the way it catches searchItems and gives each
document its account's label. A key the list gives no label, or labels two
ways, gives no account, never a guessed one.

A record is still kept under the label's masked digits, which a rename
leaves alone too, so the records kept with no account move the way 0.53.0
promised, one to one for a sign-in of one account and by what each saved
PDF prints for a sign-in of several, nothing downloaded again and no file
touched.

The list's Next page button, labeled exactly "Next page" inside the
navigation labeled "Table pagination" and turned off on the last page,
moves the list on to the page that shows a statement listed past the
first.

Everything here is invented.
"""
import itertools
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
from paperpull_core import doc_types, testkit
from paperpull_core.models import State

DAY = "2026-09-30"
BANK = "Bank Statement"
SINGLE = "Single Account Statement"
CASH = "Invented Cash - 1111"
BROKERAGE = "Invented Brokerage - 2222"
CLOSED = "Invented Closed IRA - 3333"
# keyAccountNo in the shape the tester read, ####-##-##-##.##.##.######.
K_CASH = "2011-04-05-10.11.12.000111"
K_BROKERAGE = "2013-06-07-13.14.15.000222"
K_CLOSED = "2009-01-02-03.04.05.000333"
K_UNNAMED = "2020-02-02-02.02.02.000999"
_ids = itertools.count(1)


def _entry(title, key, day=DAY, shown=""):
    """One searchItems document the way the tester's page gives it, an empty
    displayMultipleAccounts, its keyAccountNo, and the two optional
    attributes the tester read, ids no other load gives."""
    n = next(_ids)
    return {"documentGuid": "{guid-%d}" % n, "documentId": "x&rowId=060124-17%011d" % n,
            "documentTypeName": "STATEMENTS", "documentTitle": title,
            "documentDate": day + "T00:00:00.000Z", "displayMultipleAccounts": shown,
            "keyAccountNo": key,
            "optionalAttributeList": [
                {"fieldHeader": "Additional information", "fieldName": "AdditionalInformation",
                 "displayValue": "", "links": []},
                {"fieldHeader": "Delivery method", "fieldName": "DeliveryMethod",
                 "displayValue": "Online", "links": []}]}


def _list(*entries):
    return {"defaultDocumentList": list(entries), "numFound": str(len(entries))}


def _accounts(*pairs):
    """A usermetadata answer, (keyAccount, accountDisplayValue) for each
    account, with no status, the way the tester's lists closed accounts too."""
    return {"accountList": [{"keyAccount": k, "accountDisplayValue": v, "accountType": "Invented"}
                            for k, v in pairs],
            "documentTypes": [{"name": "Statements"}]}


THEIRS = _accounts((K_CASH, CASH), (K_BROKERAGE, BROKERAGE), (K_CLOSED, CLOSED))


def _their_month(day=DAY):
    """A month of the tester's, the cash account's Bank Statement and the brokerage
    account's Single Account Statement."""
    return [_entry(BANK, K_CASH, day), _entry(SINGLE, K_BROKERAGE, day)]


@pytest.fixture
def labels(monkeypatch):
    monkeypatch.setattr(site, "_ACCOUNT_MAP", {})
    monkeypatch.setattr(site, "_ACCOUNTS_UNSURE", set())


# --- the label each key has ------------------------------------------------------

def test_each_documents_account_is_the_label_its_key_has_in_the_account_list(labels):
    assert site._note_accounts(THEIRS) == 3
    docs = site._docs_from_api(_list(*_their_month()))
    assert [(d["title"], d["account"], d["unnamed"]) for d in docs] == \
        [(BANK, CASH, False), (SINGLE, BROKERAGE, False)]
    assert site.accounts_named() == 3


@pytest.mark.parametrize("answer", [
    _accounts((K_CASH, CASH)),
    _accounts((K_CASH, CASH), (K_BROKERAGE, "   ")),
    _accounts((K_CASH, CASH), (K_BROKERAGE, BROKERAGE), (K_BROKERAGE, "Invented Margin - 4444")),
    _accounts((K_CASH, CASH), (K_BROKERAGE, "invented cash -1111")),
    {"accountList": [{"keyAccount": 2222, "accountDisplayValue": BROKERAGE},
                     {"keyAccount": K_BROKERAGE, "accountDisplayValue": [BROKERAGE]}]},
    {"accountList": {"keyAccount": K_BROKERAGE, "accountDisplayValue": BROKERAGE}},
    [{"keyAccount": K_BROKERAGE, "accountDisplayValue": BROKERAGE}],
], ids=["a key the list leaves out", "an empty label", "a key labeled two ways",
        "a label two keys share", "values that are not words", "a list that is not a list",
        "an answer that is not an object"])
def test_a_label_is_never_guessed(labels, answer):
    site._note_accounts(answer)
    doc = site._docs_from_api(_list(_entry(SINGLE, K_BROKERAGE)))[0]
    assert (doc["account"], doc["unnamed"]) == ("", True)


def test_two_answers_that_label_one_key_two_ways_give_it_none(labels):
    site._note_accounts(_accounts((K_BROKERAGE, BROKERAGE)))
    site._note_accounts(_accounts((K_BROKERAGE, "Invented Margin - 4444")))
    assert site._docs_from_api(_list(_entry(SINGLE, K_BROKERAGE)))[0]["account"] == ""
    assert site.accounts_named() == 0


class _Page:
    """A tab on E*TRADE's site whose later pages of a list are `pages`."""
    url = "https://us.etrade.com/etx/pxy/accountdocs#/documents"

    def __init__(self, pages):
        self.pages = pages

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, js, arg):
        n = int(arg[2]["pageNum"])
        return {"status": 200, "url": API, "data": self.pages[n - 2]}


def test_a_later_page_of_another_accounts_statements_is_not_a_page_repeated(labels):
    """Two accounts' statements of one title and day on page 1, two more on
    page 2, which differ from the first two only by their accounts. Read as
    the same page again, the list stopped there unread."""
    site._note_accounts(THEIRS)
    first = dict(_list(_entry(SINGLE, K_CASH), _entry(SINGLE, K_BROKERAGE)), numFound="4")
    second = _list(_entry(SINGLE, K_CLOSED), _entry(SINGLE, K_UNNAMED))
    asked = {"url": API, "body": {"TimeFrame": "Last 90 Days", "pageNum": 1}, "headers": {}, "cookie": False}
    body, pages, why = site._later_pages(_Page([second]), asked, first)
    assert (pages, why, len(body["defaultDocumentList"])) == (2, "", 4)


def test_an_account_the_list_shows_itself_is_read_when_its_key_gives_none(labels):
    """The account list's label first, as #119 has it, and what the list
    shows itself for a key the account list cannot label."""
    site._note_accounts(THEIRS)
    doc = site._docs_from_api(_list(_entry(SINGLE, K_BROKERAGE, shown="Invented Joint - 5555")))[0]
    assert doc["account"] == BROKERAGE
    doc = site._docs_from_api(_list(_entry(SINGLE, K_UNNAMED, shown="Invented Joint - 5555")))[0]
    assert (doc["account"], doc["unnamed"]) == ("Invented Joint - 5555", False)
    bare = dict(_entry(SINGLE, ""), keyAccountNo=None)
    assert [(d["account"], d["unnamed"]) for d in site._docs_from_api(_list(bare))] == [("", False)]


# --- discovery in a real browser --------------------------------------------------

API = "https://ext-web.etrade.com/etaz/api/adsal/accountdocs/v2/searchItems?RequestID=7&SeqID=1"
META = "https://ext-web.etrade.com/etaz/api/adsal/accountdocs/usermetadata"
ELSEWHERE_META = "https://ext-web.etrade.com.invented.example/etaz/api/adsal/accountdocs/usermetadata"
_CORS = {"access-control-allow-origin": "*"}

PAGE = """<!doctype html><html><body><table><tbody id="rows"></tbody></table>
<script>
fetch("%s").then(r => r.json()).then(m => { window.accounts = m; });
fetch("%s", {method: "POST", headers: {"Content-Type": "text/plain"},
             body: JSON.stringify({TimeFrame: "Last 90 Days", pageNum: 1})})
  .then(r => r.json()).then(b => {
    for (const d of b.defaultDocumentList) {
      const tr = document.createElement("tr");
      tr.innerHTML = "<td>" + d.documentDate + "</td><td><a href='#'>" + d.documentTitle + "</a></td>";
      document.getElementById("rows").appendChild(tr);
    }
  });
</script></body></html>"""


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


def _discover_in(browser, meta=THEIRS, meta_url=META, entries=None):
    """Discovery of a page that loads its account list from `meta_url` and
    its documents, `entries`, the tester's month unless given."""
    entries = _their_month() if entries is None else entries

    def answer(route):
        req = route.request
        if req.url.split("?")[0].endswith("/usermetadata"):
            return route.fulfill(status=200, content_type="application/json", headers=_CORS,
                                 body=json.dumps(meta))
        if req.method == "POST":
            return route.fulfill(status=200, content_type="application/json", headers=_CORS,
                                 body=json.dumps(_list(*entries)))
        return route.fulfill(status=204, headers=_CORS)
    ctx = browser.new_context()
    try:
        ctx.route("https://us.etrade.com/**", lambda r: r.fulfill(
            status=200, content_type="text/html", body=PAGE % (meta_url, API)))
        ctx.route("https://ext-web.etrade.com/**", answer)
        ctx.route("https://ext-web.etrade.com.invented.example/**", answer)
        docs = site.collect_download_docs(ctx.new_page())
        return docs, list(site.DISCOVERY_TRACE)
    finally:
        ctx.close()


def _says_nothing_of_the_accounts(text):
    for leaked in ("Invented", "1111", "2222", "3333", "2011-04-05", "10.11.12", "000111",
                   "2013-06-07", "000222", "keyAccount"):
        assert leaked not in text, (leaked, text)


def test_discovery_gives_each_statement_its_accounts_label(browser):
    docs, trace = _discover_in(browser)
    assert sorted((d.title, d.account) for d in docs) == [(BANK, CASH), (SINGLE, BROKERAGE)]
    assert site.accounts_in(docs) == {"1111", "2222"}
    result = trace[-1]
    assert (result["accounts_named"], result["documents_of_an_account_not_named"]) == (3, 0), result
    # Counts, dates and fixed words, never a label or a key.
    _says_nothing_of_the_accounts(json.dumps(trace))


def test_an_account_list_from_another_host_is_never_read(browser):
    docs, trace = _discover_in(browser, meta_url=ELSEWHERE_META)
    assert sorted((d.title, d.account) for d in docs) == [(BANK, ""), (SINGLE, "")]
    assert docs.unread == (site.ACCOUNTS_UNREAD,)
    assert (trace[-1]["accounts_named"], trace[-1]["documents_of_an_account_not_named"]) == (0, 2)


# --- the records, through the app's own discovery ---------------------------------

_REAL_COLLECT = site.collect_download_docs


def _discovered(monkeypatch, meta, first, *wider):
    """What discovery's own parse makes of a usermetadata answer, caught as
    the page loads, and searchItems answers, the first as the default list
    and the rest as the periods' lists."""
    def capturing(page, capture):
        site._note_accounts(meta)
        capture.append(first)
        return True

    def widen(page, more, trace=None):
        more.extend(wider)
        return bool(wider)
    monkeypatch.setattr(site, "goto_docs_capturing", capturing)
    monkeypatch.setattr(site, "widen_date_filter", widen)
    return _REAL_COLLECT(None)


@pytest.fixture
def app(tmp_path, monkeypatch):
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
    a.stats = {"skipped_out_of_scope": 0, "discovered": 0, "failed": 0, "manual_review": 0}
    a.page = lambda: None
    a.check_session = lambda page: None
    a.failures = []
    a.write_failure = lambda step, reason, *more, **kw: a.failures.append((step, reason))
    monkeypatch.setattr(site, "goto_documents", lambda page: True)

    def discover(meta, *bodies):
        raws = _discovered(monkeypatch, meta, *bodies)
        monkeypatch.setattr(site, "collect_download_docs", lambda page: raws)
        a.cmd_discover(quiet=True)
        return a
    a.listing = discover
    return a


def _legacy_key(title, day=DAY):
    return "Statement:%s:%s:Unnamed" % (day, title)


def _key(title, tail, day=DAY):
    return "Statement:%s:%s:%s" % (day, title, tail)


def _key_with(title, entry, day=DAY):
    """The key 0.56.0 (the list's ids) or 0.56.1 (a place, "#1") gave a
    document the list gave no account beside another such of its date and
    title."""
    return etrade_docs.Document(category="Statement", date=day, title=title, entry=entry).key


def _record(app, title, key, name=None, state=State.COMPLETED, day=DAY, entry="", prints=None,
            folder=None):
    """A record under `key` the way a run left it, in progress and in
    discovery, its file `name` a PDF printing the lines `prints`."""
    doc = etrade_docs.Document(title=title, category="Statement", summary="Account Statement",
                               date=day, confidence="High", source_url=site.BILLING_URL, entry=entry)
    assert doc.key == key
    doc.state = state.value
    if name:
        path = (folder or app.paths.folder_for("Statement")) / name
        path.write_bytes(testkit.text_pdf(["Invented Securities", title] + list(prints or [])
                                          + ["Page 1 of 1"]))
        doc.pdf_path, doc.pdf_filename = str(path), path.name
    if state == State.COMPLETED:
        doc.downloaded_ok = True
    app.progress.data[key] = doc.to_dict()
    app.discovery.data[key] = dict(doc.to_dict())
    app.progress.save()
    app.discovery.save()
    return doc


def _left_to_take(app):
    return sorted((d.date, d.title, d.account) for d in app._select() if not app._already_done(d))


def _files(app):
    return {p.relative_to(app.paths.root): p.read_bytes() for p in app.paths.root.rglob("*.pdf")}


def test_a_sign_in_of_one_account_moves_its_records_to_the_account_and_takes_nothing_again(app):
    """Every record it kept is under the key of no account, since no account
    was ever read. With one account listed, each moves to its account's key
    and keeps its file, its name and its summary."""
    days = ["2026-09-30", "2026-08-31"]
    for n, day in enumerate(days):
        _record(app, SINGLE, _legacy_key(SINGLE, day), "%s Statement%s.pdf" % (day, " (2)" * n), day=day)
    files = _files(app)
    app.listing(_accounts((K_BROKERAGE, BROKERAGE)), _list(*[_entry(SINGLE, K_BROKERAGE, d) for d in days]))
    assert sorted(app.progress.data) == sorted(app.discovery.data) == sorted(_key(SINGLE, "2222", d) for d in days)
    for day in days:
        rec = app.progress.data[_key(SINGLE, "2222", day)]
        assert (rec["account"], rec["summary"], rec["downloaded_ok"]) == (BROKERAGE, "Account Statement", True)
    assert _left_to_take(app) == []
    assert _files(app) == files


def _their_records(app):
    """The tester's sign-in after 0.56.0. The month's two statements saved on Oct 15
    under the key of no account, each PDF printing its account's number,
    then under the list's ids from 0.56.0's Discover and Run All, the Bank
    Statement's copies set aside for review and the Single Account
    Statement saved again, and records nothing took."""
    review = app.paths.manual_review
    _record(app, BANK, _legacy_key(BANK), "2026-09-30 Statement.pdf", prints=["Account Number: XXXX-1111"])
    _record(app, SINGLE, _legacy_key(SINGLE), "2026-09-30 Statement (2).pdf",
            prints=["Account Number: XXXX-2222"])
    for n, (title, name, state, folder) in enumerate([
            (BANK, "2026-09-30 Statement.pdf", State.NEEDS_MANUAL_REVIEW, review),
            (SINGLE, "2026-09-30 Statement (3).pdf", State.COMPLETED, None),
            (BANK, None, State.DISCOVERED, None),
            (SINGLE, None, State.DISCOVERED, None)]):
        ids = "{old-%d}|x&rowId=060124-1760%09d" % (n, n)
        _record(app, title, _key_with(title, ids), name, state, entry=ids, folder=folder)


def test_their_records_fold_and_move_to_the_account_each_pdf_prints(app):
    """The records 0.56.0 kept under the ids fold into the key of no
    account, and each then moves to the account its saved PDF prints, its
    name in the summary since the sign-in has more than one. Nothing is
    left to take and no file is touched. The copies are the tester's to delete."""
    _their_records(app)
    files = _files(app)
    app.listing(THEIRS, _list(*_their_month()), _list(*_their_month()))
    assert sorted(app.progress.data) == sorted(app.discovery.data) == [_key(BANK, "1111"), _key(SINGLE, "2222")]
    assert app.progress.data[_key(BANK, "1111")]["summary"] == "Account Statement - " + CASH
    assert Path(app.progress.data[_key(SINGLE, "2222")]["pdf_path"]).name == "2026-09-30 Statement (2).pdf"
    assert _left_to_take(app) == []
    assert _files(app) == files


def test_a_statement_whose_pdf_shows_no_account_stays_and_its_accounts_is_taken(app):
    """The several-account rule of 0.53.0. A saved PDF that prints no listed
    account's digits cannot say whose it is, so it stays where it is, and
    the statement is taken again under a name that says its account."""
    _record(app, SINGLE, _legacy_key(SINGLE), "2026-09-30 Statement.pdf", prints=["No account printed"])
    app.listing(THEIRS, _list(*_their_month()))
    assert _legacy_key(SINGLE) in app.progress.data
    assert _left_to_take(app) == [(DAY, BANK, CASH), (DAY, SINGLE, BROKERAGE)]


@pytest.mark.parametrize("held", ["nothing", "a review copy"])
def test_place_records_of_a_day_the_lists_now_give_accounts_are_never_taken(app, held):
    """0.56.1 kept two accounts' statements of one title and day by their
    places and refused both. With their accounts listed, the place records
    holding nothing go, one holding a file stays as it is, and only the
    two accounts' statements are taken."""
    _record(app, SINGLE, _key_with(SINGLE, "#1"), None, State.NEEDS_MANUAL_REVIEW, entry="#1")
    if held == "a review copy":
        _record(app, SINGLE, _key_with(SINGLE, "#2"), "2026-09-30 Statement.pdf", State.NEEDS_MANUAL_REVIEW,
                entry="#2", folder=app.paths.manual_review)
        app.paths.manual_review.joinpath("2026-09-30 Statement.pdf").write_bytes(b"not a pdf")
    else:
        _record(app, SINGLE, _key_with(SINGLE, "#2"), None, State.NEEDS_MANUAL_REVIEW, entry="#2")
    app.listing(THEIRS, _list(_entry(SINGLE, K_CASH), _entry(SINGLE, K_BROKERAGE)))
    accounts = [_key(SINGLE, "1111"), _key(SINGLE, "2222")]
    kept = [_key_with(SINGLE, "#2")] if held == "a review copy" else []
    assert sorted(app.discovery.data) == sorted(accounts + kept)
    assert sorted(app.progress.data) == kept
    taken: list = []
    app._on_its_site = lambda: None
    app._delay = lambda factor=1.0: None
    app.download_one = lambda page, doc, filename: taken.append(doc.key)
    app.stats.update(skipped_completed=0)
    app.process(app._select())
    assert sorted(taken) == accounts


def test_a_statement_of_an_account_the_list_gives_no_label_is_never_given_another(app, monkeypatch, tmp_path):
    """A closed account left out of the account list. Its statement keeps
    no account, never the other one's, and on a day it shares its title
    with that one, the download refuses it before anything is pressed."""
    app.listing(_accounts((K_BROKERAGE, BROKERAGE)), _list(_entry(SINGLE, K_BROKERAGE), _entry(SINGLE, K_UNNAMED)))
    docs = {d.key: d for d in app._select()}
    assert sorted(docs) == sorted([_key(SINGLE, "2222"), _legacy_key(SINGLE)])
    assert docs[_legacy_key(SINGLE)].account == ""
    opened: list = []
    monkeypatch.setattr(site, "goto_documents", lambda page: opened.append(page) or True)
    trace: list = []
    assert not site.download_bill(None, tmp_path, DAY, tmp_path / "out.pdf", SINGLE, trace, account="")
    assert opened == [] and [t.get("why") for t in trace] == [site.SHARED_WITH_NO_ACCOUNT]


def test_an_account_renamed_on_etrade_keeps_its_records_key(app):
    app.listing(_accounts((K_BROKERAGE, BROKERAGE)), _list(_entry(SINGLE, K_BROKERAGE)))
    key = _key(SINGLE, "2222")
    app.progress.data[key] = dict(app.discovery.data[key], state=State.COMPLETED.value, downloaded_ok=True)
    app.listing(_accounts((K_BROKERAGE, "Invented Renamed Words - 2222")), _list(_entry(SINGLE, K_BROKERAGE)))
    assert sorted(app.discovery.data) == [key]
    assert app.discovery.data[key]["account"] == "Invented Renamed Words - 2222"
    assert _left_to_take(app) == []


def test_what_discovery_writes_and_logs_says_nothing_of_the_accounts(app, caplog):
    caplog.set_level(logging.INFO)
    app.listing(_accounts((K_CASH, CASH), (K_BROKERAGE, BROKERAGE)),
                _list(*_their_month(), _entry(SINGLE, K_UNNAMED, "2026-08-31")))
    written = (app.paths.diagnostics / "discovery-trace.json").read_text(encoding="utf-8")
    assert '"accounts_named": 2' in written and '"documents_of_an_account_not_named": 1' in written
    _says_nothing_of_the_accounts(written)
    _says_nothing_of_the_accounts(caplog.text)
    assert "1 document(s) of an account the page's account list gave no label" in caplog.text


# --- a statement listed on a later page -------------------------------------------

LATER = [(SINGLE, "2026-09-30", "09/30/26", "g1"), (SINGLE, "2026-08-31", "08/31/26", "g2"),
         (SINGLE, "2026-07-31", "07/31/26", "g3")]
DOCS_URL = "https://us.etrade.com/etx/pxy/accountdocs#/documents"

# The tester's pagination, the page shown in words, Previous page and Next page,
# both turned off on the last page. Drawn in the light DOM or in a shadow
# root, the next press counted, and the list moved on by the page itself.
NAV = """<ms-pagination role="navigation" aria-label="%(nav)s"></ms-pagination>%(outside)s"""
PAGED = """<!doctype html><html><body>
<table><tbody id="rows"></tbody></table>
%(nav)s
<script>
window.hits = []; window.nextPresses = 0;
document.addEventListener('click', e => {
  const g = e.target.closest && e.target.closest('[data-guid]');
  if (g) { window.hits.push(g.dataset.guid); e.preventDefault(); }
}, true);
const DOCS = %(docs)s, SIZE = 2, SHADOW = %(shadow)s, STUCK = %(stuck)s, ARIA_OFF = %(aria_off)s;
const LABEL = %(label)s, TWICE = %(twice)s, DATED = %(dated)s, WORDS = %(words)s, ALSO = %(also)s;
let shown = 1;
const pages = Math.max(1, Math.ceil(DOCS.length / SIZE));
const host = document.querySelector('ms-pagination');
const root = SHADOW ? host.attachShadow({mode: 'open'}) : host;
root.innerHTML = '<span class="where"></span><button aria-label="Previous page" class="prev-button">&lt;</button>' +
  '<button class="next-button"></button>' + (TWICE ? '<button class="next-button"></button>' : '');
const outside = document.getElementById('outside');
const nexts = Array.from(root.querySelectorAll('.next-button')).concat(outside ? [outside] : []);
if (outside && !ALSO) for (const b of root.querySelectorAll('.next-button')) b.remove();
for (const b of nexts) {
  b.textContent = WORDS;
  b.setAttribute('aria-label', LABEL);
  b.addEventListener('click', () => {
    window.nextPresses++;
    if (!STUCK && shown < pages) { shown++; draw(); }
  });
}
function draw() {
  const rows = document.getElementById('rows');
  rows.innerHTML = '';
  for (const [title, day, account, guid] of DOCS.slice((shown - 1) * SIZE, shown * SIZE)) {
    const tr = document.createElement('tr');
    tr.innerHTML = '<td>' + (DATED ? day : '') + '</td><td>' + account + '</td><td><a href="#" data-guid="' + guid +
      '" aria-label="' + title + ' PDF for ' + account + '">' + title + '</a></td>';
    rows.appendChild(tr);
  }
  root.querySelector('.where').textContent = 'Page ' + shown + ' of ' + pages;
  for (const b of nexts) {
    if (ARIA_OFF) b.setAttribute('aria-disabled', 'true');
    else b.disabled = shown >= pages;
  }
}
draw();
</script></body></html>"""


def _paged(label="Next page", nav="Table pagination", shadow=False, stuck=False, aria_off=False,
           twice=False, outside=False, docs=LATER, dated=True, words=">", also=False):
    docs = [[title, short, BROKERAGE, guid] for title, _iso, short, guid in docs]
    return PAGED % {"nav": NAV % {"nav": nav, "outside": "<button id='outside'>&gt;</button>" if outside else ""},
                    "docs": json.dumps(docs), "shadow": json.dumps(shadow), "stuck": json.dumps(stuck),
                    "aria_off": json.dumps(aria_off), "label": json.dumps(label), "twice": json.dumps(twice),
                    "dated": json.dumps(dated), "words": json.dumps(words), "also": json.dumps(also)}


@pytest.fixture
def paged(browser, monkeypatch, tmp_path):
    """The documents page at its own address, three statements two to a
    page, and a download of each that presses its row's link the way the
    real catch does and takes the PDF of the guid the press landed on."""
    _lists = [_list(*[_entry(title, "", iso, shown=BROKERAGE) for title, iso, _short, _guid in LATER])]
    for name in ("_LISTED", "_LISTED_TITLES", "_LISTED_ACCOUNTS", "_LISTED_DOCS", "_LISTED_SAME"):
        monkeypatch.setattr(site, name, {})
    site._note_listed(_lists)
    monkeypatch.setattr(site, "_MOVED_ON", [False])
    monkeypatch.setattr(site, "PAGE_MOVE_WAIT_S", 1)
    monkeypatch.setattr(site, "goto_documents", lambda pg: True)
    monkeypatch.setattr(site, "expand_all", lambda pg: None)
    hits: list = []

    def fake(pg, el, label, out_path, trace=None, dl_dir=None, pressed=None, unsure=None):
        before = len(pg.evaluate("window.hits"))
        el.click(timeout=3000)
        landed = pg.evaluate("window.hits")[before:]
        hits.extend(landed)
        if landed:
            Path(out_path).write_bytes(b"%PDF-1.4\n% invented " + landed[0].encode() + b"\n%%EOF\n")
            if pressed is not None:
                pressed.append(label)
            return True
        return False
    monkeypatch.setattr(site, "_catch_pdf", fake)
    ctx = browser.new_context()
    html = {"page": _paged()}
    for host in ("https://us.etrade.com/**", "https://us.etrade.com.invented.example/**"):
        ctx.route(host, lambda r: r.fulfill(status=200, content_type="text/html", body=html["page"]))
    pg = ctx.new_page()

    def opened(at=DOCS_URL, **kind):
        if "docs" in kind:
            site._note_listed([_list(*[_entry(title, "", iso, shown=BROKERAGE)
                                       for title, iso, _short, _guid in kind["docs"]])])
        html["page"] = _paged(**kind)
        pg.goto(at)
        return pg

    def download(iso, title=SINGLE):
        trace: list = []
        got = site.download_bill(pg, tmp_path / "dl", iso, tmp_path / ("%s.pdf" % iso), title, trace,
                                 account=BROKERAGE)
        return got, trace
    yield SimpleNamespace(open=opened, download=download, hits=hits,
                          presses=lambda: pg.evaluate("window.nextPresses"))
    ctx.close()


@pytest.mark.parametrize("shadow", [False, True], ids=["light", "shadow"])
def test_a_statement_on_the_second_page_is_taken_there(paged, shadow):
    """It went to Manual Review, its row never on the page shown."""
    paged.open(shadow=shadow)
    got, trace = paged.download("2026-07-31")
    assert got and paged.hits == ["g3"], trace
    assert paged.presses() == 1
    nexts = [t for t in trace if t.get("note") == "next page"]
    assert [(t.get("pressed"), t.get("moved")) for t in nexts] == [(True, True)], nexts
    _says_nothing_of_the_accounts(json.dumps(trace))


def test_a_statement_on_the_page_shown_presses_no_next_page(paged):
    paged.open()
    got, _trace = paged.download("2026-09-30")
    assert got and paged.hits == ["g1"] and paged.presses() == 0


def test_the_next_download_looks_from_the_first_page(paged):
    """The list stays on the page a download moved it to, and a statement on
    the first page was looked for on the last one, where Next page is off."""
    paged.open()
    assert paged.download("2026-07-31")[0]
    got, trace = paged.download("2026-08-31")
    assert got and paged.hits == ["g3", "g2"], trace
    assert paged.presses() == 0


@pytest.mark.parametrize("kind", [
    {"label": "Next"}, {"label": "Next page "}, {"label": "next page"}, {"label": "Next Page"},
    {"nav": "Pagination"}, {"outside": True}, {"outside": True, "also": True}, {"twice": True},
    {"aria_off": True},
    {"words": "Pay now"}, {"words": "Transfer funds"},
], ids=["Next", "a space after", "lower case", "Page in capitals", "another navigation",
        "outside the navigation", "one inside and one outside", "two of them", "turned off by aria",
        "saying pay",
        "saying transfer"])
def test_only_his_next_page_button_is_pressed_and_only_while_on(paged, kind):
    paged.open(**kind)
    got, trace = paged.download("2026-07-31")
    assert not got and paged.hits == [] and paged.presses() == 0, trace
    # Never so much as tried, the browser's own wait for a button it holds
    # off included.
    assert not any(t.get("pressed") or t.get("error") for t in trace if t.get("note") == "next page"), trace


def test_a_statement_the_lists_never_gave_moves_no_page(paged):
    paged.open()
    got, _trace = paged.download("2026-06-30")
    assert not got and paged.hits == [] and paged.presses() == 0


def test_a_statement_listed_on_no_page_moves_the_list_only_while_next_page_is_on(paged):
    """The lists gave it and no page shows it. The list is moved on to its
    last page, where Next page is off, and nothing more."""
    site._note_listed([_list(_entry(SINGLE, "", "2026-06-30", shown=BROKERAGE))])
    paged.open()
    got, trace = paged.download("2026-06-30")
    assert not got and paged.hits == []
    assert paged.presses() == 1
    nexts = [t for t in trace if t.get("note") == "next page"]
    assert [(t.get("pressed"), t.get("turned_on"), t.get("error")) for t in nexts] == \
        [(True, True, None), (None, False, None)], nexts


def test_a_press_that_does_not_move_the_list_is_not_made_again(paged):
    paged.open(stuck=True)
    got, trace = paged.download("2026-07-31")
    assert not got and paged.hits == [] and paged.presses() == 1
    assert [t.get("moved") for t in trace if t.get("note") == "next page"] == [False]


MIXED = [(BANK, "2026-09-30", "09/30/26", "b1"), (BANK, "2026-08-31", "08/31/26", "b2"),
         (SINGLE, "2026-07-31", "07/31/26", "s3")]


def test_a_statement_past_a_first_page_of_other_titles_is_taken_there(paged):
    paged.open(docs=MIXED)
    got, trace = paged.download("2026-07-31")
    assert got and paged.hits == ["s3"] and paged.presses() == 1, trace


def test_rows_whose_dates_cannot_be_read_move_no_page(paged):
    """The statement may be on the page shown in a shape the check does not
    read, so the list is left where it is."""
    paged.open(dated=False)
    paged.download("2026-07-31")
    assert paged.presses() == 0


SPLIT = [(BANK, "2026-09-30", "09/30/26", "b1"), (BANK, "2026-07-31", "07/31/26", "b2"),
         (SINGLE, "2026-07-31", "07/31/26", "s3")]


def test_a_date_the_page_shown_prints_keeps_the_list_where_it_is(paged):
    """A day split across two pages. Its other statement's row prints the
    date on the first page, and the list is left there, so this statement
    goes to Manual Review as it did, never past a row it might be."""
    paged.open(docs=SPLIT)
    got, _trace = paged.download("2026-07-31")
    assert not got and paged.presses() == 0


def test_next_page_is_never_pressed_on_a_tab_off_etrades_site(paged):
    paged.open(at="https://us.etrade.com.invented.example/etx/pxy/accountdocs#/documents")
    _got, trace = paged.download("2026-07-31")
    assert paged.presses() == 0
    assert [t.get("refused") for t in trace if t.get("note") == "next page"] == [True], trace



# --- what the review found ---------------------------------------------------------

def _snapshot(app):
    return json.loads(json.dumps(app.progress.data)), json.loads(json.dumps(app.discovery.data))


def _saved(app, *keys):
    for key in keys:
        app.progress.data[key] = dict(app.discovery.data[key], state=State.COMPLETED.value,
                                      downloaded_ok=True)


@pytest.mark.parametrize("meta", [{}, _accounts()], ids=["no account list", "an empty one"])
def test_a_discover_that_misses_the_account_list_stops_before_anything_moves_or_is_taken(app, meta):
    """The account list missed, late, refused or renamed. Every document read
    as one of no account, and a sign-in of one account took its whole
    history again under keys of none (review)."""
    app.listing(_accounts((K_BROKERAGE, BROKERAGE)), _list(_entry(SINGLE, K_BROKERAGE)))
    _saved(app, _key(SINGLE, "2222"))
    before = _snapshot(app)
    with pytest.raises(SystemExit):
        app.listing(meta, _list(_entry(SINGLE, K_BROKERAGE)))
    assert _snapshot(app) == before
    assert app.failures[-1] == ("read the documents list", site.ACCOUNTS_UNREAD)
    assert _left_to_take(app) == []


def test_an_account_the_lists_named_before_with_no_label_now_stops_the_run(app):
    both = [_entry(SINGLE, K_CASH), _entry(SINGLE, K_BROKERAGE)]
    app.listing(THEIRS, _list(*both))
    _saved(app, _key(SINGLE, "1111"), _key(SINGLE, "2222"))
    before = _snapshot(app)
    with pytest.raises(SystemExit):
        app.listing(_accounts((K_CASH, CASH)), _list(_entry(SINGLE, K_CASH), _entry(SINGLE, K_BROKERAGE)))
    assert _snapshot(app) == before
    assert app.failures[-1] == ("read the documents list", site.ACCOUNT_LOST)


def _key_of(title, account, entry, day=DAY):
    return etrade_docs.Document(category="Statement", date=day, title=title, account=account, entry=entry).key


def test_one_accounts_two_documents_of_a_title_and_day_stay_two_and_nothing_is_pressed(app, monkeypatch, tmp_path):
    """Two trade confirmations of one account and day. Once the account was
    read they were one record, its download refused, and the second was
    never listed (review)."""
    meta = _accounts((K_BROKERAGE, BROKERAGE))
    app.listing(meta, _list(_entry(SINGLE, K_BROKERAGE), _entry(SINGLE, K_BROKERAGE)))
    pair = sorted([_key_of(SINGLE, BROKERAGE, "#1"), _key_of(SINGLE, BROKERAGE, "#2")])
    assert sorted(app.discovery.data) == pair and all(":2222#" in k for k in pair)
    opened: list = []
    monkeypatch.setattr(site, "goto_documents", lambda page: opened.append(page) or True)
    trace: list = []
    assert not site.download_bill(None, tmp_path, DAY, tmp_path / "out.pdf", SINGLE, trace, account=BROKERAGE)
    assert opened == [] and [t.get("why") for t in trace] == [site.TWICE_FOR_ONE_ACCOUNT]
    # A later list giving the account one such document takes that one alone.
    for rec in app.discovery.data.values():
        rec["state"] = State.NEEDS_MANUAL_REVIEW.value
    app.listing(meta, _list(_entry(SINGLE, K_BROKERAGE)))
    taken: list = []
    app._on_its_site = lambda: None
    app._delay = lambda factor=1.0: None
    app.download_one = lambda page, doc, filename: taken.append(doc.key)
    app.stats.update(skipped_completed=0)
    app.process(app._select())
    assert taken == [_key(SINGLE, "2222")]


def test_an_account_with_no_label_still_counts_so_history_moves_only_by_its_pdf(app):
    """One account labeled and one not. Counted as a sign-in of one account,
    a record kept before moved to the labeled one by the list alone, though
    it may hold the other's statement (review)."""
    _record(app, SINGLE, _legacy_key(SINGLE), "2026-09-30 Statement.pdf", prints=["No account printed"])
    app.listing(_accounts((K_BROKERAGE, BROKERAGE)), _list(_entry(SINGLE, K_BROKERAGE), _entry(BANK, K_UNNAMED)))
    assert _legacy_key(SINGLE) in app.progress.data
    assert app.discovery.data[_key(SINGLE, "2222")]["summary"] == "Account Statement - " + BROKERAGE


def test_a_reload_that_fails_leaves_the_next_download_to_open_the_first_page_again(monkeypatch, tmp_path):
    """The list may still show a later page, so nothing is looked for on it
    and the next download tries again (review)."""
    monkeypatch.setattr(site, "_MOVED_ON", [True])

    class Tab:
        url = DOCS_URL

        def reload(self, **kw):
            raise RuntimeError("invented")

        def wait_for_timeout(self, ms):
            pass
    opened: list = []
    monkeypatch.setattr(site, "goto_documents", lambda page: opened.append(page) or True)
    assert not site.download_bill(Tab(), tmp_path, "2026-07-31", tmp_path / "out.pdf", SINGLE, [],
                                  account=BROKERAGE)
    assert opened == [] and site._MOVED_ON == [True]


def test_an_account_that_closes_keeps_its_records_key(app):
    """#119 reads a closed account's label, "... - 2222 (Closed)", by its
    digits, so a statement saved while it was open is not taken again."""
    app.listing(_accounts((K_BROKERAGE, BROKERAGE)), _list(_entry(SINGLE, K_BROKERAGE)))
    key = _key(SINGLE, "2222")
    _saved(app, key)
    app.listing(_accounts((K_BROKERAGE, BROKERAGE + " (Closed)")), _list(_entry(SINGLE, K_BROKERAGE)))
    assert sorted(app.discovery.data) == [key]
    assert _left_to_take(app) == []
