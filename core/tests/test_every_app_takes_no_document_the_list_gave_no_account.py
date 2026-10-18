"""A document the list gives no account is never taken for one of several.

test_every_app_tells_two_accounts_apart drives an app's own discovery with
two accounts' statements of one day, each with its account. The second
report on E*TRADE's #96 came from a sign-in of five accounts, and the list
can give a document no account at all. Discovery kept one record for every
such statement of a date and title and dropped the rest, and every guard
that reads the account passed a document of none, so the one row the page
showed was taken for it, whichever account's it was.

So every app whose own discovery that census drives is driven here too, or
says why not. Its own parse of the list reads two statements of one date
and title that carry no account, its own discovery keeps them, and its own
download of each, while the page shows one row of that date naming the
document, presses nothing. The same with one such statement is pressed
once, so the check is not of a download that presses nothing at all.

Everything here is invented.
"""
import ast
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
DAY = "2026-03-31"
TITLE = "Brokerage Statement"

sync_api = pytest.importorskip("playwright.sync_api")


def load(app: str):
    for name in [m for m in list(sys.modules)
                 if m.endswith(("_docs", "_receipts", "_site")) or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(REPO / "apps" / app))
    try:
        importlib.import_module("storage")
        return importlib.import_module("%s_docs" % app)
    finally:
        sys.path.pop(0)


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch(headless=True)
        except Exception as e:
            pytest.skip("no browser to drive: %s" % e)
        yield b
        b.close()


@pytest.fixture
def page(browser):
    pg = browser.new_page()
    yield pg
    pg.close()


def _etrade(mod, tmp_path: Path, monkeypatch, page, n: int):
    """E*TRADE's own parse of a searchItems answer holding `n` Brokerage
    Statements of one day with no displayMultipleAccounts, its own
    discovery over what that parse gives, and its own download of each
    record while the page shows one row of that day naming the document.
    Only the page's list and the catch are stood in for. Returns the
    records and every element the download chose to press."""
    site = mod.site
    storage = sys.modules["storage"]            # the app's own, loaded with it
    from paperpull_core import doc_types
    for name in ("_LISTED", "_LISTED_TITLES", "_LISTED_ACCOUNTS", "_LISTED_DOCS"):
        monkeypatch.setattr(site, name, {})
    body = {"defaultDocumentList": [
        {"documentGuid": "g%d" % i, "documentId": "id-%d" % i, "documentTypeName": "STATEMENTS",
         "documentTitle": TITLE, "documentDate": DAY + "T00:00:00.000Z"} for i in range(n)]}

    def capturing(page, capture):
        capture.append(body)
        return True
    monkeypatch.setattr(site, "goto_docs_capturing", capturing)
    monkeypatch.setattr(site, "widen_date_filter", lambda page, wider, trace=None: False)
    listed = site.collect_download_docs(None)

    app = object.__new__(mod.App)
    app.args = SimpleNamespace(start_date=None, end_date=None)
    app.config = {"document_types": ["Statement"], "owner": ""}
    app.paths = storage.Paths(tmp_path)
    app.paths.ensure()
    app.progress = storage.JsonStore(app.paths.progress_json)
    app.discovery = storage.JsonStore(app.paths.discovery_json)
    app.rules = doc_types.load_rules()
    app.stats = {"skipped_out_of_scope": 0, "discovered": 0}
    app.page = lambda: None
    app.check_session = lambda page: None
    monkeypatch.setattr(site, "goto_documents", lambda page: True)
    monkeypatch.setattr(site, "collect_download_docs", lambda page: list(listed))
    app.cmd_discover(quiet=True)

    pressed: list = []
    monkeypatch.setattr(site, "expand_all", lambda page: None)
    monkeypatch.setattr(site, "_catch_pdf", lambda pg, el, *a, **k: pressed.append(el) or False)
    for rec in app.discovery.data.values():
        page.set_content("<ul><li><span>03/31/26</span> <a href='#'>%s</a></li></ul>" % TITLE)
        site.download_bill(page, tmp_path / "dl", rec["date"], tmp_path / "out.pdf", rec["title"], [],
                           account=rec.get("account") or "")
    return app.discovery.data, pressed


# Apps driven here, each by a function that lists `n` statements of one
# title and day with no account through its own parse and discovery, and
# downloads each record with one row of that day on the page.
DRIVEN = {"etrade": _etrade}

# Apps the two-accounts census drives whose discovery is not driven here,
# each with why a document of no account is never taken for another there.
NOT_DRIVEN = {
    "wellsfargo": "with one account in its picker, or none, its documents carry no account, and "
                  "its discovery keeps one record for each date and kind with the number of rows "
                  "holding it, and its download refuses a record of more than one row "
                  "(wellsfargo_site.collect_download_docs)",
}


def _discovers() -> set:
    """The apps whose own discovery test_every_app_tells_two_accounts_apart
    drives, read from its DISCOVERS."""
    tree = ast.parse((Path(__file__).parent / "test_every_app_tells_two_accounts_apart.py")
                     .read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "DISCOVERS"
                                                for t in node.targets):
            return {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
    return set()


def test_every_app_whose_discovery_is_driven_for_two_accounts_is_asked():
    found = _discovers()
    assert "etrade" in found, found
    assert found <= set(DRIVEN) | set(NOT_DRIVEN), found - set(DRIVEN) - set(NOT_DRIVEN)
    assert not set(DRIVEN) & set(NOT_DRIVEN)


@pytest.mark.parametrize("name", sorted(DRIVEN))
def test_documents_the_list_gave_no_account_are_each_kept_and_none_is_taken_from_one_row(
        name, tmp_path, monkeypatch, page):
    mod = load(name)
    records, pressed = DRIVEN[name](mod, tmp_path, monkeypatch, page, 2)
    assert len(records) == 2, (
        "%s's discovery kept %d record(s) for two statements of one day the list gave no account"
        % (name, len(records)))
    assert len({mod.Document.from_dict(r).key for r in records.values()}) == 2, sorted(records)
    assert pressed == [], (
        "%s pressed %d element(s) for documents the list gave no account, on a day it gave "
        "their title twice" % (name, len(pressed)))


@pytest.mark.parametrize("name", sorted(DRIVEN))
def test_the_one_document_the_list_gave_no_account_that_day_is_still_taken(name, tmp_path, monkeypatch, page):
    mod = load(name)
    records, pressed = DRIVEN[name](mod, tmp_path, monkeypatch, page, 1)
    assert len(records) == 1 and len(pressed) == 1, (len(records), len(pressed))
