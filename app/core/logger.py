import sys

from app.settings import settings
from loguru import logger as _logger


def setup_logger():
    """Configure loguru logger with console and file sinks."""
    # Remove default handler
    _logger.remove()

    # Create logs directory if it doesn't exist
    settings.LOGS_DIR.mkdir(parents=True, exist_ok=True)

    # Console format with colors
    console_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )

    # File format (more detailed)
    file_format = (
        "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
        "{level: <8} | "
        "{name}:{function}:{line} - "
        "{message}"
    )

    # Add console sink
    _logger.add(
        sys.stderr,
        format=console_format,
        level=settings.LOG_LEVEL,
        colorize=True,
    )

    # Add rotating file sink
    _logger.add(
        settings.LOGS_DIR / "app.log",
        format=file_format,
        level="DEBUG",  # Always log debug to file
        rotation="10 MB",
        retention="1 week",
        compression="zip",
    )

    return _logger


# Initialize logger on import
logger = setup_logger()
