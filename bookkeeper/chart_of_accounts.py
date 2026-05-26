"""
Fetches and caches the Chart of Accounts for the current run.
Only expense-side accounts are returned to the categorizer.
"""

from .models import Account
from .qbo_client import QBOClient

_EXPENSE_CLASSIFICATIONS = {"Expense", "Cost of Goods Sold", "Other Expense"}

# These are QBO system accounts used for "I don't know yet" — we exclude them
# from suggested categories but use them to identify uncategorized records.
UNCATEGORIZED_ACCOUNT_NAMES = {
    "uncategorized expense",
    "ask my accountant",
    "uncategorized asset",
}


def fetch_accounts(client: QBOClient) -> list[Account]:
    rows = client.query("SELECT * FROM Account WHERE Active = true")
    accounts = []
    for row in rows:
        classification = row.get("Classification", "")
        if classification not in _EXPENSE_CLASSIFICATIONS:
            continue
        accounts.append(Account(
            id=row["Id"],
            name=row["Name"],
            account_type=row.get("AccountType", ""),
            account_sub_type=row.get("AccountSubType", ""),
            fully_qualified_name=row.get("FullyQualifiedName", row["Name"]),
        ))
    return accounts


def build_account_index(accounts: list[Account]) -> dict[str, Account]:
    """Return a dict keyed by lowercase account name for fast lookup."""
    return {a.name.lower(): a for a in accounts}


def is_uncategorized(account_name: str | None) -> bool:
    if not account_name:
        return True
    return account_name.lower() in UNCATEGORIZED_ACCOUNT_NAMES
