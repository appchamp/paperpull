"""Statements & Documents is reached from Wells Fargo's landing page in
whatever shape the page draws its control, and Diagnose writes its file
when it is not (#27).

A tester on PaperPull Server, signed in and on the accounts summary, had
Run All stop at its first step, "the page has no statements and documents
link". The failure file counted 50 buttons and no link. That count was of
a[href] alone, and Wells Fargo draws its links as an <a role=link> with no
address, the statements included (a recording, 2026-10-15), so a page full
of links counts none, and nothing on it looked inside a shadow root. The
app's own search, a locator by role and whole name, finds such a link and
one in an open shadow root, so what it missed was a control that did not
show, a link behind the page's menu say.

So the page's own control is pressed in each shape it could take, a link
in an open shadow root, a button, an entry behind the page's Menu button,
and only a button whose whole name is Menu is opened to look for it. A
page with none of them still stops, as it did. Diagnose run there used to
stop the same way before it wrote anything, so the tester had no file
naming the controls. It surveys the page the window shows now, and says it
could not open the documents page.

Everything here is invented, and real Chromium is driven against made-up
pages served at Wells Fargo's own addresses.
"""
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import wellsfargo_docs as app_mod
import wellsfargo_site as site
from paperpull_core import failure, pressing

SIGNED_IN = "https://connect.secure.wellsfargo.com"
SUMMARY = SIGNED_IN + "/accounts/start?_x=T0K3N"
EDOCS = SIGNED_IN + "/edocs/documents?_x=T0K3N"

# Every control on these pages notes its own press, kept for the page the
# tab goes to, and the documents
# control goes to the statements page the way Wells Fargo's does, from a
# handler, since its link has no address.
TRACK = """<script>
window.pressed = JSON.parse(sessionStorage.getItem('pressed') || '[]');
document.addEventListener('click', (e) => {
  const el = e.composedPath().find((n) => n.dataset && n.dataset.name);
  if (!el) return;
  window.pressed.push(el.dataset.name);
  sessionStorage.setItem('pressed', JSON.stringify(window.pressed));
  if (el.dataset.name === 'documents') location.href = '/edocs/documents?_x=T0K3N';
}, true);
</script>"""


def _doc(tag="a", name="Statements &amp; Documents"):
    role = ' role="link" tabindex="0"' if tag == "a" else ""
    return '<%s data-name="documents"%s>%s</%s>' % (tag, role, name, tag)


OTHERS = ('<a role="link" tabindex="0" data-name="transfer">Transfer &amp; Pay</a>'
          '<button data-name="accounts" aria-expanded="false">Accounts</button>')

LANDING = """<!doctype html><meta charset="utf-8"><title>Account Summary</title>
<header>%(header)s</header>
<main><h1>Account Summary</h1><p>Everyday Checking ...1111</p>
<button data-name="details">Account details</button></main>""" + TRACK

SHADOW = """<!doctype html><meta charset="utf-8"><title>Account Summary</title>
<wf-nav></wf-nav><main><h1>Account Summary</h1></main>
<script>
customElements.define('wf-nav', class extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode: 'open'}).innerHTML = '<nav>%(nav)s</nav>';
  }
});
</script>""" + TRACK

MENU = """<!doctype html><meta charset="utf-8"><title>Account Summary</title>
<header><button data-name="menu" aria-expanded="%(expanded)s" aria-controls="drawer"
  onclick="const o = this.getAttribute('aria-expanded') === 'true';
           this.setAttribute('aria-expanded', o ? 'false' : 'true');
           document.getElementById('drawer').hidden = o;">%(label)s</button>
<nav id="drawer" %(hidden)s>%(drawer)s</nav></header>
<main><h1>Account Summary</h1></main>""" + TRACK

EDOCS_PAGE = """<!doctype html><meta charset="utf-8"><title>Statements</title>
<main><form><a role="link" tabindex="0">Statement 09/30/26 (123K, PDF)</a></form></main>"""


class Site:
    """Wells Fargo's addresses, served from here, with every address the
    tab is sent to kept."""

    def __init__(self, landing: str):
        self.landing = landing
        self.navigations = []

    def handle(self, route):
        req = route.request
        parts = urlsplit(req.url)
        if req.is_navigation_request():
            self.navigations.append(req.url)
        if parts.hostname not in ("connect.secure.wellsfargo.com", "www.wellsfargo.com"):
            return route.abort()
        if parts.path == "/accounts/start":
            return route.fulfill(content_type="text/html", body=self.landing)
        if parts.path == "/edocs/documents":
            return route.fulfill(content_type="text/html", body=EDOCS_PAGE)
        return route.fulfill(content_type="text/html", body="<p>Wells Fargo</p>")


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
def open_site(browser):
    contexts = []

    def opener(fake: Site):
        ctx = browser.new_context()
        contexts.append(ctx)
        ctx.route("**/*", fake.handle)
        pg = ctx.new_page()
        pg.goto(SUMMARY)
        fake.navigations.clear()
        return pg
    yield opener
    for ctx in contexts:
        ctx.close()


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    monkeypatch.setattr(site, "dismiss_overlay", lambda pg: None)
    monkeypatch.setattr(site, "_SHOW_MS", 2000)


def _pressed(pg):
    return pg.evaluate("JSON.parse(sessionStorage.getItem('pressed') || '[]')")


def _menu(drawer, label="Menu", expanded="false"):
    return MENU % {"label": label, "expanded": expanded, "drawer": drawer,
                   "hidden": "hidden" if expanded == "false" else ""}


# -- each shape the page could draw its control in --------------------------------

def test_a_link_with_no_address_in_an_open_shadow_root_is_pressed(open_site):
    fake = Site(SHADOW % {"nav": OTHERS.replace("'", "\\'") + _doc().replace("'", "\\'")})
    pg = open_site(fake)
    assert site.goto_documents(pg) is True
    assert fake.navigations == [EDOCS], fake.navigations
    assert site._on_edocs(pg.url)


def test_a_button_named_statements_and_documents_is_pressed(open_site):
    fake = Site(LANDING % {"header": OTHERS + _doc("button", "Statements and Documents")})
    pg = open_site(fake)
    assert site.goto_documents(pg) is True
    assert fake.navigations == [EDOCS]


def test_a_link_behind_the_menu_is_shown_by_the_menu_and_pressed(open_site):
    fake = Site(_menu(OTHERS + _doc()))
    pg = open_site(fake)
    assert site.goto_documents(pg) is True
    assert fake.navigations == [EDOCS]
    assert _pressed(pg) == ["menu", "documents"], _pressed(pg)


def test_the_menu_is_not_opened_when_the_link_shows_already(open_site):
    fake = Site(_menu(OTHERS, expanded="false").replace(
        "<main>", "<main>" + _doc()))
    pg = open_site(fake)
    assert site.goto_documents(pg) is True
    assert _pressed(pg) == ["documents"], _pressed(pg)


# -- and what is never pressed -----------------------------------------------------

def test_a_page_with_no_such_control_stops_as_it_did(open_site):
    fake = Site(LANDING % {"header": OTHERS})
    pg = open_site(fake)
    with pytest.raises(pressing.Stop) as stop:
        site.goto_documents(pg)
    assert stop.value.reason == "the page has no statements and documents link"
    assert stop.value.facts == {"menu_pressed": False, "menu_button_shown": False,
                                "hidden_documents_links": 0}
    assert fake.navigations == [] and _pressed(pg) == []


def test_a_menu_that_holds_no_such_link_stops_with_nothing_else_pressed(open_site):
    fake = Site(_menu(OTHERS))
    pg = open_site(fake)
    with pytest.raises(pressing.Stop) as stop:
        site.goto_documents(pg)
    assert stop.value.reason == "the menu has no statements and documents link"
    assert stop.value.facts["menu_pressed"] is True
    assert fake.navigations == []
    assert _pressed(pg) == ["menu"], _pressed(pg)


@pytest.mark.parametrize("label", ["Main menu", "Menu and settings", "Account menu", "Menus"])
def test_a_button_whose_name_is_more_than_menu_is_never_opened(open_site, label):
    fake = Site(_menu(OTHERS + _doc(), label=label))
    pg = open_site(fake)
    with pytest.raises(pressing.Stop) as stop:
        site.goto_documents(pg)
    assert stop.value.reason == "the page has no statements and documents link"
    assert stop.value.facts["hidden_documents_links"] == 1
    assert _pressed(pg) == [] and fake.navigations == []


def test_a_menu_that_says_it_is_open_is_never_pressed(open_site):
    """Pressing an open menu closes it."""
    fake = Site(_menu(OTHERS, expanded="true"))
    pg = open_site(fake)
    with pytest.raises(pressing.Stop) as stop:
        site.goto_documents(pg)
    assert stop.value.reason == "the page has no statements and documents link"
    assert _pressed(pg) == []


def test_a_control_with_more_words_than_the_documents_name_is_never_pressed(open_site):
    fake = Site(LANDING % {"header": OTHERS + _doc("button", "Statements &amp; Documents settings")})
    pg = open_site(fake)
    with pytest.raises(pressing.Stop):
        site.goto_documents(pg)
    assert _pressed(pg) == []


def test_only_a_menu_button_named_menu_reads_as_one():
    assert site.is_menu_button("Menu") and site.is_menu_button("  menu ")
    for words in ("Main menu", "Menu and settings", "Transfer", "", "Menus"):
        assert not site.is_menu_button(words), words


# -- what the failure file counts ---------------------------------------------------

def test_the_failure_file_counts_links_with_no_address_shadow_roots_and_named_controls(
        open_site):
    fake = Site(SHADOW % {"nav": (OTHERS + _doc()).replace("'", "\\'")})
    pg = open_site(fake)
    counts = failure.page_state(pg)["counts"]
    assert counts["links"] == 0
    assert counts["shadow_roots"] == 1
    assert counts["shadow_links"] == 2
    assert counts["shadow_buttons"] == 1
    assert counts["statements_and_documents_controls"] == 1
    assert counts["statements_and_documents_shown"] == 1
    assert counts["statements_controls"] == 1 and counts["documents_controls"] == 1

    fake = Site(_menu(OTHERS + _doc()))
    pg = open_site(fake)
    counts = failure.page_state(pg)["counts"]
    assert counts["links_with_no_href"] == 2
    assert counts["collapsed_buttons"] == 2
    assert counts["statements_and_documents_controls"] == 1
    assert counts["statements_and_documents_shown"] == 0
    said = failure.summarize({"page": {"counts": counts}})
    assert any("does not show" in line for line in said), said


# -- Diagnose -----------------------------------------------------------------------

def _config(tmp_path):
    example = Path(app_mod.__file__).parent / "config.example.json"
    config = json.loads(example.read_text(encoding="utf-8"))
    config.update({"owner": "Dana Example", "output_dir": str(tmp_path / "out"),
                   "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
                   "delay_min_seconds": 0, "delay_max_seconds": 0})
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    return cfg


def test_diagnose_on_a_page_it_cannot_leave_writes_both_files(open_site, tmp_path,
                                                               monkeypatch, capsys):
    fake = Site(LANDING % {"header": OTHERS})
    pg = open_site(fake)
    monkeypatch.setattr(site, "survey", lambda page, dwell_ms=4000, max_follow=6: {
        "pages": [site._page_summary(page)], "responses": [], "followed": max_follow})

    def page(self):
        self._work_page = pg
        return pg
    monkeypatch.setattr(app_mod.App, "page", page)
    monkeypatch.setattr(app_mod.App, "close", lambda self: None)
    assert app_mod.main(["--config", str(_config(tmp_path)), "--diagnose"]) == 0
    said = capsys.readouterr().out
    assert "!! The run could not open Statements & Documents" in said
    assert "Diagnose could not open Statements & Documents" in said

    out = tmp_path / "out"
    (detailed,) = sorted(out.rglob("diagnose-documents.json"))
    info = json.loads(detailed.read_text(encoding="utf-8"))
    assert info["documents_page_opened"] is False
    assert info["documents_page_found"] is False
    assert info["stopped"]["reason"] == "the page has no statements and documents link"
    assert info["documents_link"] == {"shown": False, "hidden": 0, "menu_button_shown": False}
    # The page the window shows is surveyed, and no link on it followed.
    assert info["survey"]["followed"] == 0
    assert info["survey"]["pages"][0]["controls"], "no control of the page was named"

    (survey,) = sorted(out.rglob("survey-diagnose-*.json"))
    report = json.loads(survey.read_text(encoding="utf-8"))
    assert report["extra"]["stopped"]["reason"] == \
        "the page has no statements and documents link"
    assert report["page"]["counts"]["buttons"] == 2
    assert not sorted(out.rglob("failure-*.json"))
    assert fake.navigations == [] and _pressed(pg) == []
