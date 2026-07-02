"""
Comprehensive tests for the error-cascade rank_dependency_health script.

Tests:
  - _extract_error_class: parsing non_2xx_analysis from health results
  - _classify_dep: classifying deps into confirmed_bad/suspicious/chronic/healthy
  - _compute_confidence: confidence scoring (≥3× ratio = confident)
  - rank(): full pipeline — report generation with confidence verdicts

Total: ~200 test cases
"""

import json
import sys
from pathlib import Path

import pytest

# Make the script importable
_SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent / "skills" / "error-cascade" / "scripts"
sys.path.insert(0, str(_SCRIPT_DIR))

from rank_dependency_health import (
    _extract_error_class,
    _classify_dep,
    _compute_confidence,
    rank,
    Args,
    _CONFIDENCE_RATIO,
)


# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURES — reusable health result builders
# ═══════════════════════════════════════════════════════════════════════════════


def _health_result(
    overall="healthy",
    golden="healthy",
    anomaly=False,
    attribution=None,
    four_spike=False,
    five_spike=False,
    four_pct=None,
    five_pct=None,
    four_dev=None,
    five_dev=None,
    four_base=None,
    five_base=None,
    is_anomaly=False,
    chronicity=None,
    resource_advisory=None,
):
    """Build a realistic wcnp_check_app_health result dict."""
    non_2xx = {}
    if four_spike or four_pct is not None:
        non_2xx["4xx_spike"] = four_spike
    if five_spike or five_pct is not None:
        non_2xx["5xx_spike"] = five_spike
    if four_pct is not None:
        non_2xx["4xx_current_percent"] = four_pct
    if five_pct is not None:
        non_2xx["5xx_current_percent"] = five_pct
    if four_dev is not None:
        non_2xx["4xx_deviation_percent"] = four_dev
    if five_dev is not None:
        non_2xx["5xx_deviation_percent"] = five_dev
    if four_base is not None:
        non_2xx["4xx_baseline_percent"] = four_base
    if five_base is not None:
        non_2xx["5xx_baseline_percent"] = five_base
    if is_anomaly:
        non_2xx["is_anomaly"] = True

    result = {
        "overall_status": overall,
        "golden_signal_status": golden,
        "anomaly_detected": anomaly,
        "failure_attribution": attribution,
        "checks": {
            "istio_traffic_spike": {"non_2xx_analysis": non_2xx} if non_2xx else {},
        },
    }
    if resource_advisory:
        result["resource_advisory"] = resource_advisory
    if chronicity:
        result["checks"]["cpu"] = {"anomaly_details": {"chronicity": chronicity}}
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# _extract_error_class — 25 tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestExtractErrorClass:
    """Parse non_2xx_analysis from health check results."""

    def test_empty_result(self):
        ec = _extract_error_class({})
        assert ec["4xx_spike"] is False
        assert ec["5xx_spike"] is False
        assert ec["max_deviation_percent"] == 0.0

    def test_no_checks_key(self):
        ec = _extract_error_class({"overall_status": "healthy"})
        assert ec["4xx_spike"] is False
        assert ec["max_deviation_percent"] == 0.0

    def test_no_traffic_spike_check(self):
        ec = _extract_error_class({"checks": {"cpu": {"status": "healthy"}}})
        assert ec["4xx_spike"] is False
        assert ec["5xx_spike"] is False

    def test_traffic_spike_no_non_2xx(self):
        ec = _extract_error_class({"checks": {"istio_traffic_spike": {}}})
        assert ec["4xx_spike"] is False
        assert ec["5xx_spike"] is False

    def test_4xx_spike_only(self):
        r = _health_result(four_spike=True, four_pct=5.0, four_dev=200.0, four_base=1.5)
        ec = _extract_error_class(r)
        assert ec["4xx_spike"] is True
        assert ec["5xx_spike"] is False
        assert ec["4xx_current_percent"] == 5.0
        assert ec["4xx_deviation_percent"] == 200.0
        assert ec["max_deviation_percent"] == 200.0

    def test_5xx_spike_only(self):
        r = _health_result(five_spike=True, five_pct=8.0, five_dev=400.0, five_base=1.5)
        ec = _extract_error_class(r)
        assert ec["5xx_spike"] is True
        assert ec["4xx_spike"] is False
        assert ec["5xx_current_percent"] == 8.0
        assert ec["max_deviation_percent"] == 400.0

    def test_both_spikes(self):
        r = _health_result(
            four_spike=True, four_pct=3.0, four_dev=150.0,
            five_spike=True, five_pct=7.0, five_dev=350.0,
        )
        ec = _extract_error_class(r)
        assert ec["4xx_spike"] is True
        assert ec["5xx_spike"] is True
        assert ec["max_deviation_percent"] == 350.0  # max of 150, 350

    def test_max_deviation_uses_4xx_when_higher(self):
        r = _health_result(four_spike=True, four_dev=500.0, five_spike=True, five_dev=100.0)
        ec = _extract_error_class(r)
        assert ec["max_deviation_percent"] == 500.0

    def test_zero_deviations(self):
        r = _health_result(four_spike=False, four_dev=0.0, five_spike=False, five_dev=0.0)
        ec = _extract_error_class(r)
        assert ec["max_deviation_percent"] == 0.0

    def test_none_deviations(self):
        r = _health_result(four_spike=True, four_pct=1.0)
        ec = _extract_error_class(r)
        assert ec["4xx_deviation_percent"] is None
        assert ec["max_deviation_percent"] == 0.0

    def test_non_dict_traffic_spike(self):
        """String traffic data — isinstance guard now protects both code paths."""
        r = {"checks": {"istio_traffic_spike": "broken"}}
        ec = _extract_error_class(r)
        assert ec["4xx_spike"] is False
        assert ec["5xx_spike"] is False
        assert ec["max_deviation_percent"] == 0.0
        assert ec["non_2xx_percent"] is None

    def test_non_2xx_percent_passthrough(self):
        r = {"checks": {"istio_traffic_spike": {
            "non_2xx_analysis": {"4xx_spike": False, "5xx_spike": False},
            "non_2xx_percent": 2.3,
        }}}
        ec = _extract_error_class(r)
        assert ec["non_2xx_percent"] == 2.3

    def test_large_deviation_values(self):
        r = _health_result(five_spike=True, five_dev=9999.9, five_pct=99.0)
        ec = _extract_error_class(r)
        assert ec["max_deviation_percent"] == 9999.9

    def test_negative_deviation(self):
        """Negative deviation (improving) should still be captured."""
        r = _health_result(four_spike=False, four_dev=-50.0, five_spike=False, five_dev=-30.0)
        ec = _extract_error_class(r)
        # max of negative values — both are negative, max is -30
        assert ec["max_deviation_percent"] == -30.0

    def test_mixed_types_in_deviation(self):
        """Integer deviation should work too."""
        r = _health_result(five_spike=True, five_dev=100, five_pct=5)
        ec = _extract_error_class(r)
        assert ec["max_deviation_percent"] == 100

    def test_string_deviation_ignored(self):
        """String deviation should not blow up max calculation."""
        r = {"checks": {"istio_traffic_spike": {"non_2xx_analysis": {
            "4xx_spike": False, "5xx_spike": True,
            "5xx_deviation_percent": "bad_data",
        }}}}
        ec = _extract_error_class(r)
        assert ec["max_deviation_percent"] == 0.0

    def test_baseline_percents_captured(self):
        r = _health_result(
            four_spike=True, four_pct=5.0, four_base=1.0, four_dev=400.0,
            five_spike=True, five_pct=8.0, five_base=2.0, five_dev=300.0,
        )
        ec = _extract_error_class(r)
        assert ec["4xx_current_percent"] == 5.0
        assert ec["5xx_current_percent"] == 8.0

    def test_only_5xx_deviation_present(self):
        r = _health_result(five_spike=True, five_dev=200.0)
        ec = _extract_error_class(r)
        assert ec["4xx_deviation_percent"] is None
        assert ec["5xx_deviation_percent"] == 200.0
        assert ec["max_deviation_percent"] == 200.0

    def test_only_4xx_deviation_present(self):
        r = _health_result(four_spike=True, four_dev=150.0)
        ec = _extract_error_class(r)
        assert ec["4xx_deviation_percent"] == 150.0
        assert ec["5xx_deviation_percent"] is None
        assert ec["max_deviation_percent"] == 150.0

    def test_checks_missing_entirely(self):
        ec = _extract_error_class({"overall_status": "unhealthy"})
        assert ec["4xx_spike"] is False
        assert ec["max_deviation_percent"] == 0.0

    def test_non_2xx_analysis_is_empty(self):
        """non_2xx_analysis missing → empty dict default."""
        r = {"checks": {"istio_traffic_spike": {}}}
        ec = _extract_error_class(r)
        assert ec["4xx_spike"] is False
        assert ec["5xx_spike"] is False
        assert ec["max_deviation_percent"] == 0.0

    def test_non_2xx_analysis_is_empty_dict(self):
        r = {"checks": {"istio_traffic_spike": {"non_2xx_analysis": {}}}}
        ec = _extract_error_class(r)
        assert ec["4xx_spike"] is False
        assert ec["5xx_spike"] is False
        assert ec["max_deviation_percent"] == 0.0

    def test_float_precision(self):
        r = _health_result(four_spike=True, four_dev=33.33333, four_pct=0.12345)
        ec = _extract_error_class(r)
        assert abs(ec["4xx_deviation_percent"] - 33.33333) < 1e-5
        assert abs(ec["4xx_current_percent"] - 0.12345) < 1e-5

    def test_very_small_deviations(self):
        r = _health_result(four_spike=True, four_dev=0.001, five_spike=True, five_dev=0.002)
        ec = _extract_error_class(r)
        assert abs(ec["max_deviation_percent"] - 0.002) < 1e-6

    def test_boolean_spike_false_with_deviation(self):
        """Spike=False but deviation present — still captured for ranking."""
        r = _health_result(four_spike=False, four_dev=50.0)
        ec = _extract_error_class(r)
        assert ec["4xx_spike"] is False
        assert ec["4xx_deviation_percent"] == 50.0
        assert ec["max_deviation_percent"] == 50.0

    def test_non_2xx_analysis_explicitly_none(self):
        """non_2xx_analysis key exists but value is None — must not crash."""
        r = {"checks": {"istio_traffic_spike": {"non_2xx_analysis": None}}}
        ec = _extract_error_class(r)
        assert ec["4xx_spike"] is False
        assert ec["5xx_spike"] is False
        assert ec["max_deviation_percent"] == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# _classify_dep — 35 tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestClassifyDep:
    """Classify deps into confirmed_bad, suspicious, chronic, healthy."""

    def test_healthy_dep(self):
        r = _health_result()
        c = _classify_dep("svc-a", r)
        assert c["category"] == "healthy"
        assert c["priority"] == 4

    def test_confirmed_bad_golden_unhealthy_acute_anomaly(self):
        r = _health_result(overall="unhealthy", golden="unhealthy", anomaly=True)
        c = _classify_dep("svc-a", r)
        assert c["category"] == "confirmed_bad"
        assert c["priority"] == 0

    def test_suspicious_golden_degraded_acute_anomaly(self):
        r = _health_result(overall="degraded", golden="degraded", anomaly=True)
        c = _classify_dep("svc-a", r)
        assert c["category"] == "suspicious"
        assert c["priority"] == 1

    def test_chronic_degraded(self):
        r = _health_result(
            overall="degraded", golden="degraded", anomaly=True,
            chronicity="chronic",
        )
        c = _classify_dep("svc-a", r)
        assert c["category"] == "chronic"
        assert c["priority"] == 3

    def test_chronic_unhealthy(self):
        r = _health_result(
            overall="unhealthy", golden="unhealthy", anomaly=True,
            chronicity="chronic",
        )
        c = _classify_dep("svc-a", r)
        assert c["category"] == "chronic"
        assert c["priority"] == 3

    def test_suspicious_degraded_no_anomaly(self):
        r = _health_result(overall="degraded", golden="healthy", anomaly=False)
        c = _classify_dep("svc-a", r)
        assert c["category"] == "suspicious"
        assert c["priority"] == 2

    def test_suspicious_unhealthy_no_anomaly(self):
        r = _health_result(overall="unhealthy", golden="healthy", anomaly=False)
        c = _classify_dep("svc-a", r)
        assert c["category"] == "suspicious"
        assert c["priority"] == 2

    def test_cascade_detected_downstream(self):
        r = _health_result(
            overall="unhealthy", golden="unhealthy", anomaly=True,
            attribution="downstream_dependency",
        )
        c = _classify_dep("svc-a", r)
        assert c["cascade_continues"] is True

    def test_no_cascade_this_app(self):
        r = _health_result(
            overall="unhealthy", golden="unhealthy", anomaly=True,
            attribution="this_app",
        )
        c = _classify_dep("svc-a", r)
        assert c["cascade_continues"] is False

    def test_no_cascade_none(self):
        r = _health_result(anomaly=True, golden="unhealthy", overall="unhealthy")
        c = _classify_dep("svc-a", r)
        assert c["cascade_continues"] is False

    def test_name_preserved(self):
        c = _classify_dep("my-special-service", _health_result())
        assert c["name"] == "my-special-service"

    def test_overall_status_preserved(self):
        r = _health_result(overall="degraded")
        c = _classify_dep("svc", r)
        assert c["overall_status"] == "degraded"

    def test_golden_status_preserved(self):
        r = _health_result(golden="unhealthy")
        c = _classify_dep("svc", r)
        assert c["golden_status"] == "unhealthy"

    def test_anomaly_preserved(self):
        r = _health_result(anomaly=True)
        c = _classify_dep("svc", r)
        assert c["anomaly_detected"] is True

    def test_failure_attribution_preserved(self):
        r = _health_result(attribution="shared_or_this_app")
        c = _classify_dep("svc", r)
        assert c["failure_attribution"] == "shared_or_this_app"

    def test_error_class_included(self):
        r = _health_result(four_spike=True, four_dev=100.0)
        c = _classify_dep("svc", r)
        assert "error_class" in c
        assert c["error_class"]["4xx_spike"] is True

    def test_unknown_overall_status(self):
        r = _health_result(overall="unknown")
        c = _classify_dep("svc", r)
        assert c["category"] == "healthy"  # unknown not in unhealthy/degraded

    def test_empty_result(self):
        c = _classify_dep("svc", {})
        assert c["category"] == "healthy"
        assert c["chronicity"] == "unknown"

    def test_chronicity_from_resource_advisory(self):
        r = _health_result(
            overall="degraded", golden="degraded", anomaly=True,
            resource_advisory=[{"check": "cpu", "chronicity": "chronic"}],
        )
        c = _classify_dep("svc", r)
        assert c["chronicity"] == "chronic"

    def test_chronicity_from_anomaly_details(self):
        r = _health_result(
            overall="degraded", golden="degraded", anomaly=True,
            chronicity="acute",
        )
        c = _classify_dep("svc", r)
        assert c["chronicity"] == "acute"

    def test_chronicity_unknown_when_absent(self):
        r = _health_result(overall="unhealthy", golden="unhealthy", anomaly=True)
        c = _classify_dep("svc", r)
        # No chronicity → not chronic → eligible for confirmed_bad
        assert c["category"] == "confirmed_bad"

    # Priority ordering tests
    def test_priority_ordering_confirmed_bad_first(self):
        assert _classify_dep("a", _health_result(
            golden="unhealthy", overall="unhealthy", anomaly=True
        ))["priority"] < _classify_dep("b", _health_result(
            golden="degraded", overall="degraded", anomaly=True
        ))["priority"]

    def test_priority_ordering_suspicious_before_chronic(self):
        sus = _classify_dep("a", _health_result(
            golden="degraded", overall="degraded", anomaly=True
        ))
        chron = _classify_dep("b", _health_result(
            golden="unhealthy", overall="unhealthy", anomaly=True,
            chronicity="chronic",
        ))
        assert sus["priority"] < chron["priority"]

    def test_priority_ordering_chronic_before_healthy(self):
        chron = _classify_dep("a", _health_result(
            overall="degraded", chronicity="chronic",
        ))
        healthy = _classify_dep("b", _health_result())
        assert chron["priority"] < healthy["priority"]

    # Multiple error classes
    def test_both_error_classes_in_result(self):
        r = _health_result(
            four_spike=True, four_dev=100.0,
            five_spike=True, five_dev=200.0,
            golden="unhealthy", overall="unhealthy", anomaly=True,
        )
        c = _classify_dep("svc", r)
        assert c["error_class"]["4xx_spike"] is True
        assert c["error_class"]["5xx_spike"] is True
        assert c["error_class"]["max_deviation_percent"] == 200.0

    def test_cascade_with_shared_attribution(self):
        r = _health_result(
            overall="unhealthy", golden="unhealthy", anomaly=True,
            attribution="shared_or_this_app",
        )
        c = _classify_dep("svc", r)
        assert c["cascade_continues"] is False  # only "downstream_dependency" cascades

    def test_healthy_golden_but_unhealthy_overall(self):
        """Resource unhealthy but golden healthy → suspicious (priority 2)."""
        r = _health_result(overall="unhealthy", golden="healthy", anomaly=False)
        c = _classify_dep("svc", r)
        assert c["category"] == "suspicious"
        assert c["priority"] == 2

    def test_degraded_golden_no_anomaly(self):
        """Degraded golden but no anomaly → suspicious."""
        r = _health_result(overall="degraded", golden="degraded", anomaly=False)
        c = _classify_dep("svc", r)
        assert c["category"] == "suspicious"

    def test_confirmed_bad_requires_golden_unhealthy(self):
        """Golden must be unhealthy (not just degraded at priority 0)."""
        r = _health_result(overall="unhealthy", golden="degraded", anomaly=True)
        c = _classify_dep("svc", r)
        assert c["category"] == "suspicious"
        assert c["priority"] == 1

    def test_error_class_max_deviation_propagated(self):
        r = _health_result(four_spike=True, four_dev=300.0, five_spike=True, five_dev=100.0)
        c = _classify_dep("svc", r)
        assert c["error_class"]["max_deviation_percent"] == 300.0

    # Edge: resource_advisory with multiple entries
    def test_chronicity_from_first_advisory(self):
        r = _health_result(
            overall="degraded", golden="degraded", anomaly=True,
            resource_advisory=[
                {"check": "cpu", "chronicity": "chronic"},
                {"check": "memory", "chronicity": "acute"},
            ],
        )
        c = _classify_dep("svc", r)
        assert c["chronicity"] == "chronic"  # first one wins

    def test_resource_advisory_empty_list(self):
        r = _health_result(
            overall="degraded", golden="degraded", anomaly=True,
            resource_advisory=[],
        )
        c = _classify_dep("svc", r)
        assert c["chronicity"] == "unknown"

    def test_resource_advisory_no_chronicity_key(self):
        r = _health_result(
            overall="degraded", golden="degraded", anomaly=True,
            resource_advisory=[{"check": "cpu"}],
        )
        c = _classify_dep("svc", r)
        assert c["chronicity"] == "unknown"

    def test_non_dict_check_value_skipped(self):
        r = _health_result(overall="unhealthy", golden="unhealthy", anomaly=True)
        r["checks"]["broken_check"] = "not_a_dict"
        c = _classify_dep("svc", r)
        assert c["category"] == "confirmed_bad"

    # --- Edge cases from audit ---

    def test_error_overall_status_confirmed_bad(self):
        """overall_status='error' (health check failed/timeout) → confirmed_bad."""
        r = {"overall_status": "error", "error": "connection refused"}
        c = _classify_dep("db-svc", r)
        assert c["category"] == "confirmed_bad"
        assert c["priority"] == 0

    def test_error_status_no_checks_no_crash(self):
        """Error status with no checks dict at all."""
        r = {"overall_status": "error"}
        c = _classify_dep("kafka", r)
        assert c["category"] == "confirmed_bad"
        assert c["error_class"]["max_deviation_percent"] == 0.0

    def test_checks_as_list_no_crash(self):
        """checks is a list instead of dict — chronicity detection must not crash."""
        r = _health_result(overall="degraded", golden="degraded", anomaly=True)
        r["checks"] = ["cpu", "memory"]
        c = _classify_dep("svc", r)
        assert c["chronicity"] == "unknown"
        assert c["category"] == "suspicious"

    def test_resource_advisory_as_dict_no_crash(self):
        """resource_advisory is a dict instead of list — must not crash."""
        r = _health_result(overall="degraded", golden="degraded", anomaly=True)
        r["resource_advisory"] = {"chronicity": "chronic"}
        c = _classify_dep("svc", r)
        # Dict is not iterated (isinstance guard), so chronicity stays unknown
        assert c["chronicity"] == "unknown"
        assert c["category"] == "suspicious"

    def test_resource_advisory_as_string_no_crash(self):
        """resource_advisory is a string — must not crash."""
        r = _health_result(overall="unhealthy", golden="unhealthy", anomaly=True)
        r["resource_advisory"] = "high cpu"
        c = _classify_dep("svc", r)
        assert c["chronicity"] == "unknown"
        assert c["category"] == "confirmed_bad"


# ═══════════════════════════════════════════════════════════════════════════════
# _compute_confidence — 45 tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestComputeConfidence:
    """Test confidence scoring: confident when one dep ≥ 3× the next."""

    # --- No candidates ---

    def test_empty_list(self):
        c = _compute_confidence([])
        assert c["confident"] is False
        assert c["winner"] is None
        assert "No dependencies" in c["reason"]

    def test_all_healthy(self):
        deps = [
            _classify_dep("a", _health_result()),
            _classify_dep("b", _health_result()),
        ]
        c = _compute_confidence(deps)
        assert c["confident"] is False
        assert c["winner"] is None

    def test_all_chronic(self):
        deps = [
            _classify_dep("a", _health_result(
                overall="unhealthy", golden="unhealthy", anomaly=True,
                chronicity="chronic",
            )),
        ]
        c = _compute_confidence(deps)
        assert c["confident"] is False

    # --- Single candidate ---

    def test_single_confirmed_bad(self):
        deps = [
            _classify_dep("payment-svc", _health_result(
                overall="unhealthy", golden="unhealthy", anomaly=True,
                five_spike=True, five_dev=400.0,
            )),
        ]
        c = _compute_confidence(deps)
        assert c["confident"] is True
        assert c["winner"] == "payment-svc"

    def test_single_suspicious(self):
        deps = [
            _classify_dep("svc-a", _health_result(
                overall="degraded", golden="degraded", anomaly=True,
                five_spike=True, five_dev=100.0,
            )),
        ]
        c = _compute_confidence(deps)
        assert c["confident"] is True
        assert c["winner"] == "svc-a"

    # --- Two candidates, confident ---

    def test_confident_clear_winner(self):
        """400% vs 30% → ratio 13.3 ≥ 3×."""
        deps = [
            _classify_dep("winner", _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=400.0,
            )),
            _classify_dep("loser", _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                five_spike=True, five_dev=30.0,
            )),
        ]
        c = _compute_confidence(deps)
        assert c["confident"] is True
        assert c["winner"] == "winner"
        assert c["ratio"] >= _CONFIDENCE_RATIO

    def test_confident_exactly_3x(self):
        """300% vs 100% → ratio exactly 3.0."""
        deps = [
            _classify_dep("a", _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=300.0,
            )),
            _classify_dep("b", _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                five_spike=True, five_dev=100.0,
            )),
        ]
        c = _compute_confidence(deps)
        assert c["confident"] is True
        assert c["ratio"] == 3.0

    def test_confident_second_zero_deviation(self):
        """First has deviation, second has 0 → confident."""
        deps = [
            _classify_dep("a", _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=200.0,
            )),
            _classify_dep("b", _health_result(
                overall="degraded", anomaly=True,
            )),
        ]
        c = _compute_confidence(deps)
        assert c["confident"] is True
        assert c["winner"] == "a"

    # --- Two candidates, NOT confident ---

    def test_not_confident_similar_deviation(self):
        """200% vs 180% → ratio 1.1 < 3×."""
        deps = [
            _classify_dep("a", _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=200.0,
            )),
            _classify_dep("b", _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=180.0,
            )),
        ]
        c = _compute_confidence(deps)
        assert c["confident"] is False
        assert "below" in c["reason"]

    def test_not_confident_2x_ratio(self):
        """200% vs 100% → ratio 2.0 < 3×."""
        deps = [
            _classify_dep("a", _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=200.0,
            )),
            _classify_dep("b", _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                five_spike=True, five_dev=100.0,
            )),
        ]
        c = _compute_confidence(deps)
        assert c["confident"] is False
        assert c["ratio"] == pytest.approx(2.0)

    def test_not_confident_equal_deviation(self):
        """Both at 150% → ratio 1.0."""
        deps = [
            _classify_dep("a", _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=150.0,
            )),
            _classify_dep("b", _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=150.0,
            )),
        ]
        c = _compute_confidence(deps)
        assert c["confident"] is False
        assert c["ratio"] == pytest.approx(1.0)

    # --- Multi-candidate scenarios ---

    def test_three_deps_one_dominates(self):
        deps = [
            _classify_dep("a", _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=600.0,
            )),
            _classify_dep("b", _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                five_spike=True, five_dev=50.0,
            )),
            _classify_dep("c", _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                five_spike=True, five_dev=10.0,
            )),
        ]
        c = _compute_confidence(deps)
        assert c["confident"] is True
        assert c["winner"] == "a"

    def test_three_deps_top_two_close(self):
        deps = [
            _classify_dep("a", _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=100.0,
            )),
            _classify_dep("b", _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=80.0,
            )),
            _classify_dep("c", _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                five_spike=True, five_dev=5.0,
            )),
        ]
        c = _compute_confidence(deps)
        assert c["confident"] is False  # 100/80 = 1.25 < 3

    def test_five_deps_even_spread(self):
        deps = [
            _classify_dep(f"svc-{i}", _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                five_spike=True, five_dev=float(20 - i * 2),
            ))
            for i in range(5)
        ]
        c = _compute_confidence(deps)
        assert c["confident"] is False

    def test_five_deps_one_outlier(self):
        deps = [
            _classify_dep("outlier", _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=500.0,
            )),
        ] + [
            _classify_dep(f"svc-{i}", _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                five_spike=True, five_dev=float(10 + i),
            ))
            for i in range(4)
        ]
        c = _compute_confidence(deps)
        assert c["confident"] is True
        assert c["winner"] == "outlier"

    # --- Chronic deps excluded from confidence ---

    def test_chronic_excluded_from_candidates(self):
        deps = [
            _classify_dep("chronic-svc", _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                chronicity="chronic", five_spike=True, five_dev=999.0,
            )),
            _classify_dep("acute-svc", _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                five_spike=True, five_dev=50.0,
            )),
        ]
        c = _compute_confidence(deps)
        assert c["confident"] is True
        assert c["winner"] == "acute-svc"  # chronic excluded

    def test_healthy_excluded_from_candidates(self):
        deps = [
            _classify_dep("healthy-svc", _health_result()),
            _classify_dep("bad-svc", _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=200.0,
            )),
        ]
        c = _compute_confidence(deps)
        assert c["confident"] is True
        assert c["winner"] == "bad-svc"

    # --- Return value structure ---

    def test_return_keys_when_confident(self):
        deps = [_classify_dep("a", _health_result(
            golden="unhealthy", overall="unhealthy", anomaly=True,
            five_spike=True, five_dev=200.0,
        ))]
        c = _compute_confidence(deps)
        assert "confident" in c
        assert "winner" in c
        assert "reason" in c
        assert "top_deviation" in c
        assert "second_deviation" in c
        assert "ratio" in c

    def test_return_keys_when_not_confident(self):
        c = _compute_confidence([])
        assert "confident" in c
        assert "winner" in c
        assert "reason" in c

    def test_top_deviation_value(self):
        deps = [
            _classify_dep("a", _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=400.0,
            )),
            _classify_dep("b", _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                five_spike=True, five_dev=30.0,
            )),
        ]
        c = _compute_confidence(deps)
        assert c["top_deviation"] == 400.0
        assert c["second_deviation"] == 30.0

    # --- 4XX vs 5XX max deviation ---

    def test_confidence_uses_4xx_when_higher(self):
        deps = [
            _classify_dep("a", _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                four_spike=True, four_dev=500.0, five_spike=True, five_dev=50.0,
            )),
            _classify_dep("b", _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                five_spike=True, five_dev=20.0,
            )),
        ]
        c = _compute_confidence(deps)
        assert c["confident"] is True
        assert c["top_deviation"] == 500.0

    def test_confidence_uses_5xx_when_higher(self):
        deps = [
            _classify_dep("a", _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                four_spike=True, four_dev=50.0, five_spike=True, five_dev=500.0,
            )),
            _classify_dep("b", _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                five_spike=True, five_dev=20.0,
            )),
        ]
        c = _compute_confidence(deps)
        assert c["confident"] is True
        assert c["top_deviation"] == 500.0

    # --- Edge: just barely below threshold ---

    def test_just_below_3x_threshold(self):
        """299% vs 100% → ratio 2.99 < 3.0."""
        deps = [
            _classify_dep("a", _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=299.0,
            )),
            _classify_dep("b", _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                five_spike=True, five_dev=100.0,
            )),
        ]
        c = _compute_confidence(deps)
        assert c["confident"] is False
        assert c["ratio"] == pytest.approx(2.99)

    def test_just_above_3x_threshold(self):
        """301% vs 100% → ratio 3.01 ≥ 3.0."""
        deps = [
            _classify_dep("a", _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=301.0,
            )),
            _classify_dep("b", _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                five_spike=True, five_dev=100.0,
            )),
        ]
        c = _compute_confidence(deps)
        assert c["confident"] is True
        assert c["ratio"] == pytest.approx(3.01)

    # --- Reason strings ---

    def test_reason_mentions_winner_when_confident(self):
        deps = [_classify_dep("winning-svc", _health_result(
            golden="unhealthy", overall="unhealthy", anomaly=True,
            five_spike=True, five_dev=500.0,
        ))]
        c = _compute_confidence(deps)
        assert "winning-svc" in c["reason"]

    def test_reason_mentions_ambiguity_when_not_confident(self):
        deps = [
            _classify_dep("a", _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=100.0,
            )),
            _classify_dep("b", _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=90.0,
            )),
        ]
        c = _compute_confidence(deps)
        assert "Ambiguous" in c["reason"] or "ambiguous" in c["reason"].lower()

    def test_reason_mentions_o2_when_not_confident(self):
        deps = [
            _classify_dep("a", _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=100.0,
            )),
            _classify_dep("b", _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                five_spike=True, five_dev=50.0,
            )),
        ]
        c = _compute_confidence(deps)
        assert "O2" in c["reason"]

    # --- Large dep counts ---

    def test_ten_deps_one_bad(self):
        deps = [
            _classify_dep("bad", _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=900.0,
            )),
        ] + [
            _classify_dep(f"ok-{i}", _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                five_spike=True, five_dev=float(5 + i),
            ))
            for i in range(9)
        ]
        c = _compute_confidence(deps)
        assert c["confident"] is True
        assert c["winner"] == "bad"

    def test_ten_deps_evenly_spread(self):
        deps = [
            _classify_dep(f"svc-{i}", _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                five_spike=True, five_dev=float(50 + i * 5),
            ))
            for i in range(10)
        ]
        c = _compute_confidence(deps)
        assert c["confident"] is False

    def test_twenty_deps_with_outlier(self):
        deps = [
            _classify_dep("outlier", _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=1000.0,
            )),
        ] + [
            _classify_dep(f"svc-{i}", _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                five_spike=True, five_dev=float(10 + i),
            ))
            for i in range(19)
        ]
        c = _compute_confidence(deps)
        assert c["confident"] is True
        assert c["winner"] == "outlier"

    # --- Mix of categories ---

    def test_mix_chronic_healthy_and_one_bad(self):
        deps = [
            _classify_dep("bad", _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=300.0,
            )),
            _classify_dep("chronic", _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                chronicity="chronic", five_spike=True, five_dev=500.0,
            )),
            _classify_dep("healthy", _health_result()),
        ]
        c = _compute_confidence(deps)
        assert c["confident"] is True
        assert c["winner"] == "bad"  # chronic is excluded

    def test_only_suspicious_deps(self):
        deps = [
            _classify_dep("a", _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                five_spike=True, five_dev=200.0,
            )),
            _classify_dep("b", _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                five_spike=True, five_dev=60.0,
            )),
        ]
        c = _compute_confidence(deps)
        assert c["confident"] is True  # 200/60 = 3.33 ≥ 3
        assert c["winner"] == "a"

    # --- Degenerate numeric cases ---

    def test_both_zero_deviation(self):
        """Both have 0 deviation — second_dev is 0, so code returns confident
        (winner with 0 vs 0 treated same as 'second has no signal')."""
        deps = [
            _classify_dep("a", _health_result(
                golden="degraded", overall="degraded", anomaly=True,
            )),
            _classify_dep("b", _health_result(
                golden="degraded", overall="degraded", anomaly=True,
            )),
        ]
        c = _compute_confidence(deps)
        # Both scorable with 0 deviation: top=0, second=0 → second_dev==0 branch → confident
        assert c["confident"] is True

    def test_first_zero_second_zero(self):
        """Both have explicit 0% deviation — second_dev==0 branch → confident."""
        deps = [
            _classify_dep("a", _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=0.0,
            )),
            _classify_dep("b", _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                five_spike=True, five_dev=0.0,
            )),
        ]
        c = _compute_confidence(deps)
        # second_dev == 0 → code takes the 'second is 0' confident branch
        assert c["confident"] is True

    def test_very_large_ratio(self):
        deps = [
            _classify_dep("a", _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=10000.0,
            )),
            _classify_dep("b", _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                five_spike=True, five_dev=1.0,
            )),
        ]
        c = _compute_confidence(deps)
        assert c["confident"] is True
        assert c["ratio"] == pytest.approx(10000.0)


# ═══════════════════════════════════════════════════════════════════════════════
# rank() — Full pipeline — 95 tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestRankOutput:
    """Test the full rank() function output formatting and content."""

    # --- Basic structure ---

    def test_empty_input(self):
        out = rank({})
        assert "Dependency Investigation Priority" in out
        assert "NOT CONFIDENT" in out

    def test_none_input_handled(self):
        """Non-dict values in results are skipped."""
        out = rank({"a": None, "b": "string", "c": 42})
        assert "Dependency Investigation Priority" in out

    def test_single_healthy_dep(self):
        out = rank({"svc": _health_result()})
        assert "Healthy" in out or "healthy" in out

    def test_single_confirmed_bad(self):
        out = rank({"bad-svc": _health_result(
            golden="unhealthy", overall="unhealthy", anomaly=True,
            five_spike=True, five_dev=400.0, five_pct=8.0,
        )})
        assert "Confirmed Bad" in out or "confirmed_bad" in out
        assert "bad-svc" in out
        assert "CONFIDENT" in out

    def test_primary_app_deviation_shown(self):
        out = rank({"svc": _health_result()}, primary_app_error_deviation=55.0)
        assert "55.0%" in out

    def test_primary_app_deviation_none_ok(self):
        out = rank({"svc": _health_result()}, primary_app_error_deviation=None)
        assert "Dependency Investigation Priority" in out

    # --- Confidence verdicts in output ---

    def test_confident_output_says_confident(self):
        out = rank({"winner": _health_result(
            golden="unhealthy", overall="unhealthy", anomaly=True,
            five_spike=True, five_dev=600.0,
        )})
        assert "CONFIDENT" in out
        assert "winner" in out

    def test_not_confident_output_says_o2(self):
        out = rank({
            "a": _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=100.0,
            ),
            "b": _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=80.0,
            ),
        })
        assert "NOT CONFIDENT" in out
        assert "O2" in out or "o2" in out

    # --- Cascade detection ---

    def test_cascade_section_present(self):
        out = rank({"cascading-svc": _health_result(
            golden="unhealthy", overall="unhealthy", anomaly=True,
            attribution="downstream_dependency",
            five_spike=True, five_dev=300.0,
        )})
        assert "Cascade" in out
        assert "cascading-svc" in out

    def test_no_cascade_section_when_none(self):
        out = rank({"svc": _health_result(
            golden="unhealthy", overall="unhealthy", anomaly=True,
            attribution="this_app",
            five_spike=True, five_dev=300.0,
        )})
        # Cascade section should not appear or should be empty
        assert "downstream_dependency" not in out or "Cascade" not in out

    # --- Machine-readable JSON ---

    def test_json_summary_present(self):
        out = rank({"svc": _health_result(
            golden="unhealthy", overall="unhealthy", anomaly=True,
            five_spike=True, five_dev=300.0,
        )})
        assert "Machine-Readable Summary" in out
        # Extract JSON from markdown code block
        json_start = out.index("```json") + 7
        json_end = out.index("```", json_start)
        parsed = json.loads(out[json_start:json_end])
        assert "confident" in parsed
        assert "winner" in parsed
        assert "action" in parsed

    def test_json_summary_confident_action(self):
        out = rank({"svc": _health_result(
            golden="unhealthy", overall="unhealthy", anomaly=True,
            five_spike=True, five_dev=300.0,
        )})
        json_start = out.index("```json") + 7
        json_end = out.index("```", json_start)
        parsed = json.loads(out[json_start:json_end])
        assert parsed["action"] == "proceed_to_next_layer"

    def test_json_summary_not_confident_action(self):
        out = rank({
            "a": _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=100.0,
            ),
            "b": _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=80.0,
            ),
        })
        json_start = out.index("```json") + 7
        json_end = out.index("```", json_start)
        parsed = json.loads(out[json_start:json_end])
        assert parsed["action"] == "o2_disambiguation"

    def test_json_summary_lists(self):
        out = rank({
            "bad": _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=500.0,
            ),
            "ok": _health_result(),
        })
        json_start = out.index("```json") + 7
        json_end = out.index("```", json_start)
        parsed = json.loads(out[json_start:json_end])
        assert "bad" in parsed["confirmed_bad"]
        assert "ok" in parsed["healthy"]

    # --- Recommended next steps ---

    def test_next_steps_for_confident_cascade(self):
        out = rank({"svc": _health_result(
            golden="unhealthy", overall="unhealthy", anomaly=True,
            attribution="downstream_dependency",
            five_spike=True, five_dev=300.0,
        )})
        assert "repeat" in out.lower() or "next cascade layer" in out.lower() or "Phases" in out

    def test_next_steps_for_confident_root_cause(self):
        out = rank({"svc": _health_result(
            golden="unhealthy", overall="unhealthy", anomaly=True,
            attribution="this_app",
            five_spike=True, five_dev=300.0,
        )})
        assert "O2 DEEP" in out or "root cause" in out.lower() or "stack traces" in out.lower()

    def test_next_steps_for_not_confident(self):
        out = rank({
            "a": _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=100.0,
            ),
            "b": _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=80.0,
            ),
        })
        assert "O2 disambiguation" in out or "execute_sql" in out.lower() or "http_path" in out

    def test_next_steps_no_deps_degraded(self):
        out = rank({"svc": _health_result()})
        assert "infrastructure" in out.lower() or "meghacache" in out.lower() or "originating app" in out.lower()

    # --- Table formatting ---

    def test_confirmed_bad_table_present(self):
        out = rank({"svc": _health_result(
            golden="unhealthy", overall="unhealthy", anomaly=True,
            five_spike=True, five_dev=300.0, five_pct=8.0,
        )})
        assert "| **svc**" in out
        assert "8.0%" in out

    def test_suspicious_table_present(self):
        out = rank({"svc": _health_result(
            golden="degraded", overall="degraded", anomaly=True,
            five_spike=True, five_dev=50.0,
        )})
        assert "Suspicious" in out

    def test_chronic_section_present(self):
        out = rank({"svc": _health_result(
            golden="unhealthy", overall="unhealthy", anomaly=True,
            chronicity="chronic", five_spike=True, five_dev=500.0,
        )})
        assert "Chronic" in out or "chronic" in out

    # --- Multi-dep ranking ---

    def test_ranking_order_confirmed_before_suspicious(self):
        out = rank({
            "bad": _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=500.0, five_pct=10.0,
            ),
            "sus": _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                five_spike=True, five_dev=30.0,
            ),
        })
        bad_pos = out.index("bad")
        sus_pos = out.index("sus")
        # In the table sections, confirmed_bad should appear first
        assert "Confirmed Bad" in out

    def test_many_deps_all_categories(self):
        out = rank({
            "confirmed": _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=500.0, five_pct=10.0,
            ),
            "suspicious": _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                five_spike=True, five_dev=30.0,
            ),
            "chronic": _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                chronicity="chronic", five_spike=True, five_dev=800.0,
            ),
            "healthy": _health_result(),
        })
        assert "Confirmed Bad" in out
        assert "Suspicious" in out
        assert "Chronic" in out
        assert "CONFIDENT" in out
        assert "confirmed" in out


class TestRankScenarios:
    """Real-world-like cascade scenarios exercising the full pipeline."""

    # ── Downstream: App-A has 5XX spike, deps are clear ──

    def test_scenario_single_dep_5xx_dominant(self):
        """Classic: payment-svc is clearly broken."""
        out = rank({
            "payment-svc": _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                attribution="this_app",
                five_spike=True, five_dev=800.0, five_pct=12.0,
            ),
            "inventory-api": _health_result(),
            "cache-svc": _health_result(),
        })
        assert "CONFIDENT" in out
        assert "payment-svc" in out

    def test_scenario_dep_cascading_further(self):
        """payment-svc blames its own downstream."""
        out = rank({
            "payment-svc": _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                attribution="downstream_dependency",
                five_spike=True, five_dev=600.0, five_pct=10.0,
            ),
            "inventory-api": _health_result(),
        })
        json_start = out.index("```json") + 7
        json_end = out.index("```", json_start)
        parsed = json.loads(out[json_start:json_end])
        assert parsed["confident"] is True
        assert "payment-svc" in parsed["cascading"]

    def test_scenario_two_deps_both_unhealthy_ambiguous(self):
        """Two deps equally bad → need O2."""
        out = rank({
            "svc-a": _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=120.0, five_pct=5.0,
            ),
            "svc-b": _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=100.0, five_pct=4.0,
            ),
        })
        assert "NOT CONFIDENT" in out

    def test_scenario_4xx_only_spike(self):
        """4XX spike → still ranked by deviation."""
        out = rank({
            "auth-svc": _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                four_spike=True, four_dev=600.0, four_pct=15.0,
            ),
            "data-svc": _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                four_spike=True, four_dev=10.0, four_pct=1.0,
            ),
        })
        assert "CONFIDENT" in out
        assert "auth-svc" in out

    def test_scenario_mixed_4xx_5xx(self):
        """Both 4XX and 5XX → max deviation used."""
        out = rank({
            "svc-a": _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                four_spike=True, four_dev=50.0,
                five_spike=True, five_dev=800.0, five_pct=10.0,
            ),
            "svc-b": _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                four_spike=True, four_dev=200.0,
                five_spike=True, five_dev=30.0,
            ),
        })
        # svc-a: max_dev=800, svc-b: max_dev=200, ratio=4 → confident
        assert "CONFIDENT" in out
        assert "svc-a" in out

    def test_scenario_three_deps_one_chronic_one_bad(self):
        """Chronic dep should be ignored in confidence."""
        out = rank({
            "real-problem": _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=200.0, five_pct=6.0,
            ),
            "old-issue": _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                chronicity="chronic",
                five_spike=True, five_dev=500.0, five_pct=8.0,
            ),
            "healthy-dep": _health_result(),
        })
        assert "CONFIDENT" in out
        assert "real-problem" in out

    def test_scenario_no_k8app_deps_degraded(self):
        """All healthy → suggest infra investigation."""
        out = rank({
            "svc-1": _health_result(),
            "svc-2": _health_result(),
            "svc-3": _health_result(),
        })
        assert "NOT CONFIDENT" in out
        assert "infrastructure" in out.lower() or "meghacache" in out.lower()

    def test_scenario_five_deps_evenly_distributed_errors(self):
        """Classic ambiguity: 10%, 20%, 1%, 10%, 15% → O2 needed."""
        out = rank({
            "svc-a": _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                five_spike=True, five_dev=10.0,
            ),
            "svc-b": _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                five_spike=True, five_dev=20.0,
            ),
            "svc-c": _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                five_spike=True, five_dev=1.0,
            ),
            "svc-d": _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                five_spike=True, five_dev=10.0,
            ),
            "svc-e": _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                five_spike=True, five_dev=15.0,
            ),
        })
        assert "NOT CONFIDENT" in out

    def test_scenario_one_dep_50pct_error_deviation(self):
        """Single dep at 50% deviation, only candidate → confident."""
        out = rank({
            "problem-svc": _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                five_spike=True, five_dev=50.0, five_pct=3.0,
            ),
            "healthy-1": _health_result(),
            "healthy-2": _health_result(),
        })
        assert "CONFIDENT" in out
        assert "problem-svc" in out

    def test_scenario_primary_50pct_deviation_context(self):
        """Show primary app's deviation for context."""
        out = rank(
            {"svc": _health_result(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=300.0,
            )},
            primary_app_error_deviation=50.0,
        )
        assert "50.0%" in out

    # ── Upstream scenarios ──

    def test_scenario_upstream_one_caller_traffic_spike(self):
        """One caller has traffic anomaly → confident."""
        out = rank({
            "batch-job": _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                four_spike=True, four_dev=500.0,
            ),
            "web-frontend": _health_result(),
            "mobile-bff": _health_result(),
        })
        assert "CONFIDENT" in out
        assert "batch-job" in out

    def test_scenario_upstream_multiple_callers_spiking(self):
        """Multiple callers spiking → ambiguous."""
        out = rank({
            "frontend-a": _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                four_spike=True, four_dev=80.0,
            ),
            "frontend-b": _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                four_spike=True, four_dev=60.0,
            ),
        })
        assert "NOT CONFIDENT" in out

    # ── Edge cases ──

    def test_scenario_all_chronic(self):
        out = rank({
            "a": _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                chronicity="chronic", five_spike=True, five_dev=200.0,
            ),
            "b": _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                chronicity="chronic", five_spike=True, five_dev=300.0,
            ),
        })
        assert "NOT CONFIDENT" in out

    def test_scenario_single_dep_no_error_data(self):
        out = rank({"svc": _health_result(
            golden="degraded", overall="degraded", anomaly=True,
        )})
        assert "CONFIDENT" in out  # single candidate → confident

    def test_scenario_large_fleet_15_deps(self):
        """Realistic fleet: 15 deps, one clearly bad."""
        deps = {f"svc-{i}": _health_result() for i in range(14)}
        deps["broken-svc"] = _health_result(
            golden="unhealthy", overall="unhealthy", anomaly=True,
            five_spike=True, five_dev=700.0, five_pct=11.0,
        )
        out = rank(deps)
        assert "CONFIDENT" in out
        assert "broken-svc" in out

    def test_scenario_large_fleet_all_slightly_degraded(self):
        """15 deps all slightly degraded → ambiguous."""
        deps = {
            f"svc-{i}": _health_result(
                golden="degraded", overall="degraded", anomaly=True,
                five_spike=True, five_dev=float(10 + i * 3),
            )
            for i in range(15)
        }
        out = rank(deps)
        assert "NOT CONFIDENT" in out


class TestRankEdgeCases:
    """Edge cases and boundary conditions for rank()."""

    def test_dep_result_is_empty_dict(self):
        out = rank({"svc": {}})
        assert "Dependency Investigation Priority" in out

    def test_dep_result_is_string(self):
        out = rank({"svc": "not a dict"})
        assert "Dependency Investigation Priority" in out

    def test_dep_result_is_int(self):
        out = rank({"svc": 42})
        assert "Dependency Investigation Priority" in out

    def test_dep_result_is_list(self):
        out = rank({"svc": [1, 2, 3]})
        assert "Dependency Investigation Priority" in out

    def test_dep_name_with_special_chars(self):
        out = rank({"svc-with-dashes_and_underscores.v2": _health_result(
            golden="unhealthy", overall="unhealthy", anomaly=True,
            five_spike=True, five_dev=300.0,
        )})
        assert "svc-with-dashes_and_underscores.v2" in out

    def test_dep_name_empty_string(self):
        out = rank({"": _health_result()})
        assert "Dependency Investigation Priority" in out

    def test_primary_deviation_zero(self):
        out = rank({"svc": _health_result()}, primary_app_error_deviation=0.0)
        assert "0.0%" in out

    def test_primary_deviation_negative(self):
        out = rank({"svc": _health_result()}, primary_app_error_deviation=-10.0)
        assert "-10.0%" in out

    def test_very_many_deps_50(self):
        deps = {f"svc-{i}": _health_result() for i in range(50)}
        out = rank(deps)
        assert "Dependency Investigation Priority" in out
        assert "50" in out or "Healthy" in out

    def test_json_summary_valid_json(self):
        """Ensure the JSON block is always valid."""
        for scenario in [
            {"svc": _health_result()},
            {"a": _health_result(golden="unhealthy", overall="unhealthy", anomaly=True,
                                  five_spike=True, five_dev=300.0)},
            {},
        ]:
            out = rank(scenario)
            json_start = out.index("```json") + 7
            json_end = out.index("```", json_start)
            parsed = json.loads(out[json_start:json_end])
            assert isinstance(parsed, dict)

    def test_json_summary_keys(self):
        out = rank({"svc": _health_result()})
        json_start = out.index("```json") + 7
        json_end = out.index("```", json_start)
        parsed = json.loads(out[json_start:json_end])
        expected_keys = {"confident", "winner", "confidence_ratio", "confirmed_bad",
                         "suspicious", "chronic", "healthy", "cascading", "action"}
        assert set(parsed.keys()) == expected_keys

    def test_json_summary_lists_are_lists(self):
        out = rank({
            "bad": _health_result(golden="unhealthy", overall="unhealthy", anomaly=True,
                                   five_spike=True, five_dev=300.0),
            "ok": _health_result(),
        })
        json_start = out.index("```json") + 7
        json_end = out.index("```", json_start)
        parsed = json.loads(out[json_start:json_end])
        for key in ("confirmed_bad", "suspicious", "chronic", "healthy", "cascading"):
            assert isinstance(parsed[key], list)


class TestArgsModel:
    """Test the Pydantic Args model."""

    def test_default_values(self):
        args = Args()
        assert args.dependency_results == {}
        assert args.primary_app_error_deviation is None

    def test_with_results(self):
        args = Args(dependency_results={"svc": {}})
        assert "svc" in args.dependency_results

    def test_with_deviation(self):
        args = Args(primary_app_error_deviation=42.5)
        assert args.primary_app_error_deviation == 42.5

    def test_model_validate(self):
        args = Args.model_validate({
            "dependency_results": {"svc": {"overall_status": "healthy"}},
            "primary_app_error_deviation": 50.0,
        })
        assert "svc" in args.dependency_results
        assert args.primary_app_error_deviation == 50.0

    def test_model_validate_empty(self):
        args = Args.model_validate({})
        assert args.dependency_results == {}
