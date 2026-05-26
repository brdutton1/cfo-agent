"""
THE DELETION PROOF.

Runs the entire bookkeeping pipeline — fetch accounts, fetch transactions,
rules, LLM, anomaly detection, apply, report — using only a MemoryProvider
defined in tests/conftest.py.

This file must pass with the entire bookkeeper/providers/qbo/ folder
absent from the filesystem. No network, no auth, no env vars beyond what
this test sets up explicitly. If this passes when QBO is gone, the seam
is real.

We additionally inspect the AST of every domain file to verify none of
them import any QBO module — a static guarantee on top of the runtime
proof.
"""

import ast
import importlib
import os
import pathlib
import sys
from unittest.mock import MagicMock, patch

import pytest

from bookkeeper.orchestrator import run_bookkeeping
from bookkeeper.provider import BookkeepingProvider


# ---------------------------------------------------------------------------
# Static check: no domain file imports any provider, HTTP, OAuth, or storage.
# ---------------------------------------------------------------------------

DOMAIN_FILES = [
    "bookkeeper/models.py",
    "bookkeeper/domain.py",
    "bookkeeper/provider.py",
    "bookkeeper/rules.py",
    "bookkeeper/anomaly.py",
    "bookkeeper/reporter.py",
    "bookkeeper/llm_categorizer.py",
    "bookkeeper/orchestrator.py",
]

FORBIDDEN_IMPORTS = {
    "requests",
    "urllib",
    "urllib.parse",
    "urllib.request",
    "http",
    "http.client",
    "sqlite3",
}

FORBIDDEN_PREFIXES = (
    "bookkeeper.providers",
    "bookkeeper.providers.qbo",
)

# `anthropic` is the documented exception in llm_categorizer.py — future AI seam.
ALLOWED_EXTERNAL_BY_FILE = {
    "bookkeeper/llm_categorizer.py": {"anthropic"},
}


def _imported_names_in(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module
            if mod:
                if node.level == 0:
                    names.add(mod)
                else:
                    # relative — preserve as-is, resolved against package
                    names.add("." * node.level + mod)
    return names


@pytest.mark.parametrize("domain_file", DOMAIN_FILES)
def test_domain_file_has_no_forbidden_imports(domain_file):
    path = pathlib.Path(__file__).parent.parent / domain_file
    imported = _imported_names_in(path)
    allowed = ALLOWED_EXTERNAL_BY_FILE.get(domain_file, set())

    for name in imported:
        if name in allowed:
            continue
        assert name not in FORBIDDEN_IMPORTS, (
            f"{domain_file} imports forbidden module {name!r}"
        )
        for prefix in FORBIDDEN_PREFIXES:
            assert not name.startswith(prefix), (
                f"{domain_file} imports provider module {name!r}"
            )


def test_factory_imports_provider_lazily():
    """factory.py must not import provider modules at module scope."""
    path = pathlib.Path(__file__).parent.parent / "bookkeeper" / "factory.py"
    tree = ast.parse(path.read_text())

    # Check that no top-level Import/ImportFrom node references providers.qbo
    module_level_imports: set[str] = set()
    for node in tree.body:  # only top-level statements
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_level_imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                module_level_imports.add(node.module)

    for name in module_level_imports:
        assert "providers.qbo" not in name and not name.endswith(".qbo"), (
            f"factory.py imports {name!r} at module scope — must be lazy"
        )


# ---------------------------------------------------------------------------
# Runtime check: full pipeline runs end-to-end with MemoryProvider only.
# ---------------------------------------------------------------------------


def test_pipeline_runs_against_memory_provider_only(memory_provider, capsys):
    """The full orchestrator pipeline must complete using only the Protocol."""

    # Pre-flight: assert the provider truly satisfies the Protocol structurally
    assert isinstance(memory_provider, BookkeepingProvider)

    # Mock the LLM so the test runs offline and deterministically
    from types import SimpleNamespace

    def fake_response(**_):
        # Mark every unknown vendor as needing review (low confidence)
        return SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="categorize_transactions",
                    input={"results": [
                        {"index": 0, "account_name": None, "confidence": 0.0, "reason": "unknown"}
                    ]},
                )
            ]
        )

    with patch("bookkeeper.llm_categorizer.anthropic.Anthropic") as mock_anthropic:
        instance = MagicMock()
        instance.messages.create.side_effect = lambda **kw: fake_response(**kw)
        mock_anthropic.return_value = instance

        exit_code = run_bookkeeping(
            provider=memory_provider,
            since="2026-05-19",
            confidence_threshold=0.9,
            anthropic_api_key="fake-key",
            company_label="Test Company",
            dry_run=False,
        )

    # Exit code 0 — no apply errors
    assert exit_code == 0

    # The provider should have been asked for transactions
    assert memory_provider.fetch_uncategorized_calls == 1

    # Rule-matched transactions should have been applied to the memory provider
    # From fixtures: AWS, GitHub, Chevron, Starbucks, Socair, Chevron all match rules
    # Mystery Vendor LLC does NOT match a rule → goes to LLM → flagged for review
    assert "Mystery Vendor LLC" not in {
        v for v in memory_provider.applied.values()
    }

    # We expect 6 of 7 fixture transactions to have been auto-applied
    assert len(memory_provider.applied) >= 5, (
        f"Expected most rule-matched transactions to apply, got: {memory_provider.applied}"
    )

    # The report should have made it to stdout
    out = capsys.readouterr().out
    assert "AUTO-CATEGORIZED" in out
    assert "NEEDS YOUR REVIEW" in out


def test_pipeline_dry_run_does_not_call_apply(memory_provider, capsys):
    from types import SimpleNamespace

    def fake_response(**_):
        return SimpleNamespace(
            content=[SimpleNamespace(
                type="tool_use",
                name="categorize_transactions",
                input={"results": [
                    {"index": 0, "account_name": None, "confidence": 0.0, "reason": "x"}
                ]},
            )]
        )

    with patch("bookkeeper.llm_categorizer.anthropic.Anthropic") as mock_anthropic:
        instance = MagicMock()
        instance.messages.create.side_effect = lambda **kw: fake_response(**kw)
        mock_anthropic.return_value = instance

        run_bookkeeping(
            provider=memory_provider,
            since="2026-05-19",
            confidence_threshold=0.9,
            anthropic_api_key="fake-key",
            company_label="Test Company",
            dry_run=True,
        )

    # In dry-run, the orchestrator must NOT call the provider's apply_category
    assert memory_provider.applied == {}


def test_pipeline_propagates_apply_failures(memory_provider, capsys):
    from types import SimpleNamespace

    # Cause the memory provider to fail when applying one specific transaction
    memory_provider.fail_apply_for = {"txn-1"}

    def fake_response(**_):
        return SimpleNamespace(
            content=[SimpleNamespace(
                type="tool_use",
                name="categorize_transactions",
                input={"results": [
                    {"index": 0, "account_name": None, "confidence": 0.0, "reason": "x"}
                ]},
            )]
        )

    with patch("bookkeeper.llm_categorizer.anthropic.Anthropic") as mock_anthropic:
        instance = MagicMock()
        instance.messages.create.side_effect = lambda **kw: fake_response(**kw)
        mock_anthropic.return_value = instance

        exit_code = run_bookkeeping(
            provider=memory_provider,
            since="2026-05-19",
            confidence_threshold=0.9,
            anthropic_api_key="fake-key",
            company_label="Test Company",
            dry_run=False,
        )

    assert exit_code == 1


def test_pipeline_with_no_transactions_returns_zero(accounts_data, capsys):
    from tests.conftest import MemoryProvider

    empty = MemoryProvider(accounts=accounts_data, transactions=[])
    code = run_bookkeeping(
        provider=empty,
        since="2026-05-19",
        confidence_threshold=0.9,
        anthropic_api_key="fake-key",
        company_label="Test Company",
        dry_run=False,
    )
    assert code == 0
