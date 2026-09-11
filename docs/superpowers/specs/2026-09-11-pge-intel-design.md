# PG&E Statement Intelligence & Dashboard Design Spec

## 1. Overview
The PG&E Statement Intelligence tool (`pge_intel.py`) is a standalone data extraction and analytics pipeline operating on downloaded Pacific Gas and Electric (PG&E) energy statements (`apps/pge/Statements/*.pdf`). It extracts structured billing, consumption, time-of-use (TOU), and rate data from PDF statements, saves machine-readable exports (`pge_bill_data.json` and `pge_bill_data.csv`), and generates a responsive, rich interactive web dashboard (`dashboard.html`) tracking monthly trends, key performance indicators (KPIs), and year-over-year comparisons.

## 2. Scope & Boundaries
- **Isolated Module**: Kept completely decoupled from `pge_docs.py`. It operates strictly on downloaded PDFs in `Statements/`.
- **Read-Only**: Only parses local PDFs and generates local analytics reports; never makes external network calls or modifies account settings.
- **Git Branch**: Work is implemented and maintained in branch `pge-intel`.

## 3. Architecture & Data Flow

```
Statements/*.pdf
      │
      ▼
pge_intel.py (Extraction Parser)
      │
      ├───────────────────────────────┬───────────────────────────────┐
      ▼                               ▼                               ▼
pge_bill_data.json            pge_bill_data.csv                 dashboard.html
(Structured JSON)            (Spreadsheet Export)           (Interactive Web App)
                                                                      │
                                                              view_dashboard.command
                                                               (1-Click macOS/Win)
```

## 4. Extraction Engine (`pge_intel.py`)

### 4.1 Parser Strategy
Uses `pypdf` (and checks for `pikepdf` if present) to extract text content across all statement pages. It uses targeted regular expressions tailored for PG&E residential statements (specifically Time-of-Use E-TOU-C and standard residential schedules).

### 4.2 Data Schema
Each statement record extracted contains:
- `account_number`: String (e.g. `5922868370-8`)
- `service_address`: String (e.g. `264 N WHISMAN RD APT 16, MOUNTAIN VIEW, CA 94043`)
- `statement_date`: ISO Date string `YYYY-MM-DD`
- `due_date`: ISO Date string `YYYY-MM-DD`
- `billing_start_date`: ISO Date string `YYYY-MM-DD`
- `billing_end_date`: ISO Date string `YYYY-MM-DD`
- `billing_days`: Integer
- `total_amount_due`: Float ($)
- `current_electric_charges`: Float ($)
- `current_gas_charges`: Float ($)
- `care_discount`: Float ($) (California Alternate Rates for Energy discount)
- `total_kwh`: Float (kWh)
- `avg_daily_kwh`: Float (kWh/day)
- `peak_kwh`: Float (kWh)
- `peak_charges`: Float ($)
- `peak_rate`: Float ($/kWh)
- `off_peak_kwh`: Float (kWh)
- `off_peak_charges`: Float ($)
- `off_peak_rate`: Float ($/kWh)
- `baseline_allowance_kwh`: Float (kWh)
- `baseline_credit`: Float ($)
- `rate_schedule`: String (e.g. `E-TOU-C`)
- `pdf_filename`: String
- `pdf_path`: String

### 4.3 Yearly Aggregation
Calculates aggregate metrics across calendar years (2024, 2025, 2026):
- Total spend ($) and average monthly spend ($/mo)
- Total energy (kWh) and average daily energy (kWh/day)
- Total CARE savings ($)
- Year-over-Year percent change in spend and consumption
- Calendar month distribution (Jan–Dec) across each year

## 5. Interactive Dashboard (`dashboard.html`)

### 5.1 Design & Visual Aesthetics
- **Theme**: Premium modern dark mode with deep slate/indigo palette (`#090d16`, `#111827`, `#1e293b`), vibrant emerald and electric cyan accents (`#10b981`, `#06b6d4`, `#6366f1`).
- **Layout**:
  - Glassmorphic card surfaces (`backdrop-filter: blur(12px)`).
  - Clean Inter typography and formatted currency/metric readouts.
  - Fully responsive grid layout across mobile, tablet, and widescreen desktop.
- **Header**:
  - Account Number, Service Address, Statement Count, and Year Quick-Filters (`All`, `2026`, `2025`, `2024`).
- **Hero KPI Cards**:
  1. **Latest Bill**: Amount and due date.
  2. **YTD / Average Monthly Spend**: Current year cumulative spend & average bill.
  3. **Total Electricity Consumed**: Cumulative kWh and average kWh/day.
  4. **Cumulative CARE Program Savings**: Total discounts saved.
  5. **Effective Average Rate**: Overall $/kWh across billing history.
- **Charts (Chart.js via CDN or standalone fallback)**:
  1. **Monthly Spend & Usage Trend**: Dual-axis line/bar chart showing Electric Bill ($) vs. Total kWh chronologically.
  2. **Year-over-Year Comparison**: Grouped column chart overlaying calendar months (Jan–Dec) for 2024, 2025, and 2026.
  3. **Time-of-Use Distribution**: Donut breakdown of Peak vs. Off-Peak electricity consumption.
- **Interactive Data Table**:
  - Filterable, sortable table listing all bills with Date, Billing Days, Usage (kWh), Peak/Off-Peak, Charges, Savings, and direct clickable link to open the local PDF.
  - Search bar filtering by date, notes, or charge.

## 6. Launcher Scripts
- `view_dashboard.command`: Executable shell script for macOS that runs `pge_intel.py` if needed and launches `dashboard.html` in the default browser.
- `view_dashboard.bat`: Batch script for Windows.

## 7. Verification & Testing Plan
- `apps/pge/tests/test_intel.py`:
  - Test parser on actual statements in `Statements/`.
  - Validate JSON schema and CSV output rows.
  - Verify calculation of yearly aggregations and TOU breakdowns.
  - Validate generated `dashboard.html` contains valid HTML and embedded data.
