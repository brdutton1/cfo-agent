"""
Shared test fixtures and the in-memory provider used by the deletion proof.

The MemoryProvider here is intentionally simple — about 25 lines — to prove
that the BookkeepingProvider Protocol is genuinely the only API the domain
needs.
"""

import json
import pathlib

import pytest

from bookkeeper.models import Account, ApplicationResult, Transaction
from bookkeeper.provider import BookkeepingProvider

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def accounts_data() -> list[Account]:
    raw = json.loads((FIXTURES_DIR / "accounts.json").read_text())
    return [Account(**row) for row in raw]


@pytest.fixture
def transactions_data() -> list[Transaction]:
    raw = json.loads((FIXTURES_DIR / "transactions.json").read_text())
    return [Transaction(**row) for row in raw]


class MemoryProvider:
    """An in-memory BookkeepingProvider for tests and the deletion proof.

    Tracks applied categories so tests can verify what would have been
    written to a real backend.
    """

    def __init__(self, accounts: list[Account], transactions: list[Transaction]):
        self._accounts = list(accounts)
        self._transactions = list(transactions)
        self.applied: dict[str, str] = {}  # txn_id -> account_id
        self.fetch_uncategorized_calls: int = 0
        self.fail_apply_for: set[str] = set()  # txn ids to simulate failure on

    def fetch_accounts(self) -> list[Account]:
        return list(self._accounts)

    def fetch_uncategorized(self, since: str) -> list[Transaction]:
        self.fetch_uncategorized_calls += 1
        return [t for t in self._transactions if t.txn_date >= since]

    def apply_category(
        self,
        txn: Transaction,
        account: Account,
    ) -> ApplicationResult:
        if txn.id in self.fail_apply_for:
            return ApplicationResult(
                transaction_id=txn.id, success=False, error="simulated failure"
            )
        self.applied[txn.id] = account.id
        return ApplicationResult(transaction_id=txn.id, success=True)


@pytest.fixture
def memory_provider(accounts_data, transactions_data) -> BookkeepingProvider:
    return MemoryProvider(accounts=accounts_data, transactions=transactions_data)
