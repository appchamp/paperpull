"""Half of a character, made whole where a provider's text comes in.

JavaScript holds text as UTF-16, and a string cut between the two halves
of an emoji keeps one of them. Chromium shows such a half as U+FFFD, and
hands Python U+FFFD for it from evaluate, from a page's text and from an
in-page fetch (HALF OF A CHARACTER in sheets.py, measured 2026-10-16).
Text Python reads for itself keeps the half. That is a provider's JSON
read by the json module, through Response.json(), APIResponse.json() or
json.loads of a body or of text a page made with JSON.stringify, and a
PDF's text, through pypdf for the standard ToUnicode form <D83D> and
through pdfplumber for a number in a ToUnicode range (measured 2026-10-17,
pypdf 6.19.0 and pdfplumber 0.11.10).

UTF-8 has no way to write half a character, so every place an app keeps
or shows text stopped at one with UnicodeEncodeError. That was
progress.json and discovery.json, the CSV files, and print itself, which
the control panel runs with PYTHONIOENCODING=utf-8 and so strictly. A run
stopped at the first line naming the document, before anything was
written down. Windows made a file whose name held a half, and a Mac
refuses one.

So text is made whole where it comes in. Every JSON parse in an app's own
code is handed to whole_json(), and every PDF text it reads to
whole_characters, which core/tests/test_every_app_reads_text_whole.py
holds every app to. The text in memory, its record, its CSV row, its file
name and the line printed are then the same, with a half shown as U+FFFD
as the page showed it, and an order number, a key or a file name a later
run compares with what was kept is found again.

Behind that, nothing that keeps text stops at a half that came in some
other way, and everything that keeps it keeps it the same way. CsvFile
makes it whole (sheets.store_value), and so do storage.sanitize_component
for a file name and JsonStore for progress.json and discovery.json, which
also asks for a record by its key made whole, so a key holding a half
finds the record its CSV row names. Kept exactly in progress.json
instead, as an escape, a record and the row beside it disagreed, and
Rename, which finds a receipt's record by the order number its row holds,
left every such receipt's file as it was
(core/tests/test_every_app_gets_past_half_a_character.py).

A JSON file written straight from data, by atomic_write_json, writes a
half still left in it as its escape (json_escaped). That is valid JSON
that reads back as it was written, so the file is always written. It
serves a record put into a store's data straight, not by update, which
the next run reads whole, and every other file written that way. Two
halves side by side, high then low, read back as the one character they
make, as whole_characters makes them.
"""
from __future__ import annotations

import re

from .sheets import _HALF, whole_characters

__all__ = ["json_escaped", "whole_characters", "whole_json"]


def whole_json(value):
    """value, a parsed JSON answer, with every text in it made whole
    (whole_characters), a mapping's keys too, through every list, tuple and
    mapping in it. Anything else is given back as it is, and so is a value
    with no half anywhere in it, the very object, so an answer with none is
    untouched."""
    made, _changed = _whole(value)
    return made


def _whole(value):
    if isinstance(value, str):
        made = whole_characters(value)
        return made, made is not value
    if isinstance(value, dict):
        pairs = [(_whole(k), _whole(v)) for k, v in value.items()]
        if not any(k[1] or v[1] for k, v in pairs):
            return value, False
        return {k[0]: v[0] for k, v in pairs}, True
    if isinstance(value, (list, tuple)):
        items = [_whole(v) for v in value]
        if not any(changed for _made, changed in items):
            return value, False
        made = [m for m, _changed in items]
        return (made if isinstance(value, list) else tuple(made)), True
    return value, False


def _escape(match: re.Match) -> str:
    return "\\u%04x" % ord(match.group())


def json_escaped(text: str) -> str:
    """JSON text, as json.dumps(..., ensure_ascii=False) gives it, with each
    half of a character written as its escape, so UTF-8 can hold it and
    json.loads gives back the text that was dumped, except that a high half
    followed by a low one comes back as the one character they make. A
    half can only be inside a string there, where json.dumps wrote every
    backslash as two, so the escape is always read as one. Text with no
    half is given back as it is."""
    if not _HALF.search(text):
        return text
    return _HALF.sub(_escape, text)
