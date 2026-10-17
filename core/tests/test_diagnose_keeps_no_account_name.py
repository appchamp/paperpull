"""A Diagnose file keeps no account's name, even one spelled in words on the list.

A tester attached Citi's detailed Diagnose file to a public issue (#103,
spotted by appchamp) and its samples read "Citi CustomCash statement
October 9, 9999". Every digit was shaped and every word off the list too,
but Custom and Cash are on the list, so the card's product name came
through whole and said which cards the tester holds. The list is the words
a site writes for every customer, and a product's name is made of those.

So a string a page wrote, anywhere in a file built by shape_tree, keeps
only KINDS, the words that say what kind of document, when, and what part
of the page, and never a word a product, an account or a merchant is named
with. Only beneath a key of MACHINERY, an address or the field names of an
answer, does every word on the list stay.

Each app's Diagnose is tried here with an invented label, every word of it
on the list, standing in for whatever the site layer hands back. It must
not come out of what Diagnose prints, of any value Diagnose puts in its
file, or of a key a page named. Nothing here is a real value.
"""
import ast
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from paperpull_core import words as W  # noqa: E402
from paperpull_core.redact import set_private_words  # noqa: E402

import test_what_diagnose_prints_keeps_no_word_off_the_list as census  # noqa: E402

# Invented card and account names, every word of each on the list.
LABEL = "Double Cash Custom Rewards"
LABELS = (LABEL, "Custom Cash", "Double Cash Rewards", "Preferred Travel Plus",
          "Select Business Checking", "Money Market Savings", "Premium Select One")
NAME_WORD = re.compile(r"\b(double|cash|custom|rewards)\b", re.I)

APPS = census.APPS
entry_of = census.entry_of


@pytest.fixture(autouse=True)
def _no_owner():
    set_private_words([])
    yield
    set_private_words([])


def names_it(text) -> bool:
    return bool(NAME_WORD.search(str(text)))


@pytest.fixture
def labeled(monkeypatch):
    """The prints census with the label standing in for a page. A web
    address is judged by the whole list on purpose, as MACHINERY says, so
    shape_url is not what is tried here."""
    monkeypatch.setattr(census, "CANARY", LABEL)
    monkeypatch.setattr(census, "leaks", lambda text, root=None: names_it(
        str(text).replace(str(root), "<folder>") if root is not None else text))
    monkeypatch.setattr(W, "shape_url", lambda url, words=(), **_: W.Fixed("<address>"))


# -- the words a name may keep -------------------------------------------------------

def test_every_word_a_name_may_keep_is_on_the_list():
    assert W.KINDS <= W.KNOWN


@pytest.mark.parametrize("label", LABELS)
def test_the_invented_names_are_spelled_in_words_on_the_list(label):
    """Otherwise the list alone would shape them and nothing here is tried."""
    words = label.lower().split()
    assert all(w in W.KNOWN for w in words), label
    assert W.shape(label) == label
    assert not any(w in W.KINDS for w in words), label


def test_no_word_an_account_or_a_product_is_named_with_is_kept_in_a_name():
    for word in ("cash", "custom", "double", "rewards", "preferred", "select", "plus",
                 "one", "gold", "travel", "business", "premium", "home", "go", "checking",
                 "savings", "credit", "card", "cards", "loan", "brokerage", "money",
                 "market", "mile", "miles", "points", "visa", "mastercard", "secured",
                 "flex", "active", "standard", "basic", "joint", "individual", "trust",
                 "sun", "first", "single", "mortgage", "ira", "roth", "anywhere", "more",
                 "dividend", "interest", "consolidated", "banner"):
        assert word not in W.KINDS, word


@pytest.mark.parametrize("label", LABELS)
def test_a_name_leaves_as_its_shape_and_the_kind_and_date_stay(label):
    words = W.words_for("Citi")
    got = W.shape_label("Citi %s statement October 9, 2025" % label, words)
    assert not names_it(got) and not any(w in got for w in label.split()), got
    assert got.startswith("Citi ") and got.endswith(" statement October 9, 9999"), got


# -- a whole file ----------------------------------------------------------------------

def test_a_name_leaves_no_word_wherever_a_file_holds_it():
    info = {
        "samples": [{"title": LABEL, "text": "Citi %s statement" % LABEL,
                     "category": "Statement", "date": "2025-10-09"}],
        "documents_recognized": [{"account": LABEL, "kind": "statement"}],
        "documents_by_account": {LABEL + " ...1234": 3},
        "survey": {"accounts": [LABEL], "api": {LABEL: {"shape": {"statementsByYear": "list",
                                                                   LABEL: "string"}}}},
        "controls": [{"role": "button", "text": "View %s statement" % LABEL}],
        "account_options": [LABEL + " - 1234"],
        "title": "%s | Statements" % LABEL,
        "error": "waiting for locator resolved to <a>%s</a>" % LABEL,
        "a_key_added_tomorrow": LABEL,
    }
    out = W.shape_tree(info, W.words_for("Citi"))
    text = json.dumps(out)
    assert not names_it(text), text
    assert out["samples"][0]["text"] == "Citi aaaaaa aaaa aaaaaa aaaaaaa statement"
    assert out["samples"][0]["date"] == "9999-99-99"
    assert out["controls"][0] == {"role": "button",
                                  "text": "View aaaaaa aaaa aaaaaa aaaaaaa statement"}
    # The fields of an answer are the provider's, and stay whole.
    shape = out["survey"]["api"]["aaaaaa aaaa aaaaaa aaaaaaa"]["shape"]
    assert "statementsByYear" in shape


def test_an_address_and_an_answers_fields_keep_every_word_on_the_list():
    out = W.shape_tree({"landed_on": "https://online.citi.com/US/ag/statements/history",
                        "statements_api": {"fields": ["statementDate", "accountType"]},
                        "row_counts": {"table rows": 3, "pdf links": 0},
                        "note": "the API answered with no statements"},
                       W.words_for("Citi"))
    assert out["landed_on"] == "https://online.citi.com/US/aa/statements/history"
    assert out["statements_api"]["fields"] == ["statementDate", "accountType"]
    assert out["row_counts"] == {"table rows": 3, "pdf links": 0}
    assert out["note"] == "the API answered with no statements"


def test_a_string_of_ours_marked_fixed_stays_and_a_count_stays():
    out = W.shape_tree({"samples": [{"note": W.Fixed("Custom words we wrote"), "n": 3}]})
    assert out == {"samples": [{"note": "Custom words we wrote", "n": 3}]}


def test_a_file_built_from_fixed_fields_alone_keeps_the_whole_list():
    """A failure file and a recording are built from the lists field by
    field, and read the whole list throughout."""
    out = W.shape_tree({"step": "press a control", "label": "Statements and Taxes"},
                       full_list=True)
    assert out == {"step": "press a control", "label": "Statements and Taxes"}


def test_a_sample_of_an_answers_values_is_held_to_kinds_beneath_its_fields():
    """The fields of an answer keep the whole list, a sample of what they
    held does not, since a nickname is one of those values."""
    out = W.shape_tree({"statements_api": {"fields": {"accountNickname": {
        "present": 3, "distinct_sample": [LABEL, "Online Savings"]}}}})
    field = out["statements_api"]["fields"]["accountNickname"]
    assert field["present"] == 3
    assert not names_it(json.dumps(field)), field


def test_a_page_key_written_like_a_key_of_machinery_is_not_one():
    out = W.shape_tree({"Notes": LABEL, "STATUS": {"x": LABEL}})
    assert not names_it(json.dumps(out)), out


def test_a_failure_files_extra_keeps_no_name_in_a_key(tmp_path):
    """Snake case made a page's key, "Double Cash Custom Rewards", look like
    one of ours, which keeps the whole list."""
    from paperpull_core import failure
    path = failure.write_failure(tmp_path, "run", "press a control", say=lambda *_: None,
                                 extra={LABEL: 1, "verdict": "covered"})
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    assert not names_it(json.dumps(report["extra"])), report["extra"]
    assert report["extra"]["verdict"] == "covered"


def test_what_covered_a_control_names_no_card():
    from paperpull_core import pressing
    cover = pressing.described({"widget": {"tag": "div", "role": "dialog",
                                           "label": "Get the %s card" % LABEL},
                                "top": {}}, W.words_for("Citi"))
    said = " ".join(pressing.covering_lines("the Download link", cover))
    assert not names_it(said) and not names_it(json.dumps(cover)), said
    assert cover["widget"]["role"] == "dialog"


def test_no_core_file_but_the_failure_file_and_the_recording_reads_the_whole_list():
    """full_list is for a file built field by field from fixed lists."""
    users = sorted(p.name for p in (REPO / "core" / "paperpull_core").glob("*.py")
                   if "full_list=True" in p.read_text(encoding="utf-8"))
    assert users == ["failure.py", "recorder.py"], users


def test_write_shaped_holds_a_name_to_the_words_a_name_may_keep(tmp_path):
    path = tmp_path / "diagnose-documents.json"
    W.write_shaped(path, {"samples": [{"title": LABEL}]}, W.words_for("Citi"))
    assert not names_it(path.read_text(encoding="utf-8"))


# -- every app ---------------------------------------------------------------------------

@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_no_line_diagnose_prints_names_an_account(app, tmp_path, labeled):
    tree = ast.parse(entry_of(app).read_text(encoding="utf-8"))
    wrong = []
    for line, text, why in census.what_diagnose_prints(app, tree, tmp_path):
        if why:
            # The census of words off the list refuses those lines already.
            continue
        if names_it(text.replace(str(tmp_path), "<folder>")):
            wrong.append("line %d prints %r" % (line, text.replace(str(tmp_path), "<folder>")[:110]))
    assert not wrong, "%s prints an account's name in words on the list\n  %s" % (
        app.name, "\n  ".join(wrong))


def stored_values(tree):
    """Each value Diagnose stores, as (line, key, expression). A value set
    under a key, an entry of a dictionary written out, and an entry added
    to a list, under the list's key or the name it is built in."""
    for fn in census.diagnose_functions(tree):
        for node in census.own_nodes(fn):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant) \
                            and isinstance(t.slice.value, str):
                        yield node.lineno, t.slice.value, node.value
            elif isinstance(node, ast.Dict):
                for k, v in zip(node.keys, node.values):
                    if isinstance(k, ast.Constant) and isinstance(k.value, str):
                        yield node.lineno, k.value, v
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr in ("append", "extend") and node.args:
                owner = node.func.value
                if isinstance(owner, ast.Subscript) and isinstance(owner.slice, ast.Constant):
                    yield node.lineno, str(owner.slice.value), node.args[0]
                elif isinstance(owner, ast.Name):
                    yield node.lineno, owner.id, node.args[0]


def without_machinery(tree):
    """A shaped file less what sits under a key of MACHINERY."""
    if isinstance(tree, dict):
        return {k: without_machinery(v) for k, v in tree.items()
                if str(k).lower() not in W.MACHINERY}
    if isinstance(tree, list):
        return [without_machinery(v) for v in tree]
    return tree


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_no_value_diagnose_writes_names_an_account(app, tmp_path, labeled):
    """Every value Diagnose stores, tried with the label standing in for the
    page, comes out of shape_tree without a word of it. A value under a key
    of MACHINERY is an address or an answer's fields, read by the whole
    list, and the next test holds what may go there."""
    tree = ast.parse(entry_of(app).read_text(encoding="utf-8"))
    words = W.words_for(app.name, census.site_of(app))
    tried, wrong = 0, []
    for line, key, expr in stored_values(tree):
        if key.lower() in W.MACHINERY:
            continue
        fn = next(f for f in census.diagnose_functions(tree)
                  if f.lineno <= line <= f.end_lineno and expr in set(census.own_nodes(f)) | {
                      n for n in ast.walk(f)})
        try:
            value = census.Scope(app, tree, fn, tmp_path).evaluate(expr, line)
        except Exception:
            # What cannot be evaluated here is a page's whatever it is, and
            # shape_tree holds a page's string to KINDS. Only a value that
            # could be marked as ours needs trying.
            continue
        tried += 1
        out = json.dumps(without_machinery(W.shape_tree({key: value}, words)))
        if names_it(out):
            wrong.append("line %d, %s: %s" % (line, key, out[:110]))
    assert tried, "%s stores nothing Diagnose writes, so nothing was tried" % app.name
    assert not wrong, "%s writes an account's name in words on the list\n  %s" % (
        app.name, "\n  ".join(wrong))


# What a value under a key of MACHINERY is made from. An address, read
# through the app's own redaction or straight off the page, the shape of an
# answer, its fields and keys, a request's method and status, a count, or
# words of ours.
_MACHINE_MADE = re.compile(
    r"url|redact|shape|mask|persistable|status|method|path|href|headers|"
    r"query|params|^len\(|Fixed\(|\.count\(\)|route|origin|endpoint|accept|variables",
    re.I)

# The keys of an answer, sorted, and nothing of its values. sorted(d.keys())
# or sorted(str(k) for k in parsed), the name k bound by its own for.
_ONLY_KEYS = re.compile(
    r"^sorted\(\(?\{?(str\(k\)(\[:\d+\])?|k) for .*\bfor k in \w+|"
    r"^sorted\(\(?\{?(str\(k\)(\[:\d+\])?|k) for k in \w+|"
    r"^sorted\(\w+(\.\w+)*\.keys\(\)\)|^list\(\w+\.keys\(\)\)")


def machinery_values(tree, names=None):
    """Each value set under a key of MACHINERY in Diagnose, or in the site
    module's functions it calls, as (where, key, source)."""
    fns = census.diagnose_functions(tree) if names is None else [
        fn for fn in tree.body if isinstance(fn, ast.FunctionDef) and fn.name in names]
    for fn in fns:
        for node in ast.walk(fn):
            pairs = []
            if isinstance(node, ast.Dict):
                pairs = [(k.value, v) for k, v in zip(node.keys, node.values)
                         if isinstance(k, ast.Constant) and isinstance(k.value, str)]
            elif isinstance(node, ast.Assign):
                pairs = [(t.slice.value, node.value) for t in node.targets
                         if isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                         and isinstance(t.slice.value, str)]
            for key, value in pairs:
                if key.lower() in W.MACHINERY:
                    yield "%s line %d" % (fn.name, node.lineno), key, value, fn


# Read through one by one. A step and a reason a press stopped on are
# written in the app's source (failure._step holds them to that), and the
# rest are a state or a stop out of a fixed set in the site module.
_REVIEWED = frozenset((
    "stop.step", "stop.reason", "history_state(page)", "facts['why']",
    "site.goto_store_list(tab)", "site.open_trips_page(page)", "site.open_eats_page(tab)",
    "answer_kind(got)"))


def is_machine_made(value, fn=None, depth=0) -> bool:
    if ast.unparse(value) in _REVIEWED:
        return True
    return _machine_made(value, fn, depth)


def _machine_made(value, fn=None, depth=0) -> bool:
    """A constant, an empty dictionary or list filled later under its own
    key, a name in capitals the module sets, or something the regex above
    names. A local name is followed to where the function sets it."""
    if isinstance(value, ast.Constant):
        return True
    if isinstance(value, (ast.Dict, ast.List)) and not getattr(value, "keys", None) \
            and not getattr(value, "elts", None):
        return True
    if _ONLY_KEYS.search(ast.unparse(value)):
        return True
    if isinstance(value, ast.DictComp) and isinstance(value.value, ast.Dict):
        # The fields of an answer, each with counts and a sample of its
        # values, which VALUES holds to KINDS again.
        return all(isinstance(k, ast.Constant) and (k.value in W.VALUES or is_machine_made(
            v, fn, depth + 1) or isinstance(v, ast.Subscript))
            for k, v in zip(value.value.keys, value.value.values))
    if isinstance(value, ast.JoinedStr) and all(
            isinstance(v, ast.Constant) for v in value.values):
        return True
    if isinstance(value, ast.IfExp):
        return is_machine_made(value.body, fn, depth) and is_machine_made(value.orelse, fn, depth)
    if isinstance(value, ast.Name) and value.id.isupper():
        return True
    if _MACHINE_MADE.search(ast.unparse(value)):
        return True
    inner = value.value if isinstance(value, ast.Subscript) else value
    if fn is not None and depth < 3 and isinstance(inner, ast.Name):
        sets = [n.value for n in ast.walk(fn) if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == inner.id for t in n.targets)]
        return bool(sets) and all(is_machine_made(v, fn, depth + 1) for v in sets)
    return False


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_what_goes_under_a_key_of_machinery_is_an_address_or_the_fields_of_an_answer(app):
    """The whole list stays beneath those keys, so a title, a row or a label
    put there would keep its name. Held for Diagnose and for every function
    of the site module Diagnose calls."""
    tree = ast.parse(entry_of(app).read_text(encoding="utf-8"))
    called = {n.func.attr for fn in census.diagnose_functions(tree) for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and isinstance(n.func.value, ast.Name) and n.func.value.id == "site"}
    wrong = ["%s, %s = %s" % (where, key, ast.unparse(v)[:70])
             for where, key, v, fn in machinery_values(tree) if not is_machine_made(v, fn)]
    for path in sorted(app.glob("*_site.py")):
        site_tree = ast.parse(path.read_text(encoding="utf-8"))
        wrong += ["%s %s, %s = %s" % (path.name, where, key, ast.unparse(v)[:70])
                  for where, key, v, fn in machinery_values(site_tree, called)
                  if not is_machine_made(v, fn)]
    assert not wrong, "%s puts something other than an address or an answer's fields " \
        "under a key that keeps the whole list\n  %s" % (app.name, "\n  ".join(wrong))


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_no_app_writes_a_file_with_the_whole_list(app):
    """full_list is for a file built field by field from the lists, the
    failure file and the recording in the core. A provider's files hold
    what a page said, so none of them asks for it."""
    for path in [entry_of(app)] + sorted(app.glob("*_site.py")):
        assert "full_list" not in path.read_text(encoding="utf-8"), path.name


def test_the_census_catches_a_name_marked_as_ours(tmp_path, labeled):
    src = '''
import zorbank_site as site
from paperpull_core.words import Fixed, shape, shape_label, words_for, write_shaped


class Downloader:
    def cmd_diagnose(self):
        words = words_for('Zorbank', site)
        info = {"samples": []}
        for d in site.collect_documents(self.page()):
            info["samples"].append({"title": Fixed(d.title), "date": d.date})
        print(%s)
        write_shaped(self.paths.diagnostics / "diagnose-documents.json", info, words)

    def write_survey(self):
        failure.write_survey(self.paths.diagnostics, provider='Zorbank')
'''
    app = tmp_path / "zorbank"
    app.mkdir()
    tree = ast.parse(src % "shape(info['samples'][0]['title'], words)")
    values = [(key, census.Scope(app, tree, census.diagnose_functions(tree)[0], tmp_path)
               .evaluate(expr, line)) for line, key, expr in stored_values(tree)]
    assert any(names_it(json.dumps(W.shape_tree({k: v}))) for k, v in values)
    said = [text for _, text, why in census.what_diagnose_prints(app, tree, tmp_path) if not why]
    assert any(names_it(t) for t in said), said
    plain = ast.parse(src % "shape_label(info['samples'][0]['title'], words)")
    said = [text for _, text, why in census.what_diagnose_prints(app, plain, tmp_path) if not why]
    assert said and not any(names_it(t) for t in said), said
