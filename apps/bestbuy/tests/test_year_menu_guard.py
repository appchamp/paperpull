"""The range menu and its years, pressed in a real browser only when they
read as the controls the run means to press.

Best Buy's run presses two controls, the purchase history's range menu and
one year in it. Both were pressed by their selector and their text alone,
and is_safe_control, defined beside them, was never asked. Now each is
pressed only when the words it shows read as that control (is_year_menu,
is_year_option) and no label it carries is one the blocklist refuses.

The page is made up here, every word on it.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import bestbuy_site as site

sync_api = pytest.importorskip("playwright.sync_api")


def history(menu="Past 3 Years", menu_aria="", option_aria=""):
    """The range menu and two years. Each press is written down where the
    test can read it."""
    aria = ' aria-label="%s"' % menu_aria if menu_aria else ""
    option = ' aria-label="%s"' % option_aria if option_aria else ""
    return """<!doctype html><html><body><output id="log"></output>
<button data-testid="YearDate-Filter-TestID"%s
        onclick="said('menu'); document.getElementById('years').hidden = false">%s</button>
<ul id="years" hidden><li onclick="said('2026')">2026</li>
<li%s onclick="said('2025')">2025</li></ul>
<script>function said(w) { document.getElementById('log').textContent += w + ';'; }</script>
</body></html>""" % (aria, menu, option)


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
    assert not site.pick_year(page, "2025", reads=1, gap_ms=10)
    assert site.year_choices(page) == []
    assert said(page) == []


def test_a_year_carrying_a_refused_label_is_not_pressed(show):
    """The menu reads as one and is pressed. The year wanted reads 2025 and
    carries "Buy it again" besides, so it is not."""
    page = show(history(option_aria="Buy it again"))
    assert not site.pick_year(page, "2025", reads=1, gap_ms=10)
    assert said(page) == ["menu"]


def test_a_press_with_no_guard_of_the_apps_own_is_refused(show):
    page = show(history())
    with pytest.raises(site.Refused):
        site._press(page.locator(site.YEAR_MENU).first, "the range menu", lambda label: True)
    assert said(page) == []
