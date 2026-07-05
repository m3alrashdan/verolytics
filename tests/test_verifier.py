"""Verifier tests — the gate must catch hallucinated numbers and pass real ones."""
from __future__ import annotations

from api.services.verifier import (
    collect_result_numbers, extract_numbers, redact_unverified, verify_report, verify_text,
)

RESULTS = {
    "steps": {
        "step_1": {
            "scalars": {"total_revenue": 123456.789, "growth": 0.124, "avg_order": 87.5},
            "tables": {"by_month": {"rows": [
                {"month": "2024-01", "revenue": 50000.0},
                {"month": "2024-02", "revenue": 73456.789},
            ]}},
        }
    }
}
NUMBERS = collect_result_numbers(RESULTS)


def test_extract_numbers_formats():
    pairs = extract_numbers("Revenue was 1,234.56 (12.4%) across 3 regions, .5 ratio")
    values = [v for _, v in pairs]
    assert 1234.56 in values and 12.4 in values and 3 in values and 0.5 in values


def test_exact_match_passes():
    assert verify_text("Total revenue reached 123456.789", NUMBERS).ok


def test_rounded_match_passes():
    assert verify_text("Total revenue reached 123456.79", NUMBERS).ok
    assert verify_text("Average order value was 87.5", NUMBERS).ok


def test_thousands_separator_passes():
    assert verify_text("January revenue was 50,000", NUMBERS).ok


def test_percent_conversion_passes():
    # results store the ratio 0.124; narrative says 12.4%
    assert verify_text("Growth of 12.4% month over month", NUMBERS).ok


def test_thousands_shorthand_passes():
    # results store 50000; narrative says 50K
    assert verify_text("January hit 50 thousand in revenue", NUMBERS).ok


def test_numbers_inside_result_strings_pass():
    # "2024-01" in results makes 2024 and 1 legitimate
    assert verify_text("In 2024 the trend reversed", NUMBERS).ok


def test_small_integers_exempt():
    assert verify_text("The top 3 of 12 categories drive most volume", NUMBERS).ok


def test_hallucinated_number_fails():
    rep = verify_text("Total revenue reached 999888.0", NUMBERS)
    assert not rep.ok
    assert "999888.0" in rep.unmatched


def test_fabricated_precision_fails():
    # results have 87.5; claiming 87.53 adds precision that was never computed
    rep = verify_text("Average order value was 87.53", NUMBERS)
    assert not rep.ok


def test_verify_report_aggregates_fragments():
    rep = verify_report(["revenue 50,000", "made-up 777777"], RESULTS)
    assert not rep.ok
    assert rep.unmatched == ["777777"]
    assert rep.checked == 2 and rep.matched == 1


def test_verify_report_all_clean():
    rep = verify_report(["Total 123456.79", "growth 12.4%"], RESULTS)
    assert rep.ok and rep.unmatched == []


def test_grounded_share_of_total_passes():
    # 50000 / 123456.789 * 100 = 40.5% — a real ratio of two saved numbers.
    rep = verify_text("January contributed 40.5% of total revenue", NUMBERS)
    assert rep.ok, rep.unmatched
    # 73456.789 / 123456.789 * 100 = 59.5%
    assert verify_text("February made up 59.5% of revenue", NUMBERS).ok


def test_share_not_a_real_ratio_still_fails():
    # 22.2% is not (any saved number / a dominant total); must be rejected.
    rep = verify_text("January was 22.2% of revenue", NUMBERS)
    assert not rep.ok and "22.2" in rep.unmatched


def test_ratio_denominator_must_be_dominant_total():
    # avg_order (87.5) is small; a ratio using it as denominator is NOT accepted,
    # so a number derivable only via a small denominator still fails.
    # 50000 / 87.5 * 100 is huge; pick a value derivable only from small denoms:
    # 0.124 / 87.5 * 100 = 0.1417… — claiming 0.14 must fail (87.5 not a top total).
    rep = verify_text("The figure was 0.14 by that measure", NUMBERS)
    assert not rep.ok and "0.14" in rep.unmatched


def test_redaction_replaces_only_unmatched():
    text = "Real: 50,000. Fake: 777777."
    out = redact_unverified(text, ["777777"])
    assert "777777" not in out
    assert "[unverified]" in out
    assert "50,000" in out
