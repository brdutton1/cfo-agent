"""
Domain types. No imports from any provider, HTTP, OAuth, or storage layer.

The fields here describe bookkeeping concepts in provider-neutral terms.
Crucially, there is no `raw` field carrying a vendor-specific payload — the
provider keeps any state it needs in its own private cache, keyed by
Transaction.id.
"""

from dataclasses import dataclass
from typing import Literal


@dataclass
class Account:
    """A categorizable account in the books (an expense category, COGS line, etc)."""
    id: str
    name: str
    account_type: str        # broad classification ("Expense", "Cost of Goods Sold")
    account_sub_type: str    # finer classification ("AdvertisingPromotional", ...)
    fully_qualified_name: str


@dataclass
class Transaction:
    """An uncategorized money movement awaiting a category assignment.

    `id` is an opaque domain identifier. Providers maintain their own mapping
    from this id to whatever internal handle (record id, sync token, payload)
    they need to round-trip back at apply time.

    `source` distinguishes feed-imported from manually-entered transactions.
    Providers do NOT route on this field; it is here so the domain layer
    (reporter, anomaly) can describe transactions to the human.
    """
    id: str
    txn_date: str             # YYYY-MM-DD
    amount: float             # positive = expense/debit
    description: str
    vendor_name: str
    current_account_id: str | None
    current_account_name: str | None
    source: Literal["imported", "manual"]


@dataclass
class CategorizationResult:
    transaction: Transaction
    suggested_account: Account | None
    confidence: float                              # 0.0–1.0
    method: Literal["rule", "llm", "none"]
    reasoning: str
    needs_review: bool
    review_reason: str | None = None


@dataclass
class AnomalyFlag:
    transaction_id: str
    flag_type: Literal["duplicate", "first_time_vendor", "spike"]
    detail: str


@dataclass
class ApplicationResult:
    transaction_id: str
    success: bool
    error: str | None = None
