"""
QBOProvider — implements bookkeeping.provider.BookkeepingProvider against
QuickBooks Online.

The class holds a private state dict keyed by the opaque domain transaction
id; that dict carries everything provider-specific (real QBO id, sync token,
source-routing kind, raw payload). The domain layer never sees this dict
and never inspects its contents.
"""

from dataclasses import dataclass
from typing import Literal

from ...models import Account, ApplicationResult, Transaction
from ...provider import ProviderError
from .accounts import fetch_accounts as _fetch_accounts
from .applier import apply_bank_feed_item, apply_expense_record
from .auth import AuthError, get_valid_token
from .client import QBOClient, QBOError
from .config import Config, load_config
from .fetcher import fetch_all_uncategorized


@dataclass
class _TxnState:
    """Provider-private state for a single transaction."""
    qbo_id: str
    source_kind: Literal["bank_feed", "expense_record"]
    raw: dict


class QBOProvider:
    """Concrete provider. Constructed via build_qbo_provider() from env config."""

    def __init__(self, config: Config):
        self._config = config
        try:
            token = get_valid_token(config)
        except AuthError as e:
            raise ProviderError(f"QBO authorization failed: {e}") from e
        self._client = QBOClient(config, token)
        self._state: dict[str, _TxnState] = {}

    def fetch_accounts(self) -> list[Account]:
        try:
            return _fetch_accounts(self._client)
        except QBOError as e:
            raise ProviderError(f"QBO chart-of-accounts fetch failed: {e}") from e

    def fetch_uncategorized(self, since: str) -> list[Transaction]:
        try:
            fetched = fetch_all_uncategorized(self._client, since)
        except QBOError as e:
            raise ProviderError(f"QBO transaction fetch failed: {e}") from e

        out: list[Transaction] = []
        for ft in fetched:
            self._state[ft.transaction.id] = _TxnState(
                qbo_id=ft.qbo_id,
                source_kind=ft.source_kind,
                raw=ft.raw,
            )
            out.append(ft.transaction)
        return out

    def apply_category(
        self,
        txn: Transaction,
        account: Account,
    ) -> ApplicationResult:
        state = self._state.get(txn.id)
        if state is None:
            return ApplicationResult(
                transaction_id=txn.id,
                success=False,
                error=(
                    "No provider state for this transaction id — "
                    "apply_category called before fetch_uncategorized?"
                ),
            )

        if state.source_kind == "bank_feed":
            return apply_bank_feed_item(
                self._client, txn, account, raw=state.raw, qbo_id=state.qbo_id
            )
        if state.source_kind == "expense_record":
            return apply_expense_record(self._client, txn, account, raw=state.raw)

        return ApplicationResult(
            transaction_id=txn.id,
            success=False,
            error=f"Unknown internal source_kind: {state.source_kind!r}",
        )


def build_qbo_provider() -> QBOProvider:
    return QBOProvider(load_config())
