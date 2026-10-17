"""M&T's collapsed year headings, opened in a real browser, in a frame.

M&T's statements list shows one heading for each year, and only the current
year is open. Each collapsed year is a span.open-table whose press lists
that year. The app pressed the first one through page script, el.click()
run inside the frame, with nothing checking what covered it, and read the
heading's words in one call and pressed in another. Now each heading is
pressed through paperpull_core.pressing from a handle on the heading itself,
inside its frame. Something over a heading, in the frame or over the frame
in the page, stops the run before anything is pressed, and no heading is
pressed twice.

The page and its frame are made up here, every word and address on them,
and nothing is fetched from any of the statement addresses.
"""
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mtb_site as site  # noqa: E402
from paperpull_core import pressing  # noqa: E402

sync_api = pytest.importorskip("playwright.sync_api")

HEAD = """<!doctype html><html><head><meta charset="utf-8"><title>made up</title>
<script>function said(what) { document.getElementById('log').textContent += what + ';'; }</script>
<style>html, body { margin: 0; font: 16px sans-serif; }
.open-table, .close-table { display: inline-block; width: 18px; height: 18px; background: #555;
                            cursor: pointer; }
.cover { position: fixed; left: 0; top: 0; width: 100vw; height: 100vh; z-index: 10;
         background: rgba(0, 0, 0, .25); }</style>
</head><body><output id="log"></output>
"""

STATEMENT = ('<a href="https://onlinebanking.mtb.com/Statements/FetchStatementandNotices'
             '?t=MTGSTMT&amp;a=7&amp;dt=01/03/%s&amp;stmtId=X%s01">January statement</a>')

# Each year's press lists that year and marks its heading open, as M&T's
# own script does once its answer comes.
LIST_SCRIPT = """<script>
function listYear(span, year) {
  said('open-' + year);
  span.className = 'close-table';
  document.getElementById('t' + year).innerHTML = %s.replace(/YEAR/g, year);
}
</script>""" % repr(STATEMENT % ("YEAR", "YEAR"))

COVER = ('<div class="cover" role="dialog" aria-label="Chat with us" onclick="said(\'cover\')">'
         'Chat with us</div>')


def heading(year, open_=False, onclick=None, words=None, ident=True, aria=None):
    """One year's heading, which reads the year alone, as M&T's own do."""
    span = '<span class="%s"%s%s onclick="%s"></span>' % (
        "close-table" if open_ else "open-table",
        ' id="spViewStatementsElectronic-%s"' % year if ident else "",
        ' aria-label="%s"' % aria if aria else "",
        onclick or "listYear(this, '%s')" % year)
    rows = STATEMENT % (year, year) if open_ else ""
    said_words = str(year) if words is None else words
    return '<h2>%s %s</h2><table id="t%s"><tr><td>%s</td></tr></table>' % (
        said_words, span, year, rows)


def years(*extra):
    """The current year open and three collapsed, then whatever else."""
    return (heading(2026, open_=True) + heading(2025) + heading(2024) + heading(2023)
            + "".join(extra))


class _Site:
    def __init__(self):
        self.pages = {}


def _handler(fake):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            body = fake.pages.get(self.path.split("?")[0].lstrip("/"), "").encode("utf-8")
            self.send_response(200 if body else 404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass
    return Handler


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch(headless=True)
        except Exception as e:
            pytest.skip("no browser to drive: %s" % e)
        yield b
        b.close()


@pytest.fixture()
def show(browser, monkeypatch):
    """The statements page of this test's own, its list in a frame far down
    the page unless `framed` is false, on a site of its own that the app
    takes for M&T's."""
    fake = _Site()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _handler(fake))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    here = "http://127.0.0.1:%d/" % httpd.server_address[1]
    monkeypatch.setattr(site, "is_mt_frame", lambda fr: (fr.url or "").startswith(here))
    context = browser.new_context(viewport={"width": 1000, "height": 600})

    def open_page(statements, page_extra="", framed=True):
        listing = HEAD + LIST_SCRIPT + statements + "</body></html>"
        if framed:
            fake.pages["statements"] = listing
            fake.pages["main"] = (HEAD + '<div style="height: 1200px"></div>'
                                  '<iframe name="statements" src="%sstatements" '
                                  'style="width: 700px; height: 400px; border: 2px solid">'
                                  '</iframe><div style="height: 1200px"></div>%s</body></html>'
                                  % (here, page_extra))
        else:
            fake.pages["main"] = listing
        page = context.new_page()
        page.goto(here + "main")
        page.wait_for_load_state("load")
        return page

    yield open_page
    context.close()
    httpd.shutdown()
    httpd.server_close()


def said(frame):
    return [p for p in frame.locator("#log").inner_text().split(";") if p]


def listed_years(rows):
    return sorted({r["date"][:4] for r in rows})


def test_every_collapsed_year_is_opened_once_and_read(show):
    page = show(years())
    frame = page.frame(name="statements")
    rows = site.collect_statement_rows(page)
    assert said(frame) == ["open-2025", "open-2024", "open-2023"]
    assert listed_years(rows) == ["2023", "2024", "2025", "2026"]
    assert said(page.main_frame) == []


def test_a_cover_inside_the_frame_stops_the_run_with_nothing_pressed(show):
    page = show(years(COVER))
    frame = page.frame(name="statements")
    with pytest.raises(pressing.Covered) as stopped:
        site.collect_statement_rows(page)
    stop = stopped.value
    assert stop.step == "open a year of statements"
    assert "over_the_frame" not in stop.facts
    assert stop.lines[0] == ("Something on the page covers the heading of the year 2025 on "
                             "the statements list, so nothing was pressed.")
    assert said(frame) == []


def test_a_cover_over_the_frame_in_the_page_stops_the_run_with_nothing_pressed(show):
    """The page's own chat window, over the frame the list is in."""
    page = show(years(), page_extra=COVER)
    frame = page.frame(name="statements")
    with pytest.raises(pressing.Covered) as stopped:
        site.collect_statement_rows(page)
    assert stopped.value.facts["over_the_frame"] is True
    assert said(frame) == []
    assert said(page.main_frame) == []


def test_a_stop_at_a_heading_is_no_ordinary_failure(show):
    """A stop is a SystemExit, so the collector's own except Exception
    around the headings does not take it and go on reading."""
    page = show(years(COVER))
    with pytest.raises(SystemExit):
        site.collect_statement_rows(page)


def test_a_year_that_does_not_open_is_pressed_once(show):
    """Its press answers nothing, so the count of collapsed years does not
    fall. It is pressed once, the run reads what is on screen, and no other
    year is pressed after it."""
    page = show(heading(2026, open_=True) + heading(2025, onclick="said('open-2025')")
                + heading(2024))
    frame = page.frame(name="statements")
    rows = site.collect_statement_rows(page)
    assert said(frame) == ["open-2025"]
    assert listed_years(rows) == ["2026"]


# Pressing 2025 opens 2024 instead and leaves 2025 collapsed, so the count
# falls and 2025 is the first collapsed heading once more.
OPENS_ANOTHER = "said('press-2025'); listYear(document.getElementById('x2024'), '2024')"
# The same, with the whole list drawn anew, so 2025 is a new element with
# the same words and the same id.
DRAWS_ANEW = ("said('press-2025'); const l = document.getElementById('list');"
              " l.innerHTML = l.innerHTML; listYear(document.getElementById('x2024'), '2024')")


@pytest.mark.parametrize("how", ["same element", "drawn anew", "no id"])
def test_a_heading_pressed_once_is_never_pressed_again(show, how):
    """The heading of 2025 is still collapsed after its press, and the
    count of collapsed years fell all the same. It is not pressed again,
    whether it is the same element, a new one with its words and its id, or
    the same element with no id to know it by, so its words and id are no
    key to it."""
    if how == "no id":
        first = heading(2025, onclick=OPENS_ANOTHER, ident=False)
    else:
        first = heading(2025, onclick=OPENS_ANOTHER if how == "same element" else DRAWS_ANEW)
    second = heading(2024).replace('id="spViewStatementsElectronic-2024"', 'id="x2024"')
    page = show('<div id="list">' + heading(2026, open_=True) + first + second + "</div>")
    frame = page.frame(name="statements")
    site.collect_statement_rows(page)
    assert said(frame) == ["press-2025", "open-2024"]
    # Not vacuous. 2025 is still collapsed and first, so a loop that went
    # on would have pressed it again.
    assert frame.locator("span.open-table").count() == 1


@pytest.mark.parametrize("shared", ["id", "words"])
def test_years_that_share_an_id_or_words_are_each_opened(show, shared):
    """Two years can share a heading's id, or its words, should the page
    ever write one year twice. Each heading is still a heading of its own,
    and every year is opened and read."""
    years_ = [heading(2026, open_=True)]
    for year in (2025, 2024, 2023):
        h = heading(year, words="2025" if shared == "words" else None)
        if shared == "id":
            h = h.replace("spViewStatementsElectronic-%s" % year, "spViewStatementsElectronic-7")
        years_.append(h)
    page = show("".join(years_))
    frame = page.frame(name="statements")
    rows = site.collect_statement_rows(page)
    assert said(frame) == ["open-2025", "open-2024", "open-2023"]
    assert listed_years(rows) == ["2023", "2024", "2025", "2026"]


@pytest.mark.parametrize("words", [
    "Change paperless options for 2025", "Make a payment", "2025 Make a payment",
    "2025 Statements", "Statements", ""])
def test_a_heading_that_does_not_read_as_a_year_alone_is_not_pressed(show, words):
    """Nor is any heading after it. The run reads the year on screen."""
    page = show(heading(2026, open_=True) + heading(2025, words=words) + heading(2024))
    frame = page.frame(name="statements")
    rows = site.collect_statement_rows(page)
    assert said(frame) == []
    assert listed_years(rows) == ["2026"]


def test_a_heading_carrying_a_refused_label_is_not_pressed(show):
    """It reads 2025, and its own aria-label asks for a payment."""
    page = show(heading(2026, open_=True) + heading(2025, aria="Pay my mortgage"))
    frame = page.frame(name="statements")
    site.collect_statement_rows(page)
    assert said(frame) == []


def test_a_year_alone_is_a_year_heading():
    for label in ("2025", " 2019 ", "2025\n"):
        assert site.is_year_heading(label), label
    for label in ("", "25", "20255", "2025 Statements", "Statements", "Pay 2025",
                  "2025 | Make a payment", None):
        assert not site.is_year_heading(label), label
    assert site.PRESS_GUARDS == (site.is_year_heading,)


def test_headings_in_the_page_itself_are_opened_too(show):
    """A list in the page's own main frame is read and pressed there."""
    page = show(years(), framed=False)
    rows = site.collect_statement_rows(page)
    assert said(page.main_frame) == ["open-2025", "open-2024", "open-2023"]
    assert listed_years(rows) == ["2023", "2024", "2025", "2026"]
