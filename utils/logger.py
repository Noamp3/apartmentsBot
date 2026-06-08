# utils/logger.py
"""Comprehensive logging system with Hebrew support."""

import logging
import json
import sys
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


class JSONFormatter(logging.Formatter):
    """Structured JSON logging for machine parsing. Supports Hebrew text."""
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # Add extra fields if present
        if hasattr(record, "extra_data"):
            log_data["data"] = record.extra_data
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_data, ensure_ascii=False, default=str)


class HebrewConsoleFormatter(logging.Formatter):
    """Human-readable console format with Hebrew support and colors."""
    
    COLORS = {
        "DEBUG": "\033[36m",     # Cyan
        "INFO": "\033[32m",      # Green
        "WARNING": "\033[33m",   # Yellow
        "ERROR": "\033[31m",     # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"
    
    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, self.RESET)
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Short logger name
        logger_short = record.name.split(".")[-1][:12].ljust(12)
        
        message = f"{color}{timestamp} [{record.levelname:>7}] {logger_short} | {record.getMessage()}{self.RESET}"
        
        if hasattr(record, "extra_data"):
            message += f"\n    [DATA] {record.extra_data}"
            
        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
            if record.exc_text:
                message += f"\n{color}{record.exc_text}{self.RESET}"
        
        return message


class StructuredLogger:
    """Wrapper for structured logging with context."""
    
    def __init__(self, logger: logging.Logger):
        self._logger = logger
    
    def _log(self, level: int, message: str, **extra):
        record = self._logger.makeRecord(
            self._logger.name, level, "", 0, message, (), None
        )
        if extra:
            record.extra_data = extra
        self._logger.handle(record)
    
    def debug(self, message: str, **extra):
        self._log(logging.DEBUG, message, **extra)
    
    def info(self, message: str, **extra):
        self._log(logging.INFO, message, **extra)
    
    def warning(self, message: str, **extra):
        self._log(logging.WARNING, message, **extra)
    
    def error(self, message: str, **extra):
        self._log(logging.ERROR, message, **extra)
        
    def exception(self, message: str, **extra):
        import sys
        exc_info = sys.exc_info()
        record = self._logger.makeRecord(
            self._logger.name, logging.ERROR, "", 0, message, (), exc_info
        )
        if extra:
            record.extra_data = extra
        self._logger.handle(record)
    
    def critical(self, message: str, **extra):
        self._log(logging.CRITICAL, message, **extra)


class LoggerFactory:
    """Factory for creating specialized loggers."""
    
    _initialized = False
    _log_dir = Path("logs")
    
    @classmethod
    def initialize(cls, log_dir: str = "logs", debug: bool = False):
        """Initialize logging system. Call once at startup."""
        if cls._initialized:
            return
        
        cls._log_dir = Path(log_dir)
        cls._log_dir.mkdir(exist_ok=True)
        
        # Root logger config
        root_level = logging.DEBUG if debug else logging.INFO
        logging.root.setLevel(root_level)
        
        # Silence verbose third-party loggers (like httpx/httpcore used by telegram) to avoid flooding with 200 OK logs
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        logging.getLogger("telegram").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        
        # Console handler (human readable)
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(HebrewConsoleFormatter())
        console.setLevel(root_level)
        logging.root.addHandler(console)
        
        # Main log file (JSON, rotating)
        main_file = RotatingFileHandler(
            cls._log_dir / "app.log",
            maxBytes=10_000_000,  # 10MB
            backupCount=10,
            encoding="utf-8"
        )
        main_file.setFormatter(JSONFormatter())
        main_file.setLevel(logging.DEBUG)
        logging.root.addHandler(main_file)
        
        # Error log file (errors only)
        error_file = RotatingFileHandler(
            cls._log_dir / "errors.log",
            maxBytes=5_000_000,  # 5MB
            backupCount=5,
            encoding="utf-8"
        )
        error_file.setFormatter(JSONFormatter())
        error_file.setLevel(logging.ERROR)
        logging.root.addHandler(error_file)
        
        cls._initialized = True
    
    @classmethod
    def get_logger(cls, name: str) -> logging.Logger:
        """Get a logger with the given name."""
        if not cls._initialized:
            cls.initialize()
        return logging.getLogger(name)
    
    @classmethod
    def get_specialized_logger(cls, component: str) -> StructuredLogger:
        """Get a specialized logger for a specific component."""
        return StructuredLogger(cls.get_logger(f"apt_bot.{component}"))


class Loggers:
    """Centralized access to all component loggers."""
    
    @staticmethod
    def scraper() -> StructuredLogger:
        return LoggerFactory.get_specialized_logger("scraper")
    
    @staticmethod
    def ai() -> StructuredLogger:
        return LoggerFactory.get_specialized_logger("ai")
    
    @staticmethod
    def matcher() -> StructuredLogger:
        return LoggerFactory.get_specialized_logger("matcher")
    
    @staticmethod
    def bot() -> StructuredLogger:
        return LoggerFactory.get_specialized_logger("bot")
    
    @staticmethod
    def scheduler() -> StructuredLogger:
        return LoggerFactory.get_specialized_logger("scheduler")
    
    @staticmethod
    def rate_limiter() -> StructuredLogger:
        return LoggerFactory.get_specialized_logger("rate_limiter")
    
    @staticmethod
    def db() -> StructuredLogger:
        return LoggerFactory.get_specialized_logger("database")

    @staticmethod
    def app() -> StructuredLogger:
        return LoggerFactory.get_specialized_logger("app")

    @staticmethod
    def processor() -> StructuredLogger:
        return LoggerFactory.get_specialized_logger("processor")
