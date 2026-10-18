"""How much of a document PaperPull takes in, held in one place.

Every way a document reaches an app, a fetch, an answer read off the
network, a download, a ZIP opened, a PDF read for its text, used to take
whatever came, however large, for however long. A provider's answer that
never ended, an archive that unpacks a thousand times over, or a PDF built
to keep its reader busy had nothing to stop them but the computer running
out of memory or the run never finishing.

The limits are here and nowhere else, and every reader looks them up when
it reads, so changing one here changes it everywhere.

MEASURED 2026-10-17 on the maintainer's installs, sizes only. 2,644 PDFs
from 38 providers, the largest 3.9 MB (a TSP statement), 99.9 percent of
them under 2.9 MB, and no ZIP among them. A document may be twenty five
times the largest seen, and anything larger is refused before it is read,
which is generous for a statement and still a bound on a NAS.
"""
from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from typing import Optional

log = logging.getLogger("paperpull.intake")

MiB = 1024 * 1024

# The most one document may be as it arrives, a PDF or a ZIP holding one,
# whichever way it comes.
DOCUMENT_BYTES = 100 * MiB

# A ZIP is opened only when it holds one PDF and nothing else
# (receipt_pdf.open_zip). Its listing is read before any file in it, and an
# archive listing more files than this is kept whole without a look inside.
ZIP_MEMBERS = 1000
# How many times its packed size a file in a ZIP may unpack to. A PDF packs
# poorly, since its pages are compressed already, and a statement printed
# with no compression at all packs to about a tenth. An archive built to
# fill a disk unpacks a thousand times over.
ZIP_RATIO = 100
# A file this small is never refused for its ratio. A PDF written with no
# compression and padded packs a hundred times over (a review made one of
# 2 MB), and below this the size limit alone already bounds what unpacks.
ZIP_RATIO_FROM = 10 * MiB

# How long one PDF may take to be read for its pages and its text, and how
# much memory the reading may use. It happens in a process of its own
# (pdf_reader), which is stopped when either is passed.
#
# MEASURED 2026-10-17 here, a statement of 282 dense pages printed by
# Chromium had all its text read in 5.2 s, and the worker's start costs
# 0.3 s once a run and 2 ms a PDF after. A PDF of 72 KB holding one string
# of 70 MB took pypdf 6.19 175 s and stopped at once against 200 MB of
# memory. Two minutes leaves a slow NAS room for a long statement.
PDF_SECONDS = 120
PDF_MEMORY_BYTES = 1024 * MiB

# How long a download the page started may take to finish once it has
# begun, before it is cancelled. A 100 MB document at a slow 1 MB a second
# takes under two minutes.
DOWNLOAD_SECONDS = 300


class TooLarge(Exception):
    """A document, or an answer that might be one, refused for its size. Its
    words say so in a sentence a person can read."""


def raising(name: str, gives: str) -> str:
    """Which limit a refusal met and where it is raised, said after the
    refusal itself, so a person who sees it on every run knows what to
    change. A document refused for a limit is asked for again on the next
    run, as any refused document is, and comes in once the limit allows it."""
    return "%s in paperpull_core/intake.py is the limit, and raising it %s." % (name, gives)


def _mb(n: int) -> str:
    return "%d MB" % max(1, round(n / MiB)) if n >= MiB else "%d bytes" % n


_refused = 0


def refused_count() -> int:
    """How many refusals this process has said, so a capture can tell
    whether one happened while it ran, whichever reader made it."""
    return _refused


_timed_out = 0


def timed_out_count() -> int:
    """How many downloads this process has cancelled for their time."""
    return _timed_out


def refuse(what: str = "The answer for this document", size: Optional[int] = None,
           limit: Optional[int] = None) -> TooLarge:
    """The refusal for something over the limit, said once on the run's
    output and in the log, ready to raise."""
    global _refused
    _refused += 1
    limit = DOCUMENT_BYTES if limit is None else limit
    sized = " (%s)" % _mb(size) if size else ""
    said = ("%s was larger than the %s PaperPull takes in%s, so it was not read. %s"
            % (what, _mb(limit), sized, raising("DOCUMENT_BYTES", "lets a larger one in")))
    log.warning(said)
    print("  " + said)
    return TooLarge(said)


def declared(resp) -> Optional[int]:
    """The length an answer says its body has, or None when it says none.
    Playwright gives header names in lower case, for a page's answer and
    for one it asked for itself alike."""
    try:
        headers = resp.headers or {}
        value = headers.get("content-length")
    except Exception:
        return None
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def body(resp, limit: Optional[int] = None) -> bytes:
    """An answer's body, refused unread when its declared length is over
    the limit, and refused when what came is. Raises TooLarge.

    For an answer the app asked for itself (context.request), Playwright's
    driver holds the whole body before this can see any of it, and nothing
    in Playwright 1.63 bounds that (coreBundle.js gathers every chunk of
    every request). What this keeps out is the copy into this process, at
    once when the length is declared. MEASURED 2026-10-17 in Chromium 153,
    an answer to the page itself is kept by the browser only up to about
    ten megabytes, and body() then raises that it was evicted, so a page's
    answer is bounded before it gets here."""
    limit = DOCUMENT_BYTES if limit is None else limit
    said = declared(resp)
    if said is not None and said > limit:
        _let_go(resp)
        raise refuse(size=said, limit=limit)
    data = resp.body() or b""
    if len(data) > limit:
        _let_go(resp)
        raise refuse(size=len(data), limit=limit)
    return data


def _let_go(resp) -> None:
    """Have Playwright's driver drop an answer it asked for itself, which it
    otherwise holds whole until its context closes. A page's answer has
    nothing to drop."""
    try:
        dispose = getattr(resp, "dispose", None)
        if callable(dispose):
            dispose()
    except Exception:
        pass


def decode(text, *, validate: bool = False, limit: Optional[int] = None) -> bytes:
    """Base64 a page or the browser handed back, decoded, refused before it
    is decoded when it holds more than the limit. Raises TooLarge."""
    if not text:
        return b""
    limit = DOCUMENT_BYTES if limit is None else limit
    # Four characters carry three bytes, and the padding carries none.
    if len(text) > (limit // 3 + 1) * 4:
        raise refuse(size=len(text) // 4 * 3, limit=limit)
    data = base64.b64decode(text, validate=validate)
    if len(data) > limit:
        raise refuse(size=len(data), limit=limit)
    return data


def inflate(data: bytes, wbits: int = 15, limit: Optional[int] = None) -> bytes:
    """zlib.decompress(data, wbits), refused once it unpacks past the limit
    rather than after. Raises TooLarge, and zlib.error for data that is
    not whole, as zlib.decompress does."""
    import zlib
    limit = DOCUMENT_BYTES if limit is None else limit
    d = zlib.decompressobj(wbits)
    out = d.decompress(data, limit + 1)
    if len(out) > limit or d.unconsumed_tail:
        raise refuse("The packed document", limit=limit)
    # Everything was read, so what is left to come is at most one copy.
    out += d.flush()
    if len(out) > limit:
        raise refuse("The packed document", size=len(out), limit=limit)
    if not d.eof:
        raise zlib.error("incomplete or truncated stream")
    return out


def size_of(path) -> int:
    """The size of a file, 0 when it cannot be read."""
    try:
        return os.stat(path).st_size
    except (OSError, ValueError, TypeError):
        return 0


def over(path, limit: Optional[int] = None) -> bool:
    """Whether a file on disk is larger than a document may be."""
    limit = DOCUMENT_BYTES if limit is None else limit
    return size_of(path) > limit


def read_file(path, what: str = "The downloaded file", limit: Optional[int] = None) -> bytes:
    """A file's bytes, refused unread when it is larger than a document may
    be. Raises TooLarge, and whatever reading it raises."""
    check_file(path, what, limit)
    with open(path, "rb") as f:
        data = f.read((DOCUMENT_BYTES if limit is None else limit) + 1)
    if len(data) > (DOCUMENT_BYTES if limit is None else limit):
        raise refuse(what, size=len(data), limit=limit)
    return data


def check_file(path, what: str = "The downloaded file", limit: Optional[int] = None) -> None:
    """Refuse a file on disk over the limit, before anything reads it.
    Raises TooLarge. The file is left where it is."""
    limit = DOCUMENT_BYTES if limit is None else limit
    size = size_of(path)
    if size > limit:
        raise refuse(what, size=size, limit=limit)


# -- reading an answer inside the page ----------------------------------------
#
# A page fetches a document with the session's cookies and hands it back as
# base64, and Response.arrayBuffer() holds the whole answer before a single
# byte can be counted. These read it a piece at a time instead and stop at
# the limit. A snippet that reads a body calls ppRead(response) or
# ppBlob(blob) in place of arrayBuffer(), and is run through evaluate()
# below, which puts these in front of it with the limit of the moment.
#
# A page's own scripts can change fetch and every reader under it, so a
# provider's page that meant to could still hand back more. decode() then
# refuses it before it is decoded, and V8 holds no string past about 512
# million characters, which bounds what can come back at all.

READ_MARK = "PaperPull refused an answer over its limit"

_READ_JS = r"""
  const ppLimit = %(limit)d;
  const ppOver = (n) => new Error("%(mark)s of " + ppLimit + " bytes, " + n);
  const ppRead = async (r) => {
    const said = Number(r.headers.get("content-length"));
    if (said > ppLimit) {
      try { if (r.body) await r.body.cancel(); } catch (e) {}
      throw ppOver(said);
    }
    if (!r.body) return new Uint8Array(0);
    const reader = r.body.getReader();
    const parts = [];
    let got = 0;
    for (;;) {
      const {done, value} = await reader.read();
      if (done) break;
      got += value.byteLength;
      if (got > ppLimit) {
        try { await reader.cancel(); } catch (e) {}
        throw ppOver(got);
      }
      parts.push(value);
    }
    const out = new Uint8Array(got);
    let at = 0;
    for (const p of parts) { out.set(p, at); at += p.byteLength; }
    return out;
  };
  const ppBlob = async (b) => {
    if (!b) return new Uint8Array(0);
    if (b.size > ppLimit) throw ppOver(b.size);
    return new Uint8Array(await b.arrayBuffer());
  };
"""

_OPENER = "=> {"
_built: dict = {}


def reading(js: str, limit: Optional[int] = None) -> str:
    """A snippet with ppRead and ppBlob put at the top of its body, reading
    no more than `limit`. The snippet is an arrow function, and they go in
    right after the first "=> {". ValueError when it has none."""
    limit = DOCUMENT_BYTES if limit is None else int(limit)
    key = (js, limit)
    if key not in _built:
        at = js.find(_OPENER)
        if at < 0:
            raise ValueError("a snippet that reads a body must be an arrow function with a body")
        at += len(_OPENER)
        _built[key] = js[:at] + _READ_JS % {"limit": limit, "mark": READ_MARK} + js[at:]
    return _built[key]


_NO_ARG = object()


def evaluate(target, js: str, arg=_NO_ARG, limit: Optional[int] = None):
    """target.evaluate(js, arg), with js reading no more than the limit
    (reading). An answer refused in the page is said once and raised as
    TooLarge, and anything else the page raised is raised as it was."""
    limit = DOCUMENT_BYTES if limit is None else limit
    try:
        if arg is _NO_ARG:
            return target.evaluate(reading(js, limit))
        return target.evaluate(reading(js, limit), arg)
    except Exception as e:
        text = str(e)
        if READ_MARK not in text:
            raise
        size = None
        try:
            size = int(text.split(READ_MARK, 1)[1].split(",", 1)[1].split()[0])
        except (IndexError, ValueError):
            pass
        raise refuse(size=size, limit=limit) from None


def page_said_too_large(error) -> bool:
    """Whether an error a page raised is an answer refused in it."""
    return READ_MARK in str(error)


# -- a download the browser wrote ---------------------------------------------

def save_download_as(download, out_path) -> None:
    """download.save_as(out_path), within the limit.

    The browser's own copy is measured once it has finished, and one larger
    than a document may be is never copied. Where Playwright cannot say
    where its copy is, the copy is made beside `out_path` and measured
    before it takes its place, so a file already at `out_path` is never
    written over by one that is then refused. Raises TooLarge, and
    whatever save_as raises."""
    out_path = Path(out_path)
    try:
        own = download.path()
    except Exception:
        own = None
    if own:
        check_file(own, "The download for this document")
    side = out_path.with_name(out_path.name + ".saving")
    try:
        download.save_as(str(side))
        size = size_of(side)
        if size > DOCUMENT_BYTES:
            raise refuse("The download for this document", size=size)
        os.replace(side, out_path)
    finally:
        try:
            side.unlink(missing_ok=True)
        except OSError:
            pass


def waits_for(download, page, seconds: Optional[float] = None, *, finished=None,
              partial=None, poll_ms: int = 250) -> bool:
    """Whether a download finished within `seconds`, cancelled when it did
    not or when the file it is writing grew past the limit.

    `finished(download)` answers whether it has finished, and is the record
    a listener keeps by calling download.path() in its own fiber, where a
    wait for it holds nothing else (Meijer's way since #42). `partial` is the
    file the browser writes it to while it arrives, when the app knows it.
    The wait is page.wait_for_timeout, so the listener runs meanwhile."""
    global _timed_out
    seconds = DOWNLOAD_SECONDS if seconds is None else seconds
    waited = 0
    while True:
        try:
            if finished is not None and finished(download):
                return True
        except Exception:
            pass
        if partial is not None:
            for path in (partial() if callable(partial) else partial) or ():
                if over(path):
                    refuse("The download for this document", size=size_of(path))
                    _cancel(download)
                    return False
        if waited >= seconds * 1000:
            _timed_out += 1
            log.warning("a download did not finish in %d seconds and was cancelled", seconds)
            print("  The download did not finish in %d seconds, so it was cancelled. %s"
                  % (seconds, raising("DOWNLOAD_SECONDS", "gives a download longer")))
            _cancel(download)
            return False
        try:
            page.wait_for_timeout(poll_ms)
        except Exception:
            return False
        waited += poll_ms


def _cancel(download) -> None:
    try:
        download.cancel()
    except Exception:
        pass


def partials(dl_dir) -> list:
    """The files a browser is still writing in `dl_dir`."""
    from .capture import UNFINISHED
    if not dl_dir:
        return []
    try:
        return [Path(dl_dir) / n for n in os.listdir(dl_dir)
                if n.lower().endswith(UNFINISHED)]
    except OSError:
        return []
