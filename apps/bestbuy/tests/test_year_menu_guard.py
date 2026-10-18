"""The range menu and its years, pressed in a real browser only when they
read as the controls the run means to press.

Best Buy's run presses two controls, the purchase history's range menu and
one year in it. Both were pressed by their selector and their text alone,
and is_safe_control, defined beside them, was never asked. Now each is
pressed only when the words it shows read as that control (is_year_menu,
is_year_option) and no label it carries is one the blocklist refuses, the
year only when it is the one element reading it that opening the menu
showed, and each press goes through paperpull_core.pressing, which stops
the run when something covers the control.

The page is made up here, every word on it.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import bestbuy_site as site
from paperpull_core import pressing

sync_api = pytest.importorskip("playwright.sync_api")

COVER = ('<div role="dialog" aria-label="Tell us what you think" onclick="said(\'cover\')" '
         'style="position: fixed; inset: 0; z-index: 10; background: rgba(0,0,0,.2)">'
         'Tell us what you think</div>')


def history(menu="Past 3 Years", menu_aria="", option_aria="", extra=""):
    """The range menu and two years. Each press is written down where the
    test can read it."""
    aria = ' aria-label="%s"' % menu_aria if menu_aria else ""
    option = ' aria-label="%s"' % option_aria if option_aria else ""
    return """<!doctype html><html><body><output id="log"></output>
<button data-testid="YearDate-Filter-TestID"%s
        onclick="said('menu'); document.getElementById('years').hidden = false">%s</button>
<ul id="years" hidden><li onclick="said('2026')">2026</li>
<li%s onclick="said('2025')">2025</li></ul>
%s
<script>function said(w) { document.getElementById('log').textContent += w + ';'; }</script>
</body></html>""" % (aria, menu, option, extra)


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
    monkeypatch.setattr(site, "hide_survey", lambda page: None)
    context = browser.new_context()

    def open_page(html):
        page = context.new_page()
        page.set_content(html)
        return page

    yield open_page
    context.close()


def said(page):
    return [w for w in page.locator("#log").inner_text().split(";") if w]


def test_the_menu_and_the_year_wanted_are_pressed(show):
    page = show(history())
    assert site.pick_year(page, "2025", reads=1, gap_ms=10)
    assert said(page) == ["menu", "2025"]


def test_the_years_offered_are_read_from_the_menu(show):
    page = show(history())
    assert site.year_choices(page) == ["2026", "2025"]
    assert said(page) == ["menu"]


@pytest.mark.parametrize("menu, aria", [
    ("Pay Your Bill", ""),
    ("Apply Now", ""),
    ("", ""),
    ("Past 3 Years", "Sign out"),
])
def test_a_menu_that_does_not_read_as_one_is_not_pressed(show, menu, aria):
    page = show(history(menu=menu, menu_aria=aria))
    with pytest.raises(site.Refused):
        site.pick_year(page, "2025", reads=1, gap_ms=10)
    with pytest.raises(site.Refused):
        site.year_choices(page)
    assert said(page) == []


def test_a_year_carrying_a_refused_label_is_not_pressed(show):
    """The menu reads as one and is pressed. The year wanted reads 2025 and
    carries "Buy it again" besides, so it is not."""
    page = show(history(option_aria="Buy it again"))
    with pytest.raises(site.Refused):
        site.pick_year(page, "2025", reads=1, gap_ms=10)
    assert said(page) == ["menu"]


def test_a_year_written_elsewhere_on_the_page_is_never_the_one_pressed(show):
    """A heading reading 2025 below the menu, the last such element on the
    page, which get_by_text(year).last used to press. Only the year the
    menu showed is."""
    page = show(history(extra='<h2 onclick="said(\'heading\')">2025</h2>'))
    assert site.pick_year(page, "2025", reads=1, gap_ms=10)
    assert said(page) == ["menu", "2025"]


def test_a_menu_left_open_gives_its_one_year(show):
    """year_choices closes the menu with Escape, which a menu may ignore.
    Opened again, it shows nothing new, and the one element reading the
    year is its own."""
    page = show(history())
    site.year_choices(page)
    assert site.pick_year(page, "2025", reads=1, gap_ms=10)
    assert said(page) == ["menu", "menu", "2025"]


def test_a_menu_left_open_beside_a_year_written_elsewhere_presses_no_year(show):
    page = show(history(extra='<h2 onclick="said(\'heading\')">2025</h2>'))
    site.year_choices(page)
    with pytest.raises(site.Refused):
        site.pick_year(page, "2025", reads=1, gap_ms=10)
    assert said(page) == ["menu", "menu"]


def test_a_menu_that_shows_the_year_twice_presses_neither(show):
    page = show(history().replace('<li onclick="said(\'2026\')">2026</li>',
                                  '<li onclick="said(\'other\')">2025</li>'))
    with pytest.raises(site.Refused):
        site.pick_year(page, "2025", reads=1, gap_ms=10)
    assert said(page) == ["menu"]


def test_a_covered_menu_stops_the_run_and_says_what_covers_it(show):
    page = show(history(extra=COVER))
    with pytest.raises(pressing.Covered) as stopped:
        site.pick_year(page, "2025", reads=1, gap_ms=10)
    assert stopped.value.lines[0].startswith("Something on the page covers the range menu")
    assert said(page) == []


def test_a_press_with_no_guard_of_the_apps_own_is_refused(show):
    page = show(history())
    with pytest.raises(site.Refused):
        site._press(page, site._menu(page), "the range menu", site.YEAR_MENU,
                    lambda label: True)
    assert said(page) == []
