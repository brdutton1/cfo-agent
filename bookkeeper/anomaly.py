"""
Stateless anomaly detection over the full set of fetched transactions.

Three checks:
  1. Duplicate — same vendor + same amount within 3 days
  2. First-time vendor over $500 — vendor not seen elsewhere in the fetch window
  3. Spike — charge more than 2x the 30-day average for that vendor

Anomaly flags are advisory: they surface in the report but do not block
auto-categorization of an otherwise confident transaction.
"""

from collections import defaultdict
from datetime import datetime

from .models import AnomalyFlag, Transaction

_DUPLICATE_WINDOW_DAYS = 3
_FIRST_TIME_THRESHOLD = 500.0
_SPIKE_MULTIPLIER = 2.0


def _parse_date(date_str: str) -> datetime | None:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def detect_anomalies(transactions: list[Transaction]) -> list[AnomalyFlag]:
    flags: list[AnomalyFlag] = []

    # --- 1. Duplicates ---
    for i, a in enumerate(transactions):
        date_a = _parse_date(a.txn_date)
        if not date_a:
            continue
        for b in transactions[i + 1:]:
            date_b = _parse_date(b.txn_date)
            if not date_b:
                continue
            if abs((date_a - date_b).days) <= _DUPLICATE_WINDOW_DAYS and a.amount == b.amount:
                vendor_a = a.vendor_name.lower().strip()
                vendor_b = b.vendor_name.lower().strip()
                if vendor_a and vendor_b and vendor_a == vendor_b:
                    flags.append(AnomalyFlag(
                        transaction_id=b.id,
                        flag_type="duplicate",
                        detail=(
                            f"Same vendor ({a.vendor_name!r}) and amount (${a.amount:.2f}) "
                            f"as txn {a.id} within {_DUPLICATE_WINDOW_DAYS} days."
                        ),
                    ))

    # --- 2. First-time vendors over threshold ---
    vendor_counts: dict[str, int] = defaultdict(int)
    for txn in transactions:
        vendor_counts[txn.vendor_name.lower().strip()] += 1

    for txn in transactions:
        key = txn.vendor_name.lower().strip()
        if not key:
            continue
        if vendor_counts[key] == 1 and txn.amount >= _FIRST_TIME_THRESHOLD:
            flags.append(AnomalyFlag(
                transaction_id=txn.id,
                flag_type="first_time_vendor",
                detail=(
                    f"First time seeing vendor {txn.vendor_name!r} in this window "
                    f"with a charge of ${txn.amount:.2f} (>= ${_FIRST_TIME_THRESHOLD:.0f} threshold)."
                ),
            ))

    # --- 3. Spend spikes vs. vendor average ---
    vendor_amounts: dict[str, list[float]] = defaultdict(list)
    for txn in transactions:
        key = txn.vendor_name.lower().strip()
        if key:
            vendor_amounts[key].append(txn.amount)

    for txn in transactions:
        key = txn.vendor_name.lower().strip()
        if not key:
            continue
        amounts = vendor_amounts[key]
        if len(amounts) < 2:
            continue
        avg = sum(amounts) / len(amounts)
        if avg > 0 and txn.amount >= avg * _SPIKE_MULTIPLIER:
            flags.append(AnomalyFlag(
                transaction_id=txn.id,
                flag_type="spike",
                detail=(
                    f"${txn.amount:.2f} is {txn.amount / avg:.1f}x the average "
                    f"(${avg:.2f}) for {txn.vendor_name!r} in this window."
                ),
            ))

    return flags
