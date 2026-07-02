"""Cascade direction-decision and multi-layer scenario tests.

Tests the SKILL.md logic for:
  - Direction decision (downstream vs upstream vs both)
  - Confidence-gated cascade (when to call O2, when to skip)
  - Multi-layer cascade traversal with mock health data
  - End-to-end scenario simulations

These are pure data-driven tests — no LLM involved.
The tests exercise the rank_dependency_health.py pipeline with
realistic multi-layer cascade payloads.

Total: ~100 test cases
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
)


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════


def _hr(
    overall="healthy",
    golden="healthy",
    anomaly=False,
    attribution=None,
    four_spike=False,
    five_spike=False,
    four_dev=None,
    five_dev=None,
    four_pct=None,
    five_pct=None,
    four_base=None,
    five_base=None,
    chronicity=None,
):
    """Build a health result dict (compact helper)."""
    non_2xx = {}
    if four_spike or four_pct is not None or four_dev is not None:
        non_2xx["4xx_spike"] = four_spike
    if five_spike or five_pct is not None or five_dev is not None:
        non_2xx["5xx_spike"] = five_spike
    if four_pct is not None:
        non_2xx["4xx_current_percent"] = four_pct
    if five_pct is not None:
        non_2xx["5xx_current_percent"] = five_pct
    if four_base is not None:
        non_2xx["4xx_baseline_percent"] = four_base
    if five_base is not None:
        non_2xx["5xx_baseline_percent"] = five_base
    if four_dev is not None:
        non_2xx["4xx_deviation_percent"] = four_dev
    if five_dev is not None:
        non_2xx["5xx_deviation_percent"] = five_dev

    r = {
        "overall_status": overall,
        "golden_signal_status": golden,
        "anomaly_detected": anomaly,
        "failure_attribution": attribution,
        "checks": {
            "istio_traffic_spike": {"non_2xx_analysis": non_2xx} if non_2xx else {},
        },
    }
    if chronicity:
        r["checks"]["cpu"] = {"anomaly_details": {"chronicity": chronicity}}
    return r


def _parse_json_summary(output: str) -> dict:
    """Extract the Machine-Readable Summary JSON from rank() output."""
    json_start = output.index("```json") + 7
    json_end = output.index("```", json_start)
    return json.loads(output[json_start:json_end])


# ═══════════════════════════════════════════════════════════════════════════════
# DIRECTION DECISION — 25 tests
#
# Based on SKILL.md direction decision table:
#   failure_attribution + error_classes → direction
# ═══════════════════════════════════════════════════════════════════════════════


class TestDirectionDecision:
    """Test the direction decision logic using rank() output + classify results.

    The SKILL.md direction decision:
    - downstream_dependency → DOWNSTREAM cascade
    - this_app + (traffic spike + 4XX from callers) → UPSTREAM cascade
    - this_app (no traffic) → investigate this app (O2 DEEP)
    - shared_or_this_app → BOTH directions
    """

    # --- downstream_dependency → downstream cascade ---

    def test_downstream_5xx_dominant_dep(self):
        """App blames downstream + one dep is clearly broken."""
        deps = {
            "payment-svc": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                attribution="this_app",  # the dep itself blames itself
                five_spike=True, five_dev=800.0, five_pct=12.0,
            ),
            "inventory-api": _hr(),
        }
        summary = _parse_json_summary(rank(deps))
        assert summary["confident"] is True
        assert summary["winner"] == "payment-svc"
        assert summary["action"] == "proceed_to_next_layer"

    def test_downstream_dep_further_cascades(self):
        """Dep also has downstream_dependency attribution → cascade continues."""
        deps = {
            "db-proxy": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                attribution="downstream_dependency",
                five_spike=True, five_dev=500.0, five_pct=10.0,
            ),
        }
        summary = _parse_json_summary(rank(deps))
        assert summary["confident"] is True
        assert "db-proxy" in summary["cascading"]
        assert summary["action"] == "proceed_to_next_layer"

    def test_downstream_multiple_deps_ambiguous(self):
        """Two deps similarly bad → NOT confident → O2 needed."""
        deps = {
            "svc-a": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=120.0,
            ),
            "svc-b": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=100.0,
            ),
        }
        summary = _parse_json_summary(rank(deps))
        assert summary["confident"] is False
        assert summary["action"] == "o2_disambiguation"

    def test_downstream_4xx_dominant_dep(self):
        """4XX spike in dep → downstream direction."""
        deps = {
            "auth-svc": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                four_spike=True, four_dev=600.0, four_pct=15.0,
            ),
            "cache-svc": _hr(),
        }
        summary = _parse_json_summary(rank(deps))
        assert summary["confident"] is True
        assert summary["winner"] == "auth-svc"

    def test_downstream_mixed_4xx_5xx(self):
        """Both 4XX and 5XX → max deviation used for confidence."""
        deps = {
            "svc-a": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                four_spike=True, four_dev=50.0,
                five_spike=True, five_dev=800.0,
            ),
            "svc-b": _hr(
                golden="degraded", overall="degraded", anomaly=True,
                four_spike=True, four_dev=200.0,
            ),
        }
        summary = _parse_json_summary(rank(deps))
        # svc-a max=800, svc-b max=200, ratio=4 → confident
        assert summary["confident"] is True
        assert summary["winner"] == "svc-a"

    # --- this_app (root cause found) ---

    def test_this_app_root_cause(self):
        """Single dep with this_app attribution → root cause found."""
        deps = {
            "broken-svc": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                attribution="this_app",
                five_spike=True, five_dev=500.0, five_pct=10.0,
            ),
        }
        summary = _parse_json_summary(rank(deps))
        assert summary["confident"] is True
        assert "broken-svc" not in summary["cascading"]  # no further cascade

    # --- shared_or_this_app → investigate both ---

    def test_shared_needs_both_directions(self):
        """Shared attribution → ambiguous, need to check both."""
        deps = {
            "shared-svc": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                attribution="shared_or_this_app",
                five_spike=True, five_dev=300.0, five_pct=6.0,
            ),
        }
        summary = _parse_json_summary(rank(deps))
        assert summary["confident"] is True
        assert "shared-svc" not in summary["cascading"]

    # --- Upstream traffic patterns ---

    def test_upstream_single_caller_traffic_spike(self):
        """One caller has 4XX traffic spike → likely upstream issue."""
        deps = {
            "batch-job": _hr(
                golden="degraded", overall="degraded", anomaly=True,
                four_spike=True, four_dev=500.0, four_pct=10.0,
            ),
            "web-frontend": _hr(),
            "mobile-bff": _hr(),
        }
        summary = _parse_json_summary(rank(deps))
        assert summary["confident"] is True
        assert summary["winner"] == "batch-job"

    def test_upstream_two_callers_spiking(self):
        """Two callers with similar traffic spikes → ambiguous."""
        deps = {
            "frontend-a": _hr(
                golden="degraded", overall="degraded", anomaly=True,
                four_spike=True, four_dev=80.0, four_pct=5.0,
            ),
            "frontend-b": _hr(
                golden="degraded", overall="degraded", anomaly=True,
                four_spike=True, four_dev=60.0, four_pct=4.0,
            ),
        }
        summary = _parse_json_summary(rank(deps))
        assert summary["confident"] is False

    def test_upstream_one_dominant_caller(self):
        """One caller overwhelmingly dominant → confident."""
        deps = {
            "api-gateway": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                four_spike=True, four_dev=900.0, four_pct=20.0,
            ),
            "internal-svc": _hr(
                golden="degraded", overall="degraded", anomaly=True,
                four_spike=True, four_dev=30.0, four_pct=2.0,
            ),
        }
        summary = _parse_json_summary(rank(deps))
        assert summary["confident"] is True
        assert summary["winner"] == "api-gateway"


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIDENCE GATE SCENARIOS — 20 tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestConfidenceGate:
    """Test the confidence gate: when to skip O2 vs when to invoke O2."""

    def test_single_bad_dep_skips_o2(self):
        """Only one bad dep → confident → skip O2."""
        deps = {"the-one": _hr(
            golden="unhealthy", overall="unhealthy", anomaly=True,
            five_spike=True, five_dev=400.0,
        )}
        summary = _parse_json_summary(rank(deps))
        assert summary["confident"] is True
        assert summary["action"] == "proceed_to_next_layer"

    def test_clear_winner_skips_o2(self):
        """Winner 10× second → skip O2."""
        deps = {
            "winner": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=1000.0,
            ),
            "second": _hr(
                golden="degraded", overall="degraded", anomaly=True,
                five_spike=True, five_dev=100.0,
            ),
        }
        summary = _parse_json_summary(rank(deps))
        assert summary["confident"] is True
        assert summary["action"] == "proceed_to_next_layer"

    def test_exactly_3x_skips_o2(self):
        """Winner exactly 3× → confident → skip O2."""
        deps = {
            "a": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=300.0,
            ),
            "b": _hr(
                golden="degraded", overall="degraded", anomaly=True,
                five_spike=True, five_dev=100.0,
            ),
        }
        summary = _parse_json_summary(rank(deps))
        assert summary["confident"] is True

    def test_below_3x_needs_o2(self):
        """Winner 2× → NOT confident → invoke O2."""
        deps = {
            "a": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=200.0,
            ),
            "b": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=100.0,
            ),
        }
        summary = _parse_json_summary(rank(deps))
        assert summary["confident"] is False
        assert summary["action"] == "o2_disambiguation"

    def test_equal_deviation_needs_o2(self):
        """Both at same deviation → NOT confident."""
        deps = {
            "a": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=150.0,
            ),
            "b": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=150.0,
            ),
        }
        summary = _parse_json_summary(rank(deps))
        assert summary["confident"] is False
        assert summary["confidence_ratio"] == pytest.approx(1.0)

    def test_chronic_deps_excluded_from_gate(self):
        """Chronic dep with higher deviation should NOT count."""
        deps = {
            "chronic": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                chronicity="chronic",
                five_spike=True, five_dev=999.0,
            ),
            "actual": _hr(
                golden="degraded", overall="degraded", anomaly=True,
                five_spike=True, five_dev=50.0,
            ),
        }
        summary = _parse_json_summary(rank(deps))
        assert summary["confident"] is True
        assert summary["winner"] == "actual"

    def test_all_healthy_deps_not_confident(self):
        deps = {
            "a": _hr(), "b": _hr(), "c": _hr(),
        }
        summary = _parse_json_summary(rank(deps))
        assert summary["confident"] is False
        assert summary["action"] == "o2_disambiguation"

    def test_all_chronic_deps_not_confident(self):
        deps = {
            "a": _hr(golden="degraded", overall="degraded", anomaly=True,
                      chronicity="chronic", five_spike=True, five_dev=200.0),
            "b": _hr(golden="degraded", overall="degraded", anomaly=True,
                      chronicity="chronic", five_spike=True, five_dev=300.0),
        }
        summary = _parse_json_summary(rank(deps))
        assert summary["confident"] is False

    def test_five_deps_close_spread_needs_o2(self):
        """Five deps with 10-40% deviations → ambiguous."""
        deps = {f"svc-{i}": _hr(
            golden="degraded", overall="degraded", anomaly=True,
            five_spike=True, five_dev=float(10 + i * 7),
        ) for i in range(5)}
        summary = _parse_json_summary(rank(deps))
        assert summary["confident"] is False

    def test_second_dep_zero_deviation_confident(self):
        """First has deviation, second has 0 → confident."""
        deps = {
            "bad": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=200.0,
            ),
            "minor": _hr(
                golden="degraded", overall="degraded", anomaly=True,
            ),
        }
        summary = _parse_json_summary(rank(deps))
        assert summary["confident"] is True
        assert summary["winner"] == "bad"


# ═══════════════════════════════════════════════════════════════════════════════
# MULTI-LAYER CASCADE SIMULATION — 25 tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestMultiLayerCascade:
    """Simulate multi-layer cascades: App → Dep1 → Dep2 → Root Cause.

    Each test calls rank() for each layer, simulating what the LLM would do
    with the skill.
    """

    def test_two_layer_confident_cascade(self):
        """App → DepA (downstream) → DepA's deps show root cause."""
        # Layer 1: App's deps
        layer1 = rank({
            "dep-a": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                attribution="downstream_dependency",
                five_spike=True, five_dev=600.0, five_pct=10.0,
            ),
            "dep-b": _hr(),
        })
        s1 = _parse_json_summary(layer1)
        assert s1["confident"] is True
        assert s1["winner"] == "dep-a"
        assert "dep-a" in s1["cascading"]

        # Layer 2: dep-a's deps (root cause found)
        layer2 = rank({
            "dep-a-dep-1": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                attribution="this_app",
                five_spike=True, five_dev=900.0, five_pct=15.0,
            ),
            "dep-a-dep-2": _hr(),
        })
        s2 = _parse_json_summary(layer2)
        assert s2["confident"] is True
        assert s2["winner"] == "dep-a-dep-1"
        assert s2["cascading"] == []  # root cause, no further cascade

    def test_three_layer_confident_cascade(self):
        """App → DepA → DepA-X → Root Cause."""
        # Layer 1
        s1 = _parse_json_summary(rank({
            "dep-a": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                attribution="downstream_dependency",
                five_spike=True, five_dev=700.0,
            ),
        }))
        assert s1["confident"] is True
        assert "dep-a" in s1["cascading"]

        # Layer 2
        s2 = _parse_json_summary(rank({
            "dep-a-x": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                attribution="downstream_dependency",
                five_spike=True, five_dev=800.0,
            ),
            "dep-a-y": _hr(),
        }))
        assert s2["confident"] is True
        assert "dep-a-x" in s2["cascading"]

        # Layer 3: root cause
        s3 = _parse_json_summary(rank({
            "root-db": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                attribution="this_app",
                five_spike=True, five_dev=1200.0,
            ),
        }))
        assert s3["confident"] is True
        assert s3["cascading"] == []

    def test_cascade_stops_at_this_app(self):
        """Cascade stops when dep says this_app."""
        s = _parse_json_summary(rank({
            "root-svc": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                attribution="this_app",
                five_spike=True, five_dev=500.0,
            ),
        }))
        assert s["confident"] is True
        assert s["cascading"] == []

    def test_cascade_stops_at_shared(self):
        """Cascade stops when dep says shared_or_this_app."""
        s = _parse_json_summary(rank({
            "shared-svc": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                attribution="shared_or_this_app",
                five_spike=True, five_dev=500.0,
            ),
        }))
        assert s["confident"] is True
        assert s["cascading"] == []

    def test_cascade_stops_at_no_attribution(self):
        """No attribution → no cascade indicator."""
        s = _parse_json_summary(rank({
            "svc": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=500.0,
            ),
        }))
        assert s["cascading"] == []

    def test_two_layer_ambiguous_at_layer2(self):
        """Layer 1 confident → Layer 2 ambiguous → O2 needed at layer 2."""
        # Layer 1: clear winner
        s1 = _parse_json_summary(rank({
            "dep-a": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                attribution="downstream_dependency",
                five_spike=True, five_dev=600.0,
            ),
            "dep-b": _hr(),
        }))
        assert s1["confident"] is True

        # Layer 2: ambiguous among dep-a's deps
        s2 = _parse_json_summary(rank({
            "dep-a-x": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=100.0,
            ),
            "dep-a-y": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=80.0,
            ),
        }))
        assert s2["confident"] is False
        assert s2["action"] == "o2_disambiguation"

    def test_ambiguous_at_layer1(self):
        """Layer 1 ambiguous → O2 right away."""
        s1 = _parse_json_summary(rank({
            "dep-a": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=100.0,
            ),
            "dep-b": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=90.0,
            ),
        }))
        assert s1["confident"] is False
        assert s1["action"] == "o2_disambiguation"

    def test_cascade_with_chronic_noise(self):
        """Chronic deps at each layer shouldn't derail the cascade."""
        # Layer 1
        s1 = _parse_json_summary(rank({
            "real-dep": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                attribution="downstream_dependency",
                five_spike=True, five_dev=500.0,
            ),
            "chronic-dep": _hr(
                golden="degraded", overall="degraded", anomaly=True,
                chronicity="chronic",
                five_spike=True, five_dev=800.0,
            ),
        }))
        assert s1["confident"] is True
        assert s1["winner"] == "real-dep"

        # Layer 2: also has chronic noise
        s2 = _parse_json_summary(rank({
            "root-cause": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                attribution="this_app",
                five_spike=True, five_dev=400.0,
            ),
            "old-issue": _hr(
                golden="degraded", overall="degraded", anomaly=True,
                chronicity="chronic",
                five_spike=True, five_dev=700.0,
            ),
        }))
        assert s2["confident"] is True
        assert s2["winner"] == "root-cause"

    def test_cascade_with_healthy_fleet(self):
        """Many healthy deps + one bad → confident at each layer."""
        # Layer 1: 10 healthy + 1 bad
        deps1 = {f"svc-{i}": _hr() for i in range(10)}
        deps1["bad-dep"] = _hr(
            golden="unhealthy", overall="unhealthy", anomaly=True,
            attribution="downstream_dependency",
            five_spike=True, five_dev=700.0,
        )
        s1 = _parse_json_summary(rank(deps1))
        assert s1["confident"] is True
        assert s1["winner"] == "bad-dep"

        # Layer 2: 5 healthy + 1 root cause
        deps2 = {f"sub-{i}": _hr() for i in range(5)}
        deps2["root"] = _hr(
            golden="unhealthy", overall="unhealthy", anomaly=True,
            attribution="this_app",
            five_spike=True, five_dev=900.0,
        )
        s2 = _parse_json_summary(rank(deps2))
        assert s2["confident"] is True
        assert s2["winner"] == "root"

    def test_all_deps_healthy_at_every_layer(self):
        """All healthy → no cascade, investigate infrastructure."""
        s = _parse_json_summary(rank({
            "svc-1": _hr(), "svc-2": _hr(), "svc-3": _hr(),
        }))
        assert s["confident"] is False
        assert s["confirmed_bad"] == []
        assert s["suspicious"] == []


# ═══════════════════════════════════════════════════════════════════════════════
# CATEGORY COUNTS IN JSON SUMMARY — 15 tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestCategoryCountsInSummary:
    """Verify the JSON summary category lists are correct."""

    def test_single_confirmed_bad(self):
        s = _parse_json_summary(rank({
            "svc": _hr(golden="unhealthy", overall="unhealthy", anomaly=True,
                        five_spike=True, five_dev=300.0),
        }))
        assert s["confirmed_bad"] == ["svc"]
        assert s["suspicious"] == []
        assert s["chronic"] == []
        assert s["healthy"] == []

    def test_single_suspicious(self):
        s = _parse_json_summary(rank({
            "svc": _hr(golden="degraded", overall="degraded", anomaly=True,
                        five_spike=True, five_dev=50.0),
        }))
        assert s["confirmed_bad"] == []
        assert s["suspicious"] == ["svc"]

    def test_single_chronic(self):
        s = _parse_json_summary(rank({
            "svc": _hr(golden="unhealthy", overall="unhealthy", anomaly=True,
                        chronicity="chronic", five_spike=True, five_dev=500.0),
        }))
        assert s["chronic"] == ["svc"]
        assert s["confirmed_bad"] == []

    def test_single_healthy(self):
        s = _parse_json_summary(rank({"svc": _hr()}))
        assert s["healthy"] == ["svc"]

    def test_all_categories_populated(self):
        s = _parse_json_summary(rank({
            "bad": _hr(golden="unhealthy", overall="unhealthy", anomaly=True,
                        five_spike=True, five_dev=300.0),
            "sus": _hr(golden="degraded", overall="degraded", anomaly=True,
                        five_spike=True, five_dev=30.0),
            "old": _hr(golden="unhealthy", overall="unhealthy", anomaly=True,
                        chronicity="chronic", five_spike=True, five_dev=500.0),
            "ok": _hr(),
        }))
        assert "bad" in s["confirmed_bad"]
        assert "sus" in s["suspicious"]
        assert "old" in s["chronic"]
        assert "ok" in s["healthy"]

    def test_multiple_confirmed_bad(self):
        s = _parse_json_summary(rank({
            "a": _hr(golden="unhealthy", overall="unhealthy", anomaly=True,
                      five_spike=True, five_dev=200.0),
            "b": _hr(golden="unhealthy", overall="unhealthy", anomaly=True,
                      five_spike=True, five_dev=180.0),
        }))
        assert len(s["confirmed_bad"]) == 2
        assert set(s["confirmed_bad"]) == {"a", "b"}

    def test_multiple_suspicious(self):
        s = _parse_json_summary(rank({
            "a": _hr(golden="degraded", overall="degraded", anomaly=True,
                      five_spike=True, five_dev=50.0),
            "b": _hr(golden="degraded", overall="degraded", anomaly=True,
                      five_spike=True, five_dev=40.0),
        }))
        assert len(s["suspicious"]) == 2

    def test_multiple_chronic(self):
        s = _parse_json_summary(rank({
            "a": _hr(golden="degraded", overall="degraded", anomaly=True,
                      chronicity="chronic", five_spike=True, five_dev=200.0),
            "b": _hr(golden="degraded", overall="degraded", anomaly=True,
                      chronicity="chronic", five_spike=True, five_dev=300.0),
        }))
        assert len(s["chronic"]) == 2

    def test_cascading_list_populated(self):
        s = _parse_json_summary(rank({
            "a": _hr(golden="unhealthy", overall="unhealthy", anomaly=True,
                      attribution="downstream_dependency",
                      five_spike=True, five_dev=500.0),
        }))
        assert "a" in s["cascading"]

    def test_cascading_list_empty_for_this_app(self):
        s = _parse_json_summary(rank({
            "a": _hr(golden="unhealthy", overall="unhealthy", anomaly=True,
                      attribution="this_app",
                      five_spike=True, five_dev=500.0),
        }))
        assert s["cascading"] == []

    def test_cascading_from_suspicious_with_downstream(self):
        """Even suspicious deps can cascade if they have downstream_dependency."""
        s = _parse_json_summary(rank({
            "a": _hr(golden="degraded", overall="degraded", anomaly=True,
                      attribution="downstream_dependency",
                      five_spike=True, five_dev=50.0),
        }))
        assert "a" in s["cascading"]

    def test_empty_deps_all_lists_empty(self):
        s = _parse_json_summary(rank({}))
        assert s["confirmed_bad"] == []
        assert s["suspicious"] == []
        assert s["chronic"] == []
        assert s["healthy"] == []
        assert s["cascading"] == []

    def test_non_dict_deps_filtered_out(self):
        s = _parse_json_summary(rank({
            "good": _hr(),
            "bad_val": "not_a_dict",
            "bad_val2": 42,
        }))
        assert s["healthy"] == ["good"]
        assert len(s["confirmed_bad"] + s["suspicious"] + s["chronic"]) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# REAL-WORLD PRODUCTION SCENARIOS — 15 tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestProductionScenarios:
    """End-to-end production-like scenarios."""

    def test_database_connection_pool_exhaustion(self):
        """App → DB-proxy → DB (root cause: DB connection pool full)."""
        # Layer 1
        s1 = _parse_json_summary(rank({
            "db-proxy": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                attribution="downstream_dependency",
                five_spike=True, five_dev=900.0, five_pct=15.0,
            ),
            "redis-cache": _hr(),
            "msg-queue": _hr(),
        }))
        assert s1["confident"] is True
        assert s1["winner"] == "db-proxy"

        # Layer 2
        s2 = _parse_json_summary(rank({
            "primary-db": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                attribution="this_app",
                five_spike=True, five_dev=1500.0, five_pct=25.0,
            ),
        }))
        assert s2["confident"] is True
        assert s2["winner"] == "primary-db"
        assert s2["cascading"] == []

    def test_shared_redis_failure(self):
        """Multiple apps see issues → shared dependency (Redis) is root."""
        # App A's deps
        s_a = _parse_json_summary(rank({
            "redis-cluster": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                attribution="this_app",
                five_spike=True, five_dev=800.0, five_pct=12.0,
            ),
            "postgres-db": _hr(),
        }))
        assert s_a["confident"] is True
        assert s_a["winner"] == "redis-cluster"

    def test_cascading_through_api_gateway(self):
        """API-GW → Backend → Database."""
        # Layer 1: Gateway deps
        s1 = _parse_json_summary(rank({
            "backend-api": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                attribution="downstream_dependency",
                five_spike=True, five_dev=600.0,
            ),
            "auth-service": _hr(),
            "rate-limiter": _hr(),
        }))
        assert s1["confident"] is True
        assert "backend-api" in s1["cascading"]

        # Layer 2: Backend deps
        s2 = _parse_json_summary(rank({
            "sql-database": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                attribution="this_app",
                five_spike=True, five_dev=1000.0,
            ),
            "cache-svc": _hr(),
        }))
        assert s2["confident"] is True
        assert s2["cascading"] == []

    def test_noisy_chronic_services(self):
        """Production: several chronic services + one real issue."""
        s = _parse_json_summary(rank({
            "legacy-svc-1": _hr(
                golden="degraded", overall="degraded", anomaly=True,
                chronicity="chronic", five_spike=True, five_dev=400.0,
            ),
            "legacy-svc-2": _hr(
                golden="degraded", overall="degraded", anomaly=True,
                chronicity="chronic", five_spike=True, five_dev=300.0,
            ),
            "legacy-svc-3": _hr(
                golden="degraded", overall="degraded", anomaly=True,
                chronicity="chronic", five_spike=True, five_dev=200.0,
            ),
            "new-payment-svc": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=700.0, five_pct=10.0,
            ),
            "healthy-svc-1": _hr(),
            "healthy-svc-2": _hr(),
        }))
        assert s["confident"] is True
        assert s["winner"] == "new-payment-svc"
        assert len(s["chronic"]) == 3
        assert len(s["healthy"]) == 2

    def test_4xx_authentication_cascade(self):
        """Auth service returning 401s → 4XX spike in callers."""
        s = _parse_json_summary(rank({
            "auth-service": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                attribution="this_app",
                four_spike=True, four_dev=800.0, four_pct=30.0,
            ),
            "user-service": _hr(),
            "order-service": _hr(),
        }))
        assert s["confident"] is True
        assert s["winner"] == "auth-service"

    def test_gradual_degradation_multiple_deps(self):
        """Slow degradation across many deps → ambiguous."""
        deps = {f"svc-{i}": _hr(
            golden="degraded", overall="degraded", anomaly=True,
            five_spike=True, five_dev=float(20 + i * 5),
        ) for i in range(8)}
        s = _parse_json_summary(rank(deps))
        assert s["confident"] is False
        assert s["action"] == "o2_disambiguation"

    def test_large_fleet_with_one_outage(self):
        """20 deps, one complete outage."""
        deps = {f"healthy-{i}": _hr() for i in range(19)}
        deps["down-svc"] = _hr(
            golden="unhealthy", overall="unhealthy", anomaly=True,
            attribution="this_app",
            five_spike=True, five_dev=5000.0, five_pct=50.0,
        )
        s = _parse_json_summary(rank(deps))
        assert s["confident"] is True
        assert s["winner"] == "down-svc"
        assert len(s["healthy"]) == 19

    def test_two_simultaneous_failures(self):
        """Two deps fail at similar severity → ambiguous."""
        s = _parse_json_summary(rank({
            "payment-gw": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=300.0, five_pct=8.0,
            ),
            "inventory-svc": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=250.0, five_pct=7.0,
            ),
            "shipping-svc": _hr(),
        }))
        assert s["confident"] is False  # 300/250 = 1.2 < 3

    def test_intermittent_issue_low_deviation(self):
        """Small deviation but only candidate → still confident."""
        s = _parse_json_summary(rank({
            "flaky-svc": _hr(
                golden="degraded", overall="degraded", anomaly=True,
                five_spike=True, five_dev=10.0, five_pct=1.0,
            ),
            "ok-1": _hr(),
            "ok-2": _hr(),
        }))
        assert s["confident"] is True
        assert s["winner"] == "flaky-svc"

    def test_deployment_related_5xx_spike(self):
        """During deployment: one svc has 5XX spike."""
        s = _parse_json_summary(rank({
            "deploying-svc": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                attribution="this_app",
                five_spike=True, five_dev=600.0, five_pct=10.0,
            ),
            "stable-dep": _hr(),
        }))
        assert s["confident"] is True
        assert s["winner"] == "deploying-svc"
        assert s["cascading"] == []

    def test_mixed_4xx_5xx_across_deps(self):
        """One dep has 4XX, another has 5XX → max deviation used."""
        s = _parse_json_summary(rank({
            "auth-svc": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                four_spike=True, four_dev=900.0, four_pct=20.0,
            ),
            "db-svc": _hr(
                golden="degraded", overall="degraded", anomaly=True,
                five_spike=True, five_dev=50.0, five_pct=2.0,
            ),
        }))
        assert s["confident"] is True
        assert s["winner"] == "auth-svc"  # 900 vs 50

    def test_primary_deviation_context_in_output(self):
        """Primary app's own deviation shown for comparison."""
        output = rank(
            {"dep": _hr(golden="unhealthy", overall="unhealthy", anomaly=True,
                          five_spike=True, five_dev=300.0)},
            primary_app_error_deviation=75.0,
        )
        assert "75.0%" in output


# ═══════════════════════════════════════════════════════════════════════════════
# PARAMETRIZED BOUNDARY TESTS — 20 tests via parametrize
# ═══════════════════════════════════════════════════════════════════════════════


class TestConfidenceRatioBoundaries:
    """Parametrized tests for confidence ratio boundary at 3.0×."""

    @pytest.mark.parametrize("top_dev,second_dev,expected_confident", [
        # Below threshold
        (100.0, 100.0, False),  # 1.0×
        (150.0, 100.0, False),  # 1.5×
        (200.0, 100.0, False),  # 2.0×
        (250.0, 100.0, False),  # 2.5×
        (290.0, 100.0, False),  # 2.9×
        (299.0, 100.0, False),  # 2.99×
        (299.9, 100.0, False),  # 2.999×
        # At threshold
        (300.0, 100.0, True),   # 3.0× (exactly)
        # Above threshold
        (301.0, 100.0, True),   # 3.01×
        (350.0, 100.0, True),   # 3.5×
        (400.0, 100.0, True),   # 4.0×
        (500.0, 100.0, True),   # 5.0×
        (1000.0, 100.0, True),  # 10.0×
        # Different base
        (60.0, 20.0, True),     # 3.0×
        (59.0, 20.0, False),    # 2.95×
        # Small values
        (3.0, 1.0, True),       # 3.0×
        (2.9, 1.0, False),      # 2.9×
        # Large values
        (3000.0, 1000.0, True), # 3.0×
        (2999.0, 1000.0, False),# 2.999×
        (9999.0, 1.0, True),    # 9999×
    ])
    def test_ratio_boundary(self, top_dev, second_dev, expected_confident):
        deps = {
            "top": _hr(
                golden="unhealthy", overall="unhealthy", anomaly=True,
                five_spike=True, five_dev=top_dev,
            ),
            "second": _hr(
                golden="degraded", overall="degraded", anomaly=True,
                five_spike=True, five_dev=second_dev,
            ),
        }
        s = _parse_json_summary(rank(deps))
        assert s["confident"] is expected_confident, \
            f"top={top_dev}, second={second_dev}, ratio={top_dev/second_dev:.3f}"
