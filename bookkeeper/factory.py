"""
Provider factory. The ONLY domain-layer file allowed to know that providers
exist. Imports are lazy and inside the function body, so deleting any
provider package never breaks the domain-layer import graph.
"""

from .provider import BookkeepingProvider


def build_provider(name: str) -> BookkeepingProvider:
    if name == "qbo":
        from .providers.qbo import build_qbo_provider
        return build_qbo_provider()
    raise ValueError(f"Unknown provider: {name!r}. Known: 'qbo'.")
