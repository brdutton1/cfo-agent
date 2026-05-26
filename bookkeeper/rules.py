"""
Deterministic rule-based categorizer.

Rules match on vendor name or description (case-insensitive substring or regex).
First match wins. Rules are tried in order, so put more specific rules before
broader ones.

TO ADD YOUR OWN RULES: Append a VendorRule to RULES below.
  pattern   — substring (str) or compiled regex matched against vendor_name + description
  account   — exact QBO account name (must match your chart of accounts)
  confidence — 1.0 for rules you're certain about; lower if the pattern is ambiguous
"""

import re
from dataclasses import dataclass
from typing import Union

from .models import Account, CategorizationResult, Transaction


@dataclass
class VendorRule:
    pattern: Union[str, re.Pattern]
    account: str
    confidence: float = 1.0
    note: str = ""


# ---------------------------------------------------------------------------
# Starter rule set — edit freely.
# Account names must exactly match your QBO chart of accounts.
# ---------------------------------------------------------------------------
RULES: list[VendorRule] = [
    # Cloud & SaaS
    VendorRule(re.compile(r"\b(aws|amazon web services)\b", re.I), "Cloud Services"),
    VendorRule(re.compile(r"\bgoogle (cloud|workspace|gsuite)\b", re.I), "Cloud Services"),
    VendorRule(re.compile(r"\bmicrosoft (azure|365|office)\b", re.I), "Cloud Services"),
    VendorRule(re.compile(r"\b(dropbox|notion|slack|zoom|loom|figma|adobe)\b", re.I), "Software Subscriptions"),
    VendorRule(re.compile(r"\banthrop(ic|olog)\b", re.I), "Software Subscriptions"),
    VendorRule(re.compile(r"\bopenai\b", re.I), "Software Subscriptions"),
    VendorRule(re.compile(r"\bgithub\b", re.I), "Software Subscriptions"),

    # Payment processing
    VendorRule(re.compile(r"\bstripe\b", re.I), "Merchant Fees"),
    VendorRule(re.compile(r"\bpaypal.*fee\b", re.I), "Merchant Fees"),
    VendorRule(re.compile(r"\bsquare\b", re.I), "Merchant Fees"),

    # Office supplies
    VendorRule(re.compile(r"\b(office depot|office max|staples)\b", re.I), "Office Supplies"),
    VendorRule(re.compile(r"\bamazon\b", re.I), "Office Supplies", confidence=0.75,
               note="Amazon could be anything — flagged for review if below threshold"),

    # Fuel & auto
    VendorRule(re.compile(r"\b(chevron|shell|exxon|mobil|bp|sunoco|circle k|kwik trip)\b", re.I), "Fuel"),
    VendorRule(re.compile(r"\b(autozone|o'reilly|napa auto)\b", re.I), "Auto & Truck"),

    # Travel & lodging
    VendorRule(re.compile(r"\b(delta|united|southwest|american airlines|alaska airlines)\b", re.I), "Travel"),
    VendorRule(re.compile(r"\b(marriott|hilton|hyatt|ihg|best western|holiday inn)\b", re.I), "Travel"),
    VendorRule(re.compile(r"\b(airbnb|vrbo)\b", re.I), "Travel"),
    VendorRule(re.compile(r"\buber\b", re.I), "Travel", confidence=0.80,
               note="Uber could be ride or Uber Eats — lower confidence"),
    VendorRule(re.compile(r"\blyft\b", re.I), "Travel"),

    # Meals & entertainment
    VendorRule(re.compile(r"\b(doordash|grubhub|uber eats|postmates|seamless)\b", re.I), "Meals & Entertainment"),
    VendorRule(re.compile(r"\b(starbucks|dunkin|dutch bros)\b", re.I), "Meals & Entertainment"),
    VendorRule(re.compile(r"\b(chick.fil.a|mcdonald|subway|chipotle|panera|domino)\b", re.I), "Meals & Entertainment"),

    # Utilities & communications
    VendorRule(re.compile(r"\b(verizon|at&t|t.mobile|comcast|xfinity|centurylink|lumen)\b", re.I), "Utilities"),
    VendorRule(re.compile(r"\b(xcel energy|psco|holy cross energy)\b", re.I), "Utilities"),

    # Professional services
    VendorRule(re.compile(r"\bsocair\b", re.I), "Bookkeeping"),
    VendorRule(re.compile(r"\b(turn ministries|turn ministry)\b", re.I), "Charitable Contributions"),

    # Rent & coworking
    VendorRule(re.compile(r"\b(wework|regus|industrious|spaces)\b", re.I), "Rent"),

    # Payroll services
    VendorRule(re.compile(r"\b(gusto|adp|paychex|rippling|justworks)\b", re.I), "Payroll Service Fees"),

    # Insurance
    VendorRule(re.compile(r"\b(hiscox|next insurance|coterie|employers)\b", re.I), "Insurance"),
]


def _match_text(txn: Transaction) -> str:
    return f"{txn.vendor_name} {txn.description}".strip()


def run_rules(
    txn: Transaction,
    account_index: dict[str, Account],
) -> CategorizationResult | None:
    """
    Try all rules against the transaction. Return the first match, or None
    if no rule fires. Caller decides what to do with a None (pass to LLM).
    """
    text = _match_text(txn)

    for rule in RULES:
        if isinstance(rule.pattern, str):
            matched = rule.pattern.lower() in text.lower()
        else:
            matched = bool(rule.pattern.search(text))

        if not matched:
            continue

        account = account_index.get(rule.account.lower())
        if account is None:
            # The rule fired but the account name doesn't exist in this company's
            # chart of accounts. Don't auto-apply; surface it as needs-review.
            return CategorizationResult(
                transaction=txn,
                suggested_account=None,
                confidence=0.0,
                method="rule",
                reasoning=f"Rule matched '{rule.account}' but that account was not found in your chart of accounts.",
                needs_review=True,
                review_reason=f"Rule matched account '{rule.account}' — not in chart of accounts. Add it or update RULES.",
            )

        return CategorizationResult(
            transaction=txn,
            suggested_account=account,
            confidence=rule.confidence,
            method="rule",
            reasoning=rule.note or f"Matched rule pattern for {rule.account}",
            needs_review=False,
        )

    return None
