"""
Fetches uncategorized transactions from two QBO sources:

  1. Bank feed ("For Review") via the QBO Banking API.
     These are transactions that arrived via connected bank/card feeds
     but haven't been added to the books yet.

  2. Purchase/Expense records already in the books but mapped to an
     "Uncategorized Expense" or "Ask My Accountant" account.

Results are normalized into Transaction dataclasses and deduplicated by ID.
"""

from .chart_of_accounts import UNCATEGORIZED_ACCOUNT_NAMES, is_uncategorized
from .models import Transaction
from .qbo_client import QBOClient


def _normalize_bank_feed_item(item: dict) -> Transaction:
    amount = abs(float(item.get("Amount", 0)))
    description = item.get("Description", "") or item.get("Memo", "")
    payee = item.get("PayeeName", "") or description
    return Transaction(
        id=f"bf_{item['Id']}",
        txn_date=item.get("TxnDate", ""),
        amount=amount,
        description=description,
        vendor_name=payee,
        current_account_id=None,
        current_account_name=None,
        source="bank_feed",
        raw=item,
    )


def _normalize_purchase(row: dict) -> Transaction:
    amount = abs(float(row.get("TotalAmt", 0)))

    payee = ""
    entity = row.get("EntityRef", {})
    if entity:
        payee = entity.get("name", "")

    lines = row.get("Line", [])
    description = ""
    account_id = None
    account_name = None

    for line in lines:
        if line.get("DetailType") == "AccountBasedExpenseLineDetail":
            detail = line.get("AccountBasedExpenseLineDetail", {})
            account_ref = detail.get("AccountRef", {})
            account_id = account_ref.get("value")
            account_name = account_ref.get("name")
            description = line.get("Description", "") or description
            break

    if not description:
        description = row.get("PrivateNote", "") or row.get("DocNumber", "")

    return Transaction(
        id=f"pur_{row['Id']}",
        txn_date=row.get("TxnDate", ""),
        amount=amount,
        description=description,
        vendor_name=payee or description,
        current_account_id=account_id,
        current_account_name=account_name,
        source="expense_record",
        raw=row,
    )


def fetch_bank_feed_transactions(client: QBOClient) -> list[Transaction]:
    """
    Fetch unprocessed bank feed items from the QBO Banking API.

    The Banking API endpoint is separate from the main Accounting API.
    QBO returns items that are in the "For Review" state (not yet added to the books).

    NOTE: This endpoint requires the com.intuit.quickbooks.banking OAuth scope.
    If your app does not have that scope, this will return an empty list and
    log a warning — the agent will still process expense_record uncategorized items.
    """
    results = []
    start = 1
    page_size = 200

    while True:
        try:
            data = client.get(
                "/banktransaction",
                params={
                    "startPosition": start,
                    "maxResults": page_size,
                    "minorversion": 65,
                },
            )
        except Exception as e:
            # Banking scope may not be enabled; degrade gracefully
            print(f"  [warn] Banking API unavailable ({e}). Skipping bank feed source.")
            return []

        items = data.get("BankTransactionList", {}).get("BankTransaction", [])
        if not items:
            break

        for item in items:
            # Only include unprocessed (For Review) items
            if not item.get("Processed", False):
                results.append(_normalize_bank_feed_item(item))

        if len(items) < page_size:
            break
        start += page_size

    return results


def fetch_uncategorized_expense_records(client: QBOClient, since_date: str) -> list[Transaction]:
    """
    Fetch Purchase records that are mapped to an uncategorized account.
    These are expenses that were 'added' from the bank feed or entered manually
    but never properly categorized.
    """
    results = []

    # Query all recent purchases and filter client-side by account name.
    # QBO's query language doesn't support filtering on nested AccountRef names,
    # so we pull all recent records and filter ourselves.
    rows = client.query(
        f"SELECT * FROM Purchase WHERE TxnDate >= '{since_date}' ORDER BY TxnDate DESC"
    )

    for row in rows:
        lines = row.get("Line", [])
        for line in lines:
            if line.get("DetailType") != "AccountBasedExpenseLineDetail":
                continue
            detail = line.get("AccountBasedExpenseLineDetail", {})
            acct_name = detail.get("AccountRef", {}).get("name", "")
            if is_uncategorized(acct_name):
                results.append(_normalize_purchase(row))
                break  # One match per Purchase is enough

    return results


def fetch_all_uncategorized(client: QBOClient, since_date: str) -> list[Transaction]:
    """Merge both sources, deduplicating by transaction ID."""
    bank_feed = fetch_bank_feed_transactions(client)
    expense_records = fetch_uncategorized_expense_records(client, since_date)

    seen: set[str] = set()
    merged: list[Transaction] = []

    for txn in bank_feed + expense_records:
        if txn.id not in seen:
            seen.add(txn.id)
            merged.append(txn)

    return merged
