"""
QBO write-back functions. Provider-internal — take a domain Transaction +
Account plus the provider's internal raw payload / id, and POST to QBO.

The Transaction/Account here are domain types but the write-back path is
entirely QBO-specific (Line, SyncToken, AccountBasedExpenseLineDetail, ...).
That is fine and intentional: this file lives behind the seam.
"""

from ...models import Account, ApplicationResult, Transaction
from .client import QBOClient, QBOError


def apply_expense_record(
    client: QBOClient,
    txn: Transaction,
    account: Account,
    raw: dict,
) -> ApplicationResult:
    """Update an existing Purchase record's AccountRef on its expense line."""
    lines = raw.get("Line", [])
    updated_lines: list[dict] = []
    applied = False

    for line in lines:
        if not applied and line.get("DetailType") == "AccountBasedExpenseLineDetail":
            detail = line["AccountBasedExpenseLineDetail"]
            detail["AccountRef"] = {"value": account.id, "name": account.name}
            applied = True
        updated_lines.append(line)

    if not applied:
        return ApplicationResult(
            transaction_id=txn.id,
            success=False,
            error="No AccountBasedExpenseLineDetail found — cannot update.",
        )

    body = {**raw, "Line": updated_lines, "SyncToken": raw.get("SyncToken", "0")}

    try:
        client.post("/purchase", body)
        return ApplicationResult(transaction_id=txn.id, success=True)
    except QBOError as e:
        return ApplicationResult(transaction_id=txn.id, success=False, error=str(e))


def apply_bank_feed_item(
    client: QBOClient,
    txn: Transaction,
    account: Account,
    raw: dict,
    qbo_id: str,
) -> ApplicationResult:
    """Categorize a 'For Review' bank feed item."""
    body = {
        "Id": qbo_id,
        "SyncToken": raw.get("SyncToken", "0"),
        "AccountRef": {"value": account.id, "name": account.name},
        "EntityType": "Vendor",
        "TransactionType": raw.get("TransactionType", "DEBIT"),
    }

    try:
        client.post("/banktransaction", body)
        return ApplicationResult(transaction_id=txn.id, success=True)
    except QBOError as e:
        return ApplicationResult(transaction_id=txn.id, success=False, error=str(e))
