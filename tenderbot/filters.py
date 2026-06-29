"""Filter engine: match a tender against the user's rules."""
from __future__ import annotations

from typing import List

from .config import FilterRule
from .models import Tender


def _contains_any(haystack: str, needles: List[str]) -> bool:
    low = haystack.lower()
    return any(n.lower() in low for n in needles if n)


def matches_rule(tender: Tender, rule: FilterRule) -> bool:
    """Return True if the tender satisfies every condition set on the rule."""
    # Keywords (against the tender name).
    if rule.keywords:
        name = tender.name.lower()
        present = [k.lower() in name for k in rule.keywords if k]
        if rule.keyword_logic == "all":
            if not all(present):
                return False
        else:  # "any"
            if not any(present):
                return False

    # Budget range. A missing/unparseable budget cannot satisfy a budget bound.
    if rule.budget_min is not None:
        if tender.budget is None or tender.budget < rule.budget_min:
            return False
    if rule.budget_max is not None:
        if tender.budget is None or tender.budget > rule.budget_max:
            return False

    # Category / procurement method.
    if rule.categories and not _contains_any(tender.procurement_method, rule.categories):
        return False

    # Buyer.
    if rule.buyers and not _contains_any(tender.buyer, rule.buyers):
        return False

    # Region (best-effort: the listing has no aimag field, so match against the
    # buyer name + tender name, where a region is most often mentioned).
    if rule.regions:
        region_text = f"{tender.buyer} {tender.name} {tender.region}"
        if not _contains_any(region_text, rule.regions):
            return False

    return True


def matching_rules(tender: Tender, rules: List[FilterRule]) -> List[str]:
    """Names of all rules the tender matches (empty if none)."""
    return [r.name for r in rules if matches_rule(tender, r)]
