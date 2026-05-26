"""Rule-based categorizer behavior."""

from bookkeeper.domain import build_account_index
from bookkeeper.models import Transaction
from bookkeeper.rules import run_rules


def _txn(vendor="", description="", txn_id="t-1"):
    return Transaction(
        id=txn_id,
        txn_date="2026-05-20",
        amount=10.0,
        description=description,
        vendor_name=vendor,
        current_account_id=None,
        current_account_name=None,
        source="imported",
    )


def test_aws_matches_cloud_services(accounts_data):
    idx = build_account_index(accounts_data)
    result = run_rules(_txn(vendor="AWS"), idx)
    assert result is not None
    assert result.suggested_account.name == "Cloud Services"
    assert result.method == "rule"
    assert result.confidence == 1.0
    assert result.needs_review is False


def test_starbucks_matches_meals(accounts_data):
    idx = build_account_index(accounts_data)
    result = run_rules(_txn(vendor="Starbucks"), idx)
    assert result is not None
    assert result.suggested_account.name == "Meals & Entertainment"


def test_chevron_matches_fuel(accounts_data):
    idx = build_account_index(accounts_data)
    result = run_rules(_txn(vendor="Chevron"), idx)
    assert result.suggested_account.name == "Fuel"


def test_socair_matches_bookkeeping(accounts_data):
    idx = build_account_index(accounts_data)
    result = run_rules(_txn(vendor="Socair Advisors"), idx)
    assert result.suggested_account.name == "Bookkeeping"


def test_unknown_vendor_returns_none(accounts_data):
    idx = build_account_index(accounts_data)
    result = run_rules(_txn(vendor="Definitely Not A Known Vendor"), idx)
    assert result is None


def test_rule_fires_but_account_missing_flags_for_review():
    # Index contains nothing — every match will fail to find its account
    empty_index = {}
    result = run_rules(_txn(vendor="AWS"), empty_index)
    assert result is not None
    assert result.needs_review is True
    assert result.suggested_account is None
    assert "not in chart of accounts" in result.review_reason.lower() or \
           "Add it or update RULES" in (result.review_reason or "")


def test_uber_low_confidence(accounts_data):
    idx = build_account_index(accounts_data)
    result = run_rules(_txn(vendor="Uber"), idx)
    assert result is not None
    # Uber rule is intentionally below 1.0
    assert result.confidence < 1.0


def test_match_uses_both_vendor_and_description(accounts_data):
    idx = build_account_index(accounts_data)
    # Vendor blank, but description triggers a rule
    result = run_rules(_txn(vendor="", description="Payment to AWS"), idx)
    assert result is not None
    assert result.suggested_account.name == "Cloud Services"
