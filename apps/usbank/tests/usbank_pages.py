"""A made-up U.S. Bank statements page for the tests beside this file.

Its parts are the ones the tester's failure files counted (#106). The
account picker is a native select holding a placeholder and the accounts,
the year picker is a button with a list of years, and the statement list
draws one section per account, headed by its name, with a row and a
Download button for each statement. Choosing an account or a year draws
the list again. Everything here is invented, every name, number and date.
"""
import json

PLACEHOLDER = "Choose an account"
CHECKING = "Everyday Checking ...1111"
CARD = "Visa Platinum ...2222"
BUSINESS = "Business Card ...3333"

# Each account's statements by year, as their rows write the dates.
STATEMENTS = {
    CHECKING: {"2031": ["October 13, 2031", "September 13, 2031"], "2030": ["December 13, 2030"]},
    CARD: {"2031": ["October 9, 2031"], "2030": ["November 9, 2030"]},
    BUSINESS: {"2031": ["October 2, 2031", "September 2, 2031"], "2030": []},
}

PAGE = """<!doctype html><html><head><meta charset='utf-8'></head><body>
<main data-testid="document-view"><div id="drawn"></div></main>
<script>
// In a function of its own, since set_content keeps the window and a
// second page's names would clash with the first's.
(() => {
const ACCOUNTS = %(accounts)s;
const DATA = %(data)s;
const DELAY = %(delay)d;
const HEADING = %(heading)s;
const NAMES = %(names)s;
const UNNAMED = %(unnamed)s;
const NEVER = %(never)s;
const LOCKED = %(locked)s;
const BLANK = %(blank)s;
const REDRAW = %(redraw)s;
const ALSO = %(also)s;
const STUCK = %(stuck)s;
const BARE = %(bare)s;
const YEAR_DELAY = %(year_delay)d;
const LIST_DELAY = %(list_delay)d;
const HELD = %(held)s;
const waiting = [];
let chosen = %(chosen)s, year = "2031";
function rows(label) {
  return (DATA[label] && DATA[label][year] || []).map((d, i) =>
    "<li class='download-items'><span>" + d + "</span>" +
    "<button aria-label='View " + d + " statement in a new window.'>View</button>" +
    "<button data-acct='" + label + "' aria-label='Download " + d + " statement.'>Download</button></li>").join("");
}
function heading(label) {
  return UNNAMED ? "Statements" : (NAMES[label] || label) + HEADING;
}
function section(label) {
  if (BARE && !rows(label)) return "<p>No statements for this period.</p>";
  return "<div class='document-list'><h3>" + heading(label) + "</h3><ul>" + rows(label) + "</ul></div>";
}
function drawList(label) {
  const shown = label === undefined ? chosen : label;
  const list = document.querySelector("[data-testid='list-of-statements']");
  if (!shown) {
    list.innerHTML = "<p>Choose an account to see its statements.</p>";
    return;
  }
  if (NEVER.includes(shown)) {
    list.innerHTML = "";
    return;
  }
  list.innerHTML = section(shown) + (ALSO && ALSO !== shown ? section(ALSO) : "");
}
// The lists held back for the accounts in HELD, each drawn now as the
// late answer it is, that account's rows whichever account is chosen.
window.deliverHeld = () => { while (waiting.length) drawList(waiting.shift()); return true; };
function later(fn) { DELAY ? setTimeout(fn, DELAY) : fn(); }
function drawPage() {
  const options = ["<option value=''>%(placeholder)s</option>"].concat(ACCOUNTS.map((a, i) =>
    "<option value='" + (BLANK ? "" : "a" + i) + "'" + (a === chosen ? " selected" : "") + ">" + a + "</option>"));
  const years = Object.keys(DATA[ACCOUNTS[0]] || {"2031": []}).sort().reverse();
  document.getElementById("drawn").innerHTML =
    "<h2>My documents</h2><p>Statements. All documents will open as PDFs.</p>" +
    "<div data-testid='account-dropdown'><label for='account-select'>Account</label>" +
    "<select id='account-select'>" + options.join("") + "</select></div>" +
    "<div data-testid='year-filter'><div id='year-filter-select'></div></div>" +
    "<div data-testid='list-of-statements'></div>";
  const sel = document.getElementById("account-select");
  sel.addEventListener("change", () => {
    const picked = sel.selectedIndex > 0 ? sel.options[sel.selectedIndex].text : "";
    if (LOCKED.includes(picked)) {
      // The picker goes back to the account before, though the list is
      // drawn for the one chosen.
      sel.value = Array.from(sel.options).find(o => o.text === chosen).value;
    }
    chosen = picked;
    if (HELD.includes(picked)) {
      // Asked for, and held back until deliverHeld, the list before kept
      // on show meanwhile.
      waiting.push(picked);
      return;
    }
    const list = document.querySelector("[data-testid='list-of-statements']");
    if (REDRAW === "blank") list.innerHTML = "";
    if (REDRAW === "overlay") list.insertAdjacentHTML("afterbegin", "<p>Loading statements</p>");
    if (REDRAW === "heading") list.querySelectorAll(".document-list h3").forEach(
      h => { h.textContent = heading(chosen); });
    later(drawList);
  });
  YEAR_DELAY ? setTimeout(() => drawYears(years), YEAR_DELAY) : drawYears(years);
  LIST_DELAY ? setTimeout(drawList, LIST_DELAY) : drawList();
}
function drawYears(years) {
  document.getElementById("year-filter-select").innerHTML =
    "<button id='exp_button_year-filter-select' aria-expanded='false'>Statement year " +
    "<span class='dropdown__btn-selection'>" + year + "</span></button>" +
    "<ul id='years' role='listbox' hidden>" +
    years.map(y => "<li role='option' data-year='" + y + "'>" + y + "</li>").join("") + "</ul>";
  const btn = document.getElementById("exp_button_year-filter-select");
  const box = document.getElementById("years");
  btn.addEventListener("click", () => { box.hidden = !box.hidden; });
  document.addEventListener("keydown", e => { if (e.key === "Escape") box.hidden = true; });
  box.querySelectorAll("[role=option]").forEach(o => o.addEventListener("click", () => {
    box.hidden = true;
    if (STUCK.includes(o.dataset.year)) return;
    year = o.dataset.year;
    btn.querySelector(".dropdown__btn-selection").textContent = year;
    drawList();
  }));
}
later(drawPage);
})();
</script></body></html>"""


def page_html(accounts=(CHECKING, CARD, BUSINESS), statements=None, chosen=BUSINESS,
              delay_ms=0, heading=" statements", placeholder=PLACEHOLDER, never=(),
              locked=(), blank_values=False, redraw="blank", names=None, unnamed=False,
              also="", stuck=(), bare_empty=False, year_delay_ms=0, list_delay_ms=0,
              held=()):
    """The page, with `chosen` the account the picker starts on ("" for its
    placeholder) and `delay_ms` how long the page takes to draw its parts
    after it loads, and the list after each change of account.

    `redraw` is what the list does while it waits after a change of
    account, "blank" it, "keep" the list before on show, "overlay" a
    loading note on top of it, or "heading" name the new account in the
    old list's headings at once. `bare_empty` draws a list with no
    statement as a note, no section at all. `names` heads an account's
    section with another name than its picker label, and `unnamed` heads
    every section with no account at all. `also` draws that account's section under
    every account chosen. `never` are accounts whose list never draws,
    `locked` accounts the picker goes back from when one is chosen, `stuck`
    years whose choice does not take, `year_delay_ms` and `list_delay_ms`
    how long after the rest the year picker and the first list draw,
    `blank_values` puts an empty value on every option, and `held` are
    accounts whose list, once chosen, comes only when the page's
    deliverHeld() is called, the list before on show until then, and draws
    that account's rows whichever account is chosen by then."""
    return PAGE % {"accounts": json.dumps(list(accounts)),
                   "data": json.dumps(statements if statements is not None else STATEMENTS),
                   "delay": delay_ms, "heading": json.dumps(heading),
                   "names": json.dumps(dict(names or {})), "unnamed": json.dumps(bool(unnamed)),
                   "chosen": json.dumps(chosen), "placeholder": placeholder,
                   "never": json.dumps(list(never)), "locked": json.dumps(list(locked)),
                   "blank": json.dumps(bool(blank_values)), "redraw": json.dumps(redraw),
                   "also": json.dumps(also), "stuck": json.dumps(list(stuck)),
                   "bare": json.dumps(bool(bare_empty)), "year_delay": int(year_delay_ms),
                   "list_delay": int(list_delay_ms), "held": json.dumps(list(held))}


def show(page, **kw):
    page.set_content(page_html(**kw))
    return page
