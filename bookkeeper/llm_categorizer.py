"""
Claude-based categorizer for transactions that rules couldn't confidently handle.

Batches up to 10 transactions per API call to reduce cost and latency.
Passes the full chart of accounts as context so Claude picks from real accounts.
Uses structured JSON output via tool use for reliable parsing.

NOTE — future AI-provider seam:
    This module imports the `anthropic` SDK directly. If we ever want to swap
    Claude for a different model provider (OpenAI, local Llama, etc.) we will
    need to extract a second protocol (`Categorizer`?) the way we did for
    BookkeepingProvider. Not blocking today; flagged for later.
"""

import anthropic

from .models import Account, CategorizationResult, Transaction

_BATCH_SIZE = 10

_TOOL = {
    "name": "categorize_transactions",
    "description": "Assign an account category and confidence score to each transaction.",
    "input_schema": {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer", "description": "0-based index matching the input list"},
                        "account_name": {"type": "string", "description": "Exact name from the provided chart of accounts, or null if truly unknown"},
                        "confidence": {"type": "number", "description": "0.0–1.0 confidence in this categorization"},
                        "reason": {"type": "string", "description": "One sentence explaining the categorization"},
                    },
                    "required": ["index", "account_name", "confidence", "reason"],
                },
            }
        },
        "required": ["results"],
    },
}


def _account_list_text(accounts: list[Account]) -> str:
    lines = [f"  - {a.name} ({a.account_type})" for a in accounts]
    return "\n".join(lines)


def _txn_summary(i: int, txn: Transaction) -> str:
    return (
        f"[{i}] Date: {txn.txn_date} | Amount: ${txn.amount:.2f} | "
        f"Vendor: {txn.vendor_name!r} | Description: {txn.description!r}"
    )


def _build_prompt(batch: list[Transaction], accounts: list[Account]) -> str:
    txn_lines = "\n".join(_txn_summary(i, t) for i, t in enumerate(batch))
    account_list = _account_list_text(accounts)
    return (
        "You are a bookkeeper for a small architecture/design firm (S-Corp). "
        "Categorize each transaction below using ONLY accounts from the provided chart of accounts.\n\n"
        "If you genuinely cannot determine the category with reasonable confidence, set account_name to null "
        "and confidence to 0.0.\n\n"
        f"CHART OF ACCOUNTS (expense accounts only):\n{account_list}\n\n"
        f"TRANSACTIONS TO CATEGORIZE:\n{txn_lines}"
    )


def _parse_tool_result(
    tool_result: dict,
    batch: list[Transaction],
    account_index: dict[str, Account],
    threshold: float,
) -> list[CategorizationResult]:
    results: list[CategorizationResult] = []
    items = tool_result.get("results", [])

    for item in items:
        idx = item.get("index", -1)
        if idx < 0 or idx >= len(batch):
            continue

        txn = batch[idx]
        account_name = item.get("account_name")
        confidence = float(item.get("confidence", 0.0))
        reason = item.get("reason", "")

        account = account_index.get(account_name.lower()) if account_name else None

        if account is None or confidence < threshold:
            results.append(CategorizationResult(
                transaction=txn,
                suggested_account=account,
                confidence=confidence,
                method="llm",
                reasoning=reason,
                needs_review=True,
                review_reason=(
                    f"LLM confidence {confidence:.0%} below threshold"
                    if account and confidence < threshold
                    else "LLM could not determine category"
                ),
            ))
        else:
            results.append(CategorizationResult(
                transaction=txn,
                suggested_account=account,
                confidence=confidence,
                method="llm",
                reasoning=reason,
                needs_review=False,
            ))

    return results


def run_llm_categorizer(
    transactions: list[Transaction],
    accounts: list[Account],
    account_index: dict[str, Account],
    api_key: str,
    threshold: float,
) -> list[CategorizationResult]:
    if not transactions:
        return []

    client = anthropic.Anthropic(api_key=api_key)
    all_results: list[CategorizationResult] = []

    for batch_start in range(0, len(transactions), _BATCH_SIZE):
        batch = transactions[batch_start: batch_start + _BATCH_SIZE]

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": "categorize_transactions"},
            messages=[{"role": "user", "content": _build_prompt(batch, accounts)}],
        )

        tool_result = {}
        for block in response.content:
            if block.type == "tool_use" and block.name == "categorize_transactions":
                tool_result = block.input
                break

        batch_results = _parse_tool_result(tool_result, batch, account_index, threshold)

        # If parsing produced fewer results than the batch (malformed response),
        # fill in needs_review for any missing transactions.
        returned_indices = {r.transaction.id for r in batch_results}
        for txn in batch:
            if txn.id not in returned_indices:
                batch_results.append(CategorizationResult(
                    transaction=txn,
                    suggested_account=None,
                    confidence=0.0,
                    method="llm",
                    reasoning="No response from LLM for this transaction.",
                    needs_review=True,
                    review_reason="LLM did not return a result — categorize manually.",
                ))

        all_results.extend(batch_results)

    return all_results
