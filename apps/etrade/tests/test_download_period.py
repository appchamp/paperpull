"""The download chooses the one period that lists its document.

On 0.37.0 discovery found thirteen documents and Pilot saved none (#36).
Discovery walks "Year To Date" and then every year back, and each Apply
replaces the list the page shows rather than adding to it. So discovery
ended with the page showing the oldest year, which held nothing in his
account, and the download then walked every period again and ended on
an empty year once more. His failure file counted the same rows the
empty years had shown, the last lists the page loaded were the small
empty answers, and the download trace said no element on the page
carried the document's date.

The download now sets the picker to the period that lists the document,
the year of its date, or "Year To Date" for a date newer than every year
the picker offers.

The page below is the period picker page again, with the oldest year
empty, rows that print the date the way E*TRADE's rows do, and a title
link that fetches the PDF. It runs in a real browser, because the picker
is found by its accessible name and only a browser computes one.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import etrade_site as site

TITLE = "Brokerage Statement"
# Invented. The years stop short of the newest documents, which only
# "Year To Date" lists, and the oldest year holds nothing.
DATES = {"Last 90 Days": ["2026-08-31"],
         "Year To Date": ["2026-08-31", "2026-02-28"],
         "2025": ["2025-11-30", "2025-05-31"],
         "2024": []}

PAGE = """<!doctype html><html><body>
<h1>Statements &amp; Documents</h1>
<form id="filters">
  <button type="button" id="picker" aria-label="Timeframe ,  Last 90 Days"
          aria-haspopup="listbox">Last 90 Days</button>
  <div role="listbox" id="list" style="display:none">
    <div role="option">Last 90 Days</div>
    <div role="option">Year To Date</div>
    <div role="option">2025</div>
    <div role="option">2024</div>
  </div>
  <button type="reset">Reset</button>
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
function shortDate(iso) {
  const [y, m, d] = iso.slice(0, 10).split("-");
  return m + "/" + d + "/" + y.slice(2);
}
function search(tf) {
  return fetch("https://ext-web.etrade.com/etaz/api/adsal/accountdocs/v2/searchItems", {
    method: "POST", headers: {"Content-Type": "text/plain"},
    body: JSON.stringify({TimeFrame: tf, pageNum: 1})
  }).then(r => r.json()).then(b => {
    const rows = document.getElementById("rows");
    rows.innerHTML = "";
    for (const d of b.defaultDocumentList) {
      const tr = document.createElement("tr");
      tr.innerHTML = "<td>" + shortDate(d.documentDate) + "</td><td><a href='#'>" + d.documentTitle + "</a></td>";
      tr.querySelector("a").addEventListener("click", (e) => {
        e.preventDefault();
        fetch("/docs/" + d.documentDate.slice(0, 10) + ".pdf");
      });
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
</script></body></html>"""


def _answer(route):
    req = route.request
    if req.method != "POST":
        return route.fulfill(status=204, headers={"access-control-allow-origin": "*"})
    tf = json.loads(req.post_data or "{}").get("TimeFrame", "")
    body = {"defaultDocumentList": [
        {"documentGuid": "g-%s" % d, "documentId": "i-%s" % d, "documentTypeName": "Statements",
         "documentTitle": TITLE, "documentDate": d + "T00:00:00",
         "displayMultipleAccounts": "Invented Brokerage"} for d in DATES.get(tf, [])],
        "numFound": str(len(DATES.get(tf, [])))}
    route.fulfill(status=200, content_type="application/json",
                  headers={"access-control-allow-origin": "*"}, body=json.dumps(body))


def _site(route):
    url = route.request.url
    if "/docs/" in url and url.endswith(".pdf"):
        day = url.rsplit("/", 1)[-1][:-4]
        return route.fulfill(status=200, content_type="application/pdf",
                             body=b"%PDF-1.4\n% invented statement " + day.encode() + b"\n%%EOF\n")
    route.fulfill(status=200, content_type="text/html", body=PAGE)


@pytest.fixture(scope="module")
def browser():
    """One browser for the module, since one thread drives one at a time."""
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        b = driver.chromium.launch(headless=True)
    except Exception as e:                       # no browser on this machine
        pytest.skip("no browser to drive: %s" % e)
    yield b
    b.close()
    driver.stop()


@pytest.fixture(scope="module")
def after_discovery(browser):
    """A page left the way Pilot leaves it, discovery first, in one run."""
    ctx = browser.new_context()
    ctx.route("https://us.etrade.com/**", _site)
    ctx.route("https://ext-web.etrade.com/**", _answer)
    pg = ctx.new_page()
    docs = site.collect_download_docs(pg)
    yield pg, docs
    ctx.close()


def test_discovery_leaves_the_page_on_the_oldest_year(after_discovery):
    """The state his Pilot was in when it looked for the first row."""
    pg, docs = after_discovery
    assert len(docs) == 4
    assert site._find_picker(pg)[1] == "2024"
    assert site._row_count(pg) == 0


@pytest.mark.parametrize("day, period", [("2025-11-30", "2025"),
                                         ("2026-02-28", "Year To Date"),
                                         ("2025-05-31", "2025")])
def test_the_document_downloads_from_the_period_that_lists_it(after_discovery, tmp_path, day, period):
    """0.37.0 looked for every row on the oldest year's empty list (#36)."""
    pg = after_discovery[0]
    out = tmp_path / ("%s.pdf" % day)
    trace: list = []
    assert site.download_bill(pg, tmp_path / "dl", day, out, title=TITLE, trace=trace), trace
    assert out.read_bytes().startswith(b"%PDF-") and day.encode() in out.read_bytes()
    assert site._find_picker(pg)[1] == period
    note = next(t for t in trace if t.get("note") == "period for this document")
    assert note["found"] is True and note["period"] == period


def test_the_period_trace_holds_period_words_only(after_discovery):
    """download-attempt.json is attached to a public issue."""
    pg = after_discovery[0]
    trace: list = []
    site.show_period_for(pg, "2025-11-30", trace)
    text = json.dumps(trace)
    assert TITLE not in text and "Invented Brokerage" not in text
    note = trace[0]
    assert set(note) <= {"note", "found", "showing", "period", "error"}


# Invented, the shape the picker offered in his trace. Years, a few
# "Last N" periods in both capitals, and "Year To Date".
OFFERED = ["2017", "2018", "2019", "2020", "2021", "2022", "2023", "2024",
           "Last 10 Days", "Last 12 Months", "Last 30 Days", "Last 30 days",
           "Last 90 days", "Year To Date"]


@pytest.mark.parametrize("day, period", [
    ("2025-02-28", "Year To Date"),      # newer than every year offered
    ("2024-08-31", "2024"),
    ("2017-12-31", "2017"),
    ("2016-12-31", None),                # no period lists it
])
def test_the_period_for_a_date(day, period):
    assert site.period_for(day, OFFERED) == period


def test_a_period_wider_than_a_year_lists_every_date():
    assert site.period_for("2019-04-30", ["Last 90 Days", "All", "2024"]) == "All"


def test_a_picker_with_only_narrow_periods_gets_the_widest():
    assert site.period_for("2026-01-31", ["Last 30 Days", "Last 12 Months"]) == "Last 12 Months"
    assert site.period_for("2026-01-31", []) is None


# A picker page for the cases review raised, set up by the address. Its
# options are role=option or plain elements, Escape closes its list or
# does nothing, it starts on any period, and it can open a list that has
# not drawn its periods yet, or draws them a while after it opens.
# Apply is counted.
PICKER_PAGE = """<!doctype html><html><body>
<h1>Statements &amp; Documents</h1>
<form id="filters">
  <button type="button" id="picker" aria-haspopup="listbox" aria-expanded="false"></button>
  <div id="list" style="display:none"></div>
  <button type="reset">Reset</button>
  <button type="submit">Apply</button>
</form>
<script>
const q = new URLSearchParams(location.search);
const plain = q.get("opts") === "div";
const periods = (q.get("list") || "Last 90 Days|Year To Date|2025|2024").split("|");
let current = q.get("start") || "Last 90 Days", pending = null;
window.applies = 0;
const picker = document.getElementById("picker");
const list = document.getElementById("list");
function label() { picker.setAttribute("aria-label", "Timeframe ,  " + current); picker.textContent = current; }
function setOpen(open) {
  list.style.display = open ? "block" : "none";
  picker.setAttribute("aria-expanded", open ? "true" : "false");
}
label();
if (!plain) list.setAttribute("role", "listbox");
function fill() {
  list.innerHTML = "";
  for (const p of periods) {
    const o = document.createElement("div");
    if (!plain) o.setAttribute("role", "option");
    o.textContent = p;
    o.style.cursor = "pointer";
    o.addEventListener("click", () => { pending = p; setOpen(false); });
    list.appendChild(o);
  }
}
const late = +(q.get("late") || 0);
let filled = !late;
if (q.get("empty") === "1" || late) {
  list.innerHTML = "<div>Loading</div>";
} else {
  fill();
}
picker.addEventListener("click", () => {
  setOpen(list.style.display === "none");
  if (!filled) { filled = true; setTimeout(fill, late); }
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && q.get("esc") !== "0") setOpen(false);
});
document.getElementById("filters").addEventListener("submit", (e) => {
  e.preventDefault();
  window.applies += 1;
  if (pending) { current = pending; pending = null; }
  label();
  fetch("https://ext-web.etrade.com/etaz/api/adsal/accountdocs/v2/searchItems", {
    method: "POST", headers: {"Content-Type": "text/plain"},
    body: JSON.stringify({TimeFrame: current, pageNum: 1})});
});
</script></body></html>"""


@pytest.fixture(scope="module")
def picker_site(browser):
    ctx = browser.new_context()
    ctx.route("https://us.etrade.com/**", lambda r: r.fulfill(
        status=200, content_type="text/html", body=PICKER_PAGE))
    ctx.route("https://ext-web.etrade.com/**", _answer)

    def open_page(**settings):
        from urllib.parse import urlencode
        pg = ctx.new_page()
        pg.goto("https://us.etrade.com/etx/pxy/accountdocs?" + urlencode(settings))
        pg.wait_for_timeout(300)
        return pg
    yield open_page
    ctx.close()


def _list_open(pg) -> bool:
    return pg.evaluate("document.getElementById('list').style.display") != "none"


def test_the_period_showing_counts_as_offered(picker_site, monkeypatch):
    """With plain options the period the picker shows was missing from what
    the list was read to offer, since the picker's own text was there
    before the list opened. A 2025 document with 2025 showing was then
    sent to "Year To Date", which does not list it (#36, review)."""
    monkeypatch.setattr(site, "_OFFERED", [])
    pg = picker_site(opts="div", start="2025")
    trace: list = []
    assert site.show_period_for(pg, "2025-05-31", trace)
    assert site._find_picker(pg)[1] == "2025"
    assert pg.evaluate("window.applies") == 0
    assert not _list_open(pg)
    assert "2025" in site._OFFERED
    # The path that opened and read the picker writes the same few keys.
    assert trace[0]["note"] == "period for this document" and trace[0]["period"] == "2025"
    assert set(trace[0]) <= {"note", "found", "showing", "period", "error"}
    pg.close()


def test_a_read_that_finds_no_period_keeps_what_was_remembered(picker_site, monkeypatch):
    """A list that draws late reads as offering nothing. The download then
    left the page on whatever it showed, which straight after discovery is
    the empty oldest year, the #36 symptom (review)."""
    monkeypatch.setattr(site, "_OFFERED", ["2024", "2025", "Last 90 Days", "Year To Date"])

    def read_nothing(page, picker, current=""):
        picker.click(timeout=5000)
        page.wait_for_timeout(300)
        return [], 0
    monkeypatch.setattr(site, "_periods_offered", read_nothing)
    pg = picker_site(start="Year To Date")
    assert site.show_period_for(pg, "2025-05-31", [])
    assert site._find_picker(pg)[1] == "2025"
    pg.close()


def test_an_empty_read_does_not_forget_the_periods(picker_site, monkeypatch):
    remembered = ["2024", "2025", "Last 90 Days", "Year To Date"]
    monkeypatch.setattr(site, "_OFFERED", list(remembered))
    pg = picker_site(empty="1")
    picker = site._find_picker(pg)[0]
    periods, _others = site._periods_offered(pg, picker)
    assert periods == []
    assert site._OFFERED == remembered
    pg.close()


def test_the_list_is_closed_even_when_escape_leaves_it_open(picker_site, monkeypatch):
    """Nobody has seen Escape close E*TRADE's list. When the picker still
    says its list is open, the picker is pressed once more, since a list
    left open over the rows could take the click meant for a document."""
    monkeypatch.setattr(site, "_OFFERED", [])
    pg = picker_site(esc="0", list="Last 30 Days|Last 12 Months", start="Last 12 Months")
    assert site.show_period_for(pg, "2026-01-31", [])
    assert not _list_open(pg)
    assert pg.evaluate("document.getElementById('picker').getAttribute('aria-expanded')") == "false"
    assert pg.evaluate("window.applies") == 0
    pg.close()


def test_a_list_that_draws_late_is_read_once_it_draws(picker_site, monkeypatch):
    """The list shows its periods three seconds after it opens. Reading the
    controls one at a time used to give such a list a second or so more,
    and the core reads them in one call now, so the list is read again
    until it shows a period (the review after the census that followed CI
    run 36792330947)."""
    monkeypatch.setattr(site, "_OFFERED", [])
    pg = picker_site(opts="div", late="3000")
    picker = site._find_picker(pg)[0]
    periods, _others = site._periods_offered(pg, picker)
    assert "2025" in periods and "Year To Date" in periods, periods
    pg.close()


def test_click_text_checks_subsequent_elements_when_first_is_not_visible():
    """If opt.first or loc.first is hidden, _click_text checks subsequent elements."""
    class DummyElement:
        def __init__(self, visible=False):
            self._visible = visible
            self.clicked = False

        def is_visible(self):
            return self._visible

        def scroll_into_view_if_needed(self, timeout=None):
            pass

        def click(self, timeout=None):
            if not self._visible:
                raise Exception("Element not visible")
            self.clicked = True

    class DummyLocator:
        def __init__(self, elements):
            self.elements = elements

        def count(self):
            return len(self.elements)

        @property
        def first(self):
            return self.elements[0] if self.elements else None

        def nth(self, i):
            return self.elements[i]

    el_hidden = DummyElement(visible=False)
    el_visible = DummyElement(visible=True)

    class DummyPage:
        def get_by_role(self, role, name=None):
            if role == "option":
                return DummyLocator([el_hidden, el_visible])
            return DummyLocator([])

        def get_by_text(self, pat):
            return DummyLocator([])

    pg = DummyPage()
    assert site._click_text(pg, "2022") is True
    assert el_visible.clicked is True


def test_choose_period_retries_when_unopened_list_with_already_open():
    """When already_open=True is passed but option cannot be clicked,
    _choose_period reopens the picker and retries."""
    calls = []

    class DummyElement:
        def is_visible(self):
            return True

        def click(self, timeout=None):
            calls.append("picker_click")

    class DummyPage:
        def __init__(self):
            self.attempts = 0

        def evaluate(self, *a, **k):
            return 10

        def wait_for_timeout(self, ms):
            pass

        def on(self, *a):
            pass

        def remove_listener(self, *a):
            pass

        class keyboard:
            @staticmethod
            def press(k):
                pass

        def get_by_role(self, role, name=None):
            class DummyApplyLocator:
                def count(self):
                    return 0

                @property
                def first(self):
                    return None
            return DummyApplyLocator()

    pg = DummyPage()

    def mock_click_text(page, choice, unsure=None):
        pg.attempts += 1
        return pg.attempts > 1

    dummy_picker = DummyElement()
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(site, "_click_text", mock_click_text)
    monkeypatch.setattr(site, "_find_picker", lambda page: (dummy_picker, "2023"))
    monkeypatch.setattr(site, "_read_every_page", lambda *a, **k: [])

    entry = []
    ok = site._choose_period(pg, "2022", [], entry, already_open=True)
    monkeypatch.undo()
    assert ok is True
    assert "picker_click" in calls
    assert entry[0]["option_clicked"] is True



# --- a press that raised is the last one (review of #119) ---------------------

class _Candidate:
    """A period option a click may land on, which raises when told to."""

    def __init__(self, raises=False):
        self.raises, self.clicks = raises, 0

    def is_visible(self):
        return True

    def scroll_into_view_if_needed(self, timeout=None):
        pass

    def click(self, timeout=None):
        self.clicks += 1
        if self.raises:
            raise RuntimeError("invented, after the press reached the page")


class _Candidates:
    def __init__(self, elements):
        self.elements = elements

    def count(self):
        return len(self.elements)

    def nth(self, i):
        return self.elements[i]


def test_click_text_presses_nothing_more_after_a_click_that_raised():
    """A click that raised may have reached the page, so neither the next
    option of those words nor an element of the same words found by its
    text is pressed for it."""
    first, second, by_text = _Candidate(raises=True), _Candidate(), _Candidate()

    class Page:
        def get_by_role(self, role, name=None):
            return _Candidates([first, second] if role == "option" else [])

        def get_by_text(self, pat):
            return _Candidates([by_text])

    unsure: list = []
    assert site._click_text(Page(), "2022", unsure) is False
    assert (first.clicks, second.clicks, by_text.clicks, unsure) == (1, 0, 0, ["2022"])


def test_choose_period_opens_the_picker_again_only_when_nothing_was_pressed(monkeypatch):
    pressed: list = []

    class Picker:
        def click(self, timeout=None):
            pressed.append("picker")

    class Page:
        def evaluate(self, *a, **k):
            return 0

        def wait_for_timeout(self, ms):
            pass

        def on(self, *a):
            pass

        def remove_listener(self, *a):
            pass

        class keyboard:
            @staticmethod
            def press(k):
                pressed.append(k)

    def raised(page, choice, unsure=None):
        unsure.append(choice)
        return False
    monkeypatch.setattr(site, "_click_text", raised)
    monkeypatch.setattr(site, "_find_picker", lambda page: (Picker(), "2023"))
    monkeypatch.setattr(site, "_read_every_page", lambda *a, **k: [])
    trace: list = []
    assert site._choose_period(Page(), "2022", [], trace, already_open=True) is False
    assert pressed == ["Escape"] and trace[0]["outcome"] == "option not found"
