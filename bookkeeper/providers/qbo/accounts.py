"""Chart-of-accounts fetcher for QBO. Provider-internal."""

from ...models import Account
from .client import QBOClient

_CATEGORIZABLE_CLASSIFICATIONS = {"Expense", "Cost of Goods Sold", "Other Expense"}


def fetch_accounts(client: QBOClient) -> list[Account]:
    rows = client.query("SELECT * FROM Account WHERE Active = true")
    accounts: list[Account] = []
    for row in rows:
        classification = row.get("Classification", "")
        if classification not in _CATEGORIZABLE_CLASSIFICATIONS:
            continue
        accounts.append(Account(
            id=row["Id"],
            name=row["Name"],
            account_type=row.get("AccountType", ""),
            account_sub_type=row.get("AccountSubType", ""),
            fully_qualified_name=row.get("FullyQualifiedName", row["Name"]),
        ))
    return accounts
