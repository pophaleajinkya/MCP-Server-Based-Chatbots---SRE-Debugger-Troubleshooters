"""Unit tests for skills/release-review/scripts/classify_risk.py.

Tests verify the risk classification logic, tier assignment, boost rules,
sorting order, and edge cases for the file classifier used in the
release-review skill's progressive analysis workflow.
"""
from __future__ import annotations

import json
import sys
import os

import pytest

# Add the skill script directory to path so we can import directly
SCRIPT_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "skills", "release-review", "scripts"
)
sys.path.insert(0, SCRIPT_DIR)

from classify_risk import classify_files


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _file(filename: str, status: str = "modified", additions: int = 5, deletions: int = 2) -> dict:
    return {"filename": filename, "status": status, "additions": additions, "deletions": deletions}


def _tier_for(filename: str, **kwargs) -> str:
    """Classify a single file and return its risk tier."""
    result = classify_files([_file(filename, **kwargs)])
    return result["files"][0]["risk_tier"]


# ===========================================================================
# CRITICAL tier
# ===========================================================================

class TestCriticalTier:
    def test_auth_directory(self):
        assert _tier_for("src/auth/login.py") == "CRITICAL"

    def test_security_directory(self):
        assert _tier_for("src/security/validator.py") == "CRITICAL"

    def test_payment_directory(self):
        assert _tier_for("src/payment/processor.py") == "CRITICAL"

    def test_checkout_directory(self):
        assert _tier_for("src/checkout/cart.py") == "CRITICAL"

    def test_crypto_directory(self):
        assert _tier_for("lib/crypto/aes.py") == "CRITICAL"

    def test_secrets_directory(self):
        assert _tier_for("config/secrets/db.env") == "CRITICAL"

    def test_migrations_directory(self):
        assert _tier_for("db/migrations/001_add_users.sql") == "CRITICAL"

    def test_env_file(self):
        assert _tier_for(".env") == "CRITICAL"

    def test_env_production_file(self):
        assert _tier_for(".env.production") == "CRITICAL"

    def test_dockerfile(self):
        assert _tier_for("Dockerfile") == "CRITICAL"

    def test_github_workflows(self):
        assert _tier_for(".github/workflows/ci.yml") == "CRITICAL"


# ===========================================================================
# HIGH tier
# ===========================================================================

class TestHighTier:
    def test_config_directory(self):
        assert _tier_for("src/config/settings.py") == "HIGH"

    def test_middleware_directory(self):
        assert _tier_for("src/middleware/auth_middleware.py") == "HIGH"

    def test_gateway_directory(self):
        assert _tier_for("src/gateway/api_gw.py") == "HIGH"

    def test_proto_file(self):
        assert _tier_for("proto/service.proto") == "HIGH"

    def test_openapi_spec(self):
        assert _tier_for("openapi.yaml") == "HIGH"

    def test_swagger_spec(self):
        assert _tier_for("swagger.json") == "HIGH"

    def test_feature_flag_file(self):
        assert _tier_for("src/feature_flags.py") == "HIGH"

    def test_helm_directory(self):
        assert _tier_for("helm/templates/deployment.yaml") == "HIGH"

    def test_values_yaml(self):
        assert _tier_for("helm/values.yaml") == "HIGH"

    def test_k8s_directory(self):
        assert _tier_for("k8s/deployment.yaml") == "HIGH"

    def test_deploy_directory(self):
        assert _tier_for("deploy/staging.yaml") == "HIGH"


# ===========================================================================
# MEDIUM tier
# ===========================================================================

class TestMediumTier:
    def test_service_directory(self):
        assert _tier_for("src/services/cart_service.py") == "MEDIUM"

    def test_controller_directory(self):
        assert _tier_for("src/controllers/user_controller.py") == "MEDIUM"

    def test_handler_directory(self):
        assert _tier_for("src/handlers/webhook_handler.py") == "MEDIUM"

    def test_model_directory(self):
        assert _tier_for("src/models/user.py") == "MEDIUM"

    def test_repository_directory(self):
        assert _tier_for("src/repository/user_repo.py") == "MEDIUM"

    def test_dao_directory(self):
        assert _tier_for("src/dao/order_dao.py") == "MEDIUM"

    def test_utils_directory(self):
        assert _tier_for("src/utils/helpers.py") == "MEDIUM"

    def test_lib_directory(self):
        assert _tier_for("lib/shared/common.py") == "MEDIUM"

    def test_generic_src_file(self):
        assert _tier_for("src/main.py") == "MEDIUM"


# ===========================================================================
# LOW tier
# ===========================================================================

class TestLowTier:
    def test_tests_directory(self):
        assert _tier_for("tests/test_cart.py") == "LOW"

    def test_underscore_test_file(self):
        assert _tier_for("cart_test.py") == "LOW"

    def test_dot_test_file(self):
        assert _tier_for("cart.test.js") == "LOW"

    def test_spec_file(self):
        assert _tier_for("cart.spec.ts") == "LOW"

    def test_dunder_tests_directory(self):
        assert _tier_for("__tests__/cart.js") == "LOW"


# ===========================================================================
# SKIP tier
# ===========================================================================

class TestSkipTier:
    def test_markdown_file(self):
        assert _tier_for("README.md") == "SKIP"

    def test_license_file(self):
        assert _tier_for("LICENSE") == "SKIP"

    def test_changelog_file(self):
        assert _tier_for("CHANGELOG") == "SKIP"

    def test_txt_file(self):
        assert _tier_for("notes.txt") == "SKIP"

    def test_image_png(self):
        assert _tier_for("assets/logo.png") == "SKIP"

    def test_image_svg(self):
        assert _tier_for("icons/check.svg") == "SKIP"

    def test_font_file(self):
        assert _tier_for("fonts/roboto.woff2") == "SKIP"

    def test_generated_directory(self):
        assert _tier_for("generated/api_client.py") == "SKIP"

    def test_lock_file(self):
        assert _tier_for("poetry.lock") == "SKIP"

    def test_yarn_lock(self):
        assert _tier_for("yarn.lock") == "SKIP"

    def test_package_lock(self):
        assert _tier_for("package-lock.json") == "SKIP"

    def test_go_sum(self):
        assert _tier_for("go.sum") == "SKIP"


# ===========================================================================
# Boost rules
# ===========================================================================

class TestBoostRules:
    def test_large_deletion_boosts_medium_to_high(self):
        """Removed file with >50 deletions gets boosted from MEDIUM/LOW → HIGH."""
        result = classify_files([_file("src/utils/old.py", status="removed", additions=0, deletions=80)])
        assert result["files"][0]["risk_tier"] == "HIGH"

    def test_small_deletion_stays_at_original_tier(self):
        """Removed file with ≤50 deletions stays at its original tier."""
        result = classify_files([_file("src/utils/small.py", status="removed", additions=0, deletions=10)])
        assert result["files"][0]["risk_tier"] == "MEDIUM"

    def test_large_deletion_does_not_boost_critical(self):
        """CRITICAL files should not be boosted (already highest reviewable)."""
        result = classify_files([_file("src/auth/old.py", status="removed", additions=0, deletions=100)])
        assert result["files"][0]["risk_tier"] == "CRITICAL"

    def test_renamed_with_changes_boosts_skip_to_medium(self):
        """Renamed SKIP/LOW file with content changes → MEDIUM."""
        result = classify_files([_file("README.md", status="renamed", additions=5, deletions=2)])
        assert result["files"][0]["risk_tier"] == "MEDIUM"

    def test_renamed_without_changes_stays_at_skip(self):
        """Renamed file with no content changes stays at SKIP."""
        result = classify_files([_file("docs/guide.md", status="renamed", additions=0, deletions=0)])
        assert result["files"][0]["risk_tier"] == "SKIP"


# ===========================================================================
# Sorting and grouping
# ===========================================================================

class TestSortingAndGrouping:
    def test_files_sorted_by_tier_priority(self):
        files = [
            _file("tests/test_x.py"),             # LOW
            _file("src/auth/login.py"),            # CRITICAL
            _file("src/services/cart.py"),          # MEDIUM
            _file("src/config/settings.py"),        # HIGH
            _file("README.md"),                     # SKIP
        ]
        result = classify_files(files)
        tiers = [f["risk_tier"] for f in result["files"]]
        assert tiers == ["CRITICAL", "HIGH", "MEDIUM", "LOW", "SKIP"]

    def test_within_tier_sorted_by_change_size_descending(self):
        files = [
            _file("src/services/small.py", additions=2, deletions=1),
            _file("src/services/big.py",   additions=50, deletions=30),
        ]
        result = classify_files(files)
        assert result["files"][0]["filename"] == "src/services/big.py"
        assert result["files"][1]["filename"] == "src/services/small.py"

    def test_tier_counts_are_correct(self):
        files = [
            _file("src/auth/a.py"),       # CRITICAL
            _file("src/auth/b.py"),       # CRITICAL
            _file("src/config/c.py"),     # HIGH
            _file("README.md"),           # SKIP
        ]
        result = classify_files(files)
        assert result["tier_counts"]["CRITICAL"] == 2
        assert result["tier_counts"]["HIGH"]     == 1
        assert result["tier_counts"]["SKIP"]     == 1

    def test_total_files_count(self):
        files = [_file("a.py"), _file("b.py"), _file("c.py")]
        result = classify_files(files)
        assert result["total_files"] == 3

    def test_review_order_instruction_present(self):
        result = classify_files([_file("src/main.py")])
        assert "review_order" in result
        assert "instruction"  in result
        assert "CRITICAL"     in result["review_order"]


# ===========================================================================
# Edge cases
# ===========================================================================

class TestEdgeCases:
    def test_empty_filename_defaults_to_medium(self):
        result = classify_files([{"filename": "", "status": "modified", "additions": 1, "deletions": 0}])
        assert result["files"][0]["risk_tier"] == "MEDIUM"

    def test_deeply_nested_auth_still_critical(self):
        assert _tier_for("app/internal/auth/jwt_handler.py") == "CRITICAL"

    def test_first_matching_rule_wins(self):
        """auth/ in a test directory → CRITICAL (auth rule matches first)."""
        assert _tier_for("src/auth/test_login.py") == "CRITICAL"

    def test_case_insensitive_matching(self):
        assert _tier_for("src/Auth/Login.py")     == "CRITICAL"
        assert _tier_for("src/SECURITY/check.py") == "CRITICAL"
        assert _tier_for("Readme.MD")             == "SKIP"


# ===========================================================================
# CLI entry point
# ===========================================================================

class TestCLIEntryPoint:
    def test_script_handles_json_input(self):
        """Simulate CLI invocation via subprocess."""
        import subprocess
        script = os.path.join(SCRIPT_DIR, "classify_risk.py")
        input_data = json.dumps({
            "files_changed": [
                {"filename": "src/auth/login.py", "status": "modified", "additions": 10, "deletions": 2},
                {"filename": "README.md", "status": "modified", "additions": 1, "deletions": 1},
            ]
        })
        result = subprocess.run(
            [sys.executable, script, input_data],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["total_files"] == 2
        assert output["files"][0]["risk_tier"] == "CRITICAL"

    def test_script_errors_on_empty_files(self):
        import subprocess
        script = os.path.join(SCRIPT_DIR, "classify_risk.py")
        result = subprocess.run(
            [sys.executable, script, json.dumps({"files_changed": []})],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 1
        output = json.loads(result.stdout)
        assert "error" in output
