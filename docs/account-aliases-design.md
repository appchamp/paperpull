# Account Aliases & Renaming Architecture Design

## 1. Problem Statement & Motivation

In PaperPull, account identifiers (e.g., `Autograph Visa ...0305`, `Blue Visa`, `Checking Primary`) are scraped directly from provider web portals (dropdown labels, card numbers, account summary tables).

Users often want to customize how accounts are named and organized in their filesystem and reports (e.g., renaming `Autograph Visa ...0305` to `Autograph VisaSig`, or `Checking Primary` to `Joint Checking`).

Currently, changing account names manually requires modifying `progress.json`, `discovery.json`, `Document Index.csv`, and directories on disk. If done improperly, subsequent PaperPull runs either re-download existing files or crash because the site scraper cannot find elements matching the customized name.

This document proposes a native, safe **Account Aliases** feature configured directly in `config.json`.

---

## 2. Proposed Configuration

In any account's `config.json`:

```json
{
  "documents_dir": "/Users/user/Documents/Statements",
  "account_aliases": {
    "Autograph Visa ...0305": "Autograph VisaSig",
    "Checking 1111": "Joint Checking"
  },
  "account_documents_dirs": {
    "Autograph VisaSig": "/Users/user/Documents/CreditCards/Wells Fargo"
  }
}
```

### Key Semantics:
1. **Case & Whitespace Normalization**: Keys match the scraped site account name (whitespace-trimmed).
2. **Interoperability with `account_documents_dirs`**: `account_documents_dirs` must accept either the raw site name or the alias seamlessly.
3. **One-line Validation**: All aliases are validated through `on_one_line()` to prevent multiline control panel corruption.

---

## 3. Core Architecture & Separation of Concerns

```
┌────────────────────────────────────────────────────────┐
│                   Provider Scraper                     │
│               (e.g., wellsfargo_site.py)                │
│  - Selects dropdowns, radio buttons, account tabs       │
│  - STRICTLY uses doc.raw_account                       │
└──────────────────────────┬─────────────────────────────┘
                           │ Discovers Document
                           ▼
┌────────────────────────────────────────────────────────┐
│                   Storage / Core                       │
│                   (storage.py)                         │
│  - doc.raw_account = "Autograph Visa ...0305"          │
│  - doc.account = aliases.get(raw, raw)                 │
│    ("Autograph VisaSig")                               │
│  - doc.doc_key anchored to raw_account or permanent ID │
└──────────────────────────┬─────────────────────────────┘
                           │ Resolves Paths & Filenames
                           ▼
┌────────────────────────────────────────────────────────┐
│                 Naming & Relocation                    │
│            (naming.py & renaming.py)                   │
│  - {account} pattern expands to doc.account            │
│  - "Move documents" renames folders when alias changes │
└────────────────────────────────────────────────────────┘
```

### 3.1 Scraper Tier: Strict Scraper Isolation
Provider scripts interact with live DOM elements. The site scraper must **never** see or use display aliases when querying the DOM:
- `doc.raw_account`: Immutable string as presented by the financial institution's DOM.
- `doc.account`: The alias (or fallback to `raw_account`) used everywhere downstream (filenames, folders, CSV, UI).

### 3.2 Document Identity & Key Stability (`doc_key`)
PaperPull tracks downloaded documents via unique keys in `progress.json` and `discovery.json`.
- **Trap**: If `doc_key` incorporates `doc.account`, changing an alias in `config.json` will alter the key, causing PaperPull to consider all past statements un-downloaded and re-fetch them.
- **Rule**: `doc_key` generation in `storage.py` must consistently use `doc.raw_account` (or `doc.account_ref` / `document_id`), keeping keys immutable across alias edits.

### 3.3 Folder Relocation ("Move documents" Integration)
When a user adds or edits an alias in `config.json`:
1. Previously downloaded PDFs reside at `{documents_dir}/{old_alias}/{year}/...`.
2. Running **Move documents** (`PAPERPULL_MOVE_DOCUMENTS=1`):
   - Computes expected paths using the updated `doc.account`.
   - Detects when `{documents_dir}/{old_alias}` exists and moves/renames it to `{documents_dir}/{new_alias}`.
   - Updates `pdf_path` in `progress.json` and `Document Index.csv`.
   - Records the old folder in `documents-folders.json` to retain duplicate-detection tracking.

---

## 4. Edge Cases & Safety Constraints

1. **Unmapped Accounts**: Any account without an entry in `account_aliases` continues to use its scraped name with zero change in behavior.
2. **Collision Prevention**: If a user aliases two different raw accounts to the same alias (e.g. two cards to `"Visa"`), validation in `load_config()` warns or refuses to avoid collision in `{account}/{year}/`.
3. **Invalid Path Characters**: Aliases must not contain characters invalid in filesystem folder names (`/`, `\`, `:`, `*`, `?`, `"`, `<`, `>`, `|`, null bytes).
4. **Diagnostic Feedback**: If an alias key matches no accounts discovered during listing, `check_account_aliases_matched` emits a diagnostic note alerting the user to possible site renamings.

---

## 5. Implementation Roadmap

1. **Phase 1: Config & Data Model**
   - Add `account_aliases` loader in `storage.py`.
   - Ensure `Document` dataclass separates `raw_account` from `account`.
   - Anchor `doc_key` to `raw_account`.
2. **Phase 2: Naming & Storage**
   - Wire `doc.account` to `filename_pattern` expansion.
   - Resolve `account_documents_dirs` across both raw and aliased names.
3. **Phase 3: Relocation Engine**
   - Extend `renaming.py` to handle account folder renames on disk and update index files.
4. **Phase 4: Diagnostics & UI**
   - Display aliases in the desktop panel with raw account hints.
   - Add unit and integration tests in `core/tests/test_account_aliases.py`.
