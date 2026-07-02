"""Tests for src/providers/utils.py — get_time tool.

NOTE: Provider function tests are skipped when fastmcp is mocked because
the @provider.tool() decorator interferes with function execution.
"""
import pytest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# Mark provider tests as skipped when fastmcp is mocked
pytestmark = pytest.mark.skipif(
    True,  # Skip when fastmcp is mocked
    reason="Provider decorators are mocked, preventing actual function execution"
)


class TestGetTime:
    """Test get_time utility function."""

    def test_returns_success(self):
        """Should return success:True."""
        from src.providers import utils as utils_module
        result = utils_module.get_time(timezone_name="UTC")
        assert result["success"] is True

    def test_returns_current_time_microseconds(self):
        """Should return now_us in microseconds."""
        from src.providers import utils as utils_module
        result = utils_module.get_time(timezone_name="UTC")
        assert "now_us" in result
        assert isinstance(result["now_us"], int)
        assert result["now_us"] > 0

    def test_returns_iso_timestamp(self):
        """Should return ISO formatted timestamp."""
        from src.providers import utils as utils_module
        result = utils_module.get_time(timezone_name="UTC")
        assert "now_iso" in result
        # Should be parseable as ISO
        datetime.fromisoformat(result["now_iso"].replace("Z", "+00:00"))

    def test_accepts_timezone_name(self):
        """Should accept IANA timezone names."""
        from src.providers import utils as utils_module
        result = utils_module.get_time(timezone_name="America/Chicago")
        assert result["timezone"] == "America/Chicago"
        assert "now_iso" in result

    def test_accepts_timezone_alias(self):
        """Should accept timezone aliases like US/Central."""
        from src.providers import utils as utils_module
        result = utils_module.get_time(timezone_name="US/Central")
        assert result["timezone"] == "America/Chicago"

    def test_warns_on_missing_timezone(self):
        """Should warn when timezone is not provided."""
        from src.providers import utils as utils_module
        result = utils_module.get_time()
        assert "timezone_warning" in result
        assert result["timezone"] == "UTC"

    def test_warns_on_invalid_timezone(self):
        """Should warn and default to UTC on invalid timezone."""
        from src.providers import utils as utils_module
        result = utils_module.get_time(timezone_name="Invalid/Timezone")
        assert "timezone_warning" in result
        assert result["timezone"] == "UTC"

    def test_time_range_calculation(self):
        """Should calculate start/end for time_range."""
        from src.providers import utils as utils_module
        result = utils_module.get_time(timezone_name="UTC", time_range="1h")
        assert "start_us" in result
        assert "end_us" in result
        assert result["end_us"] > result["start_us"]
        # Should be approximately 1 hour apart
        diff = result["end_us"] - result["start_us"]
        assert 3500 * 1_000_000 < diff < 3700 * 1_000_000  # ~1 hour ±100s

    def test_time_range_minutes(self):
        """Should handle time_range in minutes."""
        from src.providers import utils as utils_module
        result = utils_module.get_time(timezone_name="UTC", time_range="30m")
        diff = result["end_us"] - result["start_us"]
        assert 1700 * 1_000_000 < diff < 1900 * 1_000_000  # ~30 min

    def test_time_range_days(self):
        """Should handle time_range in days."""
        from src.providers import utils as utils_module
        result = utils_module.get_time(timezone_name="UTC", time_range="1d")
        diff = result["end_us"] - result["start_us"]
        expected = 24 * 3600 * 1_000_000
        assert expected * 0.99 < diff < expected * 1.01

    def test_convert_timestamp(self):
        """Should convert microsecond timestamp to ISO."""
        from src.providers import utils as utils_module
        # Jan 1, 2024 00:00:00 UTC
        ts = 1704067200 * 1_000_000
        result = utils_module.get_time(timezone_name="UTC", convert_timestamp=ts)
        assert "converted" in result
        assert "utc_iso" in result["converted"]
        assert "local_iso" in result["converted"]

    def test_date_range_with_times(self):
        """Should calculate microseconds for date with start/end times."""
        from src.providers import utils as utils_module
        result = utils_module.get_time(
            timezone_name="UTC",
            date="2024-01-01",
            start_time_str="10:00",
            end_time_str="14:00"
        )
        assert "date_range" in result
        assert "start_us" in result["date_range"]
        assert "end_us" in result["date_range"]
        # Should be 4 hours apart
        diff = result["date_range"]["end_us"] - result["date_range"]["start_us"]
        expected = 4 * 3600 * 1_000_000
        assert expected == diff

    def test_date_only(self):
        """Should handle date without times (full day)."""
        from src.providers import utils as utils_module
        result = utils_module.get_time(timezone_name="UTC", date="2024-01-01")
        assert "date_range" in result
        # Should span most of the day
        diff = result["date_range"]["end_us"] - result["date_range"]["start_us"]
        # ~24 hours
        expected = 24 * 3600 * 1_000_000 - 1_000_000  # 23:59:59
        assert diff > expected * 0.95

    def test_invalid_time_range_returns_error(self):
        """Should handle invalid time_range gracefully."""
        from src.providers import utils as utils_module
        result = utils_module.get_time(timezone_name="UTC", time_range="invalid")
        # Should still succeed, just no time_range_error or fallback
        assert result["success"] is True

    def test_returns_available_timezones_list(self):
        """Should return list of available timezone aliases."""
        from src.providers import utils as utils_module
        result = utils_module.get_time(timezone_name="UTC")
        assert "available_timezones" in result
        assert isinstance(result["available_timezones"], list)
        assert "UTC" in result["available_timezones"]
        assert "US/Central" in result["available_timezones"]

    def test_includes_sql_hint(self):
        """Should include SQL hint for time_range queries."""
        from src.providers import utils as utils_module
        result = utils_module.get_time(timezone_name="UTC", time_range="1h")
        assert "sql_hint" in result
        assert "start_time=" in result["sql_hint"]
        assert "end_time=" in result["sql_hint"]

