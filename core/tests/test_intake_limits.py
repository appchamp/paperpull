"""A document is taken in only up to a limit, whichever way it comes.

An audit of 0.53.0 found that capture.fetch_pdf read an answer's whole
body, that receipt_pdf.open_zip unpacked whatever an archive held, and
that nothing anywhere said how large a document could be. The limits are
in paperpull_core.intake now. These drive the real code paths with made-up
inputs that are small on disk or short to send, against a real server and
a real browser where one is how the bytes come, with the limits lowered so
a test sends megabytes and not hundreds of them.

What each refusal must do, besides refusing. Say so in words, leave
nothing half written under a document's name, never touch a document that
is already there, and keep what is kept the way that path keeps whatever
it refuses.
"""
import base64
import io
import struct
import sys
import threading
import time
import zipfile
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import capture, delivery, intake, receipt_pdf, testkit  # noqa: E402

MiB = intake.MiB


class Listed(BaseException):
    """An archive listed although it must not be. Not an Exception, so no
    except of the code under test can take it for an archive that will not
    open and carry on."""
PDF = testkit.text_pdf(["Order 8421997301", "2026-01-15", "Total 1284.55"])


# -- the pieces, with stand-ins ----------------------------------------------------

class Answer:
    """An answer whose body says when it is read."""

    def __init__(self, data: bytes, declared=None):
        self.data = data
        self.headers = {} if declared is None else {"content-length": str(declared)}
        self.read = self.disposed = 0

    def body(self):
        self.read += 1
        return self.data

    def dispose(self):
        self.disposed += 1


def test_an_answer_declared_too_large_is_never_read(monkeypatch, capsys):
    monkeypatch.setattr(intake, "DOCUMENT_BYTES", 1000)
    answer = Answer(b"x" * 10, declared=5000)
    with pytest.raises(intake.TooLarge):
        intake.body(answer)
    assert answer.read == 0, "the body was read although its length said no"
    assert answer.disposed == 1, "Playwright's driver was left holding it"
    assert "larger than" in capsys.readouterr().out


def test_an_answer_that_said_nothing_is_refused_once_it_is_over(monkeypatch):
    monkeypatch.setattr(intake, "DOCUMENT_BYTES", 1000)
    answer = Answer(b"x" * 1001)
    with pytest.raises(intake.TooLarge):
        intake.body(answer)
    assert answer.disposed == 1
    assert intake.body(Answer(b"x" * 1000)) == b"x" * 1000


def test_base64_over_the_limit_is_refused_before_it_is_decoded(monkeypatch):
    monkeypatch.setattr(intake, "DOCUMENT_BYTES", 1000)

    def never(*a, **k):
        raise AssertionError("decoded although it was too long")

    monkeypatch.setattr(intake.base64, "b64decode", never)
    with pytest.raises(intake.TooLarge):
        intake.decode("A" * 2000)


def test_base64_within_the_limit_decodes_as_it_always_did(monkeypatch):
    monkeypatch.setattr(intake, "DOCUMENT_BYTES", 1000)
    raw = bytes(range(256)) * 3
    assert intake.decode(base64.b64encode(raw).decode()) == raw
    assert intake.decode("") == b"" and intake.decode(None) == b""
    with pytest.raises(Exception):
        intake.decode("not base64!", validate=True)


def test_a_packed_document_is_unpacked_only_up_to_the_limit(monkeypatch):
    """Fidelity sends a statement deflated inside its JSON. Fifty megabytes
    of nothing pack to fifty kilobytes."""
    monkeypatch.setattr(intake, "DOCUMENT_BYTES", 1 * MiB)
    bomb = zlib.compress(b"\0" * (50 * MiB), 9)
    assert len(bomb) < 100_000
    made = []
    real = zlib.decompressobj

    class Counted:
        """The unpacker, counting what each call hands back."""

        def __init__(self, *a):
            self.d = real(*a)

        def decompress(self, data, *a):
            out = self.d.decompress(data, *a)
            made.append(len(out))
            return out

        def flush(self):
            out = self.d.flush()
            made.append(len(out))
            return out

        def __getattr__(self, name):
            return getattr(self.d, name)

    monkeypatch.setattr(zlib, "decompressobj", Counted)
    with pytest.raises(intake.TooLarge):
        intake.inflate(bomb)
    assert sum(made) <= 1 * MiB + 1, "unpacked %d bytes before it refused" % sum(made)
    monkeypatch.setattr(zlib, "decompressobj", real)
    assert intake.inflate(zlib.compress(PDF)) == PDF
    with pytest.raises(zlib.error):
        intake.inflate(zlib.compress(PDF)[:-8])
    raw = zlib.compressobj(9, zlib.DEFLATED, -15)
    assert intake.inflate(raw.compress(PDF) + raw.flush(), -15) == PDF


# -- ZIP ------------------------------------------------------------------------

def zipped(members, method=zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", method) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


def review(tmp_path):
    return tmp_path / "Manual Review"


def left_in(folder):
    return sorted(p.name for p in folder.iterdir() if p.is_file())


def test_a_zip_bomb_is_kept_whole_and_never_unpacked(tmp_path, capsys):
    """One PDF that unpacks to thirty megabytes from thirty kilobytes, a
    thousand times its packed size. The default limits refuse it."""
    out = tmp_path / "1099-R.pdf"
    archive = zipped({"1099-R.pdf": b"%PDF-1.4\n" + b"\0" * (30 * MiB)})
    assert len(archive) < 100_000
    out.write_bytes(archive)
    opened = receipt_pdf.open_zip(out, review(tmp_path))
    assert opened.pdf is None and opened.failure == "the archive was over a limit"
    assert "times its packed size" in opened.reason
    assert not out.exists(), "something was left under the document's name"
    assert opened.kept.read_bytes() == archive, "the archive was not kept whole"
    assert left_in(tmp_path) == [], "something was unpacked beside it"
    assert "so it was not opened" in capsys.readouterr().out


def test_a_pdf_in_a_zip_larger_than_a_document_may_be_is_not_unpacked(tmp_path, monkeypatch):
    monkeypatch.setattr(intake, "DOCUMENT_BYTES", 1 * MiB)
    monkeypatch.setattr(intake, "ZIP_RATIO", 10 ** 9)
    out = tmp_path / "1099-R.pdf"
    out.write_bytes(zipped({"1099-R.pdf": b"%PDF-1.4\n" + b"\0" * (3 * MiB)}))
    opened = receipt_pdf.open_zip(out, review(tmp_path))
    assert opened.pdf is None and "larger than a document may be" in opened.reason
    assert left_in(tmp_path) == []


def test_a_zip_listing_too_many_files_is_kept_without_being_listed(tmp_path, monkeypatch):
    """zipfile builds an entry for every file listed before anything can
    count them, so the count is read from the archive's last record and
    zipfile is never asked."""
    monkeypatch.setattr(intake, "ZIP_MEMBERS", 20)
    out = tmp_path / "Form.pdf"
    archive = zipped({"part %d.txt" % n: b"x" for n in range(25)})
    out.write_bytes(archive)

    def never(*a, **k):
        raise Listed("the archive was listed")

    monkeypatch.setattr(zipfile, "ZipFile", never)
    opened = receipt_pdf.open_zip(out, review(tmp_path))
    assert opened.pdf is None and "listed 25 files" in opened.reason
    assert opened.failure == "the archive was over a limit"
    assert opened.kept.read_bytes() == archive


def test_a_zip_whose_count_lies_is_held_by_the_size_of_its_listing(tmp_path, monkeypatch):
    """zipfile reads entries until the listing's size is used up, whatever
    the count says. Two hundred files that say they are one."""
    monkeypatch.setattr(intake, "ZIP_MEMBERS", 2)
    archive = bytearray(zipped({"part %03d.txt" % n: b"x" for n in range(200)}))
    end = archive.rfind(b"PK\x05\x06")
    struct.pack_into("<HH", archive, end + 8, 1, 1)
    out = tmp_path / "Form.pdf"
    out.write_bytes(bytes(archive))

    def never(*a, **k):
        raise Listed("the archive was listed")

    monkeypatch.setattr(zipfile, "ZipFile", never)
    opened = receipt_pdf.open_zip(out, review(tmp_path))
    assert opened.pdf is None and opened.failure == "the archive was over a limit"
    assert "list of files was longer" in opened.reason


def test_a_zip_packed_with_bzip2_is_not_opened(tmp_path):
    out = tmp_path / "Form.pdf"
    out.write_bytes(zipped({"form.pdf": PDF}, method=zipfile.ZIP_BZIP2))
    opened = receipt_pdf.open_zip(out, review(tmp_path))
    assert opened.pdf is None and "packed in a way" in opened.reason


def test_a_pdf_written_with_no_compression_still_opens_from_a_zip(tmp_path):
    """Two megabytes of PDF padded with spaces packs over a hundred times
    smaller, and is a document like any other (review, 2026-10-17)."""
    out = tmp_path / "Form.pdf"
    data = PDF + b" " * (2 * MiB)
    archive = zipped({"form.pdf": data})
    assert len(data) > 100 * len(archive)
    out.write_bytes(archive)
    opened = receipt_pdf.open_zip(out, review(tmp_path))
    assert opened.pdf == out and out.read_bytes() == data


def test_a_zip_within_every_limit_still_opens(tmp_path):
    out = tmp_path / "Form.pdf"
    out.write_bytes(zipped({"form.pdf": PDF}))
    opened = receipt_pdf.open_zip(out, review(tmp_path))
    assert opened.pdf == out and out.read_bytes() == PDF


def test_the_same_bomb_again_is_kept_once(tmp_path):
    """Kept on every run it is asked for, it would pile up. The second is
    known for the same archive without being listed."""
    archive = zipped({"1099-R.pdf": b"%PDF-1.4\n" + b"\0" * (30 * MiB)})
    for _ in range(2):
        out = tmp_path / "1099-R.pdf"
        out.write_bytes(archive)
        receipt_pdf.open_zip(out, review(tmp_path))
    assert left_in(review(tmp_path)) == ["1099-R.zip"]


def test_a_copy_stops_reading_past_its_limit():
    src = io.BytesIO(b"x" * 5000)
    dst = io.BytesIO()
    assert not receipt_pdf._copy_counted(src, dst, 1000)
    assert dst.tell() <= 1000 and src.tell() <= 1000 + 1
    dst = io.BytesIO()
    assert receipt_pdf._copy_counted(io.BytesIO(b"x" * 1000), dst, 1000)
    assert dst.getvalue() == b"x" * 1000


# -- the download folder --------------------------------------------------------

def test_a_file_in_the_download_folder_too_large_is_left_there(tmp_path, monkeypatch):
    monkeypatch.setattr(intake, "DOCUMENT_BYTES", 2000)
    dl = tmp_path / "dl"
    dl.mkdir()
    before = capture.snapshot(dl)
    big = dl / "statement.pdf"
    big.write_bytes(b"%PDF-1.4\n" + b"\0" * 5000)
    out = tmp_path / "out" / "Statement.pdf"
    out.parent.mkdir()
    assert not capture.take_new_pdf(dl, before, out)
    assert big.exists() and not out.exists(), "it was taken, or deleted"


def test_place_refuses_bytes_too_large_and_keeps_the_document_there(tmp_path, monkeypatch):
    monkeypatch.setattr(intake, "DOCUMENT_BYTES", 2000)
    out = tmp_path / "Statement.pdf"
    out.write_bytes(b"the document already here")
    got = delivery.place(b"%PDF-" + b"\0" * 5000, out)
    assert got.outcome == delivery.TOO_LARGE
    assert out.read_bytes() == b"the document already here"
    assert left_in(tmp_path) == ["Statement.pdf"], "a staging file was left"
    assert delivery.summarize(got.report())


# -- downloads, answers and archives, with stand-ins ------------------------------

class Download:
    """A download as Playwright hands it over, whose file is `own`, or which
    cannot say where its file is when `own` is None."""

    def __init__(self, own, data=b""):
        self.own, self.data, self.copied = own, data, []

    def path(self):
        if self.own is None:
            raise RuntimeError("connected remotely, the path is not known")
        return str(self.own)

    def save_as(self, target):
        self.copied.append(target)
        Path(target).write_bytes(self.own.read_bytes() if self.own else self.data)


def test_a_download_the_browser_measured_too_large_is_never_copied(tmp_path, monkeypatch):
    monkeypatch.setattr(intake, "DOCUMENT_BYTES", 2000)
    own = tmp_path / "browser's own copy"
    own.write_bytes(b"%PDF-" + b"\0" * 5000)
    out = tmp_path / "Statement.pdf"
    out.write_bytes(b"the document already here")
    download = Download(own)
    with pytest.raises(intake.TooLarge):
        intake.save_download_as(download, out)
    assert download.copied == [], "copied although the browser's file was too large"
    assert out.read_bytes() == b"the document already here"


def test_a_download_whose_file_is_not_known_is_measured_beside_and_never_put_in_place(
        tmp_path, monkeypatch):
    monkeypatch.setattr(intake, "DOCUMENT_BYTES", 2000)
    out = tmp_path / "Statement.pdf"
    out.write_bytes(b"the document already here")
    with pytest.raises(intake.TooLarge):
        intake.save_download_as(Download(None, b"%PDF-" + b"\0" * 5000), out)
    assert out.read_bytes() == b"the document already here"
    assert left_in(tmp_path) == ["Statement.pdf"], "the copy made beside it was left"
    intake.save_download_as(Download(None, b"%PDF-1.4 a small one"), out)
    assert out.read_bytes() == b"%PDF-1.4 a small one"


def test_a_file_too_large_in_the_folder_is_left_there_by_take_download(tmp_path, monkeypatch):
    """Pointed at a folder, the browser leaves the event's own file empty
    and the document in the folder, which take_download then moves."""
    monkeypatch.setattr(intake, "DOCUMENT_BYTES", 2000)
    dl = tmp_path / "dl"
    dl.mkdir()
    before = capture.snapshot(dl)
    (dl / "statement.pdf").write_bytes(b"%PDF-1.4\n" + b"\0" * 5000)

    class Empty(Download):
        suggested_filename = "statement.pdf"

    out = tmp_path / "out" / "Statement.pdf"
    assert capture.take_download(Empty(None, b""), dl, before, out) == ""
    assert (dl / "statement.pdf").exists() and not out.exists()


def test_place_never_writes_bytes_too_large(tmp_path, monkeypatch):
    monkeypatch.setattr(intake, "DOCUMENT_BYTES", 2000)
    wrote = []
    monkeypatch.setattr(delivery.shared_folder, "write_bytes", lambda *a: wrote.append(a))
    assert delivery.place(b"%PDF-" + b"\0" * 5000, tmp_path / "x.pdf").outcome == delivery.TOO_LARGE
    assert wrote == []


def test_a_printed_page_too_large_is_not_put_in_place(tmp_path, monkeypatch):
    """The headless renderer's page.pdf writes the file itself, so what
    every capture stages is measured before it is checked or put in place."""
    monkeypatch.setattr(intake, "DOCUMENT_BYTES", 2000)
    out = tmp_path / "Receipt.pdf"
    out.write_bytes(b"the receipt already here")
    got = delivery.render(object(), lambda staged: Path(staged).write_bytes(
        b"%PDF-" + b"\0" * 5000), out)
    assert got.outcome == delivery.TOO_LARGE, got.report()
    assert out.read_bytes() == b"the receipt already here"
    assert left_in(tmp_path) == ["Receipt.pdf"]


def test_an_answer_read_in_flight_too_large_is_never_read(monkeypatch):
    monkeypatch.setattr(intake, "DOCUMENT_BYTES", 2000)

    class Response:
        url = "https://bank.example/statement.pdf"
        headers = {"content-type": "application/pdf", "content-length": "5000"}
        read = 0

        def body(self):
            Response.read += 1
            return b"%PDF-" + b"\0" * 5000

    armed = delivery._Armed(object(), is_safe_url=lambda u: True)
    armed._on_response(Response())
    assert Response.read == 0 and armed.too_large and not armed.body


def test_an_archive_larger_than_a_document_may_be_is_not_listed(tmp_path, monkeypatch):
    monkeypatch.setattr(intake, "DOCUMENT_BYTES", 1000)
    out = tmp_path / "Form.pdf"
    archive = zipped({"form.pdf": PDF}, method=zipfile.ZIP_STORED)
    assert len(archive) > 1000
    out.write_bytes(archive)

    def never(*a, **k):
        raise Listed("the archive was listed")

    monkeypatch.setattr(zipfile, "ZipFile", never)
    opened = receipt_pdf.open_zip(out, review(tmp_path))
    assert opened.pdf is None and "larger than a document may be" in opened.reason
    assert opened.kept.read_bytes() == archive


def test_a_zip_is_counted_even_where_its_last_record_cannot_be_read(tmp_path, monkeypatch):
    """zipfile's reader of that record is its own, and a later Python could
    rename it, which leaves the first count with nothing to say. The files
    are counted again once listed."""
    monkeypatch.setattr(intake, "ZIP_MEMBERS", 20)
    monkeypatch.setattr(receipt_pdf, "_archive_too_big", lambda path: "")
    out = tmp_path / "Form.pdf"
    out.write_bytes(zipped({"part %d.txt" % n: b"x" for n in range(25)}))
    opened = receipt_pdf.open_zip(out, review(tmp_path))
    assert opened.pdf is None and "listed 25 files" in opened.reason


def test_the_same_long_archive_again_is_kept_once_without_being_listed(tmp_path, monkeypatch):
    monkeypatch.setattr(intake, "ZIP_MEMBERS", 20)
    archive = zipped({"part %d.txt" % n: b"x" for n in range(25)})

    def never(*a, **k):
        raise Listed("the archive was listed")

    monkeypatch.setattr(zipfile, "ZipFile", never)
    for _ in range(2):
        out = tmp_path / "Form.pdf"
        out.write_bytes(archive)
        receipt_pdf.open_zip(out, review(tmp_path))
    assert left_in(review(tmp_path)) == ["Form.zip"]


# -- a real server and a real browser ------------------------------------------------

def _sync_playwright():
    return pytest.importorskip("playwright.sync_api", reason="needs a browser").sync_playwright


class Sent:
    """How many bytes the server managed to send, by tag."""

    def __init__(self):
        self.lock = threading.Lock()
        self.bytes = {}

    def add(self, tag, n):
        with self.lock:
            self.bytes[tag] = self.bytes.get(tag, 0) + n


@pytest.fixture(scope="module")
def server():
    """A provider that can answer with anything, any size, at any speed.

    /                      a page with a link to /doc
    /doc?n=&length=&d=&slow=&forever=&tag=
        n bytes of a PDF, with a declared length or chunked, as an
        attachment or inline, a piece every `slow` ms, or without end
    """
    sent = Sent()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            parts = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(parts.query).items()}
            if parts.path != "/doc":
                body = b'<a id="go" href="/doc?' + parts.query.encode() + b'">Statement</a>'
                self.send_response(200)
                self.send_header("content-type", "text/html")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            n = int(q.get("n", "0"))
            chunked = q.get("length") == "0"
            forever = q.get("forever") == "1"
            slow = int(q.get("slow", "0")) / 1000.0
            tag = q.get("tag", "")
            self.send_response(200)
            self.send_header("content-type", "application/pdf")
            if q.get("d"):
                self.send_header("content-disposition", '%s; filename="statement.pdf"' % q["d"])
            if chunked or forever:
                self.send_header("transfer-encoding", "chunked")
            else:
                self.send_header("content-length", str(n))
            self.end_headers()
            piece = b"%PDF-1.4\n" + b"\0" * (64 * 1024 - 9)
            done = 0
            try:
                while forever or done < n:
                    part = piece if forever else piece[:min(len(piece), n - done)]
                    if chunked or forever:
                        self.wfile.write(b"%x\r\n" % len(part) + part + b"\r\n")
                    else:
                        self.wfile.write(part)
                    done += len(part)
                    sent.add(tag, len(part))
                    if slow:
                        time.sleep(slow)
                if chunked:
                    self.wfile.write(b"0\r\n\r\n")
            except OSError:
                pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % httpd.server_address[1], sent
    httpd.shutdown()
    httpd.server_close()


ARGS = ["--disable-extensions", "--disable-sync", "--no-first-run", "--no-proxy-server"]


@pytest.fixture(scope="module")
def driver():
    with _sync_playwright()() as p:
        yield p


@pytest.fixture(scope="module")
def browser(driver):
    b = driver.chromium.launch(args=ARGS)
    yield b
    b.close()


@pytest.fixture
def page(browser, server):
    ctx = browser.new_context(accept_downloads=True)
    p = ctx.new_page()
    p.goto(server[0] + "/")
    yield p
    ctx.close()


def guard(base):
    return lambda url: str(url or "").startswith(base + "/")


@pytest.fixture
def small(monkeypatch):
    monkeypatch.setattr(intake, "DOCUMENT_BYTES", 1 * MiB)


def test_an_answer_asked_for_through_the_session_is_refused_by_its_length(
        page, server, small, monkeypatch, capsys):
    base, _ = server
    from playwright.sync_api import APIResponse
    read = []
    real = APIResponse.body
    monkeypatch.setattr(APIResponse, "body", lambda self: read.append(1) or real(self))
    assert capture.fetch_pdf(page, base + "/doc?n=%d" % (3 * MiB), guard(base)) is None
    assert read == [], "the body came into this process although its length said no"
    assert "larger than the 1 MB PaperPull takes in" in capsys.readouterr().out
    assert capture.fetch_pdf(page, base + "/doc?n=%d" % (512 * 1024), guard(base))[:5] == b"%PDF-"


def test_an_answer_with_no_length_is_refused_once_it_is_over(page, server, small):
    base, _ = server
    assert capture.fetch_pdf(page, base + "/doc?length=0&n=%d" % (3 * MiB), guard(base)) is None


def test_a_page_reads_an_answer_only_up_to_the_limit(page, server, small):
    """Read a piece at a time inside the page and stopped there, so the
    rest of the answer is never sent, and never reaches this process."""
    base, sent = server
    with pytest.raises(intake.TooLarge):
        capture.fetch_as_b64(page, base + "/doc?length=0&tag=page&n=%d" % (200 * MiB))
    assert sent.bytes.get("page", 0) < 100 * MiB, sent.bytes
    b64 = capture.fetch_as_b64(page, base + "/doc?n=%d" % (512 * 1024))
    assert intake.decode(b64)[:5] == b"%PDF-" and len(intake.decode(b64)) == 512 * 1024


def test_a_page_read_declared_too_large_is_refused_before_it_is_read(page, server, small):
    base, sent = server
    with pytest.raises(intake.TooLarge):
        capture.fetch_with_status(page, base + "/doc?tag=said&n=%d" % (200 * MiB))
    assert sent.bytes.get("said", 0) < 100 * MiB, sent.bytes


def test_delivery_asks_once_and_presses_nothing_after_a_refusal(page, server, small, tmp_path):
    base, _ = server
    pressed = []
    out = tmp_path / "Statement.pdf"
    out.write_bytes(b"the document already here")
    got = delivery.deliver(page, delivery.DocumentRequest(
        url=base + "/doc?n=%d" % (3 * MiB), trigger=lambda: pressed.append(1)),
        out, is_safe_url=guard(base))
    assert got.outcome == delivery.TOO_LARGE, got.report()
    assert pressed == [], "pressed after the document was refused for its size"
    assert out.read_bytes() == b"the document already here"
    assert left_in(tmp_path) == ["Statement.pdf"]


def test_a_download_too_large_is_never_copied(page, server, small, tmp_path):
    base, _ = server
    page.goto(base + "/?d=attachment&n=%d" % (3 * MiB))
    out = tmp_path / "Statement.pdf"
    out.write_bytes(b"the document already here")
    got = delivery.deliver(page, delivery.DocumentRequest(trigger=lambda: page.click("#go")),
                           out, is_safe_url=guard(base), settle_ms=8000)
    assert got.outcome == delivery.TOO_LARGE, got.report()
    assert out.read_bytes() == b"the document already here"
    assert left_in(tmp_path) == ["Statement.pdf"], "a staging or saving file was left"


def test_a_download_growing_past_the_limit_is_cancelled_while_it_arrives(
        driver, server, small, tmp_path):
    """Pointed at a folder, the browser writes the download there while it
    arrives, and it is cancelled once it is larger than a document may be,
    long before the provider has sent it all. The browser's own context, as
    an app attached to a person's browser has it, since a folder set over
    DevTools points that context's downloads and no other."""
    base, sent = server
    dl = tmp_path / "dl"
    ctx = driver.chromium.launch_persistent_context(
        str(tmp_path / "profile"), accept_downloads=True, args=ARGS)
    try:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        assert capture.set_download_dir(page, dl)
        page.goto(base + "/?d=attachment&tag=growing&slow=20&n=%d" % (40 * MiB))
        out = tmp_path / "out" / "Statement.pdf"
        started = time.monotonic()
        got = delivery.deliver(page, delivery.DocumentRequest(
            trigger=lambda: page.click("#go")), out, is_safe_url=guard(base),
            dl_dir=dl, settle_ms=8000)
        assert got.outcome == delivery.TOO_LARGE, got.report()
        assert time.monotonic() - started < 60
        assert not out.exists()
    finally:
        ctx.close()
    assert sent.bytes.get("growing", 0) < 20 * MiB, sent.bytes


def test_a_download_that_never_ends_is_cancelled_in_time(page, server, tmp_path, monkeypatch,
                                                         capsys):
    monkeypatch.setattr(intake, "DOWNLOAD_SECONDS", 3)
    base, _ = server
    page.goto(base + "/?d=attachment&forever=1&slow=200")
    out = tmp_path / "Statement.pdf"
    started = time.monotonic()
    got = delivery.deliver(page, delivery.DocumentRequest(trigger=lambda: page.click("#go")),
                           out, is_safe_url=guard(base), settle_ms=8000)
    # Its own outcome, never NOTHING, which RedCard presses for again.
    assert got.outcome == delivery.TOO_SLOW, got.report()
    assert time.monotonic() - started < 30
    said = capsys.readouterr().out
    assert "did not finish in 3 seconds" in said and "DOWNLOAD_SECONDS" in said
    assert not out.exists()


def test_a_download_saved_by_an_app_never_writes_over_what_is_there(page, server, small, tmp_path):
    base, _ = server
    page.goto(base + "/?d=attachment&n=%d" % (3 * MiB))
    out = tmp_path / "Statement.pdf"
    out.write_bytes(b"the document already here")
    with page.expect_download() as dl:
        page.click("#go")
    with pytest.raises(intake.TooLarge):
        receipt_pdf.save_download(dl.value, out)
    assert out.read_bytes() == b"the document already here"
    assert left_in(tmp_path) == ["Statement.pdf"]


def test_a_page_printed_larger_than_a_document_may_be_is_not_written(browser, tmp_path,
                                                                     monkeypatch):
    monkeypatch.setattr(intake, "DOCUMENT_BYTES", 20_000)
    p = browser.new_page()
    try:
        p.set_content("<body>%s</body>" % "".join(
            "<p>Line %d of a statement that goes on and on</p>" % n for n in range(4000)))
        out = tmp_path / "receipt.pdf"
        with pytest.raises(intake.TooLarge):
            receipt_pdf.print_page_to_pdf(p, out)
        assert not out.exists()
        monkeypatch.setattr(intake, "DOCUMENT_BYTES", 100 * MiB)
        receipt_pdf.print_page_to_pdf(p, out)
        assert out.read_bytes()[:5] == b"%PDF-"
    finally:
        p.close()


# The reader itself, in a page, against answers and blobs made in the page,
# so how much of a body was read can be counted.
READS = """async ([said, pieces, size]) => {
  let pulled = 0;
  const body = new ReadableStream({
    pull(c) {
      pulled++;
      if (pulled > pieces) { c.close(); return; }
      c.enqueue(new Uint8Array(size));
    }
  }, {highWaterMark: 0});
  const headers = said === null ? {} : {'content-length': String(said)};
  const r = new Response(body, {headers});
  try {
    const got = await ppRead(r);
    return {read: got.length, pulled};
  } catch (e) {
    return {refused: String(e.message || e), pulled};
  }
}"""

BLOB = """async (size) => {
  try { return (await ppBlob(new Blob([new Uint8Array(size)]))).length; }
  catch (e) { return String(e.message || e); }
}"""


def test_the_page_reader_refuses_a_declared_length_without_reading(page):
    got = page.evaluate(intake.reading(READS, 1000), [5000, 10, 100])
    assert "refused" in got and got["pulled"] == 0, got


def test_the_page_reader_stops_as_soon_as_it_is_over(page):
    got = page.evaluate(intake.reading(READS, 1000), [None, 1000, 100])
    assert "refused" in got and got["pulled"] <= 11, got
    got = page.evaluate(intake.reading(READS, 1000), [None, 10, 100])
    assert got == {"read": 1000, "pulled": 11}, got


def test_the_page_reader_refuses_a_blob_too_large(page):
    assert page.evaluate(intake.reading(BLOB, 1000), 1000) == 1000
    assert intake.READ_MARK in page.evaluate(intake.reading(BLOB, 1000), 1001)


def test_read_file_refuses_a_file_too_large(tmp_path, monkeypatch):
    """Meijer reads the browser's own copy of a download. It is measured
    before it is read."""
    monkeypatch.setattr(intake, "DOCUMENT_BYTES", 2000)
    big = tmp_path / "download"
    big.write_bytes(b"%PDF-" + b"\0" * 5000)
    opened = []
    real_open = open
    monkeypatch.setattr("builtins.open", lambda *a, **k: opened.append(a) or real_open(*a, **k))
    with pytest.raises(intake.TooLarge):
        intake.read_file(big)
    assert opened == [], "the file was opened although it was too large"
    small = tmp_path / "small"
    small.write_bytes(b"%PDF-1.4")
    assert intake.read_file(small) == b"%PDF-1.4"


def test_a_refusal_says_which_limit_and_where_it_is_raised(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(intake, "DOCUMENT_BYTES", 1000)
    with pytest.raises(intake.TooLarge) as caught:
        intake.decode("A" * 4000)
    assert "DOCUMENT_BYTES in paperpull_core/intake.py is the limit" in str(caught.value)
    monkeypatch.setattr(intake, "DOCUMENT_BYTES", 100 * MiB)
    out = tmp_path / "1099-R.pdf"
    out.write_bytes(zipped({"1099-R.pdf": b"%PDF-1.4\n" + b"\0" * (30 * MiB)}))
    opened = receipt_pdf.open_zip(out, review(tmp_path))
    assert opened.reason.endswith("ZIP_RATIO in paperpull_core/intake.py is the limit, and "
                                  "raising it lets a file unpack further"), opened.reason
    assert "ZIP_RATIO in paperpull_core/intake.py" in capsys.readouterr().out
    for name in ("DOCUMENT_BYTES", "DOWNLOAD_SECONDS", "ZIP_MEMBERS", "ZIP_RATIO",
                 "PDF_SECONDS", "PDF_MEMORY_BYTES"):
        assert isinstance(getattr(intake, name), int)
