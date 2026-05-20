"""
Structured Logging
-------------------
Uses loguru for structured, levelled logging with correlation IDs.

Architectural Decision:
  Standard print() statements are fine for scripts but invisible in production.
  Structured JSON logs mean:
    - Each log line is parseable by Datadog / CloudWatch / ELK
    - Correlation IDs link all logs from a single pipeline run
    - Agent decisions are traceable end-to-end without a debugger
    - Log level is env-configurable (DEBUG locally, INFO in prod)
"""
import sys
import uuid
from loguru import logger
from core.config import get_settings


def setup_logging():
    """Configure loguru with structured JSON output."""
    settings = get_settings()

    logger.remove()  # Remove default handler

    def stdout_format(record):
        correlation_id = record["extra"].get("correlation_id", "sys")
        agent = record["extra"].get("agent", "app")
        t = record["time"].strftime("%Y-%m-%d %H:%M:%S")
        return f"{t} | {{level}} | {correlation_id} | {agent} | {{message}}\n"

    # JSON structured logs for production / log aggregators
    logger.add(
        sys.stdout,
        format=stdout_format,
        level=settings.log_level,
        colorize=False,
        serialize=False,
    )

    def file_format(record):
        correlation_id = record["extra"].get("correlation_id", "sys")
        agent = record["extra"].get("agent", "app")
        return "{time} | {level} | " + correlation_id + " | " + agent + " | {message}\n"

    # File log for persistence
    logger.add(
        "./data/logs/app.log",
        rotation="100 MB",
        retention="7 days",
        compression="zip",
        format=file_format,
        level="DEBUG",
        serialize=False,
    )

    return logger


def get_agent_logger(agent_name: str, correlation_id: str = None):
    """
    Returns a logger bound to a specific agent and correlation ID.
    Every log line from this agent will carry both fields automatically.
    """
    return logger.bind(
        agent=agent_name,
        correlation_id=correlation_id or str(uuid.uuid4())[:8]
    )


def new_correlation_id() -> str:
    """Generate a unique ID to trace a full pipeline run."""
    return str(uuid.uuid4())[:8]
