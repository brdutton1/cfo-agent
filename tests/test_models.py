"""Domain types — no QBO contamination, no raw field, correct literals."""

import dataclasses

from bookkeeper.models import (
    Account,
    AnomalyFlag,
    ApplicationResult,
    CategorizationResult,
    Transaction,
)


def test_transaction_has_no_raw_field():
    fields = {f.name for f in dataclasses.fields(Transaction)}
    assert "raw" not in fields, "Transaction.raw should be excised"


def test_transaction_source_uses_provider_neutral_literals():
    t = Transaction(
        id="t-1",
        txn_date="2026-05-20",
        amount=10.0,
        description="x",
        vendor_name="y",
        current_account_id=None,
        current_account_name=None,
        source="imported",
    )
    assert t.source == "imported"

    t2 = dataclasses.replace(t, source="manual")
    assert t2.source == "manual"


def test_transaction_id_is_opaque_no_required_prefix():
    # IDs are opaque strings — no convention enforced by the type
    t = Transaction(
        id="this-can-be-anything",
        txn_date="2026-05-20",
        amount=10.0,
        description="",
        vendor_name="",
        current_account_id=None,
        current_account_name=None,
        source="imported",
    )
    assert t.id == "this-can-be-anything"


def test_account_fields():
    a = Account(
        id="1",
        name="Office Supplies",
        account_type="Expense",
        account_sub_type="SuppliesMaterials",
        fully_qualified_name="Office Supplies",
    )
    assert a.id == "1"
    assert a.name == "Office Supplies"


def test_categorization_result_needs_review_default_optional_reason():
    t = Transaction("t", "2026-05-20", 1.0, "", "", None, None, "imported")
    r = CategorizationResult(
        transaction=t,
        suggested_account=None,
        confidence=0.5,
        method="llm",
        reasoning="x",
        needs_review=True,
    )
    assert r.review_reason is None
    assert r.needs_review is True


def test_anomaly_flag_fields():
    f = AnomalyFlag(transaction_id="t-1", flag_type="duplicate", detail="x")
    assert f.flag_type == "duplicate"


def test_application_result_success_default():
    r = ApplicationResult(transaction_id="t-1", success=True)
    assert r.error is None
