"""LLM categorizer — mocks anthropic at the SDK boundary."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from bookkeeper.domain import build_account_index
from bookkeeper.llm_categorizer import run_llm_categorizer
from bookkeeper.models import Transaction


def _txn(txn_id, vendor, amount=10.0):
    return Transaction(
        id=txn_id,
        txn_date="2026-05-20",
        amount=amount,
        description=vendor,
        vendor_name=vendor,
        current_account_id=None,
        current_account_name=None,
        source="imported",
    )


def _tool_use_response(results):
    return SimpleNamespace(
        content=[
            SimpleNamespace(
                type="tool_use",
                name="categorize_transactions",
                input={"results": results},
            )
        ]
    )


def test_empty_input_returns_empty(accounts_data):
    idx = build_account_index(accounts_data)
    result = run_llm_categorizer(
        transactions=[],
        accounts=accounts_data,
        account_index=idx,
        api_key="fake",
        threshold=0.9,
    )
    assert result == []


def test_high_confidence_match_passes(accounts_data):
    idx = build_account_index(accounts_data)
    txns = [_txn("t-1", "Mystery Vendor")]
    with patch("bookkeeper.llm_categorizer.anthropic.Anthropic") as mock_client:
        instance = MagicMock()
        instance.messages.create.return_value = _tool_use_response([
            {"index": 0, "account_name": "Software Subscriptions", "confidence": 0.95, "reason": "looks like saas"}
        ])
        mock_client.return_value = instance
        results = run_llm_categorizer(
            transactions=txns,
            accounts=accounts_data,
            account_index=idx,
            api_key="fake",
            threshold=0.90,
        )

    assert len(results) == 1
    assert results[0].suggested_account.name == "Software Subscriptions"
    assert results[0].needs_review is False
    assert results[0].confidence == 0.95


def test_below_threshold_flagged_for_review(accounts_data):
    idx = build_account_index(accounts_data)
    txns = [_txn("t-1", "Confusing Vendor")]
    with patch("bookkeeper.llm_categorizer.anthropic.Anthropic") as mock_client:
        instance = MagicMock()
        instance.messages.create.return_value = _tool_use_response([
            {"index": 0, "account_name": "Software Subscriptions", "confidence": 0.55, "reason": "guess"}
        ])
        mock_client.return_value = instance
        results = run_llm_categorizer(
            transactions=txns,
            accounts=accounts_data,
            account_index=idx,
            api_key="fake",
            threshold=0.90,
        )

    assert results[0].needs_review is True
    assert "below threshold" in (results[0].review_reason or "").lower()


def test_unknown_account_in_llm_response_flagged(accounts_data):
    idx = build_account_index(accounts_data)
    txns = [_txn("t-1", "v")]
    with patch("bookkeeper.llm_categorizer.anthropic.Anthropic") as mock_client:
        instance = MagicMock()
        instance.messages.create.return_value = _tool_use_response([
            {"index": 0, "account_name": "Account That Does Not Exist", "confidence": 1.0, "reason": "?"}
        ])
        mock_client.return_value = instance
        results = run_llm_categorizer(
            transactions=txns,
            accounts=accounts_data,
            account_index=idx,
            api_key="fake",
            threshold=0.90,
        )

    assert results[0].needs_review is True
    assert results[0].suggested_account is None


def test_missing_llm_result_filled_as_needs_review(accounts_data):
    idx = build_account_index(accounts_data)
    txns = [_txn("t-1", "a"), _txn("t-2", "b")]
    with patch("bookkeeper.llm_categorizer.anthropic.Anthropic") as mock_client:
        instance = MagicMock()
        # Only returns a result for index 0
        instance.messages.create.return_value = _tool_use_response([
            {"index": 0, "account_name": "Software Subscriptions", "confidence": 0.95, "reason": ""}
        ])
        mock_client.return_value = instance
        results = run_llm_categorizer(
            transactions=txns,
            accounts=accounts_data,
            account_index=idx,
            api_key="fake",
            threshold=0.90,
        )

    by_id = {r.transaction.id: r for r in results}
    assert by_id["t-1"].needs_review is False
    assert by_id["t-2"].needs_review is True
    assert "did not return" in by_id["t-2"].review_reason.lower() or \
           "no response" in by_id["t-2"].reasoning.lower()


def test_batching_called_correct_number_of_times(accounts_data):
    # 23 transactions → 3 batches at batch size 10
    idx = build_account_index(accounts_data)
    txns = [_txn(f"t-{i}", f"v{i}") for i in range(23)]
    with patch("bookkeeper.llm_categorizer.anthropic.Anthropic") as mock_client:
        instance = MagicMock()

        def respond(**kwargs):
            content = kwargs["messages"][0]["content"]
            # count [N] markers in the prompt to size the response
            n = content.count("] Date:")
            return _tool_use_response([
                {"index": i, "account_name": "Software Subscriptions", "confidence": 0.95, "reason": ""}
                for i in range(n)
            ])

        instance.messages.create.side_effect = lambda **kw: respond(**kw)
        mock_client.return_value = instance
        results = run_llm_categorizer(
            transactions=txns,
            accounts=accounts_data,
            account_index=idx,
            api_key="fake",
            threshold=0.90,
        )

    assert instance.messages.create.call_count == 3  # 10 + 10 + 3
    assert len(results) == 23
