"""Unit tests for skills/release-review/scripts/generate_review_report.py.

Tests verify the go/no-go decision logic, report structure, markdown
formatting, and edge cases for the release review report generator.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

# Add the skill script directory to path so we can import directly
SCRIPT_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "skills", "release-review", "scripts"
)
sys.path.insert(0, SCRIPT_DIR)

from generate_review_report import generate_report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _finding(file: str, risk_tier: str = "MEDIUM", verdict: str = "pass", issues: list | None = None):
    return {"file": file, "risk_tier": risk_tier, "verdict": verdict, "issues": issues or []}


BASE_ARGS = {
    "owner":         "walmart-mx",
    "repo":          "checkout-service",
    "base_tag":      "v1.4.1",
    "head_tag":      "v1.4.2",
    "total_files":   50,
    "total_commits": 10,
    "compare_url":   "https://gecgithub01.walmart.com/walmart-mx/checkout-service/compare/v1.4.1...v1.4.2",
}


# ===========================================================================
# Go / No-Go Decision Logic
# ===========================================================================

class TestDecisionLogic:
    def test_no_go_when_blockers_exist(self):
        findings = [
            _finding("src/auth/login.py", "CRITICAL", "blocker", ["Hardcoded API key"]),
            _finding("src/utils/helpers.py", "LOW", "pass"),
        ]
        report = generate_report(**BASE_ARGS, findings=findings)
        assert "NO-GO" in report
        assert "🔴"    in report

    def test_go_when_no_issues(self):
        findings = [
            _finding("src/cart.py", "MEDIUM", "pass"),
            _finding("src/utils.py", "LOW", "pass"),
        ]
        report = generate_report(**BASE_ARGS, findings=findings)
        assert "GO" in report
        assert "🟢" in report
        assert "No blockers or concerns" in report

    def test_go_with_concerns_when_few_concerns(self):
        findings = [
            _finding("src/cart.py", "MEDIUM", "concern", ["N+1 query"]),
            _finding("src/utils.py", "LOW", "pass"),
        ]
        report = generate_report(**BASE_ARGS, findings=findings)
        assert "GO (with noted concerns)" in report
        assert "🟢" in report
        assert "1 minor concern" in report

    def test_conditional_go_when_many_concerns(self):
        findings = [_finding(f"src/file{i}.py", "MEDIUM", "concern", ["Issue"]) for i in range(12)]
        report = generate_report(**BASE_ARGS, findings=findings)
        assert "CONDITIONAL GO" in report
        assert "🟡"            in report
        assert "12 concerns"   in report


# ===========================================================================
# Report Structure
# ===========================================================================

class TestReportStructure:
    def test_contains_repo_info(self):
        report = generate_report(**BASE_ARGS, findings=[_finding("f.py")])
        assert "walmart-mx/checkout-service" in report
        assert "v1.4.1"                      in report
        assert "v1.4.2"                      in report

    def test_contains_commit_and_file_counts(self):
        report = generate_report(**BASE_ARGS, findings=[_finding("f.py")])
        assert "Commits**: 10"       in report
        assert "Files changed**: 50" in report

    def test_contains_risk_distribution_table(self):
        findings = [
            _finding("src/auth/a.py", "CRITICAL", "blocker", ["bug"]),
            _finding("src/cart.py", "MEDIUM", "pass"),
        ]
        report = generate_report(**BASE_ARGS, findings=findings)
        assert "Risk Distribution"      in report
        assert "CRITICAL"               in report
        assert "MEDIUM"                 in report

    def test_contains_compare_url(self):
        report = generate_report(**BASE_ARGS, findings=[_finding("f.py")])
        assert BASE_ARGS["compare_url"] in report

    def test_contains_generated_by_footer(self):
        report = generate_report(**BASE_ARGS, findings=[_finding("f.py")])
        assert "release-review" in report

    def test_contains_utc_timestamp(self):
        report = generate_report(**BASE_ARGS, findings=[_finding("f.py")])
        assert "UTC" in report


# ===========================================================================
# Blockers Section
# ===========================================================================

class TestBlockersSection:
    def test_blockers_table_present_when_blockers_exist(self):
        findings = [
            _finding("src/auth/login.py", "CRITICAL", "blocker", ["Hardcoded secret", "Missing validation"]),
        ]
        report = generate_report(**BASE_ARGS, findings=findings)
        assert "MUST FIX before production" in report
        assert "Hardcoded secret"           in report
        assert "Missing validation"         in report
        assert "`src/auth/login.py`"        in report

    def test_blockers_section_absent_when_no_blockers(self):
        findings = [_finding("src/cart.py", "MEDIUM", "pass")]
        report = generate_report(**BASE_ARGS, findings=findings)
        assert "MUST FIX" not in report

    def test_multiple_blockers_numbered(self):
        findings = [
            _finding("src/auth/a.py", "CRITICAL", "blocker", ["Issue A"]),
            _finding("src/auth/b.py", "CRITICAL", "blocker", ["Issue B"]),
        ]
        report = generate_report(**BASE_ARGS, findings=findings)
        assert "| 1 |" in report
        assert "| 2 |" in report


# ===========================================================================
# Concerns Section
# ===========================================================================

class TestConcernsSection:
    def test_concerns_table_present_when_concerns_exist(self):
        findings = [
            _finding("src/cart.py", "MEDIUM", "concern", ["N+1 query in loop"]),
        ]
        report = generate_report(**BASE_ARGS, findings=findings)
        assert "recommended to address" in report
        assert "N+1 query in loop"      in report

    def test_concerns_section_absent_when_no_concerns(self):
        findings = [_finding("src/cart.py", "MEDIUM", "pass")]
        report = generate_report(**BASE_ARGS, findings=findings)
        assert "recommended to address" not in report


# ===========================================================================
# Passed Files Section
# ===========================================================================

class TestPassedSection:
    def test_passed_files_listed(self):
        findings = [
            _finding("src/cart.py", "MEDIUM", "pass"),
            _finding("src/utils.py", "LOW", "pass"),
        ]
        report = generate_report(**BASE_ARGS, findings=findings)
        assert "Passed (2 files)" in report
        assert "`src/cart.py`"    in report

    def test_passed_capped_at_20_files(self):
        findings = [_finding(f"src/file{i}.py", "LOW", "pass") for i in range(25)]
        report = generate_report(**BASE_ARGS, findings=findings)
        assert "and 5 more" in report

    def test_passed_section_absent_when_none_passed(self):
        findings = [_finding("src/auth.py", "CRITICAL", "blocker", ["Bug"])]
        report = generate_report(**BASE_ARGS, findings=findings)
        assert "Passed (" not in report


# ===========================================================================
# Skipped Files Section
# ===========================================================================

class TestSkippedSection:
    def test_skipped_count_calculated_from_total_minus_reviewed(self):
        findings = [_finding("src/cart.py")]  # 1 reviewed, total_files=50 → 49 skipped
        report = generate_report(**BASE_ARGS, findings=findings)
        assert "Skipped (49 files)" in report

    def test_skipped_section_absent_when_all_files_reviewed(self):
        findings = [_finding(f"f{i}.py") for i in range(50)]
        report = generate_report(total_files=50, **{k: v for k, v in BASE_ARGS.items() if k != "total_files"}, findings=findings)
        assert "Skipped (0" not in report

    def test_skipped_describes_what_was_skipped(self):
        findings = [_finding("f.py")]
        report = generate_report(**BASE_ARGS, findings=findings)
        assert "docs, assets, lock files" in report


# ===========================================================================
# Edge Cases
# ===========================================================================

class TestEdgeCases:
    def test_empty_findings_produces_go_report(self):
        """No files reviewed → GO (nothing to flag)."""
        report = generate_report(**BASE_ARGS, findings=[])
        assert "GO" in report

    def test_empty_compare_url_no_link(self):
        report = generate_report(
            owner="o", repo="r", base_tag="v1", head_tag="v2",
            total_files=0, total_commits=0, compare_url="",
            findings=[],
        )
        assert "View full diff" not in report

    def test_finding_with_empty_issues_list(self):
        findings = [_finding("f.py", "MEDIUM", "pass", [])]
        report = generate_report(**BASE_ARGS, findings=findings)
        assert "f.py" in report

    def test_multiple_issues_semicolon_separated_in_table(self):
        findings = [
            _finding("src/auth.py", "CRITICAL", "blocker", ["Issue 1", "Issue 2", "Issue 3"]),
        ]
        report = generate_report(**BASE_ARGS, findings=findings)
        assert "Issue 1; Issue 2; Issue 3" in report


# ===========================================================================
# CLI entry point
# ===========================================================================

class TestCLIEntryPoint:
    def test_script_produces_markdown_report(self):
        import subprocess
        script = os.path.join(SCRIPT_DIR, "generate_review_report.py")
        input_data = json.dumps({
            "owner": "walmart-mx",
            "repo": "checkout-service",
            "base_tag": "v1.4.1",
            "head_tag": "v1.4.2",
            "total_files": 10,
            "total_commits": 3,
            "compare_url": "https://example.com/compare",
            "findings": [
                {"file": "src/auth.py", "risk_tier": "CRITICAL", "verdict": "blocker", "issues": ["Secret leak"]},
                {"file": "src/cart.py", "risk_tier": "MEDIUM", "verdict": "pass", "issues": []},
            ],
        })
        result = subprocess.run(
            [sys.executable, script, input_data],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "NO-GO"       in result.stdout
        assert "Secret leak" in result.stdout

    def test_script_errors_on_missing_required_fields(self):
        import subprocess
        script = os.path.join(SCRIPT_DIR, "generate_review_report.py")
        input_data = json.dumps({"owner": "o"})  # missing repo, base_tag, head_tag, findings
        result = subprocess.run(
            [sys.executable, script, input_data],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 1
        output = json.loads(result.stdout)
        assert "error" in output
        assert "Missing" in output["error"]
