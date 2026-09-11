"""Unit tests for PG&E Statement Intelligence extraction and analytics."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pge_intel import parse_statement_pdf, PgeStatementRecord


def test_parse_real_statement_pdf():
    pdf_path = Path(__file__).resolve().parents[1] / "Statements" / "2026-09-08 PG&E Energy Statement PG&E.pdf"
    if not pdf_path.exists():
        pytest.skip("Sample statement PDF not present")
    record = parse_statement_pdf(pdf_path)
    assert record is not None
    assert record.account_number == "5922868370-8"
    assert record.statement_date == "2026-09-08"
    assert record.due_date == "2026-09-29"
    assert record.billing_days == 32
    assert record.current_electric_charges == 49.96
    assert record.care_discount == 62.05
    assert record.total_kwh == pytest.approx(199.31, rel=1e-2)
    assert record.rate_schedule == "E-TOU-C"
    assert record.peak_kwh > 0
    assert record.off_peak_kwh > 0
    assert record.peak_rate > 0
    assert record.off_peak_rate > 0


def test_scan_and_compute_trends(tmp_path):
    from pge_intel import scan_all_statements, compute_yearly_trends, export_to_json, export_to_csv, render_dashboard

    stmts_dir = Path(__file__).resolve().parents[1] / "Statements"
    if not stmts_dir.exists():
        pytest.skip("Statements directory not present")

    records = scan_all_statements(stmts_dir)
    assert len(records) >= 10
    # Verify sorted chronologically
    dates = [r.statement_date for r in records if r.statement_date]
    assert dates == sorted(dates)

    trends = compute_yearly_trends(records)
    assert "yearly" in trends
    assert "summary" in trends
    assert "2026" in trends["yearly"]
    assert trends["summary"]["total_spend"] > 0
    assert trends["summary"]["statement_count"] == len(records)

    # Test exports
    json_path = tmp_path / "test_data.json"
    csv_path = tmp_path / "test_data.csv"
    html_path = tmp_path / "test_dashboard.html"

    export_to_json(records, trends, json_path)
    assert json_path.exists()
    assert json_path.stat().st_size > 100

    export_to_csv(records, csv_path)
    assert csv_path.exists()
    assert csv_path.stat().st_size > 100

    render_dashboard(records, trends, html_path)
    assert html_path.exists()
    content = html_path.read_text(encoding="utf-8")
    assert "PG&amp;E" in content or "PG&E" in content
    assert "Chart.js" in content or "chart.js" in content
    assert "5922868370-8" in content

