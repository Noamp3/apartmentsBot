# utils/telemetry.py
"""Telemetry and performance metrics tracking."""

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from utils.logger import Loggers

log = Loggers.app()

class TelemetryTracker:
    """Tracks system performance, scrape metrics, AI latency, and error counts."""
    
    _instance: Optional['TelemetryTracker'] = None
    
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(TelemetryTracker, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, telemetry_file: str = "logs/telemetry.json"):
        if getattr(self, "_initialized", False):
            return
            
        self.telemetry_path = Path(telemetry_file)
        self.telemetry_path.parent.mkdir(exist_ok=True)
        
        self.metrics = {
            "scrapers": {},
            "ai": {
                "calls": 0,
                "total_latency_seconds": 0.0,
                "errors": 0,
                "quota_remaining": None
            },
            "matching": {
                "total_evaluated": 0,
                "total_matches": 0,
                "total_rejections": 0,
                "match_ratio": 0.0
            },
            "errors": {},
            "cycles": {
                "total_completed": 0,
                "total_failed": 0,
                "total_duration_seconds": 0.0
            },
            "last_updated": None
        }
        
        self._load_metrics()
        self._initialized = True
        
    def _load_metrics(self):
        """Load telemetry metrics from file if it exists."""
        if self.telemetry_path.exists():
            try:
                with open(self.telemetry_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    # Merge loaded metrics to preserve structure if schema changes
                    for key in self.metrics:
                        if key in saved and isinstance(self.metrics[key], dict):
                            self.metrics[key].update(saved[key])
                        elif key in saved:
                            self.metrics[key] = saved[key]
            except Exception as e:
                log.warning(f"Failed to load telemetry file: {e}")
                
    def save(self):
        """Save telemetry metrics to logs/telemetry.json."""
        try:
            self.metrics["last_updated"] = datetime.now().isoformat()
            
            # Recalculate match ratio
            matching = self.metrics["matching"]
            total = matching["total_evaluated"]
            matching["match_ratio"] = round(matching["total_matches"] / total, 3) if total > 0 else 0.0
            
            with open(self.telemetry_path, "w", encoding="utf-8") as f:
                json.dump(self.metrics, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.error(f"Failed to save telemetry metrics: {e}")
            
    def track_scrape(self, source: str, duration_seconds: float, scraped_count: int, new_count: int, failed: bool = False):
        """Record scraper execution details."""
        if source not in self.metrics["scrapers"]:
            self.metrics["scrapers"][source] = {
                "executions": 0,
                "total_duration_seconds": 0.0,
                "total_scraped": 0,
                "total_new": 0,
                "failures": 0
            }
            
        stats = self.metrics["scrapers"][source]
        stats["executions"] += 1
        stats["total_duration_seconds"] += duration_seconds
        stats["total_scraped"] += scraped_count
        stats["total_new"] += new_count
        if failed:
            stats["failures"] += 1
            
        log.info(
            f"Telemetry: Scraped {source}",
            source=source,
            duration=round(duration_seconds, 2),
            scraped=scraped_count,
            new=new_count,
            success=not failed
        )
        self.save()
        
    def track_ai_call(self, latency_seconds: float, quota_remaining: Optional[int] = None, failed: bool = False):
        """Record AI API call details."""
        ai = self.metrics["ai"]
        ai["calls"] += 1
        ai["total_latency_seconds"] += latency_seconds
        if failed:
            ai["errors"] += 1
        if quota_remaining is not None:
            ai["quota_remaining"] = quota_remaining
            
        log.debug(
            f"Telemetry: AI Call recorded",
            latency=round(latency_seconds, 2),
            quota_remaining=quota_remaining,
            success=not failed
        )
        self.save()
        
    def track_matches(self, evaluated: int, matches: int, rejections: int):
        """Record user listing matching results."""
        matching = self.metrics["matching"]
        matching["total_evaluated"] += evaluated
        matching["total_matches"] += matches
        matching["total_rejections"] += rejections
        
        log.info(
            f"Telemetry: Matching pipeline processed",
            evaluated=evaluated,
            matches=matches,
            rejections=rejections
        )
        self.save()
        
    def track_error(self, component: str, error_type: str):
        """Record error counts per component."""
        errors = self.metrics["errors"]
        if component not in errors:
            errors[component] = {}
        errors[component][error_type] = errors[component].get(error_type, 0) + 1
        
        log.warning(
            f"Telemetry: Error recorded in {component}",
            component=component,
            error_type=error_type
        )
        self.save()
        
    def track_cycle(self, duration_seconds: float, failed: bool = False):
        """Record scheduler processing cycle execution details."""
        cycles = self.metrics["cycles"]
        if failed:
            cycles["total_failed"] += 1
        else:
            cycles["total_completed"] += 1
            cycles["total_duration_seconds"] += duration_seconds
            
        log.info(
            f"Telemetry: Cycle completed",
            duration=round(duration_seconds, 2),
            failed=failed
        )
        self.save()

# Global tracker instance
telemetry = TelemetryTracker()
