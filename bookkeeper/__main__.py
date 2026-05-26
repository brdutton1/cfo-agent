"""
CLI entry point. Provider-blind: imports only the factory and the
orchestrator, plus the Protocol's error type for top-level handling.

Run with:  python -m bookkeeper [--since YYYY-MM-DD] [--dry-run] ...
"""

import argparse
import os
import sys
from datetime import date, timedelta

from dotenv import load_dotenv

from .factory import build_provider
from .orchestrator import run_bookkeeping
from .provider import ProviderError

load_dotenv()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bookkeeper — auto-categorizes transactions from a configured provider.",
    )
    parser.add_argument(
        "--since",
        default=(date.today() - timedelta(days=1)).isoformat(),
        help="Fetch transactions on or after this date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Categorize but do not write to the provider.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Override confidence threshold (0.0–1.0).",
    )
    parser.add_argument(
        "--provider",
        default="qbo",
        help="Provider name (default: qbo).",
    )
    parser.add_argument(
        "--company-label",
        default="Allegro Design Co.",
        help="Display label used in the printed report header.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    threshold = args.threshold
    if threshold is None:
        try:
            threshold = float(os.getenv("CONFIDENCE_THRESHOLD", "0.90"))
        except ValueError as e:
            print(f"Invalid CONFIDENCE_THRESHOLD: {e}", file=sys.stderr)
            return 1

    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if not anthropic_key:
        print("ANTHROPIC_API_KEY not set.", file=sys.stderr)
        return 1

    try:
        provider = build_provider(args.provider)
    except ProviderError as e:
        print(f"Provider error: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    except Exception as e:
        # The provider's own config errors (e.g. ConfigError from QBO) are
        # not part of the domain contract — surface them as a clear message.
        print(f"Provider setup failed: {e}", file=sys.stderr)
        return 1

    return run_bookkeeping(
        provider=provider,
        since=args.since,
        confidence_threshold=threshold,
        anthropic_api_key=anthropic_key,
        company_label=args.company_label,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
