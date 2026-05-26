"""
The bookkeeping pipeline. Typed against the BookkeepingProvider Protocol;
imports zero provider, HTTP, OAuth, or storage code.

If you can construct a BookkeepingProvider implementation (real or fake),
you can call run_bookkeeping with it. That's the whole point.
"""

import sys

from .anomaly import detect_anomalies
from .domain import build_account_index
from .llm_categorizer import run_llm_categorizer
from .models import ApplicationResult, CategorizationResult
from .provider import BookkeepingProvider, ProviderError
from .reporter import print_report
from .rules import run_rules


def run_bookkeeping(
    provider: BookkeepingProvider,
    *,
    since: str,
    confidence_threshold: float,
    anthropic_api_key: str,
    company_label: str,
    dry_run: bool = False,
) -> int:
    """Run the full pipeline. Returns 0 on clean run, 1 if any apply failed."""

    # 1. Accounts
    print("Fetching chart of accounts...", end=" ", flush=True)
    try:
        accounts = provider.fetch_accounts()
    except ProviderError as e:
        print(f"\nFailed: {e}", file=sys.stderr)
        return 1
    print(f"{len(accounts)} accounts loaded.")
    if not accounts:
        print("No accounts available — cannot categorize.", file=sys.stderr)
        return 1
    account_index = build_account_index(accounts)

    # 2. Transactions
    print(f"Fetching uncategorized transactions since {since}...", end=" ", flush=True)
    try:
        transactions = provider.fetch_uncategorized(since=since)
    except ProviderError as e:
        print(f"\nFailed: {e}", file=sys.stderr)
        return 1
    print(f"{len(transactions)} found.")
    if not transactions:
        print("\nNo uncategorized transactions found. Nothing to do.")
        return 0

    # 3. Anomaly detection over the full set
    print("Running anomaly detection...")
    anomaly_flags = detect_anomalies(transactions)

    # 4. Rule-based categorizer
    print("Running rule-based categorizer...")
    rule_results: list[CategorizationResult] = []
    rule_misses: list = []
    for txn in transactions:
        result = run_rules(txn, account_index)
        if result is not None:
            rule_results.append(result)
        else:
            rule_misses.append(txn)
    print(f"  Rules matched: {len(rule_results)}  |  Passing to LLM: {len(rule_misses)}")

    # 5. LLM categorizer for rule misses
    llm_results: list[CategorizationResult] = []
    if rule_misses:
        print("Running LLM categorizer...")
        try:
            llm_results = run_llm_categorizer(
                transactions=rule_misses,
                accounts=accounts,
                account_index=account_index,
                api_key=anthropic_api_key,
                threshold=confidence_threshold,
            )
        except Exception as e:
            print(f"  [warn] LLM categorizer error: {e}. Affected transactions marked for review.")
            for txn in rule_misses:
                llm_results.append(CategorizationResult(
                    transaction=txn,
                    suggested_account=None,
                    confidence=0.0,
                    method="none",
                    reasoning="LLM categorizer failed.",
                    needs_review=True,
                    review_reason="LLM unavailable — categorize manually.",
                ))

    all_results = rule_results + llm_results

    # 6. Threshold split + promote sub-threshold to needs-review
    for r in all_results:
        if (not r.needs_review) and r.confidence < confidence_threshold:
            r.needs_review = True
            r.review_reason = (
                f"Confidence {r.confidence:.0%} below threshold {confidence_threshold:.0%}"
            )
    approved = [r for r in all_results if not r.needs_review and r.suggested_account is not None]

    # 7. Apply
    application_results: list[ApplicationResult] = []
    if approved:
        print(
            f"Applying {len(approved)} categories"
            + (" (dry run)..." if dry_run else "...")
        )
        for r in approved:
            if dry_run:
                print(
                    f"  [dry-run] Would apply '{r.suggested_account.name}' to {r.transaction.id} "
                    f"({r.transaction.vendor_name}, ${r.transaction.amount:.2f})"
                )
                application_results.append(
                    ApplicationResult(transaction_id=r.transaction.id, success=True)
                )
            else:
                application_results.append(
                    provider.apply_category(r.transaction, r.suggested_account)
                )

    # 8. Report
    print_report(
        company_name=company_label,
        since_date=since,
        total_fetched=len(transactions),
        categorization_results=all_results,
        anomaly_flags=anomaly_flags,
        application_results=application_results,
        dry_run=dry_run,
    )

    return 1 if any(not a.success for a in application_results) else 0
