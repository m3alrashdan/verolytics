"""Number verification gate.

Every number that appears in report narrative text must be traceable to the
structured results JSON produced by sandbox executions. A number "matches" if
some numeric value in the results equals it exactly, equals it after rounding
(to the precision the narrative used), or equals it via a percent conversion
(0.124 in results may legitimately appear as 12.4%).

Small whole numbers (0–12) are exempt: they cover ordinals and counts the
narrative naturally produces ("the top 3 products", "step 2", "12 months"),
which are structural rather than analytical claims. See DECISIONS.md.
"""
from __future__ import annotations

import math
import re
from typing import Any

from pydantic import BaseModel, Field

# Matches 1234, 1,234.56, .5, 12.4% — captures the numeric text
NUMBER_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\.\d+|\d+)(?![\w])")

SMALL_INT_EXEMPT_MAX = 12
MAX_ROUND_DIGITS = 6
# A narrative share like "Region A is 21.6% of revenue" is a ratio of two saved
# numbers (region_revenue / total_revenue). We accept such ratios as grounded —
# but only when the denominator is one of the few largest saved values (a
# dominant total), which keeps the match bounded and resistant to coincidence.
RATIO_DENOMINATOR_COUNT = 4


class VerificationReport(BaseModel):
    ok: bool
    checked: int = 0
    matched: int = 0
    unmatched: list[str] = Field(default_factory=list)


def extract_numbers(text: str) -> list[tuple[str, float]]:
    """Extract (raw_token, value) pairs for every number in narrative text."""
    out: list[tuple[str, float]] = []
    for m in NUMBER_RE.finditer(text):
        raw = m.group(1)
        try:
            out.append((raw, float(raw.replace(",", ""))))
        except ValueError:
            continue
    return out


def collect_result_numbers(obj: Any, acc: set[float] | None = None) -> set[float]:
    """Recursively collect every numeric value in the results JSON.

    Numbers embedded in strings (dates like "2024-03-01", labels like "Q3")
    are extracted too, so years/months mentioned in the narrative match.
    """
    if acc is None:
        acc = set()
    if isinstance(obj, bool):
        return acc
    if isinstance(obj, (int, float)):
        if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
            return acc
        acc.add(float(obj))
    elif isinstance(obj, str):
        for _, v in extract_numbers(obj):
            acc.add(v)
    elif isinstance(obj, dict):
        for v in obj.values():
            collect_result_numbers(v, acc)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            collect_result_numbers(v, acc)
    return acc


def _decimals_used(raw: str) -> int:
    if "." in raw:
        return len(raw.split(".", 1)[1])
    return 0


def _matches(raw: str, value: float, candidates: set[float],
             ratio_denominators: set[float] | None = None) -> bool:
    if value in candidates:
        return True
    digits = _decimals_used(raw)
    for r in candidates:
        # exact-precision rounding match: results value rounded to displayed digits
        if round(r, digits) == value:
            return True
        # percent conversions: results ratio 0.124 shown as 12.4 (%)
        if round(r * 100, digits) == value:
            return True
        # narrative shows ratio while results store percent
        if round(r / 100, digits) == value and r != 0:
            return True
        # thousands shorthand: results 12400 shown as 12.4 (K)
        for factor in (1_000.0, 1_000_000.0, 1_000_000_000.0):
            if round(r / factor, digits) == value and abs(r) >= factor:
                return True
    # grounded share: value == (saved numerator / dominant-total denominator) * 100
    if ratio_denominators:
        for b in ratio_denominators:
            if b == 0:
                continue
            for a in candidates:
                if round(a / b * 100.0, digits) == value:
                    return True
    return False


def _ratio_denominators(candidates: set[float]) -> set[float]:
    """The few largest positive saved values — plausible totals for share math."""
    positives = [c for c in candidates if c > 0]
    return set(sorted(positives, reverse=True)[:RATIO_DENOMINATOR_COUNT])


def verify_text(text: str, result_numbers: set[float],
                extra_allowed: set[float] | None = None) -> VerificationReport:
    """Verify every number in ``text`` against the collected result numbers."""
    allowed = set(result_numbers)
    if extra_allowed:
        allowed |= {float(v) for v in extra_allowed}
    ratio_denoms = _ratio_denominators(allowed)

    checked = matched = 0
    unmatched: list[str] = []
    for raw, value in extract_numbers(text):
        checked += 1
        if value == int(value) and 0 <= value <= SMALL_INT_EXEMPT_MAX:
            matched += 1
            continue
        if _matches(raw, value, allowed, ratio_denoms):
            matched += 1
        else:
            unmatched.append(raw)
    return VerificationReport(ok=not unmatched, checked=checked, matched=matched, unmatched=unmatched)


def verify_report(report_texts: list[str], results_json: Any,
                  extra_allowed: set[float] | None = None) -> VerificationReport:
    """Verify all narrative fragments of a report against the results JSON."""
    candidates = collect_result_numbers(results_json)
    total = VerificationReport(ok=True)
    for text in report_texts:
        part = verify_text(text or "", candidates, extra_allowed)
        total.checked += part.checked
        total.matched += part.matched
        total.unmatched.extend(part.unmatched)
    total.ok = not total.unmatched
    return total


def redact_unverified(text: str, unmatched: list[str]) -> str:
    """Last-resort fallback: replace unverifiable numbers with a marker."""
    out = text
    for raw in set(unmatched):
        out = re.sub(rf"(?<![\w.]){re.escape(raw)}(?![\w])", "[unverified]", out)
    return out
