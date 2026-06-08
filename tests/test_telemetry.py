# tests/test_telemetry.py
"""Test suite for the TelemetryTracker class."""

import json
import os
import tempfile
from pathlib import Path
import pytest

from utils.telemetry import TelemetryTracker

def test_telemetry_tracker_operations():
    """Test standard metrics logging and file persistence of TelemetryTracker."""
    with tempfile.TemporaryDirectory() as tmpdir:
        telemetry_file = os.path.join(tmpdir, "test_telemetry.json")
        
        # Reset the singleton instance logic for testing
        TelemetryTracker._instance = None
        
        tracker = TelemetryTracker(telemetry_file=telemetry_file)
        
        # 1. Test initial load / defaults
        assert tracker.metrics["scrapers"] == {}
        assert tracker.metrics["ai"]["calls"] == 0
        assert tracker.metrics["matching"]["total_evaluated"] == 0
        
        # 2. Test scrape tracking
        tracker.track_scrape("facebook", duration_seconds=2.5, scraped_count=10, new_count=3)
        assert "facebook" in tracker.metrics["scrapers"]
        fb_stats = tracker.metrics["scrapers"]["facebook"]
        assert fb_stats["executions"] == 1
        assert fb_stats["total_duration_seconds"] == 2.5
        assert fb_stats["total_scraped"] == 10
        assert fb_stats["total_new"] == 3
        assert fb_stats["failures"] == 0
        
        # 3. Test scrape failures tracking
        tracker.track_scrape("facebook", duration_seconds=1.2, scraped_count=0, new_count=0, failed=True)
        assert fb_stats["executions"] == 2
        assert fb_stats["total_duration_seconds"] == 3.7
        assert fb_stats["failures"] == 1
        
        # 4. Test AI calls tracking
        tracker.track_ai_call(latency_seconds=0.45, quota_remaining=950)
        assert tracker.metrics["ai"]["calls"] == 1
        assert tracker.metrics["ai"]["total_latency_seconds"] == 0.45
        assert tracker.metrics["ai"]["errors"] == 0
        assert tracker.metrics["ai"]["quota_remaining"] == 950
        
        # 5. Test AI failures tracking
        tracker.track_ai_call(latency_seconds=0.1, failed=True)
        assert tracker.metrics["ai"]["calls"] == 2
        assert tracker.metrics["ai"]["errors"] == 1
        
        # 6. Test match tracking
        tracker.track_matches(evaluated=5, matches=2, rejections=3)
        assert tracker.metrics["matching"]["total_evaluated"] == 5
        assert tracker.metrics["matching"]["total_matches"] == 2
        assert tracker.metrics["matching"]["total_rejections"] == 3
        
        # Trigger save to verify match_ratio calculation
        tracker.save()
        assert tracker.metrics["matching"]["match_ratio"] == 0.4
        
        # 7. Test error recording
        tracker.track_error("scrapers.facebook", "TimeoutError")
        assert tracker.metrics["errors"]["scrapers.facebook"]["TimeoutError"] == 1
        
        # 8. Test file persistence
        assert os.path.exists(telemetry_file)
        with open(telemetry_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            assert data["ai"]["calls"] == 2
            assert data["matching"]["total_evaluated"] == 5
            assert data["errors"]["scrapers.facebook"]["TimeoutError"] == 1
            
        # 9. Test reloading saved file
        TelemetryTracker._instance = None
        new_tracker = TelemetryTracker(telemetry_file=telemetry_file)
        assert new_tracker.metrics["ai"]["calls"] == 2
        assert new_tracker.metrics["matching"]["total_evaluated"] == 5
        assert "facebook" in new_tracker.metrics["scrapers"]
