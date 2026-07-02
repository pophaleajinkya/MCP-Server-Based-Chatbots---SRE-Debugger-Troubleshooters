"""Classify changed files into risk tiers for progressive release review.

Usage via run_skill_script:
  skill_name: release-review
  script_path: scripts/classify_risk.py
  args: {
    "files_changed": [
      {"filename": "src/auth/login.py", "status": "modified", "additions": 12, "deletions": 3},
      ...
    ]
  }

Returns a prioritised list grouped by risk tier:
  CRITICAL > HIGH > MEDIUM > LOW > SKIP

The LLM reviews files in this order — CRITICAL files first, SKIP files last
(or not at all if context is tight).
"""

import json
import re
import sys
from typing import Any


# ── Risk classification rules ────────────────────────────────────────────
# Each rule: (tier, compiled regex pattern, human reason)
# Order matters — first match wins.

_RULES: list[tuple[str, re.Pattern, str]] = [
    # ── CRITICAL: security, auth, payments, secrets, DB migrations ────
    ("CRITICAL", re.compile(r"(^|/)auth/",          re.I), "authentication module"),
    ("CRITICAL", re.compile(r"(^|/)security/",      re.I), "security module"),
    ("CRITICAL", re.compile(r"(^|/)payment/",       re.I), "payment processing"),
    ("CRITICAL", re.compile(r"(^|/)checkout/",      re.I), "checkout flow"),
    ("CRITICAL", re.compile(r"(^|/)crypto/",        re.I), "cryptography module"),
    ("CRITICAL", re.compile(r"(^|/)secrets?/",      re.I), "secrets directory"),
    ("CRITICAL", re.compile(r"(^|/)migrations?/",   re.I), "database migration (irreversible)"),
    ("CRITICAL", re.compile(r"\.env($|\.)",         re.I), "environment / secrets file"),
    ("CRITICAL", re.compile(r"(^|/)Dockerfile",     re.I), "container image definition"),
    ("CRITICAL", re.compile(r"(^|/)\.github/workflows/", re.I), "CI/CD pipeline"),

    # ── HIGH: config, middleware, API contracts, error handling ────────
    ("HIGH", re.compile(r"(^|/)config/",            re.I), "configuration"),
    ("HIGH", re.compile(r"(^|/)middleware/",         re.I), "middleware layer"),
    ("HIGH", re.compile(r"(^|/)interceptor",        re.I), "request interceptor"),
    ("HIGH", re.compile(r"(^|/)gateway/",           re.I), "API gateway"),
    ("HIGH", re.compile(r"(^|/)proxy/",             re.I), "proxy layer"),
    ("HIGH", re.compile(r"(^|/)grpc/",              re.I), "gRPC definitions"),
    ("HIGH", re.compile(r"\.proto$",                re.I), "protobuf schema"),
    ("HIGH", re.compile(r"(^|/)openapi",            re.I), "OpenAPI / Swagger spec"),
    ("HIGH", re.compile(r"(^|/)swagger",            re.I), "Swagger spec"),
    ("HIGH", re.compile(r"(feature[_-]?flag|toggle)", re.I), "feature flag"),
    ("HIGH", re.compile(r"(^|/)helm/",              re.I), "Helm chart"),
    ("HIGH", re.compile(r"values.*\.ya?ml$",        re.I), "Helm values"),
    ("HIGH", re.compile(r"(^|/)k8s/",              re.I), "Kubernetes manifests"),
    ("HIGH", re.compile(r"(^|/)deploy/",            re.I), "deployment config"),

    # ── MEDIUM: business logic, services, controllers ─────────────────
    ("MEDIUM", re.compile(r"(^|/)service[s]?/",     re.I), "service layer"),
    ("MEDIUM", re.compile(r"(^|/)controller[s]?/",  re.I), "controller layer"),
    ("MEDIUM", re.compile(r"(^|/)handler[s]?/",     re.I), "request handler"),
    ("MEDIUM", re.compile(r"(^|/)model[s]?/",       re.I), "data model"),
    ("MEDIUM", re.compile(r"(^|/)repository/",      re.I), "data access layer"),
    ("MEDIUM", re.compile(r"(^|/)dao/",             re.I), "data access object"),
    ("MEDIUM", re.compile(r"(^|/)util[s]?/",        re.I), "utility module"),
    ("MEDIUM", re.compile(r"(^|/)lib/",             re.I), "shared library"),
    ("MEDIUM", re.compile(r"(^|/)src/",             re.I), "source code"),

    # ── LOW: tests, docs, generated, assets ───────────────────────────
    ("LOW", re.compile(r"(^|/)test[s]?/",           re.I), "test file"),
    ("LOW", re.compile(r"[_.]test\.",               re.I), "test file"),
    ("LOW", re.compile(r"[_.]spec\.",               re.I), "spec file"),
    ("LOW", re.compile(r"__tests__/",               re.I), "test directory"),

    # ── SKIP: purely non-functional ───────────────────────────────────
    ("SKIP", re.compile(r"\.md$",                   re.I), "documentation"),
    ("SKIP", re.compile(r"LICENSE",                 re.I), "license file"),
    ("SKIP", re.compile(r"CHANGELOG",              re.I), "changelog"),
    ("SKIP", re.compile(r"\.txt$",                  re.I), "text file"),
    ("SKIP", re.compile(r"\.(png|jpg|jpeg|gif|svg|ico|woff2?|ttf|eot)$", re.I), "binary asset"),
    ("SKIP", re.compile(r"(^|/)generated/",         re.I), "generated code"),
    ("SKIP", re.compile(r"\.lock$",                 re.I), "lock file"),
    ("SKIP", re.compile(r"yarn\.lock$",             re.I), "yarn lock"),
    ("SKIP", re.compile(r"package-lock\.json$",     re.I), "npm lock"),
    ("SKIP", re.compile(r"go\.sum$",                re.I), "go checksum"),
]

# Tier ordering for sort
_TIER_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "SKIP": 4}


def classify_files(files_changed: list[dict[str, Any]]) -> dict[str, Any]:
    """Classify each file into a risk tier and return prioritised groups."""
    classified: list[dict[str, Any]] = []

    for f in files_changed:
        filename = f.get("filename", "")
        status   = f.get("status", "modified")
        adds     = f.get("additions", 0)
        dels     = f.get("deletions", 0)

        tier   = "MEDIUM"  # default if no rule matches
        reason = "general source code"

        for rule_tier, pattern, rule_reason in _RULES:
            if pattern.search(filename):
                tier   = rule_tier
                reason = rule_reason
                break

        # Boost: deleted files with many deletions → higher risk
        if status == "removed" and dels > 50 and tier in ("MEDIUM", "LOW"):
            tier   = "HIGH"
            reason = f"large file removal ({dels} lines deleted)"

        # Boost: renamed files that also changed content
        if status == "renamed" and (adds > 0 or dels > 0):
            if tier in ("LOW", "SKIP"):
                tier   = "MEDIUM"
                reason = f"renamed with content changes (+{adds}/-{dels})"

        classified.append({
            "filename":  filename,
            "status":    status,
            "additions": adds,
            "deletions": dels,
            "risk_tier": tier,
            "reason":    reason,
        })

    # Sort by tier priority, then by change size (largest first within tier)
    classified.sort(
        key=lambda x: (_TIER_ORDER.get(x["risk_tier"], 2), -(x["additions"] + x["deletions"]))
    )

    # Group counts
    tier_counts = {}
    for item in classified:
        t = item["risk_tier"]
        tier_counts[t] = tier_counts.get(t, 0) + 1

    return {
        "total_files":  len(classified),
        "tier_counts":  tier_counts,
        "files":        classified,
        "review_order": "CRITICAL → HIGH → MEDIUM → LOW → SKIP",
        "instruction":  (
            "Review files in this order. For SKIP-tier files, only review if "
            "the filename suggests hidden risk (e.g. a 'README.md' with embedded scripts). "
            "For each file, call get_file_diff() to fetch the patch, then analyze it."
        ),
    }


if __name__ == "__main__":
    try:
        raw = sys.argv[1] if len(sys.argv) > 1 else "{}"
        args = json.loads(raw)

        # Handle LLM double-encoding
        if isinstance(args, str):
            args = json.loads(args)

        files = args.get("files_changed", [])
        if not files:
            print(json.dumps({"error": "files_changed is required and must be a non-empty list"}))
            sys.exit(1)

        result = classify_files(files)
        print(json.dumps(result, indent=2))
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        print(json.dumps({"error": f"Failed to parse input: {exc}"}))
        sys.exit(1)
