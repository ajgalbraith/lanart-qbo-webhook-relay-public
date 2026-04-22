from __future__ import annotations

from collections.abc import Iterable


def matches_customer_name(
    customer_name: str,
    *,
    include_terms: Iterable[str],
    exclude_terms: Iterable[str],
) -> bool:
    haystack = customer_name.upper()
    if any(term.upper() in haystack for term in exclude_terms):
        return False
    return any(term.upper() in haystack for term in include_terms)
