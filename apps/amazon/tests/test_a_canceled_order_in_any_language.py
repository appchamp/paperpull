"""A canceled order is recorded as canceled, in the store's own language (#114).

On amazon.de a German account gets its pages in German whatever ?language=
asks for. A canceled order's printable summary names the order, says
"Storniert" over "Deine Bestellung wurde storniert" (or "... wurde vom
Verkäufer storniert" when the seller canceled) and prints no total. The app
read only English for that, so the summary went on to the question of
whether it had rendered, which needs a total, and the order was recorded
Failed and asked for again on every run.

A wrong Canceled is worse. It is final, and the receipt is never asked for
again. So the summary has to say the order was canceled, in a line that is
its status and not an item's title, and nothing on it may say otherwise, no
total above zero, no shipment delivered, on its way or still to be sent,
and no word saying the order was canceled in part. An invoice the order's
menu offers is saved whatever the summary says. An order canceled in part,
a product named for the word, and a summary with no total and no status
are all left as they were.

The pages are served from this machine to a browser the app attaches to
over CDP, the way it does at home, as in
test_the_page_printed_is_the_purchase.py. Every order id, seller, item and
amount is invented.
"""
import csv
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import amazon_receipts as app_mod
import amazon_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import testkit

NO_HOSTS = "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"
DASH = "–"   # the en dash the reporter's copy of the page showed


def lines(*shown):
    """A page whose text is these lines, one block each."""
    return "".join("<div>%s</div>" % line for line in shown)


# -- the summaries ---------------------------------------------------------------

def german_head(order):
    return ("Bestellübersicht",
            "Bestellung aufgegeben 2. Oktober 2026  Bestellnummer %s" % order,
            "Drucken")


def german_canceled(order):
    return german_head(order) + (
        "Storniert",
        "Deine Bestellung wurde storniert.",
        "Invented Kaffeemühle, Edelstahl, manuell",
        "Verkauf durch: Beispiel Handel GmbH",
        "24,99 €",
        "Zurück zum Seitenanfang")


def german_seller_canceled(order):
    # The heading and the sentence on one line, as the report quoted them.
    return german_head(order) + (
        "Storniert %s Deine Bestellung wurde vom Verkäufer storniert." % DASH,
        "Invented Wanduhr, Eiche, 30 cm",
        "Verkauf durch: Beispiel Uhren e.K.",
        "Zurück zum Seitenanfang")


def german_partly_canceled(order):
    return german_head(order) + (
        "Zahlungsart",
        "Bestellübersicht",
        "Zwischensumme:", "18,50 €",
        "Verpackung & Versand:", "0,00 €",
        "Gesamtsumme:", "18,50 €",
        "Zugestellt: 6. Oktober",
        "Paket wurde an einem sicheren Ort abgegeben",
        "Invented Teekanne, Glas, 1 Liter",
        "Verkauf durch: Beispiel Handel GmbH",
        "18,50 €",
        "Storniert",
        "Ein Artikel deiner Bestellung wurde storniert.",
        "Invented Teesieb, Edelstahl",
        "Verkauf durch: Beispiel Handel GmbH",
        "Zurück zum Seitenanfang")


def german_item_named_storniert(order):
    return german_head(order) + (
        "Zahlungsart",
        "Bestellübersicht",
        "Zwischensumme:", "21,80 €",
        "Gesamtsumme:", "21,80 €",
        "Zugestellt: 6. Oktober",
        "Storniert",
        "Verkauf durch: Beispiel Verlag",
        "9,90 €",
        "Storniert: Ein Krimi aus Köln (Taschenbuch)",
        "Verkauf durch: Beispiel Verlag",
        "11,90 €",
        "Zurück zum Seitenanfang")


def german_no_total_no_status(order):
    return german_head(order) + (
        "Invented Wanduhr, Eiche, 30 cm",
        "Verkauf durch: Beispiel Uhren e.K.",
        "Zurück zum Seitenanfang")


def french_canceled(order):
    # A date the parser reads, since this test is about the canceled words.
    return ("Récapitulatif de commande",
            "Commande effectuée le 02/10/2026  N° de commande %s" % order,
            "Imprimer",
            "Annulée",
            "Votre commande a été annulée.",
            "Invented Moulin à café manuel",
            "Vendu par : Exemple Commerce SARL",
            "Retour en haut de la page")


def english_head(order):
    return ("Details for Order #%s" % order,
            "Order Placed: October 2, 2026",
            "Amazon.com order number: %s" % order)


def english_canceled(order):
    return english_head(order) + (
        "Cancelled",
        "Your order was cancelled. You have not been charged for this order.",
        "Invented Desk Lamp, Black, Clamp Mount",
        "Sold by: Example Seller Co")


def english_partly_canceled(order):
    # The canceled item is listed first, ahead of the delivered one.
    return english_head(order) + (
        "Order Total: $18.50",
        "Cancelled",
        "One item in your order was cancelled.",
        "Invented Tea Strainer, Stainless",
        "Sold by: Example Seller Co",
        "Delivered October 6, 2026",
        "Invented Glass Teapot, 1 Liter",
        "Sold by: Example Seller Co",
        "$18.50",
        "Item(s) Subtotal: $18.50",
        "Grand Total: $18.50")


def english_item_named_cancelled(order):
    # A book called Cancelled, on an order with no shipment status line.
    return english_head(order) + (
        "Order Total: $9.99",
        "Items Ordered",
        "Cancelled",
        "Sold by: Example Books",
        "$9.99",
        "Item(s) Subtotal: $9.99",
        "Grand Total: $9.99")


# -- the order list ---------------------------------------------------------------

def german_card(order):
    return ('<div class="order-card js-order-card">'
            + lines("Bestellung aufgegeben", "2. Oktober 2026", "Summe", "24,99 €",
                    "Bestellnr. %s" % order)
            + '<a href="/gp/your-account/order-details?orderID=%s">Bestelldetails</a>'
              "</div>" % order)


def french_card(order):
    return ('<div class="order-card js-order-card">'
            + lines("Commande effectuée le", "02/10/2026", "Total", "24,99 €",
                    "N° de commande %s" % order)
            + '<a href="/gp/your-account/order-details?orderID=%s">Détails</a>'
              "</div>" % order)


def english_card(order):
    return ('<div class="order-card js-order-card">'
            + lines("Order placed", "October 2, 2026", "Total", "$18.50",
                    "Order # %s" % order)
            + '<a href="/gp/your-account/order-details?orderID=%s">View order details</a>'
              "</div>" % order)


class FakeAmazon:
    """What the made-up store shows, set by each test. Each order has its
    card on the list and its printable summary."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.orders = {}     # order id -> (card html, summary lines)
        self.invoiced = set()   # orders whose invoice menu offers a PDF
        self.shown = {}      # order id -> another order whose summary it shows
        self.seen = []

    def show(self, order, card, summary):
        self.orders[order] = (card(order), summary(order))

    def listed(self):
        return ("<!doctype html><html><head><title>Orders</title></head><body>"
                "<h1>Orders</h1>%s</body></html>"
                % "".join(card for card, _ in self.orders.values()))

    def summary(self, order):
        order = self.shown.get(order, order)
        return ("<!doctype html><html><head><meta charset='utf-8'><title>%s</title>"
                "</head><body>%s</body></html>" % (order, lines(*self.orders[order][1])))


SITE = FakeAmazon()

INVOICE_PATH = "/documents/download/00000000-0000-4000-8000-000000000011/invoice.pdf"


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _answer(self, body, kind="text/html; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parts = urlsplit(self.path)
        SITE.seen.append(self.path)
        query = parse_qs(parts.query)
        order = (query.get("orderID") or [""])[0]
        if parts.path == "/gp/css/order-history":
            self._answer(SITE.listed())
        elif parts.path == "/gp/css/summary/print.html" and order in SITE.orders:
            self._answer(SITE.summary(order))
        elif parts.path == "/your-orders/invoice/popover" and \
                (query.get("orderId") or [""])[0] in SITE.invoiced:
            self._answer('<ul><li><a class="a-link-normal" href="%s">Rechnung</a></li></ul>'
                         % INVOICE_PATH)
        elif parts.path == INVOICE_PATH and SITE.invoiced:
            order = sorted(SITE.invoiced)[0]
            self._answer(testkit.text_pdf(["Rechnung", "Bestellnummer " + order,
                                           "Invented Kaffeemuehle, Edelstahl"]),
                         "application/pdf")
        else:
            self.send_error(404)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d" % httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(scope="module")
def browser_exe():
    pytest.importorskip("playwright.sync_api")
    found = browser_launcher.browser_candidates(mode=browser_launcher.BUNDLED)
    if not found:
        pytest.skip("no browser to drive")
    return found[0][1]


@pytest.fixture(scope="module")
def attached(browser_exe, tmp_path_factory):
    try:
        with testkit.drawn_browser(browser_exe, lambda: tmp_path_factory.mktemp("attached-profile"),
                                   args=(NO_HOSTS,)) as url:
            yield url
    except testkit.NoDebugPort:
        pytest.skip("the browser opened no debugging port")


@pytest.fixture(autouse=True)
def fake_amazon(server, monkeypatch):
    """Every address the app opens points at the made-up store, whichever
    store the config names, so the store's currency, date order and
    language request are its own."""
    SITE.reset()
    real_set = site.set_marketplace

    def pointed(domain):
        out = real_set(domain)
        monkeypatch.setattr(site, "BASE", server)
        monkeypatch.setattr(site, "URLS", {"home": server + "/",
                                           "orders": server + "/gp/css/order-history"})
        return out

    monkeypatch.setattr(site, "set_marketplace", pointed)
    monkeypatch.setattr(site, "is_safe_url", lambda url: (url or "").startswith(server + "/"))
    real_scroll = site.scroll_full_page
    monkeypatch.setattr(site, "scroll_full_page",
                        lambda page, rounds=1, delay_ms=0: real_scroll(page, 1, 0))
    monkeypatch.setattr(browser_launcher, "ask_or_none", lambda prompt: "")
    yield SITE
    real_set(site.DEFAULT_MARKETPLACE)


def config_for(tmp_path, cdp_url, store):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(tmp_path / "out"), "marketplace": store,
        "profile_dir": str(tmp_path / "launched-profile"), "cdp_url": cdp_url,
        "delay_min_seconds": 0, "delay_max_seconds": 0}), encoding="utf-8")
    return cfg


def pilot(tmp_path, cdp_url, store="amazon.de", *more):
    assert app_mod.main(["--pilot", "--year", "2026", *more,
                         "--config", str(config_for(tmp_path, cdp_url, store))]) == 0


def progress(tmp_path):
    return json.loads((tmp_path / "out" / "progress.json").read_text(encoding="utf-8"))


def saved(tmp_path):
    return sorted((tmp_path / "out").rglob("*.pdf"))


def pdf_text(path):
    from pypdf import PdfReader
    return " ".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)


def index_rows(tmp_path):
    found = sorted((tmp_path / "out").rglob("Amazon Receipt Index.csv"))
    if not found:
        return []
    with open(found[0], encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def assert_canceled(tmp_path, order):
    rec = progress(tmp_path)["Online:" + order]
    assert rec["state"] == "Canceled", rec
    assert not rec.get("downloaded_ok"), rec
    assert "did not render" not in (rec.get("notes") or ""), rec
    rows = [r for r in index_rows(tmp_path) if r["Order or Receipt Number"] == order]
    assert [r["Receipt Status"] for r in rows] == ["Canceled"], rows


def assert_saved(tmp_path, order):
    rec = progress(tmp_path)["Online:" + order]
    assert rec.get("downloaded_ok") is True, rec
    assert rec["state"] != "Canceled", rec
    assert Path(rec["pdf_path"]).is_file(), rec


# -- recorded as canceled ------------------------------------------------------------

GERMAN = "302-1000000-1000011"
SELLER = "302-1000000-1000029"
PART = "302-1000000-1000037"
TITLED = "302-1000000-1000045"
BLANK = "302-1000000-1000053"
KEPT = "302-1000000-1000061"
FRENCH = "403-1000000-1000019"
EN_CANCELED = "112-1000000-1000071"
EN_PART = "112-1000000-1000089"
EN_TITLED = "112-1000000-1000097"


def test_a_german_canceled_order_is_recorded_canceled(attached, tmp_path, capsys):
    SITE.show(GERMAN, german_card, german_canceled)
    pilot(tmp_path, attached)
    assert_canceled(tmp_path, GERMAN)
    assert saved(tmp_path) == []
    assert "Canceled order - recorded, no receipt." in capsys.readouterr().out


def test_an_order_the_seller_canceled_is_recorded_canceled(attached, tmp_path):
    SITE.show(SELLER, german_card, german_seller_canceled)
    pilot(tmp_path, attached)
    assert_canceled(tmp_path, SELLER)
    assert saved(tmp_path) == []


def test_a_french_canceled_order_is_recorded_canceled(attached, tmp_path):
    SITE.show(FRENCH, french_card, french_canceled)
    pilot(tmp_path, attached, "amazon.fr")
    assert_canceled(tmp_path, FRENCH)
    assert saved(tmp_path) == []


def test_an_english_canceled_order_is_still_recorded_canceled(attached, tmp_path):
    SITE.show(EN_CANCELED, english_card, english_canceled)
    pilot(tmp_path, attached, "amazon.com")
    assert_canceled(tmp_path, EN_CANCELED)


# -- never recorded as canceled ----------------------------------------------------------

def test_an_order_canceled_in_part_is_saved(attached, tmp_path):
    SITE.show(PART, german_card, german_partly_canceled)
    pilot(tmp_path, attached)
    assert_saved(tmp_path, PART)


def test_an_english_order_canceled_in_part_is_saved_whatever_it_lists_first(attached, tmp_path):
    """The canceled item first, and the order was read as canceled by the
    first status word on the page, so its receipt was never saved."""
    SITE.show(EN_PART, english_card, english_partly_canceled)
    pilot(tmp_path, attached, "amazon.com")
    assert_saved(tmp_path, EN_PART)


def test_a_german_order_with_an_item_named_storniert_is_saved(attached, tmp_path):
    SITE.show(TITLED, german_card, german_item_named_storniert)
    pilot(tmp_path, attached)
    assert_saved(tmp_path, TITLED)


def test_a_product_named_cancelled_does_not_cancel_its_order(attached, tmp_path):
    SITE.show(EN_TITLED, english_card, english_item_named_cancelled)
    pilot(tmp_path, attached, "amazon.com")
    assert_saved(tmp_path, EN_TITLED)


def test_an_invoice_issued_before_the_cancellation_is_still_saved(attached, tmp_path):
    """The invoice menu is asked before the summary, and an invoice it offers
    is the order's document whatever the summary says."""
    SITE.show(GERMAN, german_card, german_canceled)
    SITE.invoiced.add(GERMAN)
    pilot(tmp_path, attached)
    assert_saved(tmp_path, GERMAN)
    rec = progress(tmp_path)["Online:" + GERMAN]
    assert "Bestellnummer " + GERMAN in pdf_text(rec["pdf_path"])


def test_another_orders_canceled_summary_does_not_cancel_this_one(attached, tmp_path):
    """The order's address shows another order's summary, and that order was
    canceled. It is not this order's page, so it says nothing of this order."""
    SITE.show(GERMAN, german_card, german_canceled)
    SITE.show(BLANK, german_card, german_no_total_no_status)
    SITE.shown[BLANK] = GERMAN
    pilot(tmp_path, attached)
    rec = progress(tmp_path)["Online:" + BLANK]
    assert rec["state"] == "Needs Manual Review", rec
    assert "names a different purchase" in rec["notes"], rec
    assert_canceled(tmp_path, GERMAN)


def test_a_summary_with_no_total_and_no_status_is_asked_for_again(attached, tmp_path):
    """No total alone is no evidence. A summary that did not fill in prints
    none either, and it is tried again."""
    SITE.show(BLANK, german_card, german_no_total_no_status)
    pilot(tmp_path, attached)
    rec = progress(tmp_path)["Online:" + BLANK]
    assert rec["state"] == "Failed", rec
    assert "The printable order summary did not render, tried again next run" in rec["notes"]
    assert saved(tmp_path) == []
    assert index_rows(tmp_path) == []


# -- an install that ran before ------------------------------------------------------

def seed(tmp_path, records):
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "progress.json").write_text(json.dumps(records), encoding="utf-8")


def test_an_order_an_older_version_left_failed_is_recorded_canceled(attached, tmp_path):
    """An older version recorded the canceled order Failed, as a summary
    that did not render. The next run reads it as canceled."""
    seed(tmp_path, {"Online:" + GERMAN: {
        "purchase_type": "Online", "purchase_date": "2026-10-02", "order_number": GERMAN,
        "state": "Failed", "not_shown_days": ["2026-10-17"],
        "notes": "The printable order summary did not render, tried again next run"}})
    SITE.show(GERMAN, german_card, german_canceled)
    pilot(tmp_path, attached)
    assert_canceled(tmp_path, GERMAN)


def test_a_receipt_saved_before_keeps_its_record(attached, tmp_path):
    """A saved receipt is never asked for again, and a Download again that
    meets a canceled summary keeps the saved copy's record."""
    pdf = tmp_path / "out" / "Online" / "2026-10-01 Kept Receipt.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.4 kept")
    before = {"purchase_type": "Online", "purchase_date": "2026-10-02", "order_number": KEPT,
              "state": "Completed", "downloaded_ok": True, "pdf_path": str(pdf),
              "pdf_filename": pdf.name, "summary": "Kept Receipt", "notes": ""}
    seed(tmp_path, {"Online:" + KEPT: dict(before)})
    SITE.show(KEPT, german_card, german_canceled)

    pilot(tmp_path, attached)
    assert progress(tmp_path)["Online:" + KEPT] == before
    assert not any("orderID=" + KEPT in seen for seen in SITE.seen if "print.html" in seen)

    pilot(tmp_path, attached, "amazon.de", "--redownload")
    rec = progress(tmp_path)["Online:" + KEPT]
    assert {k: rec[k] for k in ("state", "downloaded_ok", "pdf_path", "pdf_filename")} == \
        {k: before[k] for k in ("state", "downloaded_ok", "pdf_path", "pdf_filename")}, rec
    assert pdf.read_bytes() == b"%PDF-1.4 kept"


# -- the words, store by store ------------------------------------------------------

CANCELED_PAGES = {
    "English": "Cancelled\nYour order was cancelled. You have not been charged.",
    "English, US spelling": "Canceled\nThis order has been canceled.",
    "German": "Storniert\nDeine Bestellung wurde storniert.",
    "German, seller": "Storniert\nDeine Bestellung wurde vom Verkäufer storniert.",
    "German, one line": "Storniert %s Ihre Bestellung wurde storniert" % DASH,
    "French": "Annulée\nVotre commande a été annulée.",
    "Spanish": "Cancelado\nTu pedido ha sido cancelado.",
    "Italian": "Annullato\nIl tuo ordine è stato annullato.",
    "Dutch": "Geannuleerd\nJe bestelling is geannuleerd.",
    "Swedish": "Avbruten\nDin beställning har avbrutits.",
    "Polish": "Anulowane\nTwoje zamówienie zostało anulowane.",
    "the heading alone": "Bestellnummer 302-1000000-1000011\nStorniert\nInvented Lampe",
    "the sentence alone": "Bestellnummer 302-1000000-1000011\nDeine Bestellung wurde storniert.",
    "a total of zero": "Storniert\nGesamtsumme:\n0,00 €",
}


@pytest.mark.parametrize("page", sorted(CANCELED_PAGES))
def test_each_stores_words_read_as_canceled(page):
    assert site.reads_canceled(CANCELED_PAGES[page]), page


NOT_CANCELED_PAGES = {
    "a total above zero": "Storniert\nDeine Bestellung wurde storniert.\nGesamtsumme:\n12,90 €",
    "a total in French": "Annulée\nMontant total : 12,90 €",
    "a total in Swedish": "Avbruten\nTotalt:\n129,00 kr",
    "a total in Polish": "Anulowane\nSuma:\n49,99 zł",
    "a delivered shipment": "Zugestellt: 6. Oktober\nStorniert",
    "a shipment on its way": "Arriving tomorrow\nCancelled",
    # A free order canceled in part, the rest still to be sent.
    "free, the rest not yet sent": "Gesamtsumme: 0,00 €\nNoch nicht versandt\nStorniert",
    "free, the rest due tomorrow": "Gesamtsumme: 0,00 €\nLieferung morgen\nStorniert",
    "free, in French": "Total : 0,00 €\nPas encore expédié\nAnnulé",
    "free, in Spanish": "Total: 0,00 €\nLlega mañana\nCancelado",
    "free, in Italian": "Totale: 0,00 €\nNon ancora spedito\nAnnullato",
    "free, in Dutch": "Totaal: 0,00 €\nNog niet verzonden\nGeannuleerd",
    "free, in Swedish": "Totalt: 0,00 kr\nLevererat 6 okt.\nAvbruten",
    "free, in Polish": "Suma: 0,00 zł\nJeszcze nie wysłane\nAnulowane",
    # The whole order's sentence, and then "in part".
    "in part, in Spanish": "Tu pedido ha sido cancelado parcialmente.",
    "in part, in French": "Votre commande a été annulée partiellement.",
    "in part, in Italian": "Il tuo ordine è stato annullato parzialmente.",
    "in part, in Polish": "Twoje zamówienie zostało anulowane częściowo.",
    "in part, in Swedish": "Din beställning har avbrutits delvis.",
    "in part, in English": "Your order was cancelled in part.",
    "in part, in German": "Storniert\nDeine Bestellung wurde teilweise storniert.",
    "one item of the order": "Ein Artikel deiner Bestellung wurde storniert.",
    "one item, in English": "One item in your order was cancelled.",
    "not canceled": "Deine Bestellung wurde nicht storniert.",
    "an item named Storniert": "Storniert\nVerkauf durch: Beispiel Verlag\n0,00 €",
    "an item named Cancelled": "Cancelled\nSold by: Example Books",
    "a classic item line": "1 of: Cancelled\n$0.00",
    "a title holding the word": "Storniert: Ein Krimi aus Köln\nInvented Lampe",
    "nothing said": "Bestellnummer 302-1000000-1000011\nInvented Wanduhr",
    "nothing at all": "",
}


@pytest.mark.parametrize("page", sorted(NOT_CANCELED_PAGES))
def test_nothing_else_reads_as_canceled(page):
    assert not site.reads_canceled(NOT_CANCELED_PAGES[page]), page


def test_what_the_list_said_still_counts_where_nothing_says_otherwise():
    """An English order was recognized by its status alone, from the list or
    the summary, and still is. Never past a total above zero."""
    assert site.reads_canceled("Bestellnummer 302-1000000-1000011", "Cancelled")
    assert not site.reads_canceled("Grand Total: $9.99", "Cancelled")
    assert not site.reads_canceled("Delivered October 6", "Cancelled")
