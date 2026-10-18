"""Diagnose writes its survey even when it stops before the page it looks for.

Wells Fargo's Diagnose, run on the accounts summary, could not open
Statements & Documents, and the pressing.Stop that said so left
cmd_diagnose before it wrote its file and left main() before the survey it
writes after cmd_diagnose. pressing.stop_run wrote nothing for Diagnose by
design, since Diagnose downloads nothing, so the one command a tester is
asked to run to name a page's controls wrote no file at all (#27).

Each app that stops through pressing.stop_run is run here with a made-up
config and no browser, with Diagnose stopping the moment it reaches for
the page. The survey has to be there, a paperpull-survey file, and the
stop's own words said. Every word here is made up.
"""
import importlib
import json
import sys
from pathlib import Path

import pytest

from paperpull_core import failure, pressing

REPO = Path(__file__).resolve().parents[2]


def entry_of(app: Path):
    found = sorted(app.glob("*_docs.py")) + sorted(app.glob("*_receipts.py"))
    return found[0] if found else None


APPS = sorted(d for d in (REPO / "apps").iterdir()
              if d.is_dir() and not d.name.startswith(("_", ".")) and entry_of(d)
              and "pressing.stop_run(app, " in entry_of(d).read_text(encoding="utf-8"))


def load(app: Path):
    for name in [m for m in list(sys.modules)
                 if m.endswith(("_docs", "_receipts", "_site")) or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(app))
    try:
        return importlib.import_module(entry_of(app).stem)
    finally:
        sys.path.pop(0)


def test_the_apps_that_stop_through_stop_run_are_here():
    """Not vacuous. Wells Fargo, whose Diagnose stopped this way, and the
    apps whose goto stops at a page it cannot open."""
    assert {d.name for d in APPS} >= {"wellsfargo", "amex", "vanguard", "sdge", "spectrum",
                                      "venmo", "irs", "alpaca"}


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_a_diagnose_that_stops_still_writes_its_survey(app, tmp_path, monkeypatch, capsys):
    mod = load(app)
    example = app / "config.example.json"
    config = json.loads(example.read_text(encoding="utf-8")) if example.exists() else {}
    config.update({"owner": "Dana Example", "output_dir": str(tmp_path / "out"),
                   "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
                   "delay_min_seconds": 0, "delay_max_seconds": 0})
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    import playwright.sync_api as sync_api

    def no_browser(*_args, **_kwargs):
        raise AssertionError("nothing here starts a browser")
    monkeypatch.setattr(sync_api, "sync_playwright", no_browser)
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: (_ for _ in ()).throw(EOFError()))

    def stops_at_the_page(self, *_args, **_kwargs):
        raise pressing.Stop(
            "open the statements page", "the page has no statements and documents link",
            ["The run could not open the statements page from the page the window shows."])
    monkeypatch.setattr(mod.App, "page", stops_at_the_page)
    capsys.readouterr()
    with pytest.raises(SystemExit) as ended:
        mod.main(["--config", str(cfg), "--diagnose"])
    said = " ".join(capsys.readouterr().out.split())
    assert ended.value.code in (0, None), said[-1500:]
    assert "!! The run could not open the statements page" in said, said[-1500:]
    written = sorted((tmp_path / "out").rglob("survey-diagnose-*.json"))
    assert len(written) == 1, sorted(p.name for p in (tmp_path / "out").rglob("*"))
    report = json.loads(written[0].read_text(encoding="utf-8"))
    assert report["kind"] == "paperpull-survey"
    assert not sorted((tmp_path / "out").rglob("failure-*.json")), \
        "Diagnose downloads nothing and writes no failure file"


def test_stop_run_hands_the_stop_to_a_survey_that_takes_it(tmp_path):
    """An app whose write_survey takes `stopped` has the survey say why
    Diagnose stopped, in the stop's own words, which are the app's."""
    class Run:
        stats = {"mode": "diagnose"}
        progress = type("P", (), {"save": lambda self, **k: None})()

        def write_survey(self, stopped=None):
            failure.write_survey(tmp_path, provider="Testco", stopped=stopped,
                                 say=lambda *_a: None)

        def write_failure(self, *a, **k):
            raise AssertionError("Diagnose writes no failure file")

    stop = pressing.Stop("open the statements page",
                         "the page has no statements and documents link",
                         ["Could not open it."], {"menu_pressed": False, "hidden": 2})
    with pytest.raises(SystemExit):
        pressing.stop_run(Run(), stop)
    (path,) = sorted(tmp_path.glob("survey-diagnose-*.json"))
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["extra"]["stopped"] == {
        "step": "open the statements page",
        "reason": "the page has no statements and documents link",
        "facts": {"menu_pressed": False, "hidden": 2}}
