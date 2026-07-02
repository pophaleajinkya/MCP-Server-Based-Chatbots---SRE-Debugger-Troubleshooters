"""Build an ASCII histogram from time-bucketed SQL query results.

Usage via run_skill_script:
  skill_name: log-analysis
  script_path: scripts/build_histogram.py
  args: {
    "query_result": <JSON string from execute_sql>,
    "bucket_field": "bucket",
    "value_field": "requests"
  }

Takes SQL results with time buckets and a numeric value, and renders
an ASCII bar chart for quick terminal/chat visualization.
"""

import json
import sys
from datetime import datetime


def build_histogram(rows: list, bucket_field: str = "bucket",
                    value_field: str = "requests", width: int = 50) -> str:
    if not rows:
        return "No data to plot."

    # Extract bucket → value pairs
    data = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        bucket = row.get(bucket_field, "")
        value = row.get(value_field, 0)
        if value is None:
            value = 0
        elif isinstance(value, str):
            try:
                value = float(value)
            except (ValueError, TypeError):
                value = 0
        try:
            value = float(value)
        except (ValueError, TypeError):
            value = 0
        data.append((str(bucket), value))

    if not data:
        return "No plottable data found."

    max_val = max(v for _, v in data)
    if max_val == 0:
        max_val = 1  # avoid division by zero

    # Try to shorten timestamps for display
    labels = []
    for bucket, _ in data:
        try:
            # Parse ISO timestamps and show only HH:MM
            dt = datetime.fromisoformat(bucket.replace("Z", "+00:00"))
            labels.append(dt.strftime("%H:%M"))
        except (ValueError, AttributeError):
            # Truncate long labels
            labels.append(bucket[:16] if len(bucket) > 16 else bucket)

    max_label_len = max(len(l) for l in labels)

    lines = [f"## Histogram: {value_field} over time", "```"]

    for label, (_, value) in zip(labels, data):
        bar_len = int((value / max_val) * width)
        bar = "█" * bar_len
        lines.append(f"{label:>{max_label_len}} │ {bar} {value:,.0f}")

    lines.append("```")
    lines.append(f"\n**Peak**: {max_val:,.0f} | **Points**: {len(data)}")

    return "\n".join(lines)


if __name__ == "__main__":
    try:
        args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        result_raw = args.get("query_result", "{}")
        bucket_field = args.get("bucket_field", "bucket")
        value_field = args.get("value_field", "requests")

        if isinstance(result_raw, str):
            result = json.loads(result_raw)
        else:
            result = result_raw

        rows = result.get("rows", result.get("data", [])) if isinstance(result, dict) else []
        print(build_histogram(rows, bucket_field, value_field))
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        print(f"Error parsing input: {exc}. Expected JSON with 'query_result' key.")
        sys.exit(1)
