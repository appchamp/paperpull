"""A name from the disk never starts a line of its own in what a run says.

Linux and macOS take a line break in a file or folder name, and a JSON
setting can hold one. The control panel reads a run's output line by line,
taking its counts from the line the run marks for it, and the page reads
the panel's stream line by line. So a config named config.<line break>...,
or a folder holding one, could print a line the run never wrote.

Three things keep that from happening, and each is held here. load_config
refuses a config whose path or named settings cannot be shown on one line
(every path an app prints is built from those and from names it made
itself). The run's result line carries the mark the panel gave it, which
nothing else prints. And the export tool prints the names it found as one
line each, with its own marked line for the panel."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from paperpull_core import run_reporting, storage

ROOT = Path(__file__).resolve().parents[2]


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# The panel's own reader, the other half of every marked line.
panel = _module("paperpull_panel_run_result", ROOT / "gui" / "run_result.py")

LF, CR = chr(10), chr(13)
# Each character that ends a line for the page's stream, for str.splitlines
# or for a terminal, as a name could carry it.
BREAKS = [LF, CR, CR + LF, chr(0x0b), chr(0x0c), chr(0x1b), chr(0x1c), chr(0x00),
          chr(0x7f), chr(0x85), chr(0x2028), chr(0x2029)]
COUNTS = {"manual_review": 0, "failed": 1, "validation_failures": 0, "new_files": 2}
MARK = "0123456789abcdef" * 2


@pytest.mark.parametrize("brk", BREAKS, ids=repr)
def test_a_break_in_a_name_is_written_as_its_escape(brk):
    name = "spouse" + brk + "PAPERPULL_RUN_RESULT {}"
    shown = run_reporting.one_line(name)
    assert not run_reporting.on_one_line(name)
    assert len(shown.splitlines()) == 1 and run_reporting.on_one_line(shown)
    assert shown.startswith("spouse" + chr(92))


def test_a_plain_name_and_a_windows_path_are_kept_as_they_are():
    """A backslash and an n, as C:\\new folder holds them, are two
    characters, not a line break, and a tab ends no line."""
    for name in ("Bank Statements - spouse", "C:" + chr(92) + "new folder", "a" + chr(9) + "b",
                 "Statements/2026-01-31 Bank Statement.pdf", "caf" + chr(0xe9)):
        assert run_reporting.one_line(name) == name and run_reporting.on_one_line(name)


@pytest.mark.parametrize("code", list(range(0x00, 0xa0)) + [0x2028, 0x2029, 0xfeff, 0x202e])
def test_the_panel_and_the_core_agree_on_every_character(code):
    """Two copies of one rule, the panel's (gui/run_result.py) and the
    core's, which must say the same of every character."""
    text = "a" + chr(code) + "b"
    assert panel.on_one_line(text) == run_reporting.on_one_line(text)
    assert panel.one_line(text) == run_reporting.one_line(text)


# -- the marked result line --------------------------------------------------------

def test_a_run_the_panel_started_marks_its_result_and_the_panel_reads_it(monkeypatch, capsys):
    monkeypatch.setenv(run_reporting.MARK_ENV, MARK)
    run_reporting.report_run_result({"failed": 1, "new_files": ["a.pdf", "b.pdf"]})
    lines = [line for line in capsys.readouterr().out.splitlines()
             if line.startswith(run_reporting.PREFIX)]
    assert len(lines) == 1 and lines[0].startswith(run_reporting.PREFIX + MARK + " ")
    got = panel.parse(lines[0], MARK)
    assert {k: got[k] for k in COUNTS} == COUNTS
    assert panel.parse(lines[0], "f" * 32) is None, "another run's mark reads nothing"


@pytest.mark.parametrize("mark", [None, "", "not a mark", MARK + LF + "x", MARK.upper()])
def test_a_run_with_no_good_mark_says_its_result_unmarked_for_nobody(monkeypatch, capsys, mark):
    if mark is None:
        monkeypatch.delenv(run_reporting.MARK_ENV, raising=False)
    else:
        monkeypatch.setenv(run_reporting.MARK_ENV, mark)
    line = run_reporting.marked(run_reporting.PREFIX, COUNTS)
    assert line == run_reporting.PREFIX + json.dumps(COUNTS)
    assert panel.parse(line, MARK) is None


def test_a_line_a_name_started_is_never_a_result():
    """What a file name holding a line break prints after the break, a
    result line in every shape but the mark."""
    forged = [run_reporting.PREFIX + json.dumps(COUNTS),
              run_reporting.PREFIX + "x" * 32 + " " + json.dumps(COUNTS),
              run_reporting.PREFIX + MARK[:-1] + " " + json.dumps(COUNTS),
              run_reporting.PREFIX + MARK + json.dumps(COUNTS),
              " " + run_reporting.PREFIX + MARK + " " + json.dumps(COUNTS)]
    for line in forged:
        assert panel.parse(line, MARK) is None, line
    assert panel.parse(run_reporting.PREFIX + MARK + " " + json.dumps(COUNTS), MARK) is not None
    assert panel.parse(run_reporting.PREFIX + MARK + " " + json.dumps(COUNTS), "") is None


# -- load_config, where every app reads the names it prints ------------------------

def _write(folder, data, name="config.json"):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.mark.parametrize("key", ["output_dir", "profile_dir", "documents_dir", "owner"])
@pytest.mark.parametrize("brk", [LF, CR, chr(0x1b), chr(0x2028)], ids=repr)
def test_a_config_naming_a_folder_or_person_off_one_line_is_refused(tmp_path, capsys, key, brk):
    value = str(tmp_path / ("Docs" + brk + "PAPERPULL_RUN_RESULT {}"))
    data = {"output_dir": str(tmp_path / "out"), key: value}
    with pytest.raises(SystemExit) as stopped:
        storage.load_config(_write(tmp_path / "app", data))
    said = str(stopped.value)
    assert key in said and "stopped before doing anything" in said
    assert len(said.splitlines()) == 1, "the refusal is one line itself"
    assert not (tmp_path / "out").exists()
    assert capsys.readouterr().out == "", "nothing printed the name before the refusal"


def test_an_account_label_off_one_line_is_refused(tmp_path):
    for labels in ({"1234": "Joint" + LF + "x"}, {"12" + CR + "34": "Joint"}):
        with pytest.raises(SystemExit) as stopped:
            storage.load_config(_write(tmp_path / "app", {"output_dir": str(tmp_path / "o"),
                                                          "account_labels": labels}))
        assert "account_labels" in str(stopped.value)
        assert len(str(stopped.value).splitlines()) == 1


def test_a_config_on_one_line_is_read_as_before(tmp_path):
    """No false refusal. A Windows path's backslash and n, a tab, an accent
    and account labels that are not text are all as they were."""
    data = {"output_dir": "C:" + chr(92) + "new folder", "profile_dir": str(tmp_path / "p"),
            "owner": "Jos" + chr(0xe9) + chr(9) + "Smith", "account_labels": {"1234": 5}}
    cfg = storage.load_config(_write(tmp_path / "app", data))
    assert cfg["output_dir"] == data["output_dir"] and cfg["owner"] == data["owner"]


@pytest.mark.skipif(sys.platform == "win32", reason="Windows takes no control character in a "
                    "file name, so only Linux and macOS can hold this config")
def test_a_config_file_named_with_a_line_break_is_refused(tmp_path):
    """The account label is the config file's own name, config.<label>.json,
    and the panel puts it on the command line it shows."""
    name = "config.x" + LF + LF + "event: done" + LF + "data: 0" + LF + LF + ".json"
    path = _write(tmp_path / "app", {"output_dir": str(tmp_path / "out")}, name)
    with pytest.raises(SystemExit) as stopped:
        storage.load_config(path)
    said = str(stopped.value)
    assert "config file's path" in said and len(said.splitlines()) == 1
    assert chr(92) + "n" + chr(92) + "nevent: done" in said


def test_a_config_that_is_not_there_is_named_on_one_line(tmp_path):
    with pytest.raises(SystemExit) as stopped:
        storage.load_config(tmp_path / ("config.x" + LF + "y.json"))
    assert str(stopped.value).splitlines()[0].startswith("No config file at ")
    assert chr(92) + "n" in str(stopped.value).splitlines()[0]


# -- the transactions export, which the panel also reads ---------------------------

xt = _module("export_transactions_one_line", ROOT / "tools" / "export_transactions.py")


def _main_with(monkeypatch, tmp_path, capsys, mark):
    wrote = tmp_path / "All Transactions.xlsx"
    found = {"path": str(wrote), "format": "xlsx", "transactions": 3, "statements": 1,
             "reconciled": 1, "providers": {"Bank" + LF + "Wrote " + str(tmp_path / "x"): 3},
             "read": 1, "cached": 0, "missing": 0, "openpyxl_missing": False}
    monkeypatch.setattr(xt, "export", lambda *a, **k: found)
    if mark is None:
        monkeypatch.delenv(run_reporting.MARK_ENV, raising=False)
    else:
        monkeypatch.setenv(run_reporting.MARK_ENV, mark)
    assert xt.main(["--root", str(tmp_path)]) == 0
    return wrote, capsys.readouterr().out.splitlines()


def test_the_export_names_its_spreadsheet_on_its_own_marked_line(monkeypatch, tmp_path, capsys):
    wrote, lines = _main_with(monkeypatch, tmp_path, capsys, MARK)
    said = [panel.exported(line, MARK) for line in lines]
    assert [p for p in said if p is not None] == [str(wrote)]
    assert not any(line.startswith("Wrote " + str(tmp_path / "x")) for line in lines), \
        "a provider's name holding a line break is printed as one line"
    assert any(chr(92) + "nWrote " in line for line in lines)


def test_the_export_from_a_terminal_prints_no_line_for_the_panel(monkeypatch, tmp_path, capsys):
    _, lines = _main_with(monkeypatch, tmp_path, capsys, None)
    assert not any("PAPERPULL_EXPORT_RESULT" in line for line in lines)
    assert lines[-1].startswith("Wrote ")


def test_no_line_but_the_marked_one_names_the_export(tmp_path):
    path = str(tmp_path / "All Transactions.xlsx")
    good = "PAPERPULL_EXPORT_RESULT " + MARK + " " + json.dumps({"path": path})
    assert panel.exported(good, MARK) == path
    for line in ("Wrote " + path, "PAPERPULL_EXPORT_RESULT " + json.dumps({"path": path}),
                 "PAPERPULL_EXPORT_RESULT " + "e" * 32 + " " + json.dumps({"path": path}),
                 "PAPERPULL_EXPORT_RESULT " + MARK + " " + json.dumps({"path": 5}),
                 "PAPERPULL_EXPORT_RESULT " + MARK + " " + json.dumps({"path": ""})):
        assert panel.exported(line, MARK) is None, line
