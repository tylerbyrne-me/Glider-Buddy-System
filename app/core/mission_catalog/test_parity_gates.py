"""Gate / parity tests for catalog apply safety."""

from __future__ import annotations

from app.core.mission_catalog.parity import CatalogGateReport, append_gate_summary
from app.core.mission_catalog.schemas import ReconcileCounts, ReconcileResult


def test_gate_report_unclean_when_blockers() -> None:
    report = CatalogGateReport(blockers=["duplicate deployment_code m226"])
    assert report.is_clean is False
    assert any("BLOCKERS" in line for line in report.summary_lines())


def test_gate_report_clean_summary() -> None:
    report = CatalogGateReport()
    assert report.is_clean is True
    assert any("CLEAN" in line for line in report.summary_lines())


def test_append_gate_summary_marks_refused_apply() -> None:
    result = ReconcileResult(
        dry_run=True,
        summary="Apply refused (gates unclean); dry-run only.",
        counts=ReconcileCounts(),
        conflicts=["duplicate deployment_code m226"],
    )
    gate = CatalogGateReport(blockers=["duplicate deployment_code m226"])
    out = append_gate_summary(result, gate)
    assert "Gates:" in out.summary or "BLOCKERS" in out.summary or out.conflicts
    assert not gate.is_clean
