"""Every app gets past half of a character in what it writes down, and
finds it all again.

A provider's JSON can hold half of an emoji, a string cut between the two
halves JavaScript keeps it as, and Python's json module reads that half
back as itself. Every app now makes such text whole where it reads it
(paperpull_core.characters, held by test_every_app_reads_text_whole.py).
This is what stands behind that, a half that reached an app's record step
some other way. Up to now progress.json was written as UTF-8 and stopped
there with UnicodeEncodeError, so nothing was written down, and a file
name kept the half, which a Mac refuses.

Each app here is built as it is at home, from its own code, the way
test_every_app_keeps_its_csv_text_as_text.py builds it. Two documents or
two purchases are written down by the app's own code, with half of a
character in the summary, in each title and in each order number, under a
pattern that names each file by its summary and its number. Then

  - nothing stopped, and progress.json and discovery.json hold U+FFFD for
    each half, as the CSV files do and as the browser shows it, and read
    back as what the app holds,
  - the app built again, as a second run builds it, finds each record by
    the key its own model gives, half and all,
  - no file name and no CSV value holds a half, and each holds U+FFFD,
  - a receipt app's own check whether its history already has an order
    (not_shown.written_down) finds each order by its number,
  - and the app's own Rename moves both files to another pattern and back,
    and a preview after that says every file is already named as the app
    names it.
"""
import csv
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from paperpull_core import not_shown
from paperpull_core.characters import whole_characters

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_every_app_renames_each_file_for_its_own_record as census  # noqa: E402

APPS, IDS = census.APPS, census.IDS

HIGH, LOW, MARK = chr(0xD83D), chr(0xDE00), chr(0xFFFD)
HALVES = "[%s-%s]" % (chr(0xD800), chr(0xDFFF))
# A summary cut after the first half of an emoji, as a provider's own cut
# leaves one, and one more in the middle.
SUMMARY = "Gift " + LOW + " Card " + HIGH
TITLES = ("Statement " + HIGH + " - September 12, 2026",
          "Statement " + LOW + "A - September 12, 2026")
NUMBERS = ("A1111" + HIGH, LOW + "B2222")
BODIES = (census.body_of("1111"), census.body_of("2222"))
BY_NUMBER = "{summary} {date:yyyy-mm-dd}[ {account}][ {number}]"
DATE_FIRST = "{date:yyyy-mm-dd} {summary}[ {account}][ {number}]"


@pytest.fixture
def home(request, tmp_path, monkeypatch, capsys):
    return census.Home(request.param, tmp_path, monkeypatch, capsys)


def has_half(text: str) -> bool:
    return any(0xD800 <= ord(c) <= 0xDFFF for c in text)


def written_down(home) -> dict:
    """Two documents or two purchases written down by the app's own code,
    saved under BY_NUMBER, and each one's key."""
    home.set_pattern(BY_NUMBER)
    app = home.build()
    keys = []
    if hasattr(home.mod, "Document"):
        docs = census.two_documents(home, titles=TITLES, summary=SUMMARY)
        assert docs, "%s holds only one of two documents" % home.app.name
        for doc in docs:
            census.downloaded(app, doc)
            keys.append(doc.key)
    else:
        kind = next(k for k in (census.ONLINE, census.IN_STORE) if census.routes(app, k))
        for number, body in zip(NUMBERS, BODIES):
            census.purchased(home, app, number, body=body, summary=SUMMARY)
            keys.append(home.mod.Purchase(purchase_type=kind, order_number=number).key)
    census.saved(app)
    return {"app": app, "keys": keys}


def held_whole(home, app) -> None:
    """Both JSON files are UTF-8, hold U+FFFD where each half was and no
    half, not even as an escape, and read back as what the app holds."""
    for store in (app.progress, app.discovery):
        text = Path(store.path).read_bytes().decode("utf-8")
        assert json.loads(text) == store.data, (home.app.name, store.path)
        assert MARK in text, (home.app.name, store.path)
        assert not has_half(json.dumps(store.data, ensure_ascii=False)), (home.app.name, store.path)
        assert not re.search(r"\\u[dD][89abAB]", text), (home.app.name, store.path)


def no_name_holds_a_half(home) -> None:
    files = home.files()
    assert sorted(files) == sorted(BODIES), home.app.name
    for path in files.values():
        assert not has_half(str(path)), (home.app.name, ascii(str(path)))
        assert path.name.startswith(whole_characters(SUMMARY)), (home.app.name, ascii(path.name))


def csv_holds_the_mark(home, app) -> None:
    for ledger in (getattr(app, "index_csv", None), getattr(app, "order_csv", None)):
        if ledger is None:
            continue
        with open(ledger.path, encoding="utf-8-sig", newline="", errors="strict") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) >= 2, (home.app.name, ledger.path)
        for row in ledger.read_all():
            assert not any(has_half(v or "") for v in row.values()), (home.app.name, row)
            for column in ("Document Summary", "Purchase Summary"):
                if column in row:
                    assert row[column] == whole_characters(SUMMARY), (home.app.name, row[column])


def found_again(home, keys) -> None:
    """The app built again, as a second run builds it, finds each record
    by the key its own model gives, which still holds the half."""
    app = home.build()
    for key in keys:
        rec = app.progress.get(key)
        assert rec and rec.get("pdf_path"), (home.app.name, ascii(key))
        assert Path(rec["pdf_path"]).is_file(), (home.app.name, ascii(rec["pdf_path"]))
        assert app.discovery.get(key) is not None, (home.app.name, ascii(key))


def test_there_are_apps_to_check():
    assert len(APPS) >= 75, IDS


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_every_app_writes_half_a_character_down_and_finds_it_again(home):
    got = written_down(home)
    app = got["app"]
    held_whole(home, app)
    no_name_holds_a_half(home)
    csv_holds_the_mark(home, app)
    found_again(home, got["keys"])
    if not hasattr(home.mod, "Document"):
        history = app.order_csv.read_all()
        assert {r["Order or Receipt Number"] for r in history} == {
            whole_characters(n) for n in NUMBERS}
        for number in NUMBERS:
            purchase = SimpleNamespace(order_number=number,
                                       purchase_type=history[0]["Purchase Type"])
            assert not_shown.written_down(app, purchase), (home.app.name, ascii(number))


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_every_app_renames_files_named_with_half_a_character_both_ways(home):
    written_down(home)
    home.set_pattern(DATE_FIRST)
    said = home.rename("--apply")
    assert census.RENAMED_BOTH in said, said[-1500:]
    names = [p.name for p in home.files().values()]
    assert all(n.startswith(census.DATE) for n in names), (home.app.name, ascii(names))
    home.set_pattern(BY_NUMBER)
    said = home.rename("--apply")
    assert census.RENAMED_BOTH in said, said[-1500:]
    said = home.rename()
    assert census.NAMED_ALREADY in said, said[-1500:]
    files = home.files()
    assert sorted(files) == sorted(BODIES), home.app.name
    app = home.build()
    rows = app.index_csv.read_all()
    for path in files.values():
        assert not has_half(str(path)), (home.app.name, ascii(str(path)))
        mine = [r for r in rows if Path(r["PDF Full Path"]) == path]
        assert mine and all(r["PDF Filename"] == path.name for r in mine), (
            "%s's index does not name %s\n%s" % (home.app.name, ascii(path.name), said[-1500:]))
    assert home.browser.asked == 0, "Rename reached for a browser"
