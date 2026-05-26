"""
Fetches uncategorized transactions from two QBO sources:

  1. Bank feed ("For Review") via the QBO Banking API.
  2. Purchase records already on the books but mapped to an
     "Uncategorized Expense" or "Ask My Accountant" account.

Returns _FetchedTxn pairs: a domain Transaction (opaque id) plus the
provider-internal state needed to round-trip back at apply time.

The provider class consumes these, stashes the state in its private cache,
and returns only the Transaction list to the orchestrator.
"""

import uuid
from dataclasses import dataclass
from typing import Literal

from ...domain import is_uncategorized
from ...models import Transaction
from .client import QBOClient


@dataclass
class _FetchedTxn:
    """Internal: a fetched transaction plus the provider state needed for apply."""
    transaction: Transaction
    qbo_id: str
    source_kind: Literal["bank_feed", "expense_record"]
    raw: dict


def _normalize_bank_feed_item(item: dict) -> _FetchedTxn:
    qbo_id = item["Id"]
    amount = abs(float(item.get("Amount", 0)))
    description = item.get("Description", "") or item.get("Memo", "")
    payee = item.get("PayeeName", "") or description
    txn = Transaction(
        id=str(uuid.uuid4()),
        txn_date=item.get("TxnDate", ""),
        amount=amount,
        description=description,
        vendor_name=payee,
        current_account_id=None,
        current_account_name=None,
        source="imported",
    )
    return _FetchedTxn(transaction=txn, qbo_id=qbo_id, source_kind="bank_feed", raw=item)


def _normalize_purchase(row: dict) -> _FetchedTxn:
    qbo_id = row["Id"]
    amount = abs(float(row.get("TotalAmt", 0)))

    payee = ""
    entity = row.get("EntityRef", {})
    if entity:
        payee = entity.get("name", "")

    description = ""
    account_id = None
    account_name = None
    for line in row.get("Line", []):
        if line.get("DetailType") == "AccountBasedExpenseLineDetail":
            detail = line.get("AccountBasedExpenseLineDetail", {})
            account_ref = detail.get("AccountRef", {})
            account_id = account_ref.get("value")
            account_name = account_ref.get("name")
            description = line.get("Description", "") or description
            break

    if not description:
        description = row.get("PrivateNote", "") or row.get("DocNumber", "")

    txn = Transaction(
        id=str(uuid.uuid4()),
        txn_date=row.get("TxnDate", ""),
        amount=amount,
        description=description,
        vendor_name=payee or description,
        current_account_id=account_id,
        current_account_name=account_name,
        source="manual",
    )
    return _FetchedTxn(transaction=txn, qbo_id=qbo_id, source_kind="expense_record", raw=row)


def fetch_bank_feed_transactions(client: QBOClient) -> list[_FetchedTxn]:
    """Pull unprocessed bank feed items.

    Requires the com.intuit.quickbooks.banking OAuth scope. If unavailable,
    returns an empty list with a warning rather than failing the whole run.
    """
    results: list[_FetchedTxn] = []
    start = 1
    page_size = 200

    while True:
        try:
            data = client.get(
                "/banktransaction",
                params={"startPosition": start, "maxResults": page_size, "minorversion": 65},
            )
        except Exception as e:
            print(f"  [warn] Banking API unavailable ({e}). Skipping bank feed source.")
            return []

        items = data.get("BankTransactionList", {}).get("BankTransaction", [])
        if not items:
            break

        for item in items:
            if not item.get("Processed", False):
                results.append(_normalize_bank_feed_item(item))

        if len(items) < page_size:
            break
        start += page_size

    return results


def fetch_uncategorized_expense_records(client: QBOClient, since_date: str) -> list[_FetchedTxn]:
    """Pull Purchase records mapped to an uncategorized account."""
    results: list[_FetchedTxn] = []
    rows = client.query(
        f"SELECT * FROM Purchase WHERE TxnDate >= '{since_date}' ORDER BY TxnDate DESC"
    )
    for row in rows:
        for line in row.get("Line", []):
            if line.get("DetailType") != "AccountBasedExpenseLineDetail":
                continue
            detail = line.get("AccountBasedExpenseLineDetail", {})
            acct_name = detail.get("AccountRef", {}).get("name", "")
            if is_uncategorized(acct_name):
                results.append(_normalize_purchase(row))
                break
    return results


def fetch_all_uncategorized(client: QBOClient, since_date: str) -> list[_FetchedTxn]:
    """Both sources, deduplicated by QBO id within each source kind."""
    bank_feed = fetch_bank_feed_transactions(client)
    expense_records = fetch_uncategorized_expense_records(client, since_date)

    seen: set[tuple[str, str]] = set()
    merged: list[_FetchedTxn] = []
    for ft in bank_feed + expense_records:
        key = (ft.source_kind, ft.qbo_id)
        if key not in seen:
            seen.add(key)
            merged.append(ft)
    return merged
