"""Reporter — formats output correctly without crashing on edge cases."""

from io import StringIO
from unittest.mock import patch

from bookkeeper.models import (
    Account,
    AnomalyFlag,
    ApplicationResult,
    CategorizationResult,
    Transaction,
)
from bookkeeper.reporter import print_report


def _account(name="Cloud Services"):
    return Account(
        id="1",
        name=name,
        account_type="Expense",
        account_sub_type="OfficeGeneralAdministrativeExpenses",
        fully_qualified_name=name,
    )


def _txn(txn_id="t-1", vendor="AWS"):
    return Transaction(
        id=txn_id,
        txn_date="2026-05-20",
        amount=42.00,
        description="x",
        vendor_name=vendor,
        current_account_id=None,
        current_account_name=None,
        source="imported",
    )


def _capture_report(**kwargs):
    out = StringIO()
    with patch("sys.stdout", out):
        print_report(**kwargs)
    return out.getvalue()


def test_renders_with_only_auto_categorized():
    auto = CategorizationResult(
        transaction=_txn(),
        suggested_account=_account(),
        confidence=0.95,
        method="rule",
        reasoning="r",
        needs_review=False,
    )
    text = _capture_report(
        company_name="ACo",
        since_date="2026-05-19",
        total_fetched=1,
        categorization_results=[auto],
        anomaly_flags=[],
        application_results=[ApplicationResult("t-1", True)],
        dry_run=False,
    )
    assert "AUTO-CATEGORIZED" in text
    assert "Cloud Services" in text
    assert "AWS" in text
    assert "1 applied" in text


def test_renders_with_only_needs_review():
    item = CategorizationResult(
        transaction=_txn(vendor="Mystery"),
        suggested_account=None,
        confidence=0.30,
        method="llm",
        reasoning="not sure",
        needs_review=True,
        review_reason="LLM unsure",
    )
    text = _capture_report(
        company_name="ACo",
        since_date="2026-05-19",
        total_fetched=1,
        categorization_results=[item],
        anomaly_flags=[],
        application_results=[],
        dry_run=False,
    )
    assert "NEEDS YOUR REVIEW" in text
    assert "Mystery" in text
    assert "LLM unsure" in text


def test_renders_anomaly_flags():
    auto = CategorizationResult(
        transaction=_txn(),
        suggested_account=_account(),
        confidence=1.0,
        method="rule",
        reasoning="",
        needs_review=False,
    )
    flags = [AnomalyFlag(transaction_id="t-1", flag_type="duplicate", detail="dup detail")]
    text = _capture_report(
        company_name="ACo",
        since_date="2026-05-19",
        total_fetched=1,
        categorization_results=[auto],
        anomaly_flags=flags,
        application_results=[ApplicationResult("t-1", True)],
        dry_run=False,
    )
    assert "ANOMALY FLAGS" in text
    assert "[DUPE]" in text
    assert "dup detail" in text


def test_renders_write_errors():
    auto = CategorizationResult(
        transaction=_txn(),
        suggested_account=_account(),
        confidence=1.0,
        method="rule",
        reasoning="",
        needs_review=False,
    )
    text = _capture_report(
        company_name="ACo",
        since_date="2026-05-19",
        total_fetched=1,
        categorization_results=[auto],
        anomaly_flags=[],
        application_results=[ApplicationResult("t-1", False, error="permission denied")],
        dry_run=False,
    )
    assert "WRITE ERRORS" in text
    assert "permission denied" in text


def test_dry_run_header():
    text = _capture_report(
        company_name="ACo",
        since_date="2026-05-19",
        total_fetched=0,
        categorization_results=[],
        anomaly_flags=[],
        application_results=[],
        dry_run=True,
    )
    assert "DRY RUN" in text


def test_empty_run_does_not_crash():
    text = _capture_report(
        company_name="ACo",
        since_date="2026-05-19",
        total_fetched=0,
        categorization_results=[],
        anomaly_flags=[],
        application_results=[],
        dry_run=False,
    )
    assert "Transactions fetched:" in text
