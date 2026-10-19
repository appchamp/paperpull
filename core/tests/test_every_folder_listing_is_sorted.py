"""Every folder listing comes in name order, or its order reaches nothing.

A folder's listing comes back in whatever order the filesystem keeps. NTFS
keeps names in order, which is why nothing on Windows noticed, and APFS on
a Mac does not. The panel's refresh reported the files it replaced in the
order rglob gave them, and on a Mac
test_an_upgrade_refreshes_the_code_in_an_existing_install got the right
files in another order (#111).

This reads every file that ships to a person, the panel, the core, every
app, paperpull.py and the tools the panel runs, and finds each call that
lists a folder (rglob, glob, iglob, iterdir, listdir, scandir and walk). A
call passes when its order cannot leak, which is when it goes into
sorted(), set(), frozenset(), len(), any(), all() or sum(), or into a set
comprehension, or into a comprehension or generator that goes into one of
those, directly or through list() or tuple(). Every other call is named in
ORDER_REACHES_NOTHING with the reason, so a new one is looked at before it
ships. min(), max() and next() keep the first of several equal, so they do
not pass on their own. gui/tests/test_new_user.py lists a folder backwards
to show the refresh keeps name order whatever the filesystem does.
"""
import ast
import functools
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

LISTS_A_FOLDER = {"rglob", "glob", "iglob", "iterdir", "listdir", "scandir", "walk"}
TAKES_NO_ORDER = {"sorted", "set", "frozenset", "len", "any", "all", "sum"}
# Passed through as they are, so what takes them decides.
KEEPS_THE_ORDER = {"list", "tuple", "iter", "reversed"}

# The tools the panel runs, as server/build.py names them for the image.
PANEL_TOOLS = ("add_account.py", "status.py", "export_purchases.py",
               "export_transactions.py", "make_sample.py", "migrate.py")

# (file, function, call) -> why the order of what it lists reaches nothing.
ORDER_REACHES_NOTHING = {
    ("gui/app.py", "_looks_like_installs", "root.iterdir()"):
        "counts the installs",
    ("gui/app.py", "_server_template_for", "root.iterdir()"):
        "takes a template only when exactly one matches",
    ("gui/app.py", "create_install", "src.rglob('*')"):
        "copies every file the template ships, and nothing reports the order",
    ("gui/app.py", "ensure_core", "venv.rglob('paperpull_core/__init__.py')"):
        "takes the core copy in a venv, which holds one, and stops at the first "
        "rather than walking the whole venv",
    ("gui/app.py", "refresh_installs", "tmpl_root.iterdir()"):
        "maps each entry script's name to its template, and no two templates "
        "share one (test_no_two_apps_share_an_entry_script)",
    ("gui/app.py", "_set_aside", "os.walk(inside)"):
        "sorts the folders in place and the files as it goes",
    ("gui/app.py", "_removal_summary", "folder.rglob('*.pdf')"):
        "counts the PDFs",
    ("core/paperpull_core/browser.py", "_bundled_chromium", "glob.glob(str(root / pattern))"):
        "sorted by build number before it is returned",
    ("core/paperpull_core/capture.py", "snapshot", "os.listdir(dl_dir)"):
        "a Snapshot is a set of names",
    ("core/paperpull_core/capture.py", "clear_archived_copies", "folder.iterdir()"):
        "removes exact copies and counts what is left",
    ("core/paperpull_core/intake.py", "partials", "os.listdir(dl_dir)"):
        "files still being written, and any one too big refuses the download",
    ("core/paperpull_core/shared_folder.py", "first_link_out.look", "os.scandir(folder)"):
        "any one link out is reason to refuse, and the first met is named",
    ("core/paperpull_core/storage.py", "JsonStore._recover_from_backup",
     "Path(self.backups_dir).glob(f'{self.path.stem}.*.bak')"):
        "sorted newest first before any is read",
    ("apps/bilt/bilt_site.py", "_same_file_in", "folder.iterdir()"):
        "asks whether any file holds these bytes",
    ("apps/spectrum/spectrum_site.py", "_same_file_in", "folder.iterdir()"):
        "asks whether any file holds these bytes",
    ("apps/spectrum/spectrum_site.py", "_entries", "Path(dl_dir).iterdir()"):
        "a snapshot looked up by name",
    ("apps/newrez/newrez_site.py", "_unfinished", "os.listdir(dl_dir)"):
        "sizes looked up by name, and counted",
    ("apps/simmons/simmons_site.py", "empty_download_folder", "os.listdir(folder)"):
        "removes them all and says how many",
    ("apps/statefarm/statefarm_site.py", "_unfinished_downloads", "os.listdir(dl_dir)"):
        "counts the files still being written",
    ("tools/add_account.py", "ports_in_use", "Path(app_dir).glob('config*.json')"):
        "collects ports into a set",
    ("tools/make_sample.py", "build", "out.rglob('*.pdf')"):
        "counts the PDFs",
}


def sources() -> list:
    out = [REPO / "paperpull.py"]
    out += sorted(REPO.glob("gui/*.py"))
    out += sorted(REPO.glob("core/paperpull_core/*.py"))
    out += sorted(p for p in REPO.glob("apps/*/*.py")
                  if not p.name.startswith("test_") and p.name != "conftest.py")
    out += [REPO / "tools" / name for name in PANEL_TOOLS]
    return out


def _lists_a_folder(node) -> bool:
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in LISTS_A_FOLDER):
        return False
    # ast.walk walks a syntax tree, not a folder.
    return not (isinstance(node.func.value, ast.Name) and node.func.value.id == "ast")


def _order_cannot_leak(node, parent) -> bool:
    here = node
    while True:
        up = parent.get(here)
        called = (up.func.id if isinstance(up, ast.Call) and isinstance(up.func, ast.Name)
                  and up.args and up.args[0] is here else None)
        if called in TAKES_NO_ORDER:
            return True
        if called in KEEPS_THE_ORDER:
            here = up
            continue
        if isinstance(up, ast.comprehension) and up.iter is here:
            comp = parent.get(up)
            if isinstance(comp, ast.SetComp):
                return True
            if isinstance(comp, (ast.GeneratorExp, ast.ListComp)):
                here = comp
                continue
        return False


def unsorted_listings(text: str) -> list:
    """(line, function, call) for every listing in `text` whose order can leak."""
    tree = ast.parse(text)
    parent, owner = {}, {}

    def walk(node, name):
        for child in ast.iter_child_nodes(node):
            parent[child] = node
            owner[child] = name
            inner = name
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                inner = name + "." + child.name if name else child.name
            walk(child, inner)
    walk(tree, "")
    return [(node.lineno, owner.get(node, ""), ast.unparse(node))
            for node in ast.walk(tree)
            if _lists_a_folder(node) and not _order_cannot_leak(node, parent)]


@functools.lru_cache(maxsize=None)
def found() -> dict:
    out = {}
    for path in sources():
        rel = path.relative_to(REPO).as_posix()
        for line, function, call in unsorted_listings(path.read_text(encoding="utf-8-sig")):
            out.setdefault((rel, function, call), []).append(line)
    return out


def test_every_folder_listing_is_sorted_or_its_order_reaches_nothing():
    new = ["%s:%d in %s(), %s" % (rel, lines[0], function or "the module", call)
           for (rel, function, call), lines in sorted(found().items())
           if (rel, function, call) not in ORDER_REACHES_NOTHING]
    assert not new, (
        "These list a folder in the order the filesystem keeps, which differs "
        "between Windows and a Mac. Wrap each in sorted(), or name it in "
        "ORDER_REACHES_NOTHING with the reason its order reaches nothing.\n  "
        + "\n  ".join(new))


def test_every_listing_named_as_reaching_nothing_is_still_there():
    gone = sorted(key for key in ORDER_REACHES_NOTHING if key not in found())
    assert not gone, "no longer found, take these out of ORDER_REACHES_NOTHING: %s" % gone


def test_no_two_apps_share_an_entry_script():
    """refresh_installs finds an install's template by its entry script's
    name, so two templates with one name would leave the folder's order to
    choose between them."""
    names = [p.name for p in REPO.glob("apps/*/*.py")
             if p.name.endswith(("_docs.py", "_receipts.py")) and not p.name.startswith(".")]
    assert len(names) == len(set(names)), sorted(n for n in names if names.count(n) > 1)


def test_the_census_tells_a_settled_order_from_one_that_leaks():
    leaks = [
        "for p in folder.rglob('*'):\n    out.append(p)",
        "names = [p.name for p in folder.iterdir()]",
        "pdfs = list(folder.rglob('*.pdf'))",
        "first = next(iter(folder.glob('*.pdf')))",
        "newest = max(folder.glob('*.pdf'), key=when)",
        "names = os.listdir(dl_dir)",
        "for here, dirs, files in os.walk(top):\n    pass",
        "sizes = {p.name: p.stat().st_size for p in folder.iterdir()}",
    ]
    settled = [
        "for p in sorted(folder.rglob('*')):\n    out.append(p)",
        "names = sorted(p.name for p in folder.iterdir())",
        "names = {p.name for p in folder.iterdir()}",
        "seen = set(os.listdir(dl_dir))",
        "n = len(list(folder.glob('*.pdf')))",
        "any(p.is_dir() for p in folder.iterdir())",
        "n = sum(1 for d in folder.iterdir() if d.is_dir())",
        "nodes = ast.walk(tree)",
    ]
    for text in leaks:
        assert len(unsorted_listings(text)) == 1, text
    for text in settled:
        assert unsorted_listings(text) == [], text
