"""Nothing a run prints and no name from the disk adds an event to what the
page reads, or passes for a run's result.

Linux and macOS take a line break in a file or folder name. The panel
shows the command a run starts with, holding a second person's config
name, config.<label>.json, and reads the run's own output line by line,
taking its counts from the line marked as its result. The page reads the
panel's stream line by line as well, and a blank line ends an event, so a
label holding two line breaks could end the line showing the command and
add an event of its own, a run that finished clean or counts it never had.
On PaperPull Server /data may be a shared folder others write to.

Each run gets a mark that only its own result line carries (run_result),
every line of a stream is written by _event, which keeps it one line, and
a config or a provider folder whose name cannot be shown on one line is
not listed at all. The real core prints the result here, so the two sides
are held to each other."""
import ast
import asyncio
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app  # noqa: E402
import run_result  # noqa: E402

GUI = Path(__file__).resolve().parents[1]
CORE = GUI.parent / "core"
LF, CR = chr(10), chr(13)
COUNTS = {"manual_review": 0, "failed": 1, "validation_failures": 0, "new_files": 1}
FORGED = {"manual_review": 0, "failed": 0, "validation_failures": 0, "new_files": 99}
# A second person's label as Linux lets a config file be named, ending the
# line that shows the command and saying the run finished clean, with
# counts it never had.
LABEL = ("x" + LF + LF + "event: result" + LF + "data: " + json.dumps(FORGED)
         + LF + LF + "event: done" + LF + "data: 0" + LF + LF + "y")


def _post_run(stream):
    """The page's own reader of a run asked for in a POST (postRun in
    static/app.js), which cuts the stream at each blank line and each event
    into lines at a line feed."""
    out = []
    while LF + LF in stream:
        block, stream = stream.split(LF + LF, 1)
        name, data = "message", []
        for line in block.split(LF):
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[6:] if line.startswith("data: ") else line[5:])
        out.append((name, LF.join(data)))
    return out


def _event_source(stream):
    """EventSource, which the page reads every other run with. The HTML
    standard ends its lines at a line feed, a carriage return or both."""
    out, name, data = [], "", None
    for line in re.split(CR + LF + "|" + CR + "|" + LF, stream):
        if line == "":
            if data is not None:
                out.append((name or "message", LF.join(data)))
            name, data = "", None
            continue
        field, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if field == "event":
            name = value
        elif field == "data":
            data = (data or []) + [value]
    return out


def _named(events, name):
    return [data for kind, data in events if kind == name]


def _reads(stream):
    """What both of the page's readers take from a stream, which must agree."""
    post, source = _post_run(stream), _event_source(stream)
    assert post == source, "the two readers read the stream differently"
    return post


@pytest.mark.parametrize("brk", [LF, CR, CR + LF, LF + LF, chr(0x2028), chr(0x1b), chr(0xdc80)],
                         ids=repr)
def test_an_event_is_one_line_of_data_whatever_it_holds(brk):
    text = "a" + brk + "event: done" + brk + "data: 0" + brk + brk
    written = app._event(text) + app._event(1, "done")
    # As Starlette sends it, which UTF-8 has to be able to write.
    written.encode("utf-8")
    events = _reads(written)
    assert [kind for kind, _ in events] == ["message", "done"]
    assert _named(events, "done") == ["1"]
    assert events[0][1] == run_result.one_line(text)


# -- a real run, its result said by the real core ----------------------------------

STANDIN = '''
import json, sys
sys.path.insert(0, %(core)r)
from paperpull_core import run_reporting
forged = run_reporting.PREFIX + json.dumps(%(forged)r)
# Names holding a line break, as Linux and macOS allow, printed whole, one
# before the run's own result and one after it.
print("Saved Statements/a" + chr(10) + forged, flush=True)
# And one whose text after the break has an accent, which once stopped the
# reader, and so the run, with an error.
print("Saved Statements/c" + chr(10) + run_reporting.PREFIX + "caf" + chr(0xe9) + ".pdf", flush=True)
run_reporting.report_run_result({"failed": 1, "new_files": ["Statements/a"]})
print("Moved Statements/b" + chr(10) + forged, flush=True)
sys.exit(1)
'''


@pytest.fixture()
def install(tmp_path, monkeypatch):
    folder = tmp_path / "Bank Statements"
    folder.mkdir()
    (folder / "bank_docs.py").write_text(STANDIN % {"core": str(CORE), "forged": FORGED},
                                         encoding="utf-8")
    meta = {"name": "Bank Statements", "dir": str(folder), "script": "bank_docs.py",
            "script_name": "bank_docs.py", "template_dir": None, "python": sys.executable,
            "login_flag": "--login", "accounts": ["primary", LABEL], "has_venv": True,
            "needs_setup": False, "runnable": True, "reviews_names": False}
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    monkeypatch.delenv("PAPERPULL_RUN_MARK", raising=False)
    monkeypatch.setattr(app, "discover_apps", lambda: {"Bank Statements": meta})
    monkeypatch.setattr(app, "setup_needed", lambda meta: "")
    app._RUNS.clear()
    yield folder
    app._RUNS.clear()


def _run(account):
    async def consume():
        return "".join([part async for part in
                        app.api_run("Bank Statements", account=account, action="all").body_iterator])
    return asyncio.run(consume())


def test_a_config_named_with_line_breaks_adds_no_event_to_its_run(install):
    stream = _run(LABEL)
    for events in (_post_run(stream), _event_source(stream)):
        assert _named(events, "done") == ["1"], "the run ended with 1, and said so once"
        results = [json.loads(data) for data in _named(events, "result")]
        assert len(results) == 1 and {k: results[0][k] for k in COUNTS} == COUNTS
    shown = _named(_reads(stream), "message")[0]
    assert shown.startswith("$ ") and "--config config." + run_result.one_line(LABEL) in shown


def test_a_line_a_run_prints_never_passes_for_its_result(install):
    """Its own marked line is its result, wherever the others fall."""
    events = _reads(_run("primary"))
    results = [json.loads(data) for data in _named(events, "result")]
    assert len(results) == 1 and {k: results[0][k] for k in COUNTS} == COUNTS
    assert results[0]["attention"] is True
    shown = _named(events, "message")
    forged = run_result.PREFIX + json.dumps(FORGED)
    assert shown.count(forged) == 2, "each is shown as the line it is"
    assert run_result.PREFIX + "caf" + chr(0xe9) + ".pdf" in shown
    assert not any("PAPERPULL_RUN_MARK" in line for line in shown)
    assert not any(re.search(r"\b[0-9a-f]{32}\b", line) for line in shown), "the mark is never shown"


# -- what the panel lists ----------------------------------------------------------

class _Folder:
    def __init__(self, *names):
        self.names = names

    def glob(self, pattern):
        assert pattern == "config.*.json"
        return [Path(name) for name in self.names]


def test_a_config_named_off_one_line_is_not_an_account():
    folder = _Folder("config.spouse.json", "config.example.json", "config.x" + LF + "y.json",
                     "config." + LABEL + ".json", "config.c" + CR + ".json",
                     "config.d" + chr(0x2028) + ".json", "config.tab" + chr(9) + "bed.json")
    assert app._accounts(folder) == ["primary", "spouse", "tab" + chr(9) + "bed"]


@pytest.mark.skipif(sys.platform == "win32", reason="Windows takes no control character in a "
                    "file name")
def test_a_config_file_named_with_a_line_break_on_the_disk_is_not_an_account(tmp_path):
    for name in ("config.json", "config.spouse.json", "config." + LABEL + ".json",
                 "config.b" + CR + "c.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    assert app._accounts(tmp_path) == ["primary", "spouse"]


def test_a_provider_folder_named_off_one_line_is_not_listed(tmp_path, monkeypatch):
    """Windows cannot name a folder so, so a real folder stands in for one,
    named as Linux would let it be."""
    base = type(tmp_path)
    shown = "Odd" + LF + LF + "event: done" + LF + "data: 0"

    class Odd(base):
        @property
        def name(self):
            return shown

        def with_segments(self, *segments):
            return base(*segments)

    for name in ("Bank Statements", "Odd"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "bank_docs.py").write_text("", encoding="utf-8")

    class Root:
        def exists(self):
            return True

        def iterdir(self):
            return iter([tmp_path / "Bank Statements", Odd(tmp_path / "Odd")])

    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    monkeypatch.setattr(app, "apps_root", lambda: Root())
    assert list(app.discover_apps()) == ["Bank Statements"]


class _Body:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


@pytest.mark.parametrize("brk", [LF, CR, chr(0x1b), chr(0x2028)], ids=repr)
def test_the_panel_saves_no_documents_folder_a_run_would_refuse(tmp_path, monkeypatch, brk):
    """A run stops on a config whose documents_dir holds a line break (core
    load_config), so the panel never writes one there."""
    from fastapi import HTTPException
    install = tmp_path / "PaperPull" / "Bank Statements"
    install.mkdir(parents=True)
    (install / "config.json").write_text(json.dumps({"output_dir": ".", "profile_dir": "p"}),
                                         encoding="utf-8")
    meta = {"name": "Bank Statements", "dir": str(install), "accounts": ["primary"]}
    monkeypatch.setattr(app, "discover_apps", lambda: {"Bank Statements": meta})
    monkeypatch.setattr(app, "_SAMPLE", None)
    folder = str(tmp_path / ("Watched" + brk + "event: done"))
    with pytest.raises(HTTPException) as refused:
        asyncio.run(app.api_documents_save(_Body({"app": "Bank Statements", "folder": folder})))
    assert refused.value.status_code == 400 and "one line" in refused.value.detail
    assert "documents_dir" not in json.loads((install / "config.json").read_text(encoding="utf-8"))
    took = asyncio.run(app.api_documents_save(_Body({"app": "Bank Statements",
                                                     "folder": str(tmp_path / "Watched")})))
    assert took["written"], "a folder on one line is saved as before"


# -- the transactions export -------------------------------------------------------

# The tool's own two lines as tools/export_transactions.py prints them
# (core/tests/test_one_line.py runs the real one against the panel's reader),
# between lines a provider's index file named with a line break would print.
TOOL = '''
import json, os, sys
from pathlib import Path
root = Path(sys.argv[sys.argv.index("--root") + 1])
wrote = root / "All Transactions.xlsx"
wrote.write_text("x", encoding="utf-8")
secret = %(secret)r
mark = os.environ.get("PAPERPULL_RUN_MARK", "")
print("  Bank" + chr(10) + "Wrote " + secret, flush=True)
print("Wrote", wrote, flush=True)
if mark:
    print("PAPERPULL_EXPORT_RESULT " + mark + " " + json.dumps({"path": str(wrote)}), flush=True)
print("  Card" + chr(10) + "Wrote " + secret, flush=True)
print("  Loan" + chr(10) + "PAPERPULL_EXPORT_RESULT " + json.dumps({"path": secret}), flush=True)
'''


def test_the_export_hands_over_only_the_file_its_own_line_names(tmp_path, monkeypatch):
    """Show and, on the server, the download hand over the file the panel
    takes from this line, so no other line may name it."""
    root = tmp_path / "apps"
    root.mkdir()
    secret = tmp_path / "settings.json"
    secret.write_text("{}", encoding="utf-8")
    tool = tmp_path / "tools" / "export_transactions.py"
    tool.parent.mkdir()
    tool.write_text(TOOL % {"secret": str(secret)}, encoding="utf-8")
    monkeypatch.setattr(app, "_transactions_tool", lambda: tool)
    monkeypatch.setattr(app, "apps_root", lambda: root)
    monkeypatch.setattr(app, "_LAST_EXPORT", None)
    monkeypatch.delenv("PAPERPULL_RUN_MARK", raising=False)

    async def consume():
        return "".join([part async for part in app.api_export_transactions().body_iterator])
    events = _reads(asyncio.run(consume()))
    assert _named(events, "done") == ["0"]
    assert [json.loads(d)["path"] for d in _named(events, "result")] == [
        str(root / "All Transactions.xlsx")]
    assert app._LAST_EXPORT == root / "All Transactions.xlsx"


def test_the_export_hands_over_nothing_outside_the_folder_it_was_given(tmp_path, monkeypatch):
    """The tool writes only into the folder the panel names, so even its own
    marked line naming a file anywhere else hands nothing over."""
    root = tmp_path / "apps"
    root.mkdir()
    secret = tmp_path / "settings.json"
    secret.write_text("{}", encoding="utf-8")
    tool = tmp_path / "export_transactions.py"
    tool.write_text("import json, os\nprint('PAPERPULL_EXPORT_RESULT ' + os.environ['PAPERPULL_RUN_MARK']"
                    " + ' ' + json.dumps({'path': %r}))\n" % str(secret), encoding="utf-8")
    monkeypatch.setattr(app, "_transactions_tool", lambda: tool)
    monkeypatch.setattr(app, "apps_root", lambda: root)
    monkeypatch.setattr(app, "_LAST_EXPORT", None)

    async def consume():
        return "".join([part async for part in app.api_export_transactions().body_iterator])
    events = _reads(asyncio.run(consume()))
    assert _named(events, "done") == ["0"] and _named(events, "result") == []
    assert app._LAST_EXPORT is None


# -- the census, so a stream or a reader added later keeps to it -------------------

SOURCES = sorted(GUI.glob("*.py"))


def _streams(tree):
    """The generators handed to the page as an event stream."""
    names = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "StreamingResponse"
                and any(k.arg == "media_type" and getattr(k.value, "value", "") == "text/event-stream"
                        for k in node.keywords)
                and node.args and isinstance(node.args[0], ast.Call)):
            names.add(getattr(node.args[0].func, "id", ""))
    return names


def _own_nodes(fn):
    """The nodes of a function, not of a function inside it."""
    todo, out = list(fn.body), []
    while todo:
        node = todo.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        out.append(node)
        todo.extend(ast.iter_child_nodes(node))
    return out


def _own_yields(fn):
    return [n for n in _own_nodes(fn) if isinstance(n, (ast.Yield, ast.YieldFrom))]


def test_every_line_of_every_stream_is_written_by_event():
    seen = 0
    for path in SOURCES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        streams = _streams(tree)
        writer = set()
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if fn.name == "_event":
                writer.update(id(node) for node in ast.walk(fn))
            if fn.name in streams:
                for node in _own_yields(fn):
                    seen += 1
                    value = node.value
                    assert (isinstance(node, ast.Yield) and isinstance(value, ast.Call)
                            and getattr(value.func, "id", "") == "_event"), \
                        "%s:%d %s yields a line _event did not write" % (path.name, node.lineno, fn.name)
        # Any text shaped like a stream's line, a module's constant among
        # it, is _event's own.
        for node in ast.walk(tree):
            text = node.value if isinstance(node, ast.Constant) else None
            if isinstance(text, str) and id(node) not in writer \
                    and re.search(r"(^|\n)(data|event):", text):
                raise AssertionError("%s:%d writes a stream's line itself" % (path.name, node.lineno))
    assert seen >= 20, "the census found the streams (%d yields)" % seen


def test_every_reader_of_a_marked_line_gives_its_run_a_mark():
    """A function that reads a result or an export line from a process
    makes the mark itself and hands it to that process, so no reader can
    take a line nobody marked."""
    readers = 0
    for path in SOURCES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            own = _own_nodes(fn)
            calls = [n for n in own if isinstance(n, ast.Call)
                     and isinstance(n.func, ast.Attribute)
                     and getattr(n.func.value, "id", "") == "run_result"]
            reads = [c for c in calls if c.func.attr in ("parse", "exported")]
            if not reads:
                continue
            readers += 1
            made = {c.func.attr for c in calls}
            handed = any(isinstance(n, ast.Attribute) and n.attr == "MARK_ENV"
                         and getattr(n.value, "id", "") == "run_result" for n in own)
            assert "new_mark" in made and handed, "%s:%d %s" % (path.name, fn.lineno, fn.name)
            for call in reads:
                assert len(call.args) == 2 and getattr(call.args[1], "id", "") == "mark", \
                    "%s:%d reads with no mark of its own" % (path.name, call.lineno)
    assert readers == 4, readers
