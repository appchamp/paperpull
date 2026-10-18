"""A statement whose download never ends is cancelled, and the run goes on.

The row's press waits for a download with expect_download and saves it with
intake.save_download_as. Saving waited in Playwright until the download had
finished, so a provider that kept sending held the run there for good. The
save is held to DOWNLOAD_SECONDS now (paperpull_core.intake.finish).

In a real browser. The statements page is made up and served from memory,
the download comes from a server on this machine, and every other request
is refused, so nothing leaves it. The server cuts the download off after
25 seconds, so a broken guard fails the test then rather than never.
"""
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401,E402  binds this provider's AppSpec
import chase_site as site  # noqa: E402
from paperpull_core import intake  # noqa: E402

DOCUMENTS = "https://secure.chase.com/web/auth/dashboard"
ACCOUNT = "SAPPHIRE RESERVE (...1234)"
DATE = "2026-08-09"

PAGE = """<!doctype html><html><body><main><h1>Statements</h1>
<a href="%s" id="row" aria-label="Aug 09, 2026 Statement SAPPHIRE RESERVE (...1234) Saves document">Saves document</a>
</main></body></html>"""


class _Sent:
    def __init__(self):
        self.bytes = 0
        self.lock = threading.Lock()


@pytest.fixture()
def server():
    sent = _Sent()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.headers.get("Range"):
                # Chromium asks again from where a cut-off download stopped.
                # Refused, so a test whose guard is broken fails at the cut.
                self.send_response(410)
                self.send_header("content-length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("content-type", "application/pdf")
            self.send_header("content-disposition", 'attachment; filename="statement.pdf"')
            self.send_header("transfer-encoding", "chunked")
            self.end_headers()
            began = time.monotonic()
            piece = b"%PDF-1.4\n" + b"\0" * 4000
            try:
                while time.monotonic() - began < 25:
                    self.wfile.write(b"%x\r\n" % len(piece) + piece + b"\r\n")
                    with sent.lock:
                        sent.bytes += len(piece)
                    time.sleep(0.2)
                # Cut off unfinished and never kept open for another
                # request, so the browser sees the download fail.
                self.close_connection = True
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d/statement" % httpd.server_address[1], sent
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture()
def page(server):
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True, args=["--no-proxy-server"])
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    url, _ = server
    ctx = browser.new_context(accept_downloads=True)
    ctx.route("**/*", lambda r: r.abort())
    ctx.route(DOCUMENTS, lambda r: r.fulfill(status=200, content_type="text/html",
                                             body=PAGE % url))
    ctx.route(url, lambda r: r.continue_())
    p = ctx.new_page()
    p.goto(DOCUMENTS)
    yield p
    browser.close()
    driver.stop()


def test_a_download_that_never_ends_is_cancelled_and_nothing_is_saved(
        page, server, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(intake, "DOWNLOAD_SECONDS", 3)
    _, sent = server
    # The app looks for a tab for fifteen seconds once no download came.
    # Here for a tenth of that.
    wait = page.wait_for_timeout
    page.wait_for_timeout = lambda ms: wait(max(1, ms // 10))
    out = tmp_path / "Statements" / "2026-08-09 Chase Statement.pdf"
    out.parent.mkdir(parents=True)
    started = time.monotonic()
    assert site._click_row_and_capture(page, page.context, ACCOUNT, DATE, out) is False
    assert time.monotonic() - started < 15
    assert not out.exists()
    assert list(out.parent.iterdir()) == [], "a saving file was left"
    assert "DOWNLOAD_SECONDS" in capsys.readouterr().out
    time.sleep(1.0)
    first = sent.bytes
    time.sleep(1.5)
    assert sent.bytes == first, "the download was left running"
