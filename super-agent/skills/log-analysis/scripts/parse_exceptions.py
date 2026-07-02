"""Parse and classify exceptions from OpenObserve SQL query results.

Usage via run_skill_script:
  skill_name: log-analysis
  script_path: scripts/parse_exceptions.py
  args: { "query_result": <JSON string from execute_sql> }

Takes SQL result rows containing exception data and produces:
- Exception class frequency distribution
- Stack trace grouping (deduplication)
- Severity classification (Error vs Warning vs Info)
"""

import json
import re
import sys
from collections import Counter, defaultdict


def parse_exceptions(query_result: dict) -> str:
    rows = query_result.get("rows", query_result.get("data", []))

    if not rows:
        return "No exception data found in the query result."

    # Extract exception classes and messages
    exception_classes = Counter()
    exception_details = defaultdict(list)
    severity_counts = Counter()

    for row in rows:
        exc_class = (
            row.get("exception_class")
            or row.get("error_type")
            or row.get("exception_type")
            or "Unknown"
        )
        exc_msg = (
            row.get("exception_message")
            or row.get("error_message")
            or row.get("message")
            or ""
        )
        count = row.get("count", row.get("cnt", 1))
        if isinstance(count, str):
            try:
                count = int(count)
            except (ValueError, TypeError):
                count = 1
        elif not isinstance(count, (int, float)):
            count = 1
        count = int(count)

        exception_classes[exc_class] += count

        # Classify severity
        exc_lower = exc_class.lower()
        if any(k in exc_lower for k in ("timeout", "unavailable", "oom", "fatal", "outofmemory")):
            severity_counts["🔴 Critical"] += count
        elif any(k in exc_lower for k in ("warn", "retry", "throttl")):
            severity_counts["🟡 Warning"] += count
        elif any(k in exc_lower for k in ("null", "illegal", "index", "cast", "ioexception")):
            severity_counts["🟠 Error"] += count
        else:
            severity_counts["⚪ Other"] += count

        # Keep up to 3 sample messages per exception class
        if len(exception_details[exc_class]) < 3 and exc_msg:
            # Truncate long messages
            truncated = exc_msg[:200] + "..." if len(exc_msg) > 200 else exc_msg
            exception_details[exc_class].append(truncated)

    total = sum(exception_classes.values())

    lines = [
        "## Exception Analysis Report",
        "",
        f"**Total Exceptions**: {total:,}",
        f"**Unique Exception Classes**: {len(exception_classes)}",
        "",
        "### Severity Distribution",
    ]

    for sev, cnt in sorted(severity_counts.items(), key=lambda x: -x[1]):
        pct = (cnt / total * 100) if total else 0
        lines.append(f"- {sev}: {cnt:,} ({pct:.1f}%)")

    lines.extend(["", "### Top Exception Classes", ""])
    lines.append("| Rank | Exception Class | Count | % |")
    lines.append("|---:|---|---:|---:|")

    for rank, (exc_class, count) in enumerate(exception_classes.most_common(20), 1):
        pct = (count / total * 100) if total else 0
        lines.append(f"| {rank} | `{exc_class}` | {count:,} | {pct:.1f}% |")

    # Sample messages for top exceptions
    top5 = exception_classes.most_common(5)
    if any(exception_details.get(exc) for exc, _ in top5):
        lines.extend(["", "### Sample Messages (Top 5)"])
        for exc_class, _ in top5:
            samples = exception_details.get(exc_class, [])
            if samples:
                lines.append(f"\n**{exc_class}**:")
                for s in samples:
                    lines.append(f"  - `{s}`")

    return "\n".join(lines)


if __name__ == "__main__":
    try:
        args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        result_raw = args.get("query_result", "{}")

        if isinstance(result_raw, str):
            result = json.loads(result_raw)
        else:
            result = result_raw

        print(parse_exceptions(result))
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        print(f"Error parsing input: {exc}. Expected JSON with 'query_result' key.")
        sys.exit(1)
