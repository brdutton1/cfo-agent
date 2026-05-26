"""
Entry point: python -m bookkeeper [--since YYYY-MM-DD] [--dry-run] [--threshold 0.90]

Orchestration order:
  1. Load config + get valid OAuth token
  2. Fetch chart of accounts
  3. Fetch uncategorized transactions
  4. Run anomaly detection over the full set
  5. Run rule-based categorizer
  6. Run LLM categorizer on rule-missed items
  7. Split into auto-apply vs. needs-review by confidence threshold
  8. Apply approved categories to QBO (unless --dry-run)
  9. Print report
"""

import argparse
import sys
from datetime import date, timedelta

from .anomaly import detect_anomalies
from .applier import apply_categories
from .auth import AuthError, get_valid_token
from .chart_of_accounts import build_account_index, fetch_accounts
from .config import ConfigError, load_config
from .llm_categorizer import run_llm_categorizer
from .models import CategorizationResult
from .qbo_client import QBOClient, QBOError
from .reporter import print_report
from .rules import run_rules
from .transactions import fetch_all_uncategorized


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Allegro bookkeeper — auto-categorizes QBO transactions."
    )
    parser.add_argument(
        "--since",
        default=(date.today() - timedelta(days=1)).isoformat(),
        help="Fetch transactions on or after this date (YYYY-MM-DD). Defaults to yesterday.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Categorize but do not write anything to QBO.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Override confidence threshold for this run (0.0–1.0).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    # 1. Config + auth
    try:
        config = load_config()
    except ConfigError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        return 1

    if args.threshold is not None:
        config.confidence_threshold = args.threshold

    try:
        token = get_valid_token(config)
    except AuthError as e:
        print(f"Auth error: {e}", file=sys.stderr)
        return 1

    client = QBOClient(config, token)

    # 2. Chart of accounts
    print("Fetching chart of accounts...", end=" ", flush=True)
    try:
        accounts = fetch_accounts(client)
        account_index = build_account_index(accounts)
        print(f"{len(accounts)} expense accounts loaded.")
    except QBOError as e:
        print(f"\nFailed to fetch chart of accounts: {e}", file=sys.stderr)
        return 1

    if not accounts:
        print("No expense accounts found — check your QBO chart of accounts.", file=sys.stderr)
        return 1

    # 3. Uncategorized transactions
    print(f"Fetching uncategorized transactions since {args.since}...", end=" ", flush=True)
    try:
        transactions = fetch_all_uncategorized(client, since_date=args.since)
        print(f"{len(transactions)} found.")
    except QBOError as e:
        print(f"\nFailed to fetch transactions: {e}", file=sys.stderr)
        return 1

    if not transactions:
        print("\nNo uncategorized transactions found. Nothing to do.")
        return 0

    # 4. Anomaly detection (over full set before splitting)
    print("Running anomaly detection...")
    anomaly_flags = detect_anomalies(transactions)

    # 5. Rule-based categorizer
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

    # 6. LLM categorizer for rule misses
    llm_results: list[CategorizationResult] = []
    if rule_misses:
        print("Running LLM categorizer...")
        try:
            llm_results = run_llm_categorizer(
                transactions=rule_misses,
                accounts=accounts,
                account_index=account_index,
                api_key=config.anthropic_api_key,
                threshold=config.confidence_threshold,
            )
        except Exception as e:
            print(f"  [warn] LLM categorizer error: {e}. Affected transactions marked for review.")
            from .models import CategorizationResult
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

    # 7. Split by threshold + promote any rule match below threshold to review
    approved = [
        r for r in all_results
        if not r.needs_review and r.confidence >= config.confidence_threshold
    ]
    needs_review = [
        r for r in all_results
        if r.needs_review or r.confidence < config.confidence_threshold
    ]
    # Ensure needs_review flag is set for anything that fell below threshold
    for r in needs_review:
        if not r.needs_review:
            r.needs_review = True
            r.review_reason = f"Confidence {r.confidence:.0%} below threshold {config.confidence_threshold:.0%}"

    # 8. Apply
    application_results = []
    if approved:
        print(
            f"Applying {len(approved)} categories to QBO"
            + (" (dry run)..." if args.dry_run else "...")
        )
        application_results = apply_categories(client, approved, dry_run=args.dry_run)

    # 9. Report
    print_report(
        company_name="Allegro Design Co.",
        since_date=args.since,
        total_fetched=len(transactions),
        categorization_results=all_results,
        anomaly_flags=anomaly_flags,
        application_results=application_results,
        dry_run=args.dry_run,
    )

    has_errors = any(not a.success for a in application_results)
    return 1 if has_errors else 0


if __name__ == "__main__":
    sys.exit(main())
