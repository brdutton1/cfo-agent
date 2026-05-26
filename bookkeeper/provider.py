"""
The seam between the bookkeeping domain and any external system of record
(QuickBooks, Xero, FreshBooks, in-memory test fixtures, ...).

The domain calls only the three methods declared here. The provider handles
all auth, transport, format conversion, and any state needed to round-trip
from fetch to apply.

If a provider-specific concept (a QBO field name, a QBO enum value, an
account-numbering scheme, etc.) ever appears in this file, the seam has
failed. The contract is: domain types in, domain types out.
"""

from typing import Protocol, runtime_checkable

from .models import Account, ApplicationResult, Transaction


class ProviderError(Exception):
    """Raised when the provider cannot satisfy a fetch request (auth, network,
    permission). Apply failures are returned as ApplicationResult(success=False)
    so batch runs continue past individual write errors.
    """


@runtime_checkable
class BookkeepingProvider(Protocol):
    def fetch_accounts(self) -> list[Account]:
        """Return all categorizable expense accounts the provider exposes."""
        ...

    def fetch_uncategorized(self, since: str) -> list[Transaction]:
        """
        Return all uncategorized transactions dated on or after `since`
        (YYYY-MM-DD).

        Any provider-specific state needed to later apply a category to a
        returned transaction (external IDs, sync tokens, payload fragments,
        endpoint hints) MUST be stored inside the provider's own private
        state, keyed by the domain Transaction.id this method emits.
        The domain layer never sees that state.
        """
        ...

    def apply_category(
        self,
        txn: Transaction,
        account: Account,
    ) -> ApplicationResult:
        """
        Write `account` as the category for `txn`. The provider resolves
        `txn.id` against its own internal state to recover whatever it
        needs (real ID, sync token, source-type routing, payload shape).
        """
        ...
