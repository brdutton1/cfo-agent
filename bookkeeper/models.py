from dataclasses import dataclass, field
from typing import Literal


@dataclass
class Account:
    id: str
    name: str
    account_type: str       # e.g. "Expense", "Cost of Goods Sold"
    account_sub_type: str   # e.g. "AdvertisingPromotional"
    fully_qualified_name: str


@dataclass
class Transaction:
    id: str
    txn_date: str           # YYYY-MM-DD
    amount: float           # positive = expense/debit
    description: str
    vendor_name: str
    current_account_id: str | None
    current_account_name: str | None
    source: Literal["bank_feed", "expense_record"]
    raw: dict = field(default_factory=dict, repr=False)


@dataclass
class CategorizationResult:
    transaction: Transaction
    suggested_account: Account | None
    confidence: float
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
