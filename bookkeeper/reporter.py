"""
Formats and prints the bookkeeper run report to stdout.
No external dependencies — plain ASCII, readable in a terminal or chat window.
"""

from datetime import datetime, timezone

from .models import AnomalyFlag, ApplicationResult, CategorizationResult


def _divider(char: str = "─", width: int = 72) -> str:
    return char * width


def _fmt_amount(amount: float) -> str:
    return f"${amount:,.2f}"


def _fmt_confidence(c: float) -> str:
    return f"{c:.0%}"


def print_report(
    company_name: str,
    since_date: str,
    total_fetched: int,
    categorization_results: list[CategorizationResult],
    anomaly_flags: list[AnomalyFlag],
    application_results: list[ApplicationResult],
    dry_run: bool,
) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    mode = " [DRY RUN — no changes written to QBO]" if dry_run else ""

    print()
    print(_divider("═"))
    print(f"  ALLEGRO BOOKKEEPER RUN — {now}{mode}")
    print(f"  Company: {company_name}  |  Window: since {since_date}")
    print(_divider("═"))

    # ── Counts summary ──────────────────────────────────────────────────────
    auto = [r for r in categorization_results if not r.needs_review]
    needs_review = [r for r in categorization_results if r.needs_review]
    applied_ok = sum(1 for a in application_results if a.success)
    applied_err = sum(1 for a in application_results if not a.success)

    print(f"\n  Transactions fetched:   {total_fetched}")
    print(f"  Auto-categorized:       {len(auto)}"
          + (f"  ({applied_ok} applied, {applied_err} errors)" if not dry_run else ""))
    print(f"  Needs your review:      {len(needs_review)}")
    print(f"  Anomaly flags:          {len(anomaly_flags)}")

    # ── Auto-categorized ────────────────────────────────────────────────────
    if auto:
        print(f"\n{_divider()}")
        print("  AUTO-CATEGORIZED")
        print(_divider())
        for r in auto:
            t = r.transaction
            flag_marker = " ⚠" if any(f.transaction_id == t.id for f in anomaly_flags) else ""
            print(
                f"  {t.txn_date}  {_fmt_amount(t.amount):>10}  "
                f"{t.vendor_name[:28]:<28}  →  {r.suggested_account.name}"
                f"  [{r.method} {_fmt_confidence(r.confidence)}]{flag_marker}"
            )

    # ── Needs review ────────────────────────────────────────────────────────
    if needs_review:
        print(f"\n{_divider()}")
        print("  NEEDS YOUR REVIEW")
        print(_divider())
        for r in needs_review:
            t = r.transaction
            flag_marker = " ⚠" if any(f.transaction_id == t.id for f in anomaly_flags) else ""
            acct_hint = f"  (suggested: {r.suggested_account.name})" if r.suggested_account else ""
            print(f"\n  {t.txn_date}  {_fmt_amount(t.amount):>10}  {t.vendor_name}{flag_marker}")
            print(f"    Reason:  {r.review_reason}{acct_hint}")
            if r.reasoning and r.reasoning != r.review_reason:
                print(f"    Detail:  {r.reasoning}")
    else:
        print(f"\n{_divider()}")
        print("  NEEDS YOUR REVIEW — none")

    # ── Anomaly flags ───────────────────────────────────────────────────────
    if anomaly_flags:
        print(f"\n{_divider()}")
        print("  ANOMALY FLAGS")
        print(_divider())
        flag_labels = {
            "duplicate": "DUPE",
            "first_time_vendor": "NEW VENDOR",
            "spike": "SPIKE",
        }
        for flag in anomaly_flags:
            label = flag_labels.get(flag.flag_type, flag.flag_type.upper())
            print(f"  [{label}]  {flag.detail}")

    # ── Application errors ──────────────────────────────────────────────────
    errors = [a for a in application_results if not a.success]
    if errors:
        print(f"\n{_divider()}")
        print("  QBO WRITE ERRORS (manual follow-up required)")
        print(_divider())
        for e in errors:
            print(f"  {e.transaction_id}: {e.error}")

    print(f"\n{_divider('═')}\n")
