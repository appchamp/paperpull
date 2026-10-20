"""The browser the tests beside this file drive, and a page in it whose
waits are cut short (usbank_pages has the made-up page itself). A test
file that defines a browser or a page of its own keeps its own."""
import pytest


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
def page(browser):
    """A page whose waits are a twentieth of the app's, so a walk of three
    accounts and two years takes a second or two rather than half a
    minute. The page's own drawing keeps its real time."""
    pg = browser.new_page()
    real = pg.wait_for_timeout
    pg.wait_for_timeout = lambda ms: real(max(1, int(ms) // 20))
    yield pg
    pg.close()
