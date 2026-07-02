"""Build an RCA timeline from blame, commit, PR, and incident data.

Usage via run_skill_script:
  skill_name: incident-rca
  script_path: scripts/build_rca_timeline.py
  args: {
    "blame_result": <JSON from blame_file_line/lines>,
    "commit_result": <JSON from get_commit>,
    "pr_result": <JSON from get_pr_for_commit>,
    "tag_result": <JSON from find_tag_for_commit>,
    "incident_result": <JSON from fetch_incident_details>
  }

Assembles all RCA chain artifacts into a chronological timeline
showing: code authored → PR merged → release tagged → incident opened.
"""

import json
import sys
from datetime import datetime, timezone as _tz


# Sentinel for sorting events with unknown timestamps — must be timezone-aware
# to avoid "can't compare offset-naive and offset-aware datetimes".
_MAX_AWARE_DT = datetime.max.replace(tzinfo=_tz.utc)


def _parse_time(ts) -> datetime | None:
    """Try to parse an ISO timestamp string.  Returns timezone-aware UTC or None."""
    if not ts or not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        return None


def build_timeline(
    blame: dict | None = None,
    commit: dict | None = None,
    pr: dict | None = None,
    tag: dict | None = None,
    incident: dict | None = None,
) -> str:
    events = []

    # Blame → code authorship
    if blame:
        author = blame.get("author", blame.get("commit", {}).get("author", {}).get("name", "unknown"))
        date = blame.get("date", blame.get("commit", {}).get("author", {}).get("date", ""))
        sha = (blame.get("sha") or blame.get("commit", {}).get("sha") or "")[:8]
        events.append({
            "time": _parse_time(date),
            "label": "Code Authored",
            "detail": f"by **{author}** (commit `{sha}`)",
            "raw_time": date,
        })

    # Commit details
    if commit:
        commit_date = commit.get("commit", {}).get("committer", {}).get("date", "")
        sha = (commit.get("sha") or "")[:8]
        msg = commit.get("commit", {}).get("message", "").split("\n")[0][:80]
        events.append({
            "time": _parse_time(commit_date),
            "label": "Commit Pushed",
            "detail": f"`{sha}` — {msg}",
            "raw_time": commit_date,
        })

    # PR merge
    if pr:
        merged_at = pr.get("merged_at", pr.get("closed_at", ""))
        pr_num = pr.get("number", "?")
        pr_title = pr.get("title", "")[:80]
        merger = pr.get("merged_by", {}).get("login", "unknown") if isinstance(pr.get("merged_by"), dict) else "unknown"
        events.append({
            "time": _parse_time(merged_at),
            "label": "PR Merged",
            "detail": f"PR #{pr_num} — {pr_title} (merged by **{merger}**)",
            "raw_time": merged_at,
        })

    # Release tag
    if tag:
        tag_name = tag.get("name", tag.get("tag", "unknown"))
        tag_date = tag.get("date", tag.get("commit", {}).get("committer", {}).get("date", ""))
        events.append({
            "time": _parse_time(tag_date),
            "label": "Release Tagged",
            "detail": f"**{tag_name}**",
            "raw_time": tag_date,
        })

    # Incident
    if incident:
        opened = incident.get("opened_at", incident.get("sys_created_on", ""))
        inc_num = incident.get("number", incident.get("incident_number", "?"))
        priority = incident.get("priority", "?")
        short_desc = incident.get("short_description", "")[:80]
        events.append({
            "time": _parse_time(opened),
            "label": "Incident Opened",
            "detail": f"**{inc_num}** [{priority}] — {short_desc}",
            "raw_time": opened,
        })

    if not events:
        return "No RCA data provided — pass at least one of: blame_result, commit_result, pr_result, tag_result, incident_result."

    # Sort chronologically (None times go last)
    events.sort(key=lambda e: e["time"] or _MAX_AWARE_DT)

    lines = ["## RCA Timeline", ""]
    for i, evt in enumerate(events):
        connector = "→" if i < len(events) - 1 else "⏹"
        time_str = evt["time"].strftime("%Y-%m-%d %H:%M UTC") if evt["time"] else evt["raw_time"] or "unknown time"
        lines.append(f"{connector} **{evt['label']}** ({time_str})")
        lines.append(f"  {evt['detail']}")
        lines.append("")

    # Time gap analysis
    if len(events) >= 2 and events[0]["time"] and events[-1]["time"]:
        delta = events[-1]["time"] - events[0]["time"]
        hours = delta.total_seconds() / 3600
        lines.append(f"**Total span**: {hours:.1f} hours from code authorship to last event")

    return "\n".join(lines)


if __name__ == "__main__":
    try:
        args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}

        def _load(key):
            raw = args.get(key)
            if raw is None:
                return None
            if isinstance(raw, str):
                try:
                    return json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    return None
            return raw

        print(build_timeline(
            blame=_load("blame_result"),
            commit=_load("commit_result"),
            pr=_load("pr_result"),
            tag=_load("tag_result"),
            incident=_load("incident_result"),
        ))
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        print(f"Error parsing input: {exc}. Expected JSON args.")
        sys.exit(1)
