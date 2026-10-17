"""Half of a character, made whole where a provider's text comes in, and
kept whole by everything that keeps text (paperpull_core.characters).

What a browser and a PDF reader hand Python is measured here first, since
the census in test_every_app_reads_text_whole.py rests on it. Python keeps
half of a character from a provider's JSON read by the json module and
from a PDF's text, and the browser gives U+FFFD everywhere else. Then
whole_json is held to whole_characters for every text in an answer, and
json_escaped to what Python's own JSON writes, and core storage to keeping
text whole, so a key holding a half still finds its record.
"""
import json
import random
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from paperpull_core import identity, not_shown, receipt_pdf, storage
from paperpull_core.characters import json_escaped, whole_characters, whole_json
from paperpull_core.storage import CsvFile, JsonStore, atomic_write_json, sanitize_component

HIGH, LOW, MARK = chr(0xD83D), chr(0xDE00), chr(0xFFFD)
EMOJI = chr(0x1F600)
BACKSLASH = chr(92)


def has_half(value) -> bool:
    return any(0xD800 <= ord(c) <= 0xDFFF for c in json.dumps(value, ensure_ascii=False))


# -- what a browser hands Python ----------------------------------------------------

# A provider's answer as its JSON writes half of an emoji, an escape.
ANSWER = ('{"items": [{"name": "Gift Card ' + BACKSLASH + 'ud83d", "n' + BACKSLASH
          + 'ude00": "x"}]}').encode("ascii")


@pytest.fixture()
def served():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = ANSWER if self.path.startswith("/answer") else b"<html><body>ok</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "application/json" if self.path.startswith("/answer")
                             else "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_a):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % server.server_address[1]
    server.shutdown()


@pytest.fixture()
def page(served):
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        chromium = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    context = chromium.new_context()
    tab = context.new_page()
    tab.goto(served + "/page")
    yield tab
    context.close()
    chromium.close()
    driver.stop()


def test_python_keeps_the_half_only_where_it_reads_a_providers_json_itself(page, served):
    """Measured in Playwright's own Chromium. The page and the DevTools
    protocol give U+FFFD, and Python's json module gives the half, from a
    Response, from the context's own requests and from text the page made
    with JSON.stringify. whole_json makes each of those what the browser
    gives."""
    url = served + "/answer"
    shown = page.evaluate("u => fetch(u).then(r => r.json())", url)
    assert shown == {"items": [{"name": "Gift Card " + MARK, "n" + MARK: "x"}]}
    kept = [
        page.goto(url).json(),
        page.context.request.get(url).json(),
        json.loads(page.evaluate("u => fetch(u).then(r => r.text())", url)),
        json.loads(page.evaluate("u => fetch(u).then(r => r.json()).then(JSON.stringify)", url)),
    ]
    for answer in kept:
        assert answer == {"items": [{"name": "Gift Card " + HIGH, "n" + LOW: "x"}]}
        assert whole_json(answer) == shown


# -- what a PDF reader hands Python -------------------------------------------------

def _pdf(cmap_body: str, lines) -> bytes:
    """A one-page PDF of these lines in Helvetica, whose ToUnicode map is
    cmap_body."""
    def literal(text):
        return text.replace(BACKSLASH, BACKSLASH * 2).replace("(", BACKSLASH + "(").replace(
            ")", BACKSLASH + ")")
    content = ("BT /F1 10 Tf 14 TL 40 750 Td "
               + " ".join("(%s) Tj T*" % literal(line) for line in lines) + " ET").encode("ascii")
    cmap = ("/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
            "/CMapName /Halves def\n1 begincodespacerange\n<00> <FF>\nendcodespacerange\n"
            + cmap_body + "endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n"
            ).encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /ToUnicode 6 0 R >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(cmap), cmap),
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for n, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (n, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


# The standard form, a character named by its UTF-16 code, here the codes
# of ~, { and | as a high half, a high half and a low half.
STANDARD = "3 beginbfchar\n<7E> <D83D>\n<7B> <D83D>\n<7C> <DE00>\nendbfchar\n"
STATEMENT = ["Gift Card ~ Statement", "{| Cafe Total $12.34"]


def test_pypdf_gives_the_half_and_every_core_reader_of_a_pdf_makes_it_whole(tmp_path):
    """pypdf takes a ToUnicode map's code in the standard form <D83D> for
    the half itself (measured 2026-10-17, pypdf 6.19.0), where pdfplumber
    drops it. Every app checks its PDFs with pypdf through the core, and
    each reader there gives U+FFFD and the emoji two halves make."""
    pypdf = pytest.importorskip("pypdf")
    path = tmp_path / "statement.pdf"
    path.write_bytes(_pdf(STANDARD, STATEMENT))
    given = pypdf.PdfReader(str(path)).pages[0].extract_text()
    assert "Gift Card " + HIGH in given and HIGH + LOW + " Cafe" in given, ascii(given)
    for text in (identity._text_of(path, 1), receipt_pdf.pdf_text(path)):
        assert "Gift Card " + MARK in text and EMOJI + " Cafe" in text, ascii(text)
        assert not has_half(text)


# -- whole_json and json_escaped ----------------------------------------------------

def _texts(rng, n=60) -> list:
    pool = [HIGH, LOW, MARK, EMOJI, BACKSLASH, '"', "a", "Z", " ", chr(0), chr(0xE9),
            chr(0xD800), chr(0xDBFF), chr(0xDC00), chr(0xDFFF)]
    return ["".join(rng.choice(pool) for _ in range(rng.randrange(0, 8))) for _ in range(n)]


def _value(rng, texts, depth=0):
    kind = rng.randrange(6 if depth < 4 else 3)
    if kind == 0:
        return rng.choice(texts)
    if kind == 1:
        return rng.choice([None, True, 0, -1.5, 12])
    if kind == 2:
        return rng.choice(texts)
    if kind == 3:
        return [_value(rng, texts, depth + 1) for _ in range(rng.randrange(4))]
    if kind == 4:
        return tuple(_value(rng, texts, depth + 1) for _ in range(rng.randrange(3)))
    return {rng.choice(texts): _value(rng, texts, depth + 1) for _ in range(rng.randrange(4))}


def _each_text_whole(given, made) -> bool:
    """made is given with every text in it, a key too, whole_characters of
    it, walked by a model of its own."""
    if isinstance(given, str):
        return made == whole_characters(given)
    if isinstance(given, (list, tuple)):
        return (type(made) is type(given) and len(made) == len(given)
                and all(_each_text_whole(g, m) for g, m in zip(given, made)))
    if isinstance(given, dict):
        # Two keys that come out the same are one, the later one's value
        # kept, as a dict built from them keeps it.
        expected = {}
        for k, v in given.items():
            expected[whole_characters(k) if isinstance(k, str) else k] = v
        return (type(made) is dict and list(made) == list(expected)
                and all(_each_text_whole(expected[k], made[k]) for k in made))
    return made is given


def test_whole_json_makes_every_text_in_an_answer_whole_and_leaves_one_with_none_as_it_was():
    rng = random.Random(20261017)
    texts = _texts(rng)
    for _ in range(3000):
        value = _value(rng, texts)
        made = whole_json(value)
        assert _each_text_whole(value, made), ascii(value)
        assert not has_half(made)
        if not has_half(value):
            assert made is value
    nested = {"a": [1, {"b": ("c",)}], "d": None}
    assert whole_json(nested) is nested
    assert whole_json({"k" + HIGH: [HIGH + LOW, (LOW,)]}) == {"k" + MARK: [EMOJI, (MARK,)]}


def test_json_escaped_writes_what_pythons_own_json_reads_back():
    """Read back, the escaped text is what Python's own JSON, which escapes
    everything outside ASCII, reads back, over every code point and every
    half next to a backslash or a quote. Two halves side by side read back
    as the character they make, which no JSON can tell apart."""
    every = "".join(chr(n) for n in range(0x110000))
    rng = random.Random(20261017)
    values = [every, {every: [every]}] + [_value(rng, _texts(rng)) for _ in range(2000)]
    for value in values:
        text = json.dumps(value, ensure_ascii=False, indent=2)
        escaped = json_escaped(text)
        escaped.encode("utf-8")
        assert json.loads(escaped) == json.loads(json.dumps(value)), ascii(value)[:200]
    plain = json.dumps({"a": "b" + EMOJI}, ensure_ascii=False)
    assert json_escaped(plain) is plain


# -- what keeps text ---------------------------------------------------------------

def test_a_json_file_with_a_half_in_it_is_written_and_reads_back_exactly(tmp_path):
    """atomic_write_json stopped at a half with UnicodeEncodeError and wrote
    nothing. A half left in a file written straight from data is kept as
    its escape, so a name a disk gave Python, which Linux gives as a half
    for each byte it cannot read, still names its file."""
    path = tmp_path / "note.json"
    data = {"k" + HIGH: ["x" + BACKSLASH + HIGH, "/data/caf" + chr(0xDCE9)]}
    atomic_write_json(path, data)
    assert json.loads(path.read_bytes().decode("utf-8")) == data


def test_a_store_keeps_text_whole_and_finds_a_record_by_a_key_holding_a_half(tmp_path):
    """Up to now JsonStore.update stopped at a half and progress.json was
    not written. Now the record and the key are whole, U+FFFD as the CSV
    beside them holds it, and a record is asked for by its key made whole
    too, so a key holding a half finds it, in this run and the next."""
    path = tmp_path / "progress.json"
    store = JsonStore(path)
    key = "Online:A1111" + HIGH
    store.update(key, {"summary": "Gift " + HIGH, "items": [{"name": LOW + "Kettle"}],
                       "order_number": "A1111" + HIGH})
    assert store.get(key)["summary"] == "Gift " + MARK
    assert list(store.data) == ["Online:A1111" + MARK]
    held = path.read_bytes().decode("utf-8")
    assert not has_half(json.loads(held)) and BACKSLASH + "ud83d" not in held
    again = JsonStore(path)
    assert again.get(key)["items"] == [{"name": MARK + "Kettle"}]
    assert again.get("Online:A1111" + MARK) is again.get(key)

    # A record put into the store's data straight, not by update, is
    # written with its half as an escape, and the next run reads it whole.
    store.data["Online:B" + LOW] = {"summary": HIGH}
    store.save()
    after = JsonStore(path)
    assert after.get("Online:B" + LOW) == {"summary": MARK}
    store.data["Online:C" + LOW] = {"summary": HIGH}
    store.save(leaving=True)
    assert JsonStore(path).get("Online:C" + MARK) == {"summary": MARK}


def test_a_record_put_into_a_store_straight_under_a_key_holding_a_half_is_never_split(tmp_path):
    """Two apps put a record into the store's data straight, not by update.
    Under a key holding a half, get found nothing there and update started a
    second record under the key made whole, and the next run, reading the
    file whole, kept only one of the two. Now get finds it, update joins the
    two, and two records a file holds under such keys are read as one with
    the fields of both."""
    path = tmp_path / "progress.json"
    store = JsonStore(path)
    store.data["Online:B" + LOW] = {"summary": "Kettle", "pdf_path": "a.pdf"}
    assert store.get("Online:B" + LOW) == {"summary": "Kettle", "pdf_path": "a.pdf"}
    store.update("Online:B" + LOW, {"state": "Completed"})
    assert list(store.data) == ["Online:B" + MARK]
    again = JsonStore(path).get("Online:B" + LOW)
    assert (again["summary"], again["pdf_path"], again["state"]) == ("Kettle", "a.pdf", "Completed")

    both = {"Online:C" + HIGH: {"summary": "Lid", "pdf_path": "c.pdf"},
            "Online:C" + MARK: {"state": "Completed"}}
    atomic_write_json(path, both)
    read = JsonStore(path).get("Online:C" + MARK)
    assert read == {"summary": "Lid", "pdf_path": "c.pdf", "state": "Completed"}


def test_a_file_name_holds_no_half(tmp_path):
    """sanitize_component kept a half, Windows made the file and a Mac
    refuses one, and the index beside it held U+FFFD. Now the name holds
    U+FFFD too, and two halves side by side the emoji they make."""
    assert sanitize_component("Gift " + HIGH) == "Gift " + MARK
    assert sanitize_component(HIGH + LOW + " Cafe") == EMOJI + " Cafe"
    named = storage.file_name_of(["Gift " + LOW, "Statement " + HIGH])
    assert named == "Statement " + MARK + ".pdf" and named.folder == "Gift " + MARK
    path = tmp_path / named
    path.write_bytes(b"%PDF-1.4\n")
    assert [p.name for p in tmp_path.iterdir()] == ["Statement " + MARK + ".pdf"]


def test_a_receipt_apps_history_check_finds_an_order_number_holding_a_half(tmp_path):
    """The order history holds the half as U+FFFD, and written_down asks for
    the order number made whole the same way, so a purchase set aside is
    written down once."""
    history = CsvFile(tmp_path / "history.csv", ["Purchase Type", "Order or Receipt Number"])
    history.append_rows([{"Purchase Type": "Online", "Order or Receipt Number": "A1111" + HIGH}])
    app = SimpleNamespace(order_csv=history)
    assert not_shown.written_down(app, SimpleNamespace(order_number="A1111" + HIGH,
                                                       purchase_type="Online"))
    assert not not_shown.written_down(app, SimpleNamespace(order_number="A1111",
                                                           purchase_type="Online"))
    assert [r["Order or Receipt Number"] for r in history.read_all()] == ["A1111" + MARK]
    assert Path(history.path).read_bytes().decode("utf-8-sig")
