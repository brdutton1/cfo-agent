"""
Writes approved categories back to QBO.

  - bank_feed transactions:  POST to /banktransaction to move them out of "For Review"
  - expense_record items:    POST to /purchase with the updated AccountRef (sparse update)

In --dry-run mode, logs what would be applied without making any API calls.
"""

from .models import ApplicationResult, CategorizationResult
from .qbo_client import QBOClient, QBOError


def _apply_expense_record(client: QBOClient, result: CategorizationResult) -> ApplicationResult:
    """Update an existing Purchase record with the new account category."""
    txn = result.transaction
    raw = txn.raw

    # Build a sparse update: preserve SyncToken and all existing fields,
    # replace the first AccountBasedExpenseLine's AccountRef.
    lines = raw.get("Line", [])
    updated_lines = []
    applied = False

    for line in lines:
        if not applied and line.get("DetailType") == "AccountBasedExpenseLineDetail":
            detail = line["AccountBasedExpenseLineDetail"]
            detail["AccountRef"] = {
                "value": result.suggested_account.id,
                "name": result.suggested_account.name,
            }
            applied = True
        updated_lines.append(line)

    if not applied:
        return ApplicationResult(
            transaction_id=txn.id,
            success=False,
            error="No AccountBasedExpenseLineDetail found in raw transaction — cannot update.",
        )

    body = {
        **raw,
        "Line": updated_lines,
        "SyncToken": raw.get("SyncToken", "0"),
    }

    try:
        client.post("/purchase", body)
        return ApplicationResult(transaction_id=txn.id, success=True)
    except QBOError as e:
        return ApplicationResult(transaction_id=txn.id, success=False, error=str(e))


def _apply_bank_feed_item(client: QBOClient, result: CategorizationResult) -> ApplicationResult:
    """
    Categorize a bank feed "For Review" item by creating a Purchase linked to it.

    The QBO Banking API accepts a PUT to /banktransaction with the EntityType,
    EntityRef, and account assignment to move the item from "For Review" to booked.

    The raw bank feed item ID has the "bf_" prefix stripped to get the QBO ID.
    """
    txn = result.transaction
    qbo_id = txn.id.removeprefix("bf_")
    raw = txn.raw

    body = {
        "Id": qbo_id,
        "SyncToken": raw.get("SyncToken", "0"),
        "AccountRef": {
            "value": result.suggested_account.id,
            "name": result.suggested_account.name,
        },
        "EntityType": "Vendor",
        "TransactionType": raw.get("TransactionType", "DEBIT"),
    }

    try:
        client.post("/banktransaction", body)
        return ApplicationResult(transaction_id=txn.id, success=True)
    except QBOError as e:
        return ApplicationResult(transaction_id=txn.id, success=False, error=str(e))


def apply_categories(
    client: QBOClient,
    approved: list[CategorizationResult],
    dry_run: bool = False,
) -> list[ApplicationResult]:
    results: list[ApplicationResult] = []

    for result in approved:
        txn = result.transaction
        acct = result.suggested_account

        if dry_run:
            print(
                f"  [dry-run] Would apply '{acct.name}' to {txn.id} "
                f"({txn.vendor_name}, ${txn.amount:.2f})"
            )
            results.append(ApplicationResult(transaction_id=txn.id, success=True))
            continue

        if txn.source == "expense_record":
            results.append(_apply_expense_record(client, result))
        else:
            results.append(_apply_bank_feed_item(client, result))

    return results
