"""
Pure domain constants and predicates. Zero external imports.

The names and rules here describe bookkeeping concepts in the abstract — they
do not depend on QuickBooks, Xero, or any specific provider. They happen to
match common system-account labels in QBO because those labels are themselves
generic bookkeeping vocabulary, not QBO-specific concepts.
"""

UNCATEGORIZED_ACCOUNT_NAMES: frozenset[str] = frozenset({
    "uncategorized expense",
    "ask my accountant",
    "uncategorized asset",
})


def is_uncategorized(account_name: str | None) -> bool:
    """True when an account name represents 'I don't know yet'."""
    if not account_name:
        return True
    return account_name.lower() in UNCATEGORIZED_ACCOUNT_NAMES


def build_account_index(accounts) -> dict:
    """Return a dict keyed by lowercase account name for fast lookup.

    Typed loosely on purpose: this is a one-line helper used by the orchestrator
    and tests. The caller passes a list of Account.
    """
    return {a.name.lower(): a for a in accounts}
