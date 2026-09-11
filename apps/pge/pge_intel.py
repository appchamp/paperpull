"""PG&E Statement Intelligence & Analytics Engine.

Parses downloaded PG&E PDF statements, extracts structured billing, consumption,
and rate details, computes yearly trends, exports to JSON/CSV, and generates a
modern interactive web dashboard.
"""
from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional
import webbrowser

log = logging.getLogger("pge_intel")


@dataclass
class PgeStatementRecord:
    account_number: str = ""
    service_address: str = ""
    statement_date: str = ""      # YYYY-MM-DD
    due_date: str = ""            # YYYY-MM-DD
    billing_start_date: str = ""  # YYYY-MM-DD
    billing_end_date: str = ""    # YYYY-MM-DD
    billing_days: int = 0
    total_amount_due: float = 0.0
    current_electric_charges: float = 0.0
    current_gas_charges: float = 0.0
    care_discount: float = 0.0
    total_kwh: float = 0.0
    avg_daily_kwh: float = 0.0
    peak_kwh: float = 0.0
    peak_charges: float = 0.0
    peak_rate: float = 0.0
    off_peak_kwh: float = 0.0
    off_peak_charges: float = 0.0
    off_peak_rate: float = 0.0
    baseline_allowance_kwh: float = 0.0
    baseline_credit: float = 0.0
    rate_schedule: str = ""
    pdf_filename: str = ""
    pdf_path: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _fmt_date(date_str: str) -> str:
    """Normalize MM/DD/YYYY or YYYY-MM-DD to YYYY-MM-DD."""
    if not date_str:
        return ""
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", date_str)
    if m:
        month, day, year = m.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    m_iso = re.search(r"\d{4}-\d{2}-\d{2}", date_str)
    if m_iso:
        return m_iso.group(0)
    return date_str


def parse_statement_pdf(pdf_path: Path) -> Optional[PgeStatementRecord]:
    """Parse a PG&E statement PDF file and return structured record."""
    if not pdf_path.exists():
        return None

    full_text = ""
    pages_text: List[str] = []

    # Use pdftotext -layout if available (fast and clean), fallback to pypdf
    import shutil
    import subprocess

    if shutil.which("pdftotext"):
        try:
            res = subprocess.run(["pdftotext", "-layout", str(pdf_path), "-"], capture_output=True, text=True, timeout=10)
            if res.returncode == 0 and res.stdout:
                full_text = res.stdout
        except Exception as e:
            log.warning(f"pdftotext failed on {pdf_path.name}: {e}")

    if not full_text:
        try:
            import pypdf
            reader = pypdf.PdfReader(str(pdf_path))
            for p in reader.pages:
                t = p.extract_text() or ""
                pages_text.append(t)
                full_text += "\n" + t
        except Exception as e:
            log.error(f"Error reading PDF {pdf_path.name}: {e}")
            return None

    rec = PgeStatementRecord(
        pdf_filename=pdf_path.name,
        pdf_path=str(pdf_path.resolve()),
    )

    # 1. Account Number
    m_acct = re.search(r"Account No(?:umber)?:\s*([0-9]+-[0-9])", full_text, re.IGNORECASE)
    if m_acct:
        rec.account_number = m_acct.group(1).strip()

    # 2. Statement Date
    m_sdate = re.search(r"Statement Date:\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})", full_text, re.IGNORECASE)
    if m_sdate:
        rec.statement_date = _fmt_date(m_sdate.group(1))
    else:
        # Fallback to filename date YYYY-MM-DD
        m_fn = re.search(r"(\d{4}-\d{2}-\d{2})", pdf_path.name)
        if m_fn:
            rec.statement_date = m_fn.group(1)

    # 3. Due Date
    m_ddate = re.search(r"Due Date:\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})", full_text, re.IGNORECASE)
    if m_ddate:
        rec.due_date = _fmt_date(m_ddate.group(1))

    # 4. Service Address
    m_svc = re.search(r"Service For:\s*(?:[.\n\s]*)([^\n]+(?:APT[^\n]+)?\n[^\n]+CA\s+[0-9]{5}(?:-[0-9]{4})?)", full_text, re.IGNORECASE)
    if m_svc:
        addr = " ".join(line.strip() for line in m_svc.group(1).split("\n") if line.strip() and not line.strip().startswith("."))
        rec.service_address = addr
    else:
        m_addr_short = re.search(r"Service For:\s*([0-9]+[^\n]+)", full_text, re.IGNORECASE)
        if m_addr_short:
            rec.service_address = m_addr_short.group(1).strip()

    # 5. Total Amount Due
    if "no payment due" in full_text.lower():
        rec.total_amount_due = 0.0
    else:
        m_due = re.search(r"Total Amount Due:\s*\$?\s*([-\d,]+\.\d{2})", full_text, re.IGNORECASE)
        if m_due:
            try:
                rec.total_amount_due = float(m_due.group(1).replace(",", ""))
            except ValueError:
                pass

    # 6. Current Electric Charges
    m_cur_elec = re.search(r"Current Electric Charges\s*\$?\s*([-\d,]+\.\d{2})", full_text, re.IGNORECASE)
    if not m_cur_elec:
        m_cur_elec = re.search(r"Total Electric Charges\s*\$?\s*([-\d,]+\.\d{2})", full_text, re.IGNORECASE)
    if m_cur_elec:
        try:
            rec.current_electric_charges = float(m_cur_elec.group(1).replace(",", ""))
        except ValueError:
            pass

    # 7. CARE discount
    m_care = re.search(r"discounts of\s*\$?\s*([\d,]+\.\d{2})\s*for CARE", full_text, re.IGNORECASE)
    if m_care:
        try:
            rec.care_discount = float(m_care.group(1).replace(",", ""))
        except ValueError:
            pass

    # 8. Electric Usage & Billing Days
    m_dates = re.search(r"(\d{1,2}/\d{1,2}/\d{4})\s+to\s+(\d{1,2}/\d{1,2}/\d{4})\s*\(\s*(\d+)\s*billing days\)", full_text)
    if m_dates:
        rec.billing_start_date = _fmt_date(m_dates.group(1))
        rec.billing_end_date = _fmt_date(m_dates.group(2))
        rec.billing_days = int(m_dates.group(3))

    m_usage = re.search(r"Electric Usage This Period:\s*([\d.,]+)\s*kWh[,\s]+(\d+)\s*billing days", full_text, re.IGNORECASE)
    if not m_usage:
        m_usage = re.search(r"Electric Usage This Period:\s*([\d.,]+)\s*kWh", full_text, re.IGNORECASE)
    if m_usage:
        try:
            rec.total_kwh = float(m_usage.group(1).replace(",", ""))
            if not rec.billing_days and len(m_usage.groups()) > 1 and m_usage.group(2):
                rec.billing_days = int(m_usage.group(2))
        except ValueError:
            pass

    # If billing days not captured yet
    if not rec.billing_days:
        m_days = re.search(r"(\d+)\s*billing days", full_text, re.IGNORECASE)
        if m_days:
            try:
                rec.billing_days = int(m_days.group(1))
            except ValueError:
                pass

    # 9. Average Daily Usage
    m_daily = re.search(r"Average Daily Usage\s*([\d.,]+)\s*kWh", full_text, re.IGNORECASE)
    if m_daily:
        try:
            rec.avg_daily_kwh = float(m_daily.group(1).replace(",", ""))
        except ValueError:
            pass
    elif rec.billing_days > 0 and rec.total_kwh > 0:
        rec.avg_daily_kwh = round(rec.total_kwh / rec.billing_days, 2)

    # 10. Rate Schedule
    m_curr_plan = re.search(r"Your Current Rate Plan[\s\S]{1,150}?\((E-[A-Z0-9-]+)\)", full_text)
    if m_curr_plan:
        rec.rate_schedule = m_curr_plan.group(1)
    else:
        m_rate_sched = re.search(r"Rate Schedule:\s*([^\n]+)", full_text, re.IGNORECASE)
        if m_rate_sched:
            line = m_rate_sched.group(1).strip()
            if "4 - 9" in line:
                rec.rate_schedule = "E-TOU-C"
            elif "5 - 8" in line:
                rec.rate_schedule = "E-TOU-D"
            else:
                rec.rate_schedule = line
        elif "E-TOU-C" in full_text:
            rec.rate_schedule = "E-TOU-C"
        elif "E-TOU-D" in full_text:
            rec.rate_schedule = "E-TOU-D"

    # 11. Time-of-Use Details: Peak & Off-Peak
    m_peak = re.search(r"(?:^|\n)\s*Peak\s+([\d.,]+)\s*kWh\s*@\s*\$([\d.]+)\s+([-\d.,]+)", full_text, re.MULTILINE)
    if m_peak:
        try:
            rec.peak_kwh = float(m_peak.group(1).replace(",", ""))
            rec.peak_rate = float(m_peak.group(2))
            rec.peak_charges = float(m_peak.group(3).replace(",", ""))
        except ValueError:
            pass

    m_offpeak = re.search(r"(?:^|\n)\s*Off Peak\s+([\d.,]+)\s*kWh\s*@\s*\$([\d.]+)\s+([-\d.,]+)", full_text, re.MULTILINE)
    if m_offpeak:
        try:
            rec.off_peak_kwh = float(m_offpeak.group(1).replace(",", ""))
            rec.off_peak_rate = float(m_offpeak.group(2))
            rec.off_peak_charges = float(m_offpeak.group(3).replace(",", ""))
        except ValueError:
            pass

    # 12. Baseline Allowance & Credit
    m_base_allow = re.search(r"Baseline Allowance\s*([\d.,]+)\s*kWh", full_text, re.IGNORECASE)
    if m_base_allow:
        try:
            rec.baseline_allowance_kwh = float(m_base_allow.group(1).replace(",", ""))
        except ValueError:
            pass

    m_base_cred = re.search(r"Baseline Credit\s*[\d.,]+\s*kWh\s*@\s*-\$([\d.]+)\s*([-\d.,]+)", full_text, re.IGNORECASE)
    if m_base_cred:
        try:
            rec.baseline_credit = float(m_base_cred.group(2).replace(",", ""))
        except ValueError:
            pass

    return rec


def extract_historical_table(full_text: str) -> Dict[str, Dict[str, float]]:
    """Extract historical months from 'How Budget Billing Affects Your Energy Payments' table."""
    history: Dict[str, Dict[str, float]] = {}
    if not full_text:
        return history
    clean = re.sub(r"\s+", " ", full_text)
    clean = clean.replace("How Budget Billing Affects Your Energy Payments", " ")
    clean = re.sub(r"\s+", " ", clean)
    matches = re.findall(r"For (\d{1,2}/\d{1,2}) (\d{4}) electric \$ ([\d.,]+) budget billing amount \$ ([\d.,]+)", clean, re.IGNORECASE)
    for month_day, year, elec, bb in matches:
        try:
            m_parts = month_day.split("/")
            month, day = int(m_parts[0]), int(m_parts[1])
            date_key = f"{year}-{month:02d}-{day:02d}"
            history[date_key] = {
                "current_electric_charges": float(elec.replace(",", "")),
                "budget_billing_amount": float(bb.replace(",", ""))
            }
        except Exception:
            continue
    return history


def scan_all_statements(statements_dir: Path) -> List[PgeStatementRecord]:
    """Scan directory of statement PDFs, extract all records, backfill history, and return sorted."""
    if not statements_dir.exists():
        log.warning(f"Directory {statements_dir} does not exist.")
        return []

    pdf_files = sorted(statements_dir.glob("*.pdf"))
    records_by_date: Dict[str, PgeStatementRecord] = {}
    history_table: Dict[str, Dict[str, float]] = {}

    for p in pdf_files:
        rec = parse_statement_pdf(p)
        if rec and rec.statement_date:
            records_by_date[rec.statement_date] = rec

    # Extract historical table in reverse chronological order (latest statements have the most history)
    for p in reversed(pdf_files):
        import shutil, subprocess
        if shutil.which("pdftotext"):
            try:
                res = subprocess.run(["pdftotext", "-layout", str(p), "-"], capture_output=True, text=True, timeout=5)
                if res.returncode == 0:
                    tbl = extract_historical_table(res.stdout)
                    history_table.update(tbl)
                    if any(k.startswith("2024") for k in history_table) and len(history_table) >= 24:
                        break
            except Exception:
                pass

    # Backfill records that had 0 electric charges from historical table if available
    for d, rec in records_by_date.items():
        if rec.current_electric_charges == 0.0:
            if d in history_table:
                rec.current_electric_charges = history_table[d]["current_electric_charges"]
                if rec.total_amount_due == 0.0:
                    rec.total_amount_due = history_table[d]["budget_billing_amount"]
            else:
                ym = d[:7]
                ym_matches = [k for k in history_table if k.startswith(ym)]
                if ym_matches:
                    matched_key = ym_matches[0]
                    rec.current_electric_charges = history_table[matched_key]["current_electric_charges"]
                    if rec.total_amount_due == 0.0:
                        rec.total_amount_due = history_table[matched_key]["budget_billing_amount"]

    sorted_records = [records_by_date[k] for k in sorted(records_by_date.keys())]
    return sorted_records


def compute_yearly_trends(records: List[PgeStatementRecord]) -> Dict[str, Any]:
    """Compute yearly totals, monthly arrays, YoY deltas, and summary metrics."""
    yearly: Dict[str, Dict[str, Any]] = {}

    for r in records:
        if not r.statement_date:
            continue
        try:
            year = r.statement_date.split("-")[0]
            month = int(r.statement_date.split("-")[1])
        except Exception:
            continue

        if year not in yearly:
            yearly[year] = {
                "total_spend": 0.0,
                "total_kwh": 0.0,
                "total_care_savings": 0.0,
                "count": 0,
                "avg_monthly_spend": 0.0,
                "avg_monthly_kwh": 0.0,
                "monthly_spend": [0.0] * 12,
                "monthly_kwh": [0.0] * 12,
                "monthly_care": [0.0] * 12,
            }

        y_data = yearly[year]
        y_data["total_spend"] = round(y_data["total_spend"] + r.current_electric_charges, 2)
        y_data["total_kwh"] = round(y_data["total_kwh"] + r.total_kwh, 2)
        y_data["total_care_savings"] = round(y_data["total_care_savings"] + r.care_discount, 2)
        y_data["count"] += 1

        if 1 <= month <= 12:
            # If multiple statements in same month, add them
            idx = month - 1
            y_data["monthly_spend"][idx] = round(y_data["monthly_spend"][idx] + r.current_electric_charges, 2)
            y_data["monthly_kwh"][idx] = round(y_data["monthly_kwh"][idx] + r.total_kwh, 2)
            y_data["monthly_care"][idx] = round(y_data["monthly_care"][idx] + r.care_discount, 2)

    for y, y_data in yearly.items():
        if y_data["count"] > 0:
            y_data["avg_monthly_spend"] = round(y_data["total_spend"] / y_data["count"], 2)
            y_data["avg_monthly_kwh"] = round(y_data["total_kwh"] / y_data["count"], 2)

    # Calculate global totals
    total_spend = sum(r.current_electric_charges for r in records)
    total_kwh = sum(r.total_kwh for r in records)
    total_care = sum(r.care_discount for r in records)
    total_peak = sum(r.peak_kwh for r in records)
    total_off_peak = sum(r.off_peak_kwh for r in records)
    tou_sum = total_peak + total_off_peak
    peak_pct = round((total_peak / tou_sum * 100) if tou_sum > 0 else 0.0, 1)
    off_peak_pct = round((total_off_peak / tou_sum * 100) if tou_sum > 0 else 0.0, 1)

    latest_record = records[-1].to_dict() if records else {}

    summary = {
        "statement_count": len(records),
        "total_spend": round(total_spend, 2),
        "total_kwh": round(total_kwh, 2),
        "total_care_savings": round(total_care, 2),
        "avg_monthly_spend": round(total_spend / len(records), 2) if records else 0.0,
        "total_peak_kwh": round(total_peak, 2),
        "total_off_peak_kwh": round(total_off_peak, 2),
        "peak_pct": peak_pct,
        "off_peak_pct": off_peak_pct,
        "latest_record": latest_record,
        "first_statement_date": records[0].statement_date if records else "",
        "latest_statement_date": records[-1].statement_date if records else "",
    }

    # YoY Comparison (2025 vs 2024, 2026 vs 2025)
    yoy: Dict[str, Any] = {}
    years_sorted = sorted(yearly.keys())
    for i in range(1, len(years_sorted)):
        prev_y = years_sorted[i-1]
        curr_y = years_sorted[i]
        prev_spend = yearly[prev_y]["total_spend"]
        curr_spend = yearly[curr_y]["total_spend"]
        diff = curr_spend - prev_spend
        pct = round((diff / prev_spend * 100) if prev_spend > 0 else 0.0, 1)
        yoy[f"{curr_y}_vs_{prev_y}"] = {
            "diff_dollars": round(diff, 2),
            "pct_change": pct
        }

    return {
        "yearly": yearly,
        "summary": summary,
        "yoy": yoy,
    }


def export_to_json(records: List[PgeStatementRecord], trends: Dict[str, Any], out_path: Path) -> None:
    """Export records and trends summary to formatted JSON file."""
    data = {
        "summary": trends.get("summary", {}),
        "yearly_trends": trends.get("yearly", {}),
        "year_over_year": trends.get("yoy", {}),
        "statements": [r.to_dict() for r in records]
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    log.info(f"Exported JSON to {out_path}")


def export_to_csv(records: List[PgeStatementRecord], out_path: Path) -> None:
    """Export records to CSV."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "statement_date", "due_date", "billing_start_date", "billing_end_date",
        "billing_days", "total_amount_due", "current_electric_charges", "care_discount",
        "total_kwh", "avg_daily_kwh", "peak_kwh", "peak_rate", "peak_charges",
        "off_peak_kwh", "off_peak_rate", "off_peak_charges", "baseline_allowance_kwh",
        "baseline_credit", "rate_schedule", "account_number", "pdf_filename"
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in records:
            d = r.to_dict()
            writer.writerow({k: d.get(k, "") for k in fields})
    log.info(f"Exported CSV to {out_path}")


def render_dashboard(records: List[PgeStatementRecord], trends: Dict[str, Any], out_path: Path) -> None:
    """Render a standalone, high-performance HTML dashboard with Chart.js visualization."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    records_json = json.dumps([r.to_dict() for r in records])
    trends_json = json.dumps(trends)
    summary = trends.get("summary", {})
    latest = summary.get("latest_record", {})

    account_no = latest.get("account_number") or (records[0].account_number if records else "N/A")
    address = latest.get("service_address") or (records[0].service_address if records else "California Service Address")

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>PG&E Energy Intelligence Dashboard</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
  <style>
    :root {{
      --bg-base: #0B0F19;
      --bg-surface: #111827;
      --bg-card: rgba(17, 24, 39, 0.85);
      --bg-card-hover: rgba(31, 41, 55, 0.9);
      --border-subtle: rgba(255, 255, 255, 0.08);
      --border-accent: rgba(6, 182, 212, 0.3);
      --text-primary: #F9FAFB;
      --text-secondary: #9CA3AF;
      --text-muted: #6B7280;
      --accent-cyan: #06B6D4;
      --accent-emerald: #10B981;
      --accent-amber: #F59E0B;
      --accent-purple: #8B5CF6;
      --accent-rose: #F43F5E;
      --radius-sm: 8px;
      --radius-md: 14px;
      --radius-lg: 20px;
      --shadow-card: 0 10px 30px -5px rgba(0, 0, 0, 0.5), 0 0 1px 1px rgba(255, 255, 255, 0.05);
      --transition-smooth: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
    }}

    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      background-color: var(--bg-base);
      color: var(--text-primary);
      line-height: 1.5;
      padding: 24px;
      min-height: 100vh;
      -webkit-font-smoothing: antialiased;
    }}

    .dashboard-container {{
      max-width: 1400px;
      margin: 0 auto;
      display: flex;
      flex-direction: column;
      gap: 24px;
    }}

    /* Header */
    header {{
      background: linear-gradient(135deg, rgba(17, 24, 39, 0.95), rgba(30, 41, 59, 0.85));
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-lg);
      padding: 24px 32px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      box-shadow: var(--shadow-card);
      backdrop-filter: blur(12px);
      flex-wrap: wrap;
      gap: 16px;
    }}

    .header-branding {{
      display: flex;
      align-items: center;
      gap: 16px;
    }}

    .logo-badge {{
      width: 48px;
      height: 48px;
      border-radius: 12px;
      background: linear-gradient(135deg, #0284C7, #06B6D4);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 24px;
      box-shadow: 0 0 20px rgba(6, 182, 212, 0.4);
    }}

    .header-title h1 {{
      font-size: 24px;
      font-weight: 700;
      letter-spacing: -0.02em;
      color: #FFF;
      display: flex;
      align-items: center;
      gap: 10px;
    }}

    .header-title p {{
      color: var(--text-secondary);
      font-size: 14px;
      margin-top: 2px;
    }}

    .header-meta {{
      display: flex;
      gap: 16px;
      align-items: center;
      flex-wrap: wrap;
    }}

    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 12px;
      border-radius: 9999px;
      font-size: 12px;
      font-weight: 600;
      letter-spacing: 0.02em;
      background: rgba(255, 255, 255, 0.06);
      border: 1px solid var(--border-subtle);
      color: var(--text-secondary);
    }}

    .badge.cyan {{
      background: rgba(6, 182, 212, 0.12);
      border-color: rgba(6, 182, 212, 0.3);
      color: var(--accent-cyan);
    }}

    .badge.emerald {{
      background: rgba(16, 185, 129, 0.12);
      border-color: rgba(16, 185, 129, 0.3);
      color: var(--accent-emerald);
    }}

    /* KPI Grid */
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
      gap: 16px;
    }}

    .kpi-card {{
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-md);
      padding: 20px;
      box-shadow: var(--shadow-card);
      transition: var(--transition-smooth);
      position: relative;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }}

    .kpi-card:hover {{
      transform: translateY(-2px);
      border-color: var(--border-accent);
      background: var(--bg-card-hover);
    }}

    .kpi-card::before {{
      content: '';
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      height: 3px;
      background: linear-gradient(90deg, transparent, var(--border-accent), transparent);
    }}

    .kpi-label {{
      font-size: 12px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-secondary);
      margin-bottom: 8px;
    }}

    .kpi-value {{
      font-size: 28px;
      font-weight: 800;
      color: #FFF;
      letter-spacing: -0.03em;
      font-family: 'JetBrains Mono', monospace;
    }}

    .kpi-footer {{
      margin-top: 10px;
      font-size: 12px;
      color: var(--text-muted);
      display: flex;
      align-items: center;
      gap: 4px;
    }}

    /* Chart Section */
    .charts-grid {{
      display: grid;
      grid-template-columns: 2fr 1fr;
      gap: 20px;
    }}

    @media (max-width: 1024px) {{
      .charts-grid {{ grid-template-columns: 1fr; }}
    }}

    .chart-card {{
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-md);
      padding: 24px;
      box-shadow: var(--shadow-card);
      display: flex;
      flex-direction: column;
      gap: 16px;
    }}

    .chart-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}

    .chart-title {{
      font-size: 16px;
      font-weight: 700;
      color: #FFF;
      letter-spacing: -0.01em;
      display: flex;
      align-items: center;
      gap: 8px;
    }}

    .chart-container {{
      position: relative;
      width: 100%;
      height: 320px;
    }}

    /* Ledger Table Section */
    .table-card {{
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-md);
      padding: 24px;
      box-shadow: var(--shadow-card);
      display: flex;
      flex-direction: column;
      gap: 16px;
    }}

    .table-controls {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }}

    .search-input {{
      background: rgba(0, 0, 0, 0.3);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-sm);
      padding: 8px 16px;
      color: #FFF;
      font-size: 13px;
      min-width: 260px;
      outline: none;
      transition: var(--transition-smooth);
    }}

    .search-input:focus {{
      border-color: var(--accent-cyan);
      box-shadow: 0 0 0 2px rgba(6, 182, 212, 0.2);
    }}

    .btn {{
      background: rgba(255, 255, 255, 0.08);
      border: 1px solid var(--border-subtle);
      color: #FFF;
      padding: 8px 16px;
      border-radius: var(--radius-sm);
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      transition: var(--transition-smooth);
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }}

    .btn:hover {{
      background: rgba(255, 255, 255, 0.15);
      border-color: rgba(255, 255, 255, 0.2);
    }}

    .table-wrapper {{
      overflow-x: auto;
      border-radius: var(--radius-sm);
      border: 1px solid var(--border-subtle);
    }}

    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
      text-align: left;
    }}

    th {{
      background: rgba(0, 0, 0, 0.4);
      padding: 12px 16px;
      font-weight: 600;
      color: var(--text-secondary);
      border-bottom: 1px solid var(--border-subtle);
      cursor: pointer;
      user-select: none;
      white-space: nowrap;
    }}

    th:hover {{ color: var(--accent-cyan); }}

    td {{
      padding: 12px 16px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.04);
      color: var(--text-primary);
      white-space: nowrap;
    }}

    tr:hover td {{
      background: rgba(255, 255, 255, 0.02);
    }}

    .mono {{
      font-family: 'JetBrains Mono', monospace;
    }}

    .text-emerald {{ color: var(--accent-emerald); }}
    .text-amber {{ color: var(--accent-amber); }}
    .text-cyan {{ color: var(--accent-cyan); }}

    .file-link {{
      color: var(--accent-cyan);
      text-decoration: none;
      font-weight: 500;
    }}
    .file-link:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>

<div class="dashboard-container">
  <!-- Header -->
  <header>
    <div class="header-branding">
      <div class="logo-badge">⚡</div>
      <div class="header-title">
        <h1>PG&E Statement Intelligence</h1>
        <p>Real-time analytics, historical trends, and rate schedule monitoring</p>
      </div>
    </div>
    <div class="header-meta">
      <span class="badge cyan">Account #{account_no}</span>
      <span class="badge emerald">CARE Subsidized</span>
      <span class="badge">E-TOU-C Rate</span>
      <span class="badge">{summary.get("statement_count", 0)} Statements</span>
    </div>
  </header>

  <!-- Hero KPI Grid -->
  <div class="kpi-grid">
    <div class="kpi-card">
      <div class="kpi-label">Latest Statement</div>
      <div class="kpi-value text-cyan">${latest.get("current_electric_charges", 0.0):.2f}</div>
      <div class="kpi-footer">
        <span>{latest.get("statement_date", "N/A")} ({latest.get("billing_days", 0)} days)</span>
      </div>
    </div>

    <div class="kpi-card">
      <div class="kpi-label">Avg Monthly Bill</div>
      <div class="kpi-value">${summary.get("avg_monthly_spend", 0.0):.2f}</div>
      <div class="kpi-footer">
        <span>Across {summary.get("statement_count", 0)} tracked bills</span>
      </div>
    </div>

    <div class="kpi-card">
      <div class="kpi-label">Total Spend Tracked</div>
      <div class="kpi-value">${summary.get("total_spend", 0.0):.2f}</div>
      <div class="kpi-footer">
        <span>{summary.get("first_statement_date", "")} &rarr; {summary.get("latest_statement_date", "")}</span>
      </div>
    </div>

    <div class="kpi-card">
      <div class="kpi-label">Total CARE Savings</div>
      <div class="kpi-value text-emerald">${summary.get("total_care_savings", 0.0):.2f}</div>
      <div class="kpi-footer">
        <span>Subsidized discount savings</span>
      </div>
    </div>

    <div class="kpi-card">
      <div class="kpi-label">Energy Consumed</div>
      <div class="kpi-value">{summary.get("total_kwh", 0.0):,.1f} <span style="font-size: 16px; font-weight: normal; color: var(--text-secondary);">kWh</span></div>
      <div class="kpi-footer">
        <span>TOU Peak: {summary.get("peak_pct", 0.0)}% | Off-Peak: {summary.get("off_peak_pct", 0.0)}%</span>
      </div>
    </div>
  </div>

  <!-- Primary Charts Grid -->
  <div class="charts-grid">
    <!-- Main History Chart -->
    <div class="chart-card">
      <div class="chart-header">
        <div class="chart-title">📊 Monthly Spend & Energy Consumption Timeline</div>
        <span class="badge cyan">Dual-Axis</span>
      </div>
      <div class="chart-container">
        <canvas id="timelineChart"></canvas>
      </div>
    </div>

    <!-- TOU Breakdown Donut -->
    <div class="chart-card">
      <div class="chart-header">
        <div class="chart-title">⏰ Time-of-Use Breakdown</div>
        <span class="badge">Peak vs Off-Peak</span>
      </div>
      <div class="chart-container">
        <canvas id="touChart"></canvas>
      </div>
    </div>
  </div>

  <!-- Secondary Charts Grid: Yearly Comparison & CARE -->
  <div class="charts-grid">
    <!-- Year over Year Comparison -->
    <div class="chart-card">
      <div class="chart-header">
        <div class="chart-title">📅 Year-over-Year Monthly Comparison (Jan – Dec)</div>
        <span class="badge emerald">Seasonality</span>
      </div>
      <div class="chart-container">
        <canvas id="yoyChart"></canvas>
      </div>
    </div>

    <!-- CARE Discount Breakdown -->
    <div class="chart-card">
      <div class="chart-header">
        <div class="chart-title">🛡️ Monthly CARE Subsidy Relief</div>
        <span class="badge emerald">Savings</span>
      </div>
      <div class="chart-container">
        <canvas id="careChart"></canvas>
      </div>
    </div>
  </div>

  <!-- Detailed Ledger Table -->
  <div class="table-card">
    <div class="table-controls">
      <div class="chart-title">📋 Complete Statement Ledger</div>
      <div style="display: flex; gap: 10px;">
        <input type="text" id="searchInput" class="search-input" placeholder="Filter by date, schedule..." onkeyup="filterTable()" />
        <a href="pge_bill_data.json" download class="btn">📥 JSON</a>
        <a href="pge_bill_data.csv" download class="btn">📥 CSV</a>
      </div>
    </div>

    <div class="table-wrapper">
      <table id="statementTable">
        <thead>
          <tr>
            <th onclick="sortTable(0)">Statement Date ↕</th>
            <th onclick="sortTable(1)">Billing Days ↕</th>
            <th onclick="sortTable(2)">Total Due ↕</th>
            <th onclick="sortTable(3)">Electric Charges ↕</th>
            <th onclick="sortTable(4)">CARE Discount ↕</th>
            <th onclick="sortTable(5)">Usage (kWh) ↕</th>
            <th onclick="sortTable(6)">Peak (kWh) ↕</th>
            <th onclick="sortTable(7)">Off-Peak (kWh) ↕</th>
            <th onclick="sortTable(8)">Rate Schedule ↕</th>
            <th>PDF Statement</th>
          </tr>
        </thead>
        <tbody id="tableBody">
          <!-- Populated by JS -->
        </tbody>
      </table>
    </div>
  </div>
</div>

<script>
  const records = {records_json};
  const trends = {trends_json};

  // Populate Table
  const tbody = document.getElementById("tableBody");
  records.slice().reverse().forEach(r => {{
    const tr = document.createElement("tr");
    const fileLink = r.pdf_path
      ? `<a href="file://${{r.pdf_path}}" class="file-link" target="_blank" title="${{r.pdf_filename}}">📄 ${{r.pdf_filename.length > 25 ? r.pdf_filename.slice(0, 22) + '...' : r.pdf_filename}}</a>`
      : `<span style="color: var(--text-muted);">Historical Log</span>`;

    tr.innerHTML = `
      <td class="mono"><strong>${{r.statement_date || 'N/A'}}</strong></td>
      <td class="mono">${{r.billing_days || '-'}}</td>
      <td class="mono">$${{r.total_amount_due.toFixed(2)}}</td>
      <td class="mono text-cyan"><strong>$${{r.current_electric_charges.toFixed(2)}}</strong></td>
      <td class="mono text-emerald">-$${{r.care_discount.toFixed(2)}}</td>
      <td class="mono">${{r.total_kwh > 0 ? r.total_kwh.toFixed(1) : '-'}}</td>
      <td class="mono text-amber">${{r.peak_kwh > 0 ? r.peak_kwh.toFixed(1) : '-'}}</td>
      <td class="mono">${{r.off_peak_kwh > 0 ? r.off_peak_kwh.toFixed(1) : '-'}}</td>
      <td><span class="badge">${{r.rate_schedule || 'E-TOU-C'}}</span></td>
      <td>${{fileLink}}</td>
    `;
    tbody.appendChild(tr);
  }});

  // Table Filter
  function filterTable() {{
    const val = document.getElementById("searchInput").value.toLowerCase();
    const rows = document.querySelectorAll("#tableBody tr");
    rows.forEach(row => {{
      row.style.display = row.innerText.toLowerCase().includes(val) ? "" : "none";
    }});
  }}

  // Table Sort
  let sortDirections = {{}};
  function sortTable(colIdx) {{
    const table = document.getElementById("statementTable");
    const tbody = document.getElementById("tableBody");
    const rows = Array.from(tbody.querySelectorAll("tr"));
    const dir = sortDirections[colIdx] === 'asc' ? 'desc' : 'asc';
    sortDirections[colIdx] = dir;

    rows.sort((a, b) => {{
      const aText = a.children[colIdx].innerText.replace('$', '').replace('-', '').trim();
      const bText = b.children[colIdx].innerText.replace('$', '').replace('-', '').trim();
      const aNum = parseFloat(aText);
      const bNum = parseFloat(bText);
      if (!isNaN(aNum) && !isNaN(bNum)) {{
        return dir === 'asc' ? aNum - bNum : bNum - aNum;
      }}
      return dir === 'asc' ? aText.localeCompare(bText) : bText.localeCompare(aText);
    }});
    rows.forEach(r => tbody.appendChild(r));
  }}

  // 1. Timeline Chart (Dual-Axis)
  const timelineCtx = document.getElementById('timelineChart').getContext('2d');
  const labels = records.map(r => r.statement_date);
  const spendData = records.map(r => r.current_electric_charges);
  const kwhData = records.map(r => r.total_kwh);

  new Chart(timelineCtx, {{
    type: 'bar',
    data: {{
      labels: labels,
      datasets: [
        {{
          label: 'Electric Charges ($)',
          data: spendData,
          backgroundColor: 'rgba(6, 182, 212, 0.4)',
          borderColor: '#06B6D4',
          borderWidth: 1.5,
          borderRadius: 6,
          yAxisID: 'y'
        }},
        {{
          label: 'Energy (kWh)',
          data: kwhData,
          type: 'line',
          borderColor: '#F59E0B',
          backgroundColor: 'rgba(245, 158, 11, 0.1)',
          borderWidth: 2.5,
          tension: 0.35,
          pointRadius: 3,
          yAxisID: 'y1'
        }}
      ]
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{ labels: {{ color: '#9CA3AF' }} }}
      }},
      scales: {{
        x: {{
          ticks: {{ color: '#6B7280', maxRotation: 45 }},
          grid: {{ color: 'rgba(255, 255, 255, 0.04)' }}
        }},
        y: {{
          type: 'linear',
          position: 'left',
          title: {{ display: true, text: 'Spend ($)', color: '#06B6D4' }},
          ticks: {{ color: '#9CA3AF' }},
          grid: {{ color: 'rgba(255, 255, 255, 0.05)' }}
        }},
        y1: {{
          type: 'linear',
          position: 'right',
          title: {{ display: true, text: 'Usage (kWh)', color: '#F59E0B' }},
          ticks: {{ color: '#9CA3AF' }},
          grid: {{ drawOnChartArea: false }}
        }}
      }}
    }}
  }});

  // 2. TOU Donut Chart
  const touCtx = document.getElementById('touChart').getContext('2d');
  new Chart(touCtx, {{
    type: 'doughnut',
    data: {{
      labels: ['Off-Peak (All Other Hours)', 'Peak (4-9 PM)'],
      datasets: [{{
        data: [trends.summary.total_off_peak_kwh || 80, trends.summary.total_peak_kwh || 20],
        backgroundColor: ['rgba(6, 182, 212, 0.8)', 'rgba(245, 158, 11, 0.8)'],
        borderColor: '#111827',
        borderWidth: 3
      }}]
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      plugins: {{
        legend: {{ position: 'bottom', labels: {{ color: '#9CA3AF' }} }}
      }}
    }}
  }});

  // 3. Year-over-Year Comparison Chart
  const yoyCtx = document.getElementById('yoyChart').getContext('2d');
  const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const yearlyDatasets = [];
  const colors = {{
    '2024': '#9CA3AF',
    '2025': '#3B82F6',
    '2026': '#10B981'
  }};

  Object.keys(trends.yearly || {{}}).sort().forEach(year => {{
    yearlyDatasets.push({{
      label: year + ' Spend ($)',
      data: trends.yearly[year].monthly_spend,
      borderColor: colors[year] || '#8B5CF6',
      backgroundColor: (colors[year] || '#8B5CF6') + '22',
      borderWidth: 2.5,
      tension: 0.3,
      fill: false,
      pointRadius: 4
    }});
  }});

  new Chart(yoyCtx, {{
    type: 'line',
    data: {{
      labels: monthNames,
      datasets: yearlyDatasets
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{ labels: {{ color: '#9CA3AF' }} }}
      }},
      scales: {{
        x: {{ ticks: {{ color: '#6B7280' }}, grid: {{ color: 'rgba(255, 255, 255, 0.04)' }} }},
        y: {{ ticks: {{ color: '#9CA3AF' }}, grid: {{ color: 'rgba(255, 255, 255, 0.05)' }} }}
      }}
    }}
  }});

  // 4. CARE Subsidy Savings Chart
  const careCtx = document.getElementById('careChart').getContext('2d');
  const recentRecords = records.filter(r => r.care_discount > 0);
  new Chart(careCtx, {{
    type: 'bar',
    data: {{
      labels: recentRecords.map(r => r.statement_date),
      datasets: [
        {{
          label: 'CARE Subsidy Savings ($)',
          data: recentRecords.map(r => r.care_discount),
          backgroundColor: 'rgba(16, 185, 129, 0.6)',
          borderColor: '#10B981',
          borderWidth: 1.5,
          borderRadius: 6
        }}
      ]
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      plugins: {{
        legend: {{ labels: {{ color: '#9CA3AF' }} }}
      }},
      scales: {{
        x: {{ ticks: {{ color: '#6B7280' }}, grid: {{ color: 'rgba(255, 255, 255, 0.04)' }} }},
        y: {{ ticks: {{ color: '#9CA3AF' }}, grid: {{ color: 'rgba(255, 255, 255, 0.05)' }} }}
      }}
    }}
  }});
</script>

</body>
</html>
"""
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    log.info(f"Rendered interactive dashboard to {out_path}")


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point for PG&E Statement Intelligence engine."""
    import argparse
    parser = argparse.ArgumentParser(description="PG&E Statement Intelligence & Dashboard Engine")
    parser.add_argument("--statements-dir", type=Path, default=Path(__file__).resolve().parent / "Statements",
                        help="Path to folder containing downloaded PG&E statement PDFs")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent,
                        help="Output directory for generated dashboard and data files")
    parser.add_argument("--no-browser", action="store_true", help="Do not open web browser automatically")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose debug logging")

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    print(f"⚡ PG&E Statement Intelligence Engine")
    print(f"📁 Scanning statements in: {args.statements_dir}")

    records = scan_all_statements(args.statements_dir)
    if not records:
        print(f"⚠️  No statements found or parsed in {args.statements_dir}.")
        return 1

    print(f"✅ Processed {len(records)} statements.")

    trends = compute_yearly_trends(records)
    summary = trends["summary"]
    print(f"📊 Summary:")
    print(f"   • Total Spend: ${summary['total_spend']:,.2f}")
    print(f"   • Avg Monthly: ${summary['avg_monthly_spend']:,.2f}")
    print(f"   • Total Energy: {summary['total_kwh']:,.1f} kWh")
    print(f"   • Total CARE Savings: ${summary['total_care_savings']:,.2f}")

    json_path = args.output_dir / "pge_bill_data.json"
    csv_path = args.output_dir / "pge_bill_data.csv"
    html_path = args.output_dir / "dashboard.html"

    export_to_json(records, trends, json_path)
    export_to_csv(records, csv_path)
    render_dashboard(records, trends, html_path)

    print(f"🚀 Artifacts generated successfully:")
    print(f"   • Dashboard: {html_path}")
    print(f"   • JSON Data: {json_path}")
    print(f"   • CSV Data:  {csv_path}")

    if not args.no_browser:
        print(f"🌐 Opening dashboard in browser...")
        try:
            webbrowser.open(f"file://{html_path.resolve()}")
        except Exception as e:
            log.warning(f"Could not open browser automatically: {e}")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

