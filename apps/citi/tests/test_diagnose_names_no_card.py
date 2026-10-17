"""Citi's detailed Diagnose file names no card.

A tester posted diagnose-documents.json publicly (#103, spotted by
appchamp) and its samples read "Citi CustomCash statement October 9, 9999".
The digits were shaped, but Custom and Cash are on PaperPull's word list,
so the card's product name came through and said which cards the tester
holds. Here Diagnose runs whole against a made-up signed-in page whose
cards are named only in words on the list, and nothing of those names may
reach the file or the console. No real account, no network.
"""
import json
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import citi_docs as docs  # noqa: E402
import citi_site as site  # noqa: E402

# Invented, every word of each on the list.
CARDS = ("Custom Cash Card - 1234", "Double Cash Rewards Card - 5678")
NAME_WORDS = ("custom", "cash", "double", "rewards")


class _Control:
    def __init__(self, text):
        self.text = text

    def inner_text(self, timeout=None):
        return self.text

    def get_attribute(self, name):
        return ""


class _Controls:
    def __init__(self, texts):
        self.texts = texts

    def count(self):
        return len(self.texts)

    def nth(self, i):
        return _Control(self.texts[i])


class _Found:
    def count(self):
        return 0

    def all_inner_texts(self):
        return ["%s Statements" % CARDS[0]]

    def inner_text(self, timeout=None):
        return "Account Statements"


class _SignedInPage:
    """The Account Statements page, with two cards named in ordinary words."""
    url = site.STATEMENTS_URL

    def is_closed(self):
        return False

    def title(self):
        return "Account Statements | %s" % CARDS[0]

    def locator(self, *_):
        return _Found()

    def get_by_role(self, role):
        return _Controls(["View %s statement" % c for c in CARDS] if role == "link" else [])

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, _js, args):
        url = args[0]
        if url == site.API_ACCOUNTS:
            return {"status": 200, "ct": "application/json", "json": {"eligibleAccounts": {
                "cardAccounts": [{"accountId": "uuid-%d" % i, "accountNickname": c}
                                 for i, c in enumerate(CARDS)]}}}
        return {"status": 200, "ct": "application/json", "json": {"statementsByYear": [
            {"displayYearTitle": "2026", "statementsByMonth": [
                {"statementDate": "10/09/2026"}, {"statementDate": "09/09/2026"}]}]}}


def test_the_detailed_file_and_what_diagnose_prints_name_no_card(tmp_path, capsys):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"owner": "Dana Example", "output_dir": str(tmp_path / "out"),
                               "profile_dir": str(tmp_path / "profile")}), encoding="utf-8")
    with mock.patch.object(docs.App, "_setup_logging", lambda self: None):
        app = docs.App(docs.build_parser().parse_args(["--config", str(cfg)]))
    page = _SignedInPage()
    app.page = lambda: page
    app.cmd_diagnose()
    written = (app.paths.diagnostics / "diagnose-documents.json").read_text(encoding="utf-8")
    info = json.loads(written)
    assert "error" not in info, info.get("error")
    # What the samples are for is still there, the kind and the date.
    assert info["samples"] and all(s["date"] == "9999-99-99" for s in info["samples"])
    assert all(s["category"] == "Statement" for s in info["samples"])
    assert info["samples"][0]["text"] == "Citi aaaaaa aaaa statement October 9, 9999"
    assert info["documents_recognized"][0]["account"] == "aaaaaa aaaa"
    said = capsys.readouterr().out
    for text in (written, said):
        low = text.lower()
        for word in NAME_WORDS:
            assert word not in low, "%r reached %s" % (word, "the file" if text is written
                                                       else "the console")
