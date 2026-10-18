"""Every way a document's bytes come in goes through a limit.

An audit of 0.53.0 found that a document could be any size and take any
time. capture.fetch_pdf read an answer's whole body, receipt_pdf.open_zip
unpacked whatever an archive held, and validate_pdf and pdf_text let pypdf
read a PDF for as long as it liked in the app's own process. The fix put
the limits in paperpull_core.intake and the reading of PDFs in
paperpull_core.pdf_reader, and this reads every file that ships, the
apps' own included and the tests apart, so that no way in skips them.

A way in is any of these, and each is allowed in the one place that holds
its limit and nowhere else.

    an answer's body          resp.body()                   intake.body
    base64 handed back        base64.b64decode()            intake.decode
    a download's file         download.save_as(), .path()   intake.save_download_as,
                                                            intake.read_file
    a body read in the page   arrayBuffer(), blob(), ...    intake.reading, ppRead, ppBlob
    a printed page            "Page.printToPDF"             receipt_pdf.printed_pdf
    a PDF read                PdfReader, extract_text       pdf_reader
    an archive opened         zipfile.ZipFile               receipt_pdf.open_zip
    packed bytes unpacked     zlib.decompress, ...          intake.inflate

and a snippet that reads a body in the page (ppRead, ppBlob) is run
through intake.evaluate, which puts the reader in front of it with the
limit of the moment and says a refusal in words. Each such snippet is
compiled in a real browser with the reader in front, since a test of the
Python around it proves nothing of the JavaScript.

A use that is not a document is named below with the reason.

Not counted here, and so not held by these limits, is what a page hands
back that is not a document's bytes, a listing's JSON, a page's text or
HTML, which V8 holds to about 512 million characters and Chromium keeps
of a page's own answer only up to about ten megabytes.
"""
import ast
import functools
import os
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

ROOTS = ("apps", "core", "gui", "server", "tools", "packaging")
MADE_FOLDERS = {"build", "dist", "site-packages", "node_modules"}

INTAKE = "core/paperpull_core/intake.py"
READER = "core/paperpull_core/pdf_reader.py"
RECEIPT_PDF = "core/paperpull_core/receipt_pdf.py"
DELIVERY = "core/paperpull_core/delivery.py"

# Where each kind of way in is allowed, the one place holding its limit.
HOME = {
    "body": {INTAKE},
    "decode": {INTAKE},
    "save_as": {INTAKE},
    "download_path": {INTAKE, DELIVERY},
    "page_read": {INTAKE},
    "print": {RECEIPT_PDF},
    "pdf": {READER},
    "zip": {RECEIPT_PDF},
    "inflate": {INTAKE},
}

# Uses that are not a document coming in, or that hold the limit another
# way, with the reason. Keyed by the file, the function the use is in (""
# for the module) and the kind.
NOT_A_DOCUMENT = {
    ("apps/lowes/lowes_site.py", "details_id", "decode"):
        "an order's id in a link, at most 80 characters, checked to be base64",
    ("apps/lowes/lowes_site.py", "pair_cards", "decode"):
        "an order's id in a link, at most 80 characters, checked to be base64",
    ("apps/meijer/meijer_site.py", "on_download", "download_path"):
        "waited for in the listener's own fiber, the file then read through "
        "intake.read_file",
    ("apps/spectrum/spectrum_site.py", "decode_statement_id", "decode"):
        "a statement's id, which holds its account and date, not a document",
    ("apps/spectrum/spectrum_site.py", "pair", "decode"):
        "a statement's id, which holds its account and date, not a document",
    ("apps/spectrum/spectrum_site.py", "private_words_of", "decode"):
        "a statement's id, which holds its account and date, not a document",
    ("apps/uber/uber_site.py", "token_time", "decode"):
        "a list's page token, which holds a time, not a document",
    ("core/paperpull_core/receipt_pdf.py", "printed_pdf", "decode"):
        "a piece of a printed page, asked for a megabyte at a time and counted "
        "against the limit as it comes",
    ("core/paperpull_core/testkit.py", "sample_pdf", "pdf"):
        "a stand-in PDF a test writes, never one read in",
    ("gui/app.py", "_history_upload", "decode"):
        "a history export sent to the panel, held to HISTORY_MAX_BYTES as it "
        "streams in and read under tools/migrate.py's own limits",
    ("gui/app.py", "api_aside_download", "zip"):
        "a ZIP of Manual Review the panel writes for a download, nothing read in",
    ("packaging/build_windows.py", "zip_it", "zip"):
        "the release's own ZIP, written when a release is built",
    ("server/selftest.py", "browser_checks", "decode"):
        "the server's self test printing a blank page of its own, never a provider's",
    ("server/selftest.py", "browser_checks", "print"):
        "the server's self test printing a blank page of its own, never a provider's",
    ("tools/export_transactions.py", "pdf_lines", "pdf"):
        "the person's own archive, read by a tool the panel runs in a process "
        "of its own, which a stuck read leaves the panel usable beside",
    ("tools/migrate.py", "read", "zip"):
        "a history export, read under the module's own MAX_ limits",
    ("tools/migrate.py", "build", "zip"):
        "a history export being written, nothing read in",
}

# A body read whole inside a page, in a snippet's own text.
PAGE_READS = re.compile(r"\.arrayBuffer\(|\.blob\(\)|getReader\(|readAsDataURL|readAsArrayBuffer|"
                        r"readAsBinaryString|\.bytes\(\)")
DECODERS = {"b64decode", "urlsafe_b64decode", "standard_b64decode", "decodebytes",
            "a2b_base64"}
PDF_NAMES = {"PdfReader", "PdfWriter", "PdfFileReader", "PdfMerger", "PdfDocument"}
UNPACKERS = {"zlib", "_zlib", "gzip", "bz2", "lzma", "brotli", "zstd"}
READERS = re.compile(r"\bpp(?:Read|Blob)\(")
# A snippet that fetches and hands bytes back to Python as base64, which
# has to have read them with ppRead or ppBlob.
HANDS_BACK = re.compile(r"\bbtoa\(|\bb64\s*[:=]")


def is_test(path: Path) -> bool:
    parts = path.relative_to(REPO).parts
    return ("tests" in parts or path.name.startswith("test_")
            or path.name == "conftest.py" or ".venv" in parts
            or any(p.startswith(".") for p in parts))


def sources():
    """Every Python file that ships, tests and copies a build made apart."""
    out = sorted(REPO.glob("*.py"))
    for root in ROOTS:
        for folder, dirs, files in os.walk(REPO / root):
            dirs[:] = [d for d in dirs if d not in MADE_FOLDERS and not d.startswith(".")
                       and d != "__pycache__"]
            out.extend(Path(folder) / f for f in files if f.endswith(".py"))
    return [p for p in out if not is_test(p)]


@functools.lru_cache(maxsize=None)
def _parsed(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    owner = {}

    def walk(node, name):
        for child in ast.iter_child_nodes(node):
            owner[child] = name
            inner = child.name if isinstance(child, (ast.FunctionDef,
                                                     ast.AsyncFunctionDef)) else name
            walk(child, inner)
    walk(tree, "")
    return tree, owner


def _strings(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node, node.value


def ways_in(path: Path, root: Path = REPO):
    """The file's path from `root`, and (kind, line, function, what) for
    every way in it holds outside that kind's home."""
    rel = path.relative_to(root).as_posix()
    tree, owner = _parsed(path)
    found = []
    for node in ast.walk(tree):
        fn = owner.get(node, "")
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            bare = not node.args and not node.keywords
            if name == "body" and isinstance(f, ast.Attribute) and bare:
                found.append(("body", node.lineno, fn, "an answer's body read whole"))
            elif name in DECODERS:
                found.append(("decode", node.lineno, fn, "base64 decoded"))
            elif name == "save_as" and isinstance(f, ast.Attribute):
                found.append(("save_as", node.lineno, fn, "a download copied"))
            elif name == "path" and isinstance(f, ast.Attribute) and bare:
                found.append(("download_path", node.lineno, fn, "a download's own file"))
            elif name in ("extract_text", "open") and isinstance(f, ast.Attribute) \
                    and (name == "extract_text" or getattr(f.value, "id", "") == "pdfplumber"):
                found.append(("pdf", node.lineno, fn, "a PDF's text read"))
            elif name == "ZipFile":
                found.append(("zip", node.lineno, fn, "an archive opened"))
            elif name in ("decompress", "decompressobj") and isinstance(f, ast.Attribute) \
                    and getattr(f.value, "id", "") in UNPACKERS:
                found.append(("inflate", node.lineno, fn, "packed bytes unpacked"))
        if isinstance(node, (ast.Name, ast.Attribute)):
            name = node.id if isinstance(node, ast.Name) else node.attr
            if name in PDF_NAMES:
                found.append(("pdf", node.lineno, fn, "pypdf used directly"))
        if isinstance(node, ast.alias) and node.name.split(".")[-1] in PDF_NAMES:
            found.append(("pdf", getattr(node, "lineno", 0), fn, "pypdf imported directly"))
    for node, text in _strings(tree):
        fn = owner.get(node, "")
        if PAGE_READS.search(text):
            found.append(("page_read", node.lineno, fn, "a body read whole in the page"))
        elif HANDS_BACK.search(text) and "fetch(" in text and not READERS.search(text):
            found.append(("page_read", node.lineno, fn, "bytes fetched in the page and "
                          "handed back unread by ppRead"))
        if text.strip() == "Page.printToPDF":
            found.append(("print", node.lineno, fn, "a page printed whole"))
    return rel, [w for w in found if rel not in HOME[w[0]]]


def unlimited(paths=None, root: Path = REPO):
    out = []
    for path in paths if paths is not None else sources():
        rel, found = ways_in(path, root)
        for kind, line, fn, what in found:
            if (rel, fn, kind) in NOT_A_DOCUMENT:
                continue
            out.append("%s:%d %s (%s, in %s)" % (rel, line, what, kind, fn or "the module"))
    return sorted(set(out))


def test_every_way_a_document_comes_in_goes_through_its_limit():
    left = unlimited()
    assert not left, "a way in with no limit:\n" + "\n".join(left)


# -- a snippet that reads a body is run through intake.evaluate ----------------

def _reader_names(tree):
    """Names bound to a snippet that calls ppRead or ppBlob."""
    names = set()
    for node in ast.walk(tree):
        # Built of strings, never a call that was handed one.
        if isinstance(node, ast.Assign) and isinstance(node.value, (ast.Constant, ast.BinOp,
                                                                    ast.JoinedStr)):
            text = "".join(c.value for c in ast.walk(node.value)
                           if isinstance(c, ast.Constant) and isinstance(c.value, str))
            if READERS.search(text):
                names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


def _is_intake_evaluate(func) -> bool:
    if isinstance(func, ast.Attribute) and func.attr == "evaluate":
        return getattr(func.value, "id", "") in ("intake", "_intake")
    return False


def snippets_run_without_the_reader(paths=None, root: Path = REPO):
    out = []
    for path in paths if paths is not None else sources():
        rel = path.relative_to(root).as_posix()
        if rel == INTAKE:
            continue
        tree, _ = _parsed(path)
        names = _reader_names(tree)
        inline = [n for n, text in _strings(tree) if READERS.search(text)]
        if not names and not inline:
            continue
        handed = {id(a) for node in ast.walk(tree) if isinstance(node, ast.Call)
                  and _is_intake_evaluate(node.func) for a in node.args[1:2]}
        assigned = {id(t) for node in ast.walk(tree) if isinstance(node, ast.Assign)
                    for t in node.targets}
        # A piece of a snippet built by joining strings belongs to the name
        # it is assigned to, and that name is what is checked.
        pieces = {id(c) for node in ast.walk(tree) if isinstance(node, ast.Assign)
                  for c in ast.walk(node.value)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in names and id(node) not in assigned \
                    and id(node) not in handed:
                out.append("%s:%d %s is used other than through intake.evaluate"
                           % (rel, node.lineno, node.id))
        for node in inline:
            if id(node) not in handed and id(node) not in pieces:
                out.append("%s:%d a snippet that reads a body is not run through "
                           "intake.evaluate" % (rel, node.lineno))
    return sorted(out)


def test_every_snippet_that_reads_a_body_runs_through_intake_evaluate():
    left = snippets_run_without_the_reader()
    assert not left, "\n".join(left)


SAMPLE = (
    "import base64, zipfile\n"
    "from pypdf import PdfReader\n"
    "JS = 'async (u) => { const r = await fetch(u); return await r.arrayBuffer(); }'\n"
    "B64 = 'async (u) => { const r = await fetch(u); return {b64: btoa(await r.text())}; }'\n"
    "READ = 'async (u) => { const r = await fetch(u); return await ppRead(r); }'\n"
    "def take(page, resp, dl, path):\n"
    "    resp.body()\n"
    "    base64.b64decode('')\n"
    "    dl.save_as(path)\n"
    "    open(dl.path(), 'rb').read()\n"
    "    PdfReader(path).pages[0].extract_text()\n"
    "    zipfile.ZipFile(path)\n"
    "    page.context.new_cdp_session(page).send('Page.printToPDF', {})\n"
    "    page.evaluate(READ, 'x')\n"
    "    import zlib\n"
    "    zlib.decompress(b'')\n")


def test_the_census_finds_what_it_looks_for(tmp_path):
    """Not passing on nothing. Each kind of way in is found in a made-up
    app, which is written to a folder of the test's own and never into the
    checkout, and a snippet handed straight to the page is found too."""
    sample = tmp_path / "apps" / "sample" / "sample_site.py"
    sample.parent.mkdir(parents=True)
    sample.write_text(SAMPLE, encoding="utf-8")
    _, found = ways_in(sample, tmp_path)
    kinds = {k for k, *_ in found}
    assert kinds == set(HOME), kinds
    assert len([w for w in found if w[0] == "page_read"]) == 2, found
    assert any("sample_site.py" in line
               for line in snippets_run_without_the_reader([sample], tmp_path))
    good = sample.with_name("good_site.py")
    good.write_text("from paperpull_core import intake\n"
                    "READ = 'async (u) => { const r = await fetch(u); return await ppRead(r); }'\n"
                    "def take(page):\n"
                    "    return intake.evaluate(page, READ, 'x')\n", encoding="utf-8")
    assert snippets_run_without_the_reader([good], tmp_path) == []
    assert unlimited([good], tmp_path) == []


def test_every_reason_still_names_a_use_that_is_there():
    """A reason whose use has gone stays here as a hole a new use could slip
    through, so it goes too."""
    seen = set()
    for path in sources():
        rel, found = ways_in(path)
        seen.update((rel, fn, kind) for kind, _, fn, _ in found)
    gone = sorted("%s %s %s" % k for k in NOT_A_DOCUMENT if k not in seen)
    assert not gone, "named with a reason and not there any more:\n" + "\n".join(gone)


# -- every bounded snippet compiles in a real browser ---------------------------

def bounded_snippets():
    """(file, name, source) of every module-level snippet that reads a body
    through ppRead or ppBlob, its pieces joined the way the module joins
    them, from the source and without importing the app."""
    out = []
    for path in sources():
        rel = path.relative_to(REPO).as_posix()
        if rel == INTAKE:
            continue
        tree, _ = _parsed(path)
        strings: dict = {}
        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1 \
                    or not isinstance(node.targets[0], ast.Name):
                continue
            try:
                value = eval(compile(ast.Expression(node.value), rel, "eval"),
                             {"__builtins__": {}}, dict(strings))
            except Exception:
                continue
            if isinstance(value, str):
                strings[node.targets[0].id] = value
                if READERS.search(value):
                    out.append((rel, node.targets[0].id, value))
        named = {value for where, _, value in out if where == rel}
        for node, text in _strings(tree):
            # A whole snippet written where it is run, not one bound to a name.
            if READERS.search(text) and text.lstrip().startswith("async") and text not in named:
                out.append((rel, "line %d" % node.lineno, text))
    return out


def test_the_census_compiles_every_snippet_it_should():
    found = {(rel, name) for rel, name, _ in bounded_snippets()}
    for expected in (("core/paperpull_core/capture.py", "FETCH_AS_B64"),
                     ("core/paperpull_core/blob_capture.py", "TAKE_JS"),
                     ("apps/mypay/mypay_site.py", "_PDF_JS"),
                     ("apps/usaa/usaa_site.py", "_BLOB_FETCH_JS")):
        assert expected in found, expected
    assert len(found) >= 30, len(found)


def test_every_bounded_snippet_compiles_in_a_browser():
    from paperpull_core import intake
    sync_playwright = pytest.importorskip("playwright.sync_api",
                                          reason="needs a browser").sync_playwright
    snippets = bounded_snippets()
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--disable-extensions", "--disable-sync",
                                          "--no-first-run"])
        try:
            page = browser.new_page()
            broken = page.evaluate("""(all) => all.map(([where, src]) => {
                try {
                    const f = (0, eval)('(' + src + ')');
                    return typeof f === 'function' ? '' : where + ' is not a function';
                } catch (e) { return where + ': ' + String(e); }
            }).filter(Boolean)""", [["%s %s" % (rel, name), intake.reading(src)]
                                    for rel, name, src in snippets])
        finally:
            browser.close()
    assert not broken, "\n".join(broken)
