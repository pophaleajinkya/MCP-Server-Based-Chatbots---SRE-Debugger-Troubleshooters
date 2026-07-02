"""Utility tools — no network required.

Tools:
  get_time   Current time + microsecond helpers for SQL queries
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastmcp.server.providers import LocalProvider

provider = LocalProvider()

_TIMEZONES: dict[str, str] = {
    "UTC":            "UTC",
    "US/Pacific":     "America/Los_Angeles",
    "US/Mountain":    "America/Denver",
    "US/Central":     "America/Chicago",
    "US/Eastern":     "America/New_York",
    "Mexico":         "America/Mexico_City",
    "Canada/Eastern": "America/Toronto",
    "Canada/Pacific": "America/Vancouver",
    "Chile":          "America/Santiago",
    "India":          "Asia/Kolkata",
    "UK":             "Europe/London",
    "Germany":        "Europe/Berlin",
}

_DELTA_UNITS: dict[str, str] = {"m": "minutes", "h": "hours", "d": "days"}


@provider.tool("get_time")
def get_time(
    timezone_name: str = "",
    time_range: str = "",
    convert_timestamp: int = 0,
    date: str = "",
    start_time_str: str = "",
    end_time_str: str = "",
) -> dict[str, Any]:
    """
    Get current time and microsecond timestamp helpers for SQL queries.

    ── TIMEZONE IS MANDATORY ─────────────────────────────────────────────────
    ALWAYS pass timezone_name. Your system context block contains:

        User timezone : America/Chicago   ← copy this value exactly

    Pass it as: get_time(timezone_name="America/Chicago", ...)

    Never leave timezone_name empty or default to "UTC" — doing so will
    produce incorrect timestamps when the user refers to local times like
    "3 PM yesterday" or "from 10 AM to 2 PM". Both IANA names
    (e.g. "America/Chicago") and short aliases (e.g. "US/Central") are accepted.

    ── WHY MICROSECONDS MATTER ────────────────────────────────────────────────
    OpenObserve _timestamp is in MICROSECONDS (seconds × 1,000,000).
    NEVER hardcode timestamps in SQL queries — use this tool to get
    microsecond values, then pass them as start_time/end_time to execute_sql.

    ── COMMON USES ────────────────────────────────────────────────────────────
    1. Get current time in the user's local timezone:
       get_time(timezone_name="America/Chicago")
       → {"now_us": N, "now_iso": "2026-04-07T14:32:00-05:00"}

    2. Get start/end for a relative window:
       get_time(timezone_name="America/Chicago", time_range="3h")
       → {"start_us": ..., "end_us": ..., "sql_hint": "start_time=..., end_time=..."}

    3. Convert a _timestamp from query results to local time:
       get_time(timezone_name="America/Chicago", convert_timestamp=1704067200123456)
       → {"converted": {"utc_iso": "...", "local_iso": "2024-01-01T08:00:00-06:00"}}

    4. Get timestamps for a specific incident window:
       get_time(timezone_name="America/Chicago", date="2026-04-07",
                start_time_str="14:00", end_time_str="15:30")
       → {"date_range": {"start_us": ..., "end_us": ...}}

    Parameters:
        timezone_name:     IANA timezone or alias — READ FROM YOUR SYSTEM CONTEXT.
                           Examples: "America/Chicago", "US/Central", "Asia/Kolkata".
                           Available aliases: UTC, US/Pacific, US/Mountain, US/Central,
                           US/Eastern, Mexico, India, UK, Germany, Canada/Eastern, Canada/Pacific.
        time_range:        Relative window: "30m"|"1h"|"3h"|"24h"|"7d".
        convert_timestamp: Microsecond _timestamp from query results to convert.
        date:              Specific date "YYYY-MM-DD".
        start_time_str:    Start time "HH:MM" for date window (requires date).
        end_time_str:      End time "HH:MM" for date window (requires date).

    Returns:
        {"now_us": N, "now_iso": "...", "start_us": N, "end_us": N, ...}
        If timezone_name was missing: includes "timezone_warning" key explaining the issue.
    """
    tz_warning: str = ""

    # No timezone provided — default to UTC but warn loudly so the agent
    # knows to retry with the correct timezone from its system context.
    if not timezone_name or not timezone_name.strip():
        tz = timezone.utc
        tz_name = "UTC"
        tz_warning = (
            "timezone_name was not provided — defaulted to UTC. "
            "Your system context block contains 'User timezone: <iana_tz>'. "
            "Pass that value as timezone_name to get correct local timestamps. "
            f"Available aliases: {', '.join(_TIMEZONES.keys())}. "
            "IANA names (e.g. 'America/Chicago') also accepted."
        )
    else:
        tz_name = _TIMEZONES.get(timezone_name, timezone_name)
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = timezone.utc
            tz_warning = (
                f"Unknown timezone {timezone_name!r} — defaulted to UTC. "
                "Your system context block contains 'User timezone: <iana_tz>'. "
                f"Available aliases: {', '.join(_TIMEZONES.keys())}. "
                "IANA names (e.g. 'America/Chicago') also accepted."
            )
            tz_name = "UTC"

    now_utc = datetime.now(timezone.utc)
    now_us = int(now_utc.timestamp() * 1_000_000)

    result: dict[str, Any] = {
        "success": True,
        "timezone": tz_name,
        "now_us": now_us,
        "now_iso": now_utc.astimezone(tz).isoformat(),
        "now_utc_iso": now_utc.isoformat(),
        "available_timezones": list(_TIMEZONES.keys()),
        "note": "OpenObserve _timestamp is in MICROSECONDS (seconds × 1,000,000)",
    }
    if tz_warning:
        result["timezone_warning"] = tz_warning

    if date and start_time_str and end_time_str:
        try:
            y, mo, d = (int(p) for p in date.split("-"))
            sh, sm = (int(p) for p in start_time_str.split(":"))
            eh, em = (int(p) for p in end_time_str.split(":"))
            s_dt = datetime(y, mo, d, sh, sm, tzinfo=tz).astimezone(timezone.utc)
            e_dt = datetime(y, mo, d, eh, em, tzinfo=tz).astimezone(timezone.utc)
            start_us = int(s_dt.timestamp() * 1_000_000)
            end_us = int(e_dt.timestamp() * 1_000_000)
            result["date_range"] = {
                "date": date,
                "start_time": start_time_str,
                "end_time": end_time_str,
                "timezone": tz_name,
                "start_us": start_us,
                "end_us": end_us,
                "start_utc_iso": s_dt.isoformat(),
                "end_utc_iso": e_dt.isoformat(),
                "sql_hint": f"start_time={start_us}, end_time={end_us} (pass as API params)",
            }
        except Exception as exc:
            result["date_range_error"] = str(exc)

    elif date:
        try:
            y, mo, d = (int(p) for p in date.split("-"))
            s_dt = datetime(y, mo, d, 0, 0, 0, tzinfo=tz).astimezone(timezone.utc)
            e_dt = datetime(y, mo, d, 23, 59, 59, tzinfo=tz).astimezone(timezone.utc)
            result["date_range"] = {
                "date": date,
                "start_us": int(s_dt.timestamp() * 1_000_000),
                "end_us": int(e_dt.timestamp() * 1_000_000),
                "timezone": tz_name,
            }
        except Exception as exc:
            result["date_range_error"] = str(exc)

    if time_range:
        try:
            unit = time_range[-1].lower()
            val = int(time_range[:-1])
            kwarg = _DELTA_UNITS.get(unit, "hours")
            start_us = int((now_utc - timedelta(**{kwarg: val})).timestamp() * 1_000_000)
            result["start_us"] = start_us
            result["end_us"] = now_us
            result["sql_hint"] = f"start_time={start_us}, end_time={now_us} (pass as API params)"
        except Exception as exc:
            result["time_range_error"] = str(exc)

    if convert_timestamp:
        try:
            dt_utc = datetime.fromtimestamp(convert_timestamp / 1_000_000, tz=timezone.utc)
            result["converted"] = {
                "input_us": convert_timestamp,
                "utc_iso": dt_utc.isoformat(),
                "local_iso": dt_utc.astimezone(tz).isoformat(),
                "timezone": tz_name,
            }
        except Exception as exc:
            result["conversion_error"] = str(exc)

    return result
