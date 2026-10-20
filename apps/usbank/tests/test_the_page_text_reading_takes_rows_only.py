"""When U.S. Bank's pickers cannot be read, the page's text is read for rows,
and only for rows, each dated by the one date it shows (#106).

That reading took any element holding a date and a control for a row. A
header holding the account picker became a statement, and so did a whole
section holding two statements, titled with the text of both and dated
with the first. A date that does not exist, September 31st, fell through
to its year alone and was filed on the last day of December. Now an
element holding a picker, more than one date or a row of its own is not a
row, and a date is taken only as the row writes it, a day or a month.
Everything here is invented.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import storage  # noqa: F401  binds this provider's AppSpec
import usbank_site as site

# No statement list the pickers read. A header with the account picker and
# a date, and a section of two statements in rows of their own.
PAGE = """<!doctype html><meta charset='utf-8'><main>
<div class='documents-header'><h2>My documents</h2><p>Updated October 13, 2031</p>
  <select><option>Choose an account</option><option>Visa Platinum ...2222</option></select>
  <a href='#' aria-label='Download all statements'>Download</a></div>
<div class='document-section'><h3>Visa Platinum ...2222 statements</h3><ul>
  <li>October 9, 2031 <button aria-label='Download October 9, 2031 statement.'>Download</button></li>
  <li>January 12, 2031 <button aria-label='Download January 12, 2031 statement.'>Download</button></li>
</ul></div></main>"""


def test_only_rows_are_read_from_the_page_text(page):
    page.set_content(PAGE)
    got = site.collect_documents(page)
    assert sorted(d.date_text for d in got) == ["January 12, 2031", "October 9, 2031"]
    for d in got:
        assert "Choose an account" not in d.text
        assert d.text.count("2031") == 1, d.text


def test_each_record_the_page_text_makes_is_dated_by_its_own_row(page):
    page.set_content(PAGE)
    got = site.usbank_collect(page)
    assert sorted(r["date"] for r in got) == ["2031-01-12", "2031-10-09"]
    for r in got:
        assert "2031" not in r["title"], r


def test_a_section_of_one_statement_is_read_as_that_row_alone(page):
    """A section holding one statement shows one date, its row's. The row is
    the statement, and the section around it is not a second one."""
    page.set_content("<!doctype html><meta charset='utf-8'><main>"
                     "<div class='document-section'><h3>Everyday Checking ...1111 statements</h3>"
                     "<ul><li>October 13, 2031 <button aria-label='Download October 13, 2031 "
                     "statement.'>Download</button></li></ul></div></main>")
    got = site.collect_documents(page)
    assert [d.text for d in got] == ["October 13, 2031 Download"]


def test_a_block_showing_two_dates_is_no_row(page):
    """Two statements in one block whose parts are no rows of their own. It
    shows two dates, so it is no one statement and is not read as one."""
    page.set_content("<!doctype html><meta charset='utf-8'><main>"
                     "<div class='statement-summary'><span>October 9, 2031</span>"
                     "<span>January 12, 2031</span><button aria-label='Download "
                     "statements'>Download</button></div></main>")
    assert site.collect_documents(page) == []


def test_a_control_naming_only_a_year_is_no_statement(page):
    """A page with no statement list and no account picker, whose controls
    are read by their names. One naming a year alone gives no date."""
    page.set_content("<!doctype html><meta charset='utf-8'><main>"
                     "<button aria-label='Download 2031 statement'>Download</button></main>")
    assert site.read_rows(page, "Visa Platinum ...2222") == []


def test_a_day_that_does_not_exist_is_not_filed_on_the_years_last_day(page):
    page.set_content("<!doctype html><meta charset='utf-8'><ul><li>September 31, 2031 "
                     "<button aria-label='Download statement'>Download</button></li></ul>")
    assert site.usbank_collect(page) == []
