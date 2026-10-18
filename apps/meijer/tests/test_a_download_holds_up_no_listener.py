"""A download the receipt control starts holds up no listener after Meijer's.

Meijer's download listener waited in Download.path() until the download
finished. Playwright's sync API runs every listener of one event in a
single fiber, one after another, so each listener registered after it heard
nothing until the download finished or the press gave up on it twenty
seconds later. pressing.press_once registers its own ear for what a press
brought after Meijer's listener. The listener now only keeps the download
and has it followed (intake.follow), and the press waits for it through
intake.finish.

The orders page and the receipt are served over TLS as www.meijer.com by a
server on this machine, with a certificate made for the test, so Meijer's
own address check is the one that runs. No other name resolves. Every date,
store and amount is invented.
"""
import datetime
import socket
import ssl
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import meijer_site as site
from paperpull_core.models import IN_STORE

ORDERS = "https://www.meijer.com/shopping/orders.html"

# Meijer's wait for a download, shortened for the test that runs it out.
WAIT = 6
# How long the receipt that does finish takes to arrive.
SLOW = 4

RECEIPT = b"%PDF-1.4\n% invented receipt 09/19/2026\n" + b"x" * 3000 + b"\n%%EOF\n"

PAGE = """<!doctype html><html><body><main><div id='store'><ul>
<li class='order-card'><div class='date'>In-Store: 09/19/2026</div><div>1600 Invented Road</div>
<div class='totals'><span>$31.23</span>&nbsp;&nbsp;6 items</div>
<a href='javascript:void(0)' onclick="go();return false">view receipt pdf</a></li>
</ul></div><script>
function go() {
  const a = document.createElement('a');
  a.href = '/receipt/KIND.pdf';
  a.download = 'receipt.pdf';
  document.body.appendChild(a);
  a.click();
}
</script></main></body></html>"""


def _certificate(folder: Path):
    """A certificate for www.meijer.com and its key, made for this test."""
    x509 = pytest.importorskip("cryptography.x509")
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "www.meijer.com")])
    now = datetime.datetime.now(datetime.timezone.utc)
    made = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("www.meijer.com")]),
                           critical=False)
            .sign(key, hashes.SHA256()))
    cert, private = folder / "cert.pem", folder / "key.pem"
    cert.write_bytes(made.public_bytes(serialization.Encoding.PEM))
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                          serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    return cert, private


class Served:
    """When each receipt began to be sent and how many bytes went, by kind."""

    def __init__(self):
        self.lock = threading.Lock()
        self.began = {}
        self.bytes = {}
        self.port = 0

    def add(self, kind, n):
        with self.lock:
            self.bytes[kind] = self.bytes.get(kind, 0) + n


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    """www.meijer.com, with the orders page and two receipts.

    /shopping/orders.html?receipt=KIND   one row, whose receipt control
                                         downloads /receipt/KIND.pdf
    /receipt/forever.pdf                 a piece every 200 ms without end,
                                         cut off after 25 seconds so a test
                                         whose guard is broken fails then
    /receipt/slow.pdf                    a whole receipt over SLOW seconds
    """
    served = Served()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            parts = urlparse(self.path)
            if parts.path == "/shopping/orders.html":
                kind = parse_qs(parts.query).get("receipt", ["slow"])[0]
                body = PAGE.replace("KIND", kind).encode()
                self.send_response(200)
                self.send_header("content-type", "text/html")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parts.path not in ("/receipt/forever.pdf", "/receipt/slow.pdf") \
                    or self.headers.get("Range"):
                # Chromium asks again from where a cut-off download stopped,
                # and is refused, so a broken guard fails at the cut.
                self.send_response(404 if not self.headers.get("Range") else 410)
                self.send_header("content-length", "0")
                self.end_headers()
                return
            kind = parts.path.split("/")[-1].split(".")[0]
            forever = kind == "forever"
            self.send_response(200)
            self.send_header("content-type", "application/pdf")
            self.send_header("content-disposition", 'attachment; filename="receipt.pdf"')
            if forever:
                self.send_header("transfer-encoding", "chunked")
            else:
                self.send_header("content-length", str(len(RECEIPT)))
            self.end_headers()
            served.began.setdefault(kind, time.monotonic())
            try:
                if forever:
                    piece = RECEIPT[:64]
                    while time.monotonic() - served.began[kind] < 25:
                        self.wfile.write(b"%x\r\n" % len(piece) + piece + b"\r\n")
                        served.add(kind, len(piece))
                        time.sleep(0.2)
                    self.connection.shutdown(socket.SHUT_RDWR)
                    return
                pieces = 16
                size = -(-len(RECEIPT) // pieces)
                for at in range(0, len(RECEIPT), size):
                    self.wfile.write(RECEIPT[at:at + size])
                    served.add(kind, size)
                    time.sleep(SLOW / pieces)
            except OSError:
                pass

    cert, private = _certificate(tmp_path_factory.mktemp("tls"))
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert, private)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.socket = tls.wrap_socket(httpd.socket, server_side=True)
    served.port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield served
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(scope="module")
def browser(server):
    pw = pytest.importorskip("playwright.sync_api")
    driver = pw.sync_playwright().start()
    try:
        launched = driver.chromium.launch(headless=True, args=[
            "--host-resolver-rules=MAP www.meijer.com 127.0.0.1:%d, MAP * ~NOTFOUND" % server.port,
            "--no-proxy-server", "--disable-extensions", "--disable-sync", "--no-first-run"])
    except Exception as e:
        driver.stop()
        pytest.skip("no browser to drive: %s" % e)
    yield launched
    launched.close()
    driver.stop()


@pytest.fixture
def orders(browser):
    """The orders page showing a row whose receipt is of the kind asked for,
    and the row's purchase."""
    contexts = []

    def open_(kind):
        ctx = browser.new_context(accept_downloads=True, ignore_https_errors=True)
        contexts.append(ctx)
        pg = ctx.new_page()
        pg.goto(ORDERS + "?receipt=" + kind)
        purchase = next(p for p in map(site.card_to_purchase, site.collect_cards(pg))
                        if p.purchase_date == "2026-09-19")
        purchase.purchase_type = IN_STORE
        return pg, purchase
    yield open_
    for ctx in contexts:
        ctx.close()


def _heard_after_meijers(monkeypatch) -> list:
    """When a listener registered after Meijer's own heard the download. It
    is registered just before the press, where pressing's own ear is."""
    heard = []
    real = site.pressing.press_once

    def press_once(page, *args, **kwargs):
        page.on("download", lambda d: heard.append(time.monotonic()))
        return real(page, *args, **kwargs)
    monkeypatch.setattr(site.pressing, "press_once", press_once)
    return heard


def _sending_stopped(server, kind) -> bool:
    """Whether the server stopped sending, which it does once the browser
    lets go of the download. A piece or two may still be on its way."""
    time.sleep(1.0)
    first = server.bytes.get(kind, 0)
    time.sleep(1.5)
    return server.bytes.get(kind, 0) == first


def test_a_download_that_never_ends_holds_up_no_listener_after_meijers(
        server, orders, monkeypatch, capsys):
    monkeypatch.setattr(site, "RECEIPT_DOWNLOAD_SECONDS", WAIT)
    pg, purchase = orders("forever")
    heard = _heard_after_meijers(monkeypatch)
    trace: list = []
    said: dict = {}
    started = time.monotonic()
    assert site.press_row_receipt(pg, purchase, trace, said) is None
    assert time.monotonic() - started < WAIT + 15
    assert said["outcome"] == site.NO_PDF
    assert {"note": "the download did not finish in time"} in trace, trace
    assert heard, "the listener after Meijer's never heard the download"
    # Heard as the download began, not once Meijer gave up on it.
    assert heard[0] - server.began["forever"] < WAIT / 2, heard[0] - server.began["forever"]
    assert _sending_stopped(server, "forever"), "the download was left running"
    # Meijer's own wait is said in seconds alone, since raising the core's
    # DOWNLOAD_SECONDS would not change it.
    out = capsys.readouterr().out
    assert "did not finish in %d seconds" % WAIT in out and "DOWNLOAD_SECONDS" not in out, out


def test_a_download_that_finishes_in_time_is_read_and_heard_as_it_begins(
        server, orders, monkeypatch):
    pg, purchase = orders("slow")
    heard = _heard_after_meijers(monkeypatch)
    trace: list = []
    body = site.press_row_receipt(pg, purchase, trace)
    assert body == RECEIPT, trace
    assert {"note": "the receipt came from the row's control", "control": "view receipt pdf",
            "how": "a download"} in trace, trace
    assert heard, "the listener after Meijer's never heard the download"
    assert heard[0] - server.began["slow"] < SLOW / 2, heard[0] - server.began["slow"]
